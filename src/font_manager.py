"""한글 폰트 관리 모듈

시스템에 설치된 한글 폰트를 감지하고, LaTeX 컴파일에 적합한 폰트를 선택합니다.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FontManager:
    """한글 폰트 자동 감지 및 관리"""

    # 우선순위가 높은 순서로 정렬된 한글 폰트 목록
    PREFERRED_FONTS = [
        "Noto Sans KR",
        "Noto Sans CJK KR",
        "Noto Serif KR",
        "Noto Serif CJK KR",
        "NanumGothic",
        "NanumMyeongjo",
        "Nanum Gothic",
        "Nanum Myeongjo",
        "AppleSDGothicNeo",  # macOS
        "Malgun Gothic",     # Windows
        "Batang",           # Windows
    ]

    MONO_FONTS = [
        "Noto Sans Mono CJK KR",
        "NanumGothicCoding",
        "D2Coding",
        "Menlo",  # macOS fallback
        "Courier New",  # Universal fallback
    ]

    def __init__(self):
        self.system = platform.system()
        self._font_cache = None

    def get_available_fonts(self) -> list[str]:
        """시스템에 설치된 모든 폰트 목록 조회 (캐싱)"""
        if self._font_cache is not None:
            return self._font_cache

        logger.info(f"시스템 폰트 조회 중... (OS: {self.system})")

        if self.system == "Darwin":  # macOS
            fonts = self._get_macos_fonts()
        elif self.system == "Linux":
            fonts = self._get_linux_fonts()
        elif self.system == "Windows":
            fonts = self._get_windows_fonts()
        else:
            logger.warning(f"지원하지 않는 OS: {self.system}")
            fonts = []

        self._font_cache = fonts
        logger.info(f"총 {len(fonts)}개의 폰트 발견")
        return fonts

    def _get_macos_fonts(self) -> list[str]:
        """macOS 폰트 목록 조회"""
        try:
            # fc-list를 사용하여 폰트 조회 (fontconfig가 설치되어 있는 경우)
            result = subprocess.run(
                ["fc-list", ":", "family"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                fonts = set()
                for line in result.stdout.splitlines():
                    # 여러 폰트 패밀리가 쉼표로 구분되어 있을 수 있음
                    for font in line.split(','):
                        fonts.add(font.strip())
                return list(fonts)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.debug("fc-list를 사용할 수 없음, 폰트 경로 직접 스캔")

        # Fallback: 폰트 디렉토리 직접 스캔
        font_dirs = [
            Path.home() / "Library/Fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
        ]

        fonts = set()
        for font_dir in font_dirs:
            if font_dir.exists():
                for font_file in font_dir.rglob("*.[ot]tf"):
                    # 파일명에서 폰트 이름 추출 (간단한 방법)
                    font_name = font_file.stem.replace("-", " ")
                    fonts.add(font_name)

        return list(fonts)

    def _get_linux_fonts(self) -> list[str]:
        """Linux 폰트 목록 조회"""
        try:
            result = subprocess.run(
                ["fc-list", ":", "family"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                fonts = set()
                for line in result.stdout.splitlines():
                    for font in line.split(','):
                        fonts.add(font.strip())
                return list(fonts)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error("fc-list를 찾을 수 없습니다. fontconfig를 설치해주세요.")
            return []

    def _get_windows_fonts(self) -> list[str]:
        """Windows 폰트 목록 조회"""
        try:
            import winreg

            fonts = set()
            registry_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
            )

            for i in range(winreg.QueryInfoKey(registry_key)[1]):
                font_name, _, _ = winreg.EnumValue(registry_key, i)
                # "(TrueType)" 등의 접미사 제거
                font_name = font_name.split('(')[0].strip()
                fonts.add(font_name)

            winreg.CloseKey(registry_key)
            return list(fonts)
        except Exception as e:
            logger.error(f"Windows 폰트 조회 실패: {e}")
            return []

    def find_korean_font(self, preferred_font: Optional[str] = None) -> str:
        """한글 폰트 찾기

        Args:
            preferred_font: 사용자가 지정한 선호 폰트 (없으면 자동 선택)

        Returns:
            사용 가능한 한글 폰트 이름

        Raises:
            RuntimeError: 사용 가능한 한글 폰트가 없는 경우
        """
        available_fonts = self.get_available_fonts()

        # 사용자 지정 폰트가 있으면 우선 확인
        if preferred_font:
            if self._is_font_available(preferred_font, available_fonts):
                logger.info(f"✓ 사용자 지정 폰트 사용: {preferred_font}")
                return preferred_font
            else:
                logger.warning(f"⚠ 지정한 폰트를 찾을 수 없음: {preferred_font}")

        # 우선순위 목록에서 사용 가능한 폰트 찾기
        for font in self.PREFERRED_FONTS:
            if self._is_font_available(font, available_fonts):
                logger.info(f"✓ 한글 폰트 발견: {font}")
                return font

        # 한글 폰트를 찾지 못한 경우
        logger.error("❌ 시스템에 한글 폰트가 설치되어 있지 않습니다.")
        logger.error("다음 폰트 중 하나를 설치해주세요:")
        for font in self.PREFERRED_FONTS[:5]:
            logger.error(f"  - {font}")

        raise RuntimeError("사용 가능한 한글 폰트가 없습니다.")

    def find_mono_font(self, preferred_font: Optional[str] = None) -> str:
        """고정폭 한글 폰트 찾기"""
        available_fonts = self.get_available_fonts()

        if preferred_font:
            if self._is_font_available(preferred_font, available_fonts):
                logger.info(f"✓ 사용자 지정 고정폭 폰트 사용: {preferred_font}")
                return preferred_font

        for font in self.MONO_FONTS:
            if self._is_font_available(font, available_fonts):
                logger.info(f"✓ 고정폭 폰트 발견: {font}")
                return font

        # Fallback: 일반 한글 폰트 사용
        logger.warning("고정폭 한글 폰트를 찾지 못함, 일반 폰트 사용")
        return self.find_korean_font()

    def _is_font_available(self, font_name: str, available_fonts: list[str]) -> bool:
        """폰트가 사용 가능한지 확인 (부분 일치 포함)"""
        # 정확한 일치
        if font_name in available_fonts:
            return True

        # 대소문자 무시 일치
        font_lower = font_name.lower()
        for available in available_fonts:
            if available.lower() == font_lower:
                return True

        # 부분 일치 (공백/하이픈 무시)
        font_normalized = font_name.replace(" ", "").replace("-", "").lower()
        for available in available_fonts:
            available_normalized = available.replace(" ", "").replace("-", "").lower()
            if font_normalized in available_normalized or available_normalized in font_normalized:
                return True

        return False

    def generate_latex_font_config(
        self,
        main_font: Optional[str] = None,
        mono_font: Optional[str] = None
    ) -> str:
        """LaTeX 폰트 설정 코드 생성

        Args:
            main_font: 주 폰트 (없으면 자동 감지)
            mono_font: 고정폭 폰트 (없으면 자동 감지)

        Returns:
            LaTeX preamble에 삽입할 폰트 설정 코드
        """
        try:
            main_font = main_font or self.find_korean_font()
            mono_font = mono_font or self.find_mono_font()
        except RuntimeError as e:
            logger.error(f"폰트 설정 생성 실패: {e}")
            raise

        # XeLaTeX 전용 폰트 설정 (kotex 제거, xeCJK만 사용하여 충돌 방지)
        # FakeSlant는 ItalicFont에만 적용, FakeBold는 BoldFont에만 적용
        font_config = f"""
