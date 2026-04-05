"""설정 관리 모듈

YAML 설정 파일 및 CLI 인자 처리
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TranslationConfig:
    """번역 설정"""

    # LLM 설정
    provider: str = "openai"  # openai, claude
    model: str = "gpt-4"
    api_key: Optional[str] = None

    # 번역 설정
    target_language: str = "Korean"
    dynamic_chunking: bool = True
    custom_instruction: Optional[str] = None
    custom_instruction_file: Optional[str] = None

    # 폰트 설정
    main_font: Optional[str] = None
    mono_font: Optional[str] = None

    # 출력 설정
    output_dir: str = "output"
    download_dir: str = "arxiv_downloads"

    # 기타
    force_download: bool = False
    compile_twice: bool = True

    def __post_init__(self):
        """초기화 후 처리"""
        # 커스텀 프롬프트 파일 읽기
        if self.custom_instruction_file:
            instruction_path = Path(self.custom_instruction_file)
            if instruction_path.exists():
                with open(instruction_path, 'r', encoding='utf-8') as f:
                    self.custom_instruction = f.read()
                logger.info(f"커스텀 프롬프트 로드: {instruction_path}")
            else:
                logger.warning(f"커스텀 프롬프트 파일을 찾을 수 없음: {instruction_path}")

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "TranslationConfig":
        """YAML 파일에서 설정 로드

        Args:
            yaml_path: YAML 설정 파일 경로

        Returns:
            TranslationConfig 인스턴스
        """
        config_file = Path(yaml_path)

        if not config_file.exists():
            logger.warning(f"설정 파일을 찾을 수 없음: {yaml_path}")
            logger.info("기본 설정 사용")
            return cls()

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            logger.info(f"설정 파일 로드: {yaml_path}")
            return cls(**data)

        except Exception as e:
            logger.error(f"설정 파일 로드 실패: {e}")
            logger.info("기본 설정 사용")
            return cls()

    def to_yaml(self, yaml_path: str) -> None:
        """설정을 YAML 파일로 저장

        Args:
            yaml_path: 저장할 YAML 파일 경로
        """
        config_file = Path(yaml_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # dataclass를 dict로 변환
        data = {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_')
        }

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

            logger.info(f"설정 저장: {yaml_path}")

        except Exception as e:
            logger.error(f"설정 저장 실패: {e}")

    def merge_cli_args(self, **kwargs) -> "TranslationConfig":
        """CLI 인자로 설정 오버라이드

        Args:
            **kwargs: CLI에서 전달된 인자

        Returns:
            병합된 설정
        """
        # None이 아닌 값만 오버라이드
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key):
                setattr(self, key, value)
                logger.debug(f"설정 오버라이드: {key}={value}")

        return self

    def validate(self) -> None:
        """설정 검증

        Raises:
            ValueError: 잘못된 설정
        """
        # API 키 확인
        if not self.api_key:
            raise ValueError(
                f"{self.provider.upper()} API 키가 설정되지 않았습니다. "
                f"--api-key 옵션을 사용하거나 환경 변수를 설정하세요."
            )

        # 제공자 확인
        if self.provider not in ["openai", "claude"]:
            raise ValueError(f"지원하지 않는 LLM 제공자: {self.provider}")

        logger.debug("설정 검증 완료")

    def get_provider_display_name(self) -> str:
        """제공자 표시 이름"""
        return f"{self.provider.capitalize()}/{self.model}"
