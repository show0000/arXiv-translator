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

            # \\documentclass 다음에 폰트 설정 삽입
            for i, line in enumerate(lines):
                if line.startswith(r'\documentclass'):
                    lines.insert(i + 1, font_config + '\n')
                    break

            with open(tex_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info("✓ 폰트 설정 추가 완료")

        except Exception as e:
            logger.error(f"폰트 설정 추가 실패: {e}")
            raise

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
        """컴파일 로그에서 에러 추출"""
        # 중요한 에러만 추출
        error_patterns = [
            r'! .*',  # LaTeX 에러
            r'.*Error.*',  # 일반 에러
            r'.*Warning.*',  # 경고
        ]

        important_lines = []
        for line in log_output.splitlines():
            for pattern in error_patterns:
                if re.match(pattern, line):
                    important_lines.append(line)
                    break

        if important_lines:
            logger.debug("컴파일 로그 (중요 부분):")
            for line in important_lines[:20]:  # 최대 20줄만
                logger.debug(f"  {line}")

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

        # 폰트 설정 추가
        self.add_font_configuration(main_tex, main_font, mono_font)

        # 컴파일
        pdf_file = self.compile_to_pdf(main_tex, output_dir)

        return pdf_file