% Korean font configuration (XeLaTeX + xeCJK)
\\usepackage{{xeCJK}}
\\setCJKmainfont{{{main_font}}}[
    BoldFont={{{main_font}}},
    BoldFeatures={{FakeBold=1.5}},
    ItalicFont={{{main_font}}},
    ItalicFeatures={{FakeSlant=0.2}},
    BoldItalicFont={{{main_font}}},
    BoldItalicFeatures={{FakeBold=1.5, FakeSlant=0.2}}
]
\\setCJKsansfont{{{main_font}}}[
    BoldFont={{{main_font}}},
    BoldFeatures={{FakeBold=1.5}},
    ItalicFont={{{main_font}}},
    ItalicFeatures={{FakeSlant=0.2}},
    BoldItalicFont={{{main_font}}},
    BoldItalicFeatures={{FakeBold=1.5, FakeSlant=0.2}}
]
\\setCJKmonofont{{{mono_font}}}
\\xeCJKsetup{{CJKspace=true}}
"""

        logger.info(f"LaTeX 폰트 설정 생성 완료 (main: {main_font}, mono: {mono_font})")
        return font_config

    def verify_xelatex(self) -> bool:
        """XeLaTeX 컴파일러 설치 확인"""
        try:
            result = subprocess.run(
                ["xelatex", "--version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("✓ XeLaTeX 컴파일러 확인됨")
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        logger.error("❌ XeLaTeX 컴파일러를 찾을 수 없습니다.")
        logger.error("LaTeX 배포판을 설치해주세요:")
        logger.error("  - macOS: brew install --cask mactex")
        logger.error("  - Linux: sudo apt-get install texlive-xetex texlive-lang-korean")
        logger.error("  - Windows: https://www.tug.org/texlive/")
        return False
