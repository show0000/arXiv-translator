"""LaTeX 컴파일 모듈

번역된 LaTeX 파일을 PDF로 컴파일합니다.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from .font_manager import FontManager

logger = logging.getLogger(__name__)


class LatexCompiler:
    """LaTeX → PDF 컴파일러"""

    def __init__(self, font_manager: Optional[FontManager] = None):
        self.font_manager = font_manager or FontManager()

    def find_main_tex_file(self, directory: Path) -> Optional[Path]:
        """메인 .tex 파일 찾기

        Args:
            directory: 검색할 디렉토리

        Returns:
            메인 .tex 파일 경로 (찾지 못하면 None)
        """
        logger.info(f"메인 .tex 파일 검색: {directory}")

        # .tex 파일 찾기 (백업 파일 제외)
        candidate_files = [
            f for f in directory.rglob("*.tex")
            if "_original" not in f.name
        ]

        if not candidate_files:
            logger.warning("❌ .tex 파일을 찾을 수 없습니다.")
            return None

        # \\documentclass가 있는 파일 찾기
        main_candidates = []
        for file in candidate_files:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    contents = f.read()

                # 메인 파일 판별 조건
                has_documentclass = r'\documentclass' in contents
                has_begin_document = r'\begin{document}' in contents

                if has_documentclass and has_begin_document:
                    logger.debug(f"메인 파일 후보: {file}")
                    main_candidates.append(file)

            except Exception as e:
                logger.debug(f"파일 읽기 실패 (무시): {file} - {e}")
                continue

        # 후보가 있으면 첫 번째 반환
        if main_candidates:
            main_file = main_candidates[0]
            logger.info(f"✓ 메인 파일 발견: {main_file.name}")
            return main_file

        # 메인 파일을 찾지 못하면 가장 큰 파일 반환
        if candidate_files:
            main_file = max(candidate_files, key=lambda f: f.stat().st_size)
            logger.warning(f"⚠ 메인 파일을 확정할 수 없어 가장 큰 파일 선택: {main_file.name}")
            return main_file

        return None

    def remove_conflicting_packages(self, tex_file: Path) -> None:
        """XeLaTeX과 충돌하는 패키지 제거

        CJK 패키지, inputenc, fontenc 등 XeLaTeX에서 불필요하거나 충돌하는
        패키지를 제거합니다.

        Args:
            tex_file: .tex 파일 경로
        """
        logger.debug(f"충돌 패키지 제거: {tex_file}")

        # 제거할 패키지/명령어 키워드
        conflict_keywords = [
            # CJK 관련
            r'\usepackage{CJKutf8}',
            r'\usepackage{kotex}',
            r'\begin{CJK}',
            r'\end{CJK}',
            r'\CJKfamily',
            r'\CJK@',
            # XeLaTeX과 충돌하는 인코딩 패키지
            r'\usepackage[utf8]{inputenc}',
            r'\usepackage[utf-8]{inputenc}',
            r'\usepackage{inputenc}',
            r'\usepackage[T1]{fontenc}',
            r'\usepackage[T2A]{fontenc}',
            r'\usepackage{fontenc}',
        ]

        # 정규식 패턴으로도 매칭
        # \usepackage 와 \RequirePackage 모두 매칭 (.cls/.sty 파일 대응)
        conflict_patterns = [
            re.compile(r'\\(?:usepackage|RequirePackage)(\[.*?\])?\{inputenc\}'),
            re.compile(r'\\(?:usepackage|RequirePackage)(\[.*?\])?\{fontenc\}'),
        ]

        try:
            with open(tex_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                # 키워드 매칭
                if any(keyword in line for keyword in conflict_keywords):
                    logger.debug(f"  제거: {line.strip()}")
                    continue
                # 정규식 매칭
                if any(pattern.search(line) for pattern in conflict_patterns):
                    logger.debug(f"  제거: {line.strip()}")
                    continue
                new_lines.append(line)

            with open(tex_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            logger.debug("충돌 패키지 제거 완료")

        except Exception as e:
            logger.error(f"충돌 패키지 제거 실패: {e}")
            raise

    # xeCJK보다 먼저 로드되면 fontspec과 충돌하는 폰트 패키지 목록
    FONT_PACKAGES_TO_RELOCATE = {
        'XCharter', 'charter', 'mathdesign',
        'newtxtext', 'newtxmath', 'txfonts',
        'newpxtext', 'newpxmath', 'pxfonts',
        'mathpazo', 'palatino',
        'mathptmx', 'times', 'helvet', 'courier',
        'libertine', 'libertinus', 'libertinust1math',
        'kpfonts', 'lmodern', 'tgtermes', 'tgpagella',
        'stix', 'stix2',
    }

    def _relocate_font_packages(self, directory: Path) -> list[str]:
        """cls/sty 파일에서 폰트 패키지를 주석 처리하고 재삽입용 라인 반환

        XCharter 등의 폰트 패키지가 cls 파일에서 xeCJK 이전에 로드되면
        fontspec과 충돌한다. 해당 패키지를 주석 처리하고, main tex에서
        xeCJK 이후에 다시 로드할 수 있도록 라인을 수집한다.

        Returns:
            main tex 파일의 xeCJK 설정 이후에 삽입할 \\usepackage 라인 목록
        """
        relocated_lines = []
        pattern = re.compile(
            r'\\(?:RequirePackage|usepackage)(\[.*?\])?\{([^}]+)\}'
        )

        for ext in ("*.cls", "*.sty"):
            for aux_file in directory.rglob(ext):
                if "_original" in aux_file.name:
                    continue
                try:
                    lines = aux_file.read_text(encoding='utf-8').splitlines(
                        keepends=True
                    )
                    modified = False
                    new_lines = []
                    for line in lines:
                        m = pattern.search(line)
                        if m and not line.strip().startswith('%'):
                            pkg_names = {
                                p.strip() for p in m.group(2).split(',')
                            }
                            if pkg_names & self.FONT_PACKAGES_TO_RELOCATE:
                                opts = m.group(1) or ''
                                # \usepackage 형태로 재삽입할 라인 생성
                                use_line = f"\\usepackage{opts}{{{m.group(2)}}}\n"
                                relocated_lines.append(use_line)
                                new_lines.append('% [relocated for xeCJK] ' + line)
                                logger.info(
                                    f"  폰트 패키지 재배치: {aux_file.name} → "
                                    f"{m.group(2)}"
                                )
                                modified = True
                                continue
                        new_lines.append(line)
                    if modified:
                        aux_file.write_text(''.join(new_lines), encoding='utf-8')
                except Exception as e:
                    logger.warning(
                        f"폰트 패키지 재배치 실패 ({aux_file.name}): {e}"
                    )

        return relocated_lines

    def _soften_newcommands(self, tex_file: Path) -> None:
        """보조 .tex 파일에서 \\newcommand를 \\providecommand로 변환

        XeLaTeX + xeCJK가 로드하는 패키지(unicode-math, fontspec 등)가
        이미 정의한 명령어와 논문 부속 파일의 \\newcommand가 충돌하면
        "Command \\foo already defined" 에러가 발생한다.
        \\providecommand로 바꾸면 기존 정의가 없을 때만 정의하므로
        충돌을 방지할 수 있다.
        """
        try:
            content = tex_file.read_text(encoding='utf-8')
            # \newcommand → \providecommand (이미 존재하면 건너뜀)
            new_content = content.replace(r'\newcommand', r'\providecommand')
            if new_content != content:
                count = content.count(r'\newcommand')
                logger.debug(
                    f"  {tex_file.name}: \\newcommand → \\providecommand ({count}건)"
                )
                tex_file.write_text(new_content, encoding='utf-8')
        except Exception as e:
            logger.warning(f"\\newcommand 변환 실패 ({tex_file.name}): {e}")

    def add_font_configuration(
        self,
        tex_file: Path,
        main_font: Optional[str] = None,
        mono_font: Optional[str] = None,
        extra_packages: Optional[list[str]] = None
    ) -> None:
        """한글 폰트 설정 추가

        Args:
            tex_file: .tex 파일 경로
            main_font: 주 폰트 (없으면 자동 감지)
            mono_font: 고정폭 폰트 (없으면 자동 감지)
            extra_packages: xeCJK 이후에 삽입할 패키지 라인 목록
                (cls/sty에서 재배치된 폰트 패키지)
        """
        logger.info(f"폰트 설정 추가: {tex_file}")

        # XeLaTeX 충돌 패키지 제거
        self.remove_conflicting_packages(tex_file)

        # 폰트 설정 생성
        font_config = self.font_manager.generate_latex_font_config(
            main_font=main_font,
            mono_font=mono_font
        )

        # cls/sty에서 재배치된 폰트 패키지를 xeCJK 설정 뒤에 추가
        if extra_packages:
            pkg_block = '% Relocated font packages (moved after xeCJK)\n'
            pkg_block += ''.join(extra_packages)
            font_config = font_config + pkg_block

        try:
            with open(tex_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # \\documentclass 바로 뒤에 폰트 설정 삽입
            # xeCJK + 재배치 폰트 패키지가 \input{math_commands} 등
            # 보조 파일보다 먼저 로드되어야 명령어 충돌을 방지할 수 있음
            inserted = False
            for i, line in enumerate(lines):
                if r'\documentclass' in line and not line.strip().startswith('%'):
                    # \documentclass 줄 뒤에 삽입
                    lines.insert(i + 1, font_config + '\n')
                    inserted = True
                    break

            if not inserted:
                # fallback: \begin{document} 앞
                for i, line in enumerate(lines):
                    if r'\begin{document}' in line and not line.strip().startswith('%'):
                        lines.insert(i, font_config + '\n')
                        inserted = True
                        break

            if not inserted:
                logger.warning("⚠ 삽입 위치를 찾지 못함 — 파일 시작에 폰트 설정 삽입")
                lines.insert(0, font_config + '\n')

            with open(tex_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info("✓ 폰트 설정 추가 완료")

        except Exception as e:
            logger.error(f"폰트 설정 추가 실패: {e}")
            raise

    def sanitize_translated_tex(self, tex_file: Path) -> None:
        """번역된 tex 파일을 원본과 비교하여 구조적 손상을 포괄적으로 복원

        LLM의 비결정적 출력으로 인한 모든 유형의 LaTeX 구조 손상을 감지하고 수정합니다.
        개별 패턴 수정이 아닌 줄 단위 원본 대비 검증 방식으로 동작합니다.
        """
        backup_file = tex_file.with_suffix('.tex_original')
        if not backup_file.exists():
            return

        original_lines = backup_file.read_text(encoding='utf-8').splitlines(keepends=True)
        translated_lines = tex_file.read_text(encoding='utf-8').splitlines(keepends=True)

        # 원본에서 사용된 유효한 LaTeX 명령어 수집
        # 디렉토리 내 모든 _original 파일에서 명령어 수집 (preamble 등 포함)
        original_content = ''
        for orig_file in tex_file.parent.rglob('*.tex_original'):
            original_content += orig_file.read_text(encoding='utf-8')
        if not original_content:
            original_content = ''.join(original_lines)
        valid_cmds = set(re.findall(r'\\([a-zA-Z]+)', original_content))
        valid_cmds.update({
            'textbf', 'textit', 'emph', 'text', 'mathrm', 'mathbf', 'mathit',
            'section', 'subsection', 'subsubsection', 'paragraph',
            'begin', 'end', 'item', 'label', 'ref', 'cite', 'caption',
            'footnote', 'footnotetext', 'thanks',
            'centering', 'includegraphics', 'usepackage', 'newcommand',
            'renewcommand', 'providecommand', 'def', 'let', 'hline', 'toprule', 'midrule',
            'bottomrule', 'cline', 'multicolumn', 'multirow',
            'vspace', 'hspace', 'noindent', 'par', 'newline', 'linebreak',
            'small', 'footnotesize', 'scriptsize', 'tiny', 'large', 'Large',
            'LARGE', 'huge', 'Huge', 'normalsize',
            'it', 'bf', 'rm', 'sf', 'tt', 'sc', 'sl',
        })

        fixed_count = 0
        result_lines = []

        # 줄 수가 다를 수 있으므로 번역 파일 기준으로 순회
        for i, line in enumerate(translated_lines):
            fixed_line = line

            # === 1. 잘못된 제어 시퀀스 수정 (\maximiz → maximiz) ===
            for cmd in set(re.findall(r'\\([a-zA-Z]+)', line)):
                if cmd not in valid_cmds:
                    fixed_line = re.sub(
                        r'\\' + re.escape(cmd) + r'(?![a-zA-Z])',
                        cmd, fixed_line
                    )
                    if fixed_line != line:
                        fixed_count += 1

            # === 2. \(한글) 수식 오인 수정 ===
            new_line = re.sub(r'\\[(]([가-힣])', lambda m: '(' + m.group(1), fixed_line)
            if new_line != fixed_line:
                fixed_line = new_line
                fixed_count += 1

            # === 3. \명령어+한글 직접 연결 수정 (\method를 → \method{}를) ===
            # LaTeX는 \cmd 뒤에 알파벳이 오면 명령어 이름의 일부로 인식
            def _fix_cmd_korean(m):
                return '\\' + m.group(1) + '{}' + m.group(2)
            new_line = re.sub(
                r'\\([a-zA-Z]+)([가-힣])',
                lambda m: _fix_cmd_korean(m) if m.group(1) in valid_cmds else m.group(0),
                fixed_line
            )
            if new_line != fixed_line:
                fixed_line = new_line
                fixed_count += 1

            result_lines.append(fixed_line)

        # === 3. 환경 구조 검증: begin/end 매칭 ===
        content = ''.join(result_lines)
        lines = content.splitlines(keepends=True)

        # 고아 \item 주석 처리 + \begin{itemize} 다음 \item 누락 수정
        # Itemize/Enumerate 등 커스텀 리스트 환경도 포함
        list_pattern = re.compile(
            r'\\(begin|end)\{(itemize|enumerate|description'
            r'|Itemize|Enumerate|compactitem|compactenum|inparaenum)\}'
        )
        list_depth = 0
        prev_was_begin_list = False
        for idx in range(len(lines)):
            stripped = lines[idx].lstrip()
            # 고아 \item 주석 처리 (begin/end 처리 전에 체크)
            if list_depth == 0 and stripped.startswith('\\item '):
                lines[idx] = '%% [auto-fixed] ' + lines[idx]
                fixed_count += 1
            # \begin{itemize} 다음에 \item 없으면 추가
            elif prev_was_begin_list and stripped and not stripped.startswith('\\item') and not stripped.startswith('%') and not stripped.startswith('\\begin'):
                lines[idx] = '    \\item ' + lines[idx].lstrip()
                fixed_count += 1
            prev_was_begin_list = False
            for m in list_pattern.finditer(lines[idx]):
                if m.group(1) == 'begin':
                    list_depth += 1
                    prev_was_begin_list = True
                else:
                    list_depth = max(0, list_depth - 1)
                    prev_was_begin_list = False

        content = ''.join(lines)

        # === 4. 전체 begin/end 균형 검증 — 불균형 환경을 원본 블록으로 복원 ===
        env_pattern = re.compile(r'\\(begin|end)\{([^}]+)\}')
        stack = []
        broken_envs = set()
        for m in env_pattern.finditer(content):
            if m.group(1) == 'begin':
                stack.append(m.group(2))
            elif m.group(1) == 'end':
                env = m.group(2)
                if stack and stack[-1] == env:
                    stack.pop()
                else:
                    broken_envs.add(env)
        if stack:
            broken_envs.update(stack)

        if broken_envs:
            logger.warning(f"⚠ 불균형 환경 감지: {broken_envs} — 해당 블록 원본 복원 시도")
            # 불균형 환경의 블록을 원본에서 찾아 복원
            for env in broken_envs:
                orig_blocks = re.findall(
                    r'(\\begin\{' + re.escape(env) + r'\}.*?\\end\{' + re.escape(env) + r'\})',
                    original_content, re.DOTALL
                )
                trans_blocks = re.findall(
                    r'(\\begin\{' + re.escape(env) + r'\}.*?\\end\{' + re.escape(env) + r'\})',
                    content, re.DOTALL
                )
                # 블록 수가 다르면 원본으로 복원
                if len(orig_blocks) != len(trans_blocks):
                    for orig_block in orig_blocks:
                        if orig_block not in content:
                            # 해당 환경의 시작점을 찾아 원본 블록 삽입
                            # (복잡한 경우이므로 로그만 남기고 개별 수정에 맡김)
                            logger.debug(f"  {env} 환경 블록 수 불일치 — 수동 확인 필요")

        if fixed_count > 0:
            tex_file.write_text(content, encoding='utf-8')
            logger.info(f"🔧 번역 후처리: {fixed_count}개 항목 자동 수정")

    def compile_to_pdf(
        self,
        tex_file: Path,
        output_dir: Optional[Path] = None,
        compile_twice: bool = True
    ) -> Optional[Path]:
        """LaTeX 파일을 PDF로 컴파일

        Args:
            tex_file: 컴파일할 .tex 파일
            output_dir: PDF 출력 디렉토리 (없으면 현재 디렉토리)
            compile_twice: 참조 해결을 위해 2번 컴파일

        Returns:
            생성된 PDF 파일 경로 (실패 시 None)
        """
        logger.info(f"PDF 컴파일 시작: {tex_file.name}")

        # XeLaTeX 확인
        if not self.font_manager.verify_xelatex():
            raise RuntimeError("XeLaTeX 컴파일러를 찾을 수 없습니다.")

        tex_dir = tex_file.parent
        tex_filename = tex_file.name
        tex_stem = tex_file.stem

        # bibtex 실행 (.bib 파일이 있는 경우)
        bib_files = list(tex_dir.rglob("*.bib"))
        if bib_files:
            # 1차 xelatex로 .aux 생성
            logger.info("컴파일 준비: xelatex (aux 생성)...")
            subprocess.run(
                ['xelatex', '-interaction=nonstopmode', tex_filename],
                cwd=tex_dir, capture_output=True, text=True, timeout=300
            )
            # bibtex 실행
            logger.info("컴파일 준비: bibtex (참고문헌 처리)...")
            subprocess.run(
                ['bibtex', tex_stem],
                cwd=tex_dir, capture_output=True, text=True, timeout=60
            )

        # 컴파일 실행
        compile_count = 2 if compile_twice else 1

        for i in range(compile_count):
            logger.info(f"컴파일 {i+1}/{compile_count} 실행 중...")

            try:
                result = subprocess.run(
                    ['xelatex', '-interaction=nonstopmode', tex_filename],
                    cwd=tex_dir,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5분 타임아웃
                )

                # 에러 확인
                if result.returncode != 0:
                    logger.warning(f"⚠ 컴파일 경고/에러 발생 (returncode: {result.returncode})")
                    # 에러 로그에서 중요한 부분만 추출
                    self._log_compile_errors(result.stdout)

            except subprocess.TimeoutExpired:
                logger.error("❌ 컴파일 타임아웃 (5분 초과)")
                return None
            except Exception as e:
                logger.error(f"❌ 컴파일 실패: {e}")
                return None

        # PDF 파일 확인
        pdf_file = tex_dir / tex_file.stem.replace('.tex', '.pdf')

        if not pdf_file.exists():
            # .pdf 확장자가 없는 경우도 확인
            pdf_file = tex_dir / f"{tex_file.stem}.pdf"

        if not pdf_file.exists():
            logger.error("❌ PDF 파일이 생성되지 않았습니다.")
            logger.error("컴파일 로그를 확인하세요:")
            log_file = tex_dir / f"{tex_file.stem}.log"
            if log_file.exists():
                logger.error(f"  로그 파일: {log_file}")
            return None

        # 출력 디렉토리로 이동
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            final_pdf = output_dir / pdf_file.name

            pdf_file.rename(final_pdf)
            logger.info(f"✓ PDF 이동: {final_pdf}")
            pdf_file = final_pdf

        logger.info(f"✓ PDF 컴파일 완료: {pdf_file}")
        return pdf_file

    def _log_compile_errors(self, log_output: str) -> None:
        """컴파일 로그에서 에러/경고 추출 및 분류"""
        errors = []
        warnings = []

        for line in log_output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # LaTeX 치명적 에러
            if stripped.startswith('!') or 'Fatal error' in stripped:
                errors.append(stripped)
            # 패키지/폰트 에러
            elif re.match(r'.*(Error|error).*', stripped) and 'Warning' not in stripped:
                errors.append(stripped)
            # 경고 (패키지 충돌, 누락 폰트 등)
            elif re.match(r'.*(Warning|warning).*', stripped):
                warnings.append(stripped)
            # 누락 파일/폰트
            elif 'Missing' in stripped or 'not found' in stripped:
                warnings.append(stripped)

        if errors:
            logger.warning(f"  컴파일 에러 ({len(errors)}개):")
            for line in errors[:15]:
                logger.warning(f"    ❌ {line}")
        if warnings:
            # 중복 제거
            unique_warnings = list(dict.fromkeys(warnings))
            logger.warning(f"  컴파일 경고 ({len(unique_warnings)}개):")
            for line in unique_warnings[:15]:
                logger.warning(f"    ⚠ {line}")

    def compile_directory(
        self,
        directory: Path,
        output_dir: Optional[Path] = None,
        main_font: Optional[str] = None,
        mono_font: Optional[str] = None
    ) -> Optional[Path]:
        """디렉토리에서 메인 .tex 파일을 찾아 컴파일

        Args:
            directory: LaTeX 소스 디렉토리
            output_dir: PDF 출력 디렉토리
            main_font: 주 폰트
            mono_font: 고정폭 폰트

        Returns:
            생성된 PDF 파일 경로 (실패 시 None)
        """
        # 메인 파일 찾기
        main_tex = self.find_main_tex_file(directory)

        if not main_tex:
            logger.error("메인 .tex 파일을 찾을 수 없습니다.")
            return None

        # 모든 .tex, .cls, .sty 파일에서 충돌 패키지 제거
        # .cls/.sty도 포함: 논문 동봉 클래스 파일이 fontenc/inputenc를
        # \RequirePackage로 로드하면 xeCJK/fontspec과 충돌
        auxiliary_files = []
        for ext in ("*.tex", "*.cls", "*.sty"):
            auxiliary_files.extend(
                f for f in directory.rglob(ext)
                if "_original" not in f.name
            )
        for aux_file in auxiliary_files:
            if aux_file != main_tex:
                self.remove_conflicting_packages(aux_file)

        # cls/sty 파일에서 xeCJK와 충돌하는 폰트 패키지를 주석 처리하고 수집
        # (xeCJK 이후에 다시 로드해야 하므로)
        relocated_packages = self._relocate_font_packages(directory)

        # 번역으로 생긴 잘못된 제어 시퀀스 정리 (메인 + 모든 서브 파일)
        for tex_file in directory.rglob("*.tex"):
            if "_original" not in tex_file.name and tex_file.with_suffix(
                '.tex_original'
            ).exists():
                self.sanitize_translated_tex(tex_file)

        # 보조 .tex 파일에서 \newcommand 충돌 방지
        # sanitize 이후에 실행해야 sanitize가 \providecommand의 \ 를 제거하지 않음
        for aux_file in auxiliary_files:
            if aux_file != main_tex:
                self._soften_newcommands(aux_file)

        # 메인 파일에 폰트 설정 추가 (내부에서 충돌 패키지 제거 포함)
        self.add_font_configuration(
            main_tex, main_font, mono_font,
            extra_packages=relocated_packages,
        )

        # 컴파일
        pdf_file = self.compile_to_pdf(main_tex, output_dir)

        return pdf_file
