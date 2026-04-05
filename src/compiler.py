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

        # 정규식 패턴으로도 매칭 (옵션이 다를 수 있으므로)
        conflict_patterns = [
            re.compile(r'\\usepackage(\[.*?\])?\{inputenc\}'),
            re.compile(r'\\usepackage(\[.*?\])?\{fontenc\}'),
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

    def add_font_configuration(
        self,
        tex_file: Path,
        main_font: Optional[str] = None,
        mono_font: Optional[str] = None
    ) -> None:
        """한글 폰트 설정 추가

        Args:
            tex_file: .tex 파일 경로
            main_font: 주 폰트 (없으면 자동 감지)
            mono_font: 고정폭 폰트 (없으면 자동 감지)
        """
        logger.info(f"폰트 설정 추가: {tex_file}")

        # XeLaTeX 충돌 패키지 제거
        self.remove_conflicting_packages(tex_file)

        # 폰트 설정 생성
        font_config = self.font_manager.generate_latex_font_config(
            main_font=main_font,
            mono_font=mono_font
        )

        try:
            with open(tex_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # \\begin{document} 바로 앞에 폰트 설정 삽입
            # 이 위치가 가장 안전: 모든 조건문/패키지 로드 이후, 문서 시작 전
            inserted = False
            for i, line in enumerate(lines):
                if r'\begin{document}' in line and not line.strip().startswith('%'):
                    lines.insert(i, font_config + '\n')
                    inserted = True
                    break

            if not inserted:
                # fallback: 마지막 \documentclass 바로 뒤
                for i in range(len(lines) - 1, -1, -1):
                    if r'\documentclass' in lines[i] and not lines[i].strip().startswith('%'):
                        lines.insert(i + 1, font_config + '\n')
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

    def fix_spurious_commands(self, tex_file: Path) -> None:
        """번역 과정에서 LLM이 생성한 잘못된 제어 시퀀스를 수정

        원본에 없는 \\word 패턴을 찾아 백슬래시를 제거합니다.
        예: \\maximiz → maximiz, \\compact → compact
        """
        # 원본 파일에서 사용된 명령어 수집
        backup_file = tex_file.with_suffix('.tex_original')
        if not backup_file.exists():
            return

        original_content = backup_file.read_text(encoding='utf-8')
        # 원본에서 사용된 모든 \command 패턴 수집
        original_cmds = set(re.findall(r'\\([a-zA-Z]+)', original_content))
        # LaTeX 내장 명령어 추가 (원본에 없어도 유효한 것들)
        builtin_cmds = {
            'textbf', 'textit', 'emph', 'text', 'mathrm', 'mathbf', 'mathit',
            'section', 'subsection', 'subsubsection', 'paragraph',
            'begin', 'end', 'item', 'label', 'ref', 'cite', 'caption',
            'footnote', 'footnotetext', 'thanks',
            'centering', 'includegraphics', 'usepackage', 'newcommand',
            'renewcommand', 'def', 'let', 'hline', 'toprule', 'midrule',
            'bottomrule', 'cline', 'multicolumn', 'multirow',
            'vspace', 'hspace', 'noindent', 'par', 'newline', 'linebreak',
            'small', 'footnotesize', 'scriptsize', 'tiny', 'large', 'Large',
            'LARGE', 'huge', 'Huge', 'normalsize',
            'it', 'bf', 'rm', 'sf', 'tt', 'sc', 'sl',
        }
        valid_cmds = original_cmds | builtin_cmds

        # 번역된 파일에서 잘못된 명령어 탐지 및 수정
        content = tex_file.read_text(encoding='utf-8')
        translated_cmds = set(re.findall(r'\\([a-zA-Z]+)', content))
        spurious = translated_cmds - valid_cmds

        if not spurious:
            return

        fixed_count = 0
        for cmd in spurious:
            # \cmd → cmd (백슬래시 제거)
            pattern = re.compile(r'\\' + re.escape(cmd) + r'(?![a-zA-Z])')
            if pattern.search(content):
                content = pattern.sub(cmd, content)
                fixed_count += 1
                logger.debug(f"  잘못된 명령어 수정: \\{cmd} → {cmd}")

        # 2. \(한글) 패턴 수정 — "vs.\ (right)" → "\(우)" 수식 모드 오인 방지
        # \( 뒤에 한글이 오면 수식이 아니라 번역 오류
        math_fix_count = 0
        fixed_content = re.sub(
            r'\\[(]([가-힣])',
            lambda m: '(' + m.group(1),
            content
        )
        if fixed_content != content:
            math_fix_count = len(content) - len(fixed_content) + content.count(r'\(') - fixed_content.count(r'\(')
            content = fixed_content
            fixed_count += 1

        # 3. list 환경 밖의 \item 감지 및 주석 처리
        list_pattern = re.compile(r'\\(begin|end)\{(itemize|enumerate|description)\}')
        lines = content.split('\n')
        list_depth = 0
        for idx, line in enumerate(lines):
            # \item 체크는 \begin/\end 처리 전에 수행
            # (같은 줄에 \item과 \end{itemize}가 있으면 \item은 아직 list 안)
            if list_depth == 0 and line.lstrip().startswith('\\item '):
                lines[idx] = '%% [auto-fixed] ' + line
                fixed_count += 1
                logger.debug(f"  고아 \\item 주석 처리: 줄 {idx}")
            for m in list_pattern.finditer(line):
                if m.group(1) == 'begin':
                    list_depth += 1
                else:
                    list_depth = max(0, list_depth - 1)
        content = '\n'.join(lines)

        if fixed_count > 0:
            tex_file.write_text(content, encoding='utf-8')
            logger.info(f"🔧 잘못된 제어 시퀀스 {fixed_count}개 수정")

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

        # 모든 .tex 파일에서 충돌 패키지 제거 (서브 파일 포함)
        all_tex_files = [
            f for f in directory.rglob("*.tex")
            if "_original" not in f.name
        ]
        for tex_file in all_tex_files:
            if tex_file != main_tex:
                self.remove_conflicting_packages(tex_file)

        # 번역으로 생긴 잘못된 제어 시퀀스 정리
        self.fix_spurious_commands(main_tex)

        # 메인 파일에 폰트 설정 추가 (내부에서 충돌 패키지 제거 포함)
        self.add_font_configuration(main_tex, main_font, mono_font)

        # 컴파일
        pdf_file = self.compile_to_pdf(main_tex, output_dir)

        return pdf_file
