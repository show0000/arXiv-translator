#!/usr/bin/env python3
"""arXiv 논문 한글 번역기

arXiv 논문을 다운로드하고 LaTeX 소스를 번역하여 한글 PDF를 생성합니다.
"""

import logging
import os
import sys
from pathlib import Path

import click

from src.compiler import LatexCompiler
from src.config import TranslationConfig
from src.downloader import ArxivDownloader
from src.font_manager import FontManager
from src.translator import ClaudeProvider, LatexTranslator, OpenAIProvider

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


@click.command()
@click.argument('arxiv_id', required=False)
@click.option(
    '--config', '-c',
    type=click.Path(exists=True),
    default='config.yaml',
    help='설정 파일 경로 (기본: config.yaml)'
)
@click.option(
    '--provider',
    type=click.Choice(['openai', 'claude'], case_sensitive=False),
    help='LLM 제공자 (openai/claude)'
)
@click.option(
    '--model', '-m',
    help='사용할 모델 (예: gpt-4, claude-3-5-sonnet-20241022)'
)
@click.option(
    '--api-key',
    envvar='ARXIV_TRANSLATOR_API_KEY',
    help='API 키 (또는 환경변수 ARXIV_TRANSLATOR_API_KEY)'
)
@click.option(
    '--target-language', '-l',
    default='Korean',
    help='목표 언어 (기본: Korean)'
)
@click.option(
    '--custom-prompt',
    type=click.Path(exists=True),
    help='커스텀 번역 프롬프트 파일'
)
@click.option(
    '--main-font',
    help='주 폰트 (예: Noto Sans KR)'
)
@click.option(
    '--mono-font',
    help='고정폭 폰트 (예: Noto Sans Mono CJK KR)'
)
@click.option(
    '--output-dir', '-o',
    type=click.Path(),
    default='output',
    help='출력 디렉토리 (기본: output)'
)
@click.option(
    '--chunk-size',
    type=int,
    help='번역 청크 크기 (기본: 100)'
)
@click.option(
    '--force',
    is_flag=True,
    help='기존 다운로드 파일 무시하고 재다운로드'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='상세 로그 출력'
)
@click.option(
    '--generate-config',
    is_flag=True,
    help='기본 config.yaml 생성 후 종료'
)
def main(
    arxiv_id: str,
    config: str,
    provider: str,
    model: str,
    api_key: str,
    target_language: str,
    custom_prompt: str,
    main_font: str,
    mono_font: str,
    output_dir: str,
    chunk_size: int,
    force: bool,
    verbose: bool,
    generate_config: bool
):
    """arXiv 논문을 한글로 번역합니다.

    ARXIV_ID: arXiv 논문 ID 또는 URL (예: 2301.12345 또는 https://arxiv.org/abs/2301.12345)

    예시:

        # OpenAI로 번역
        python main.py 2301.12345 --provider openai --model gpt-4 --api-key sk-...

        # Claude로 번역
        python main.py 2301.12345 --provider claude --model claude-3-5-sonnet-20241022 --api-key sk-ant-...

        # 설정 파일 생성
        python main.py --generate-config
    """
    # 상세 로그 설정
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 설정 파일 생성
    if generate_config:
        default_config = TranslationConfig()
        default_config.to_yaml('config.yaml')
        click.echo("✓ config.yaml 생성 완료")
        click.echo("\n설정을 수정한 후 다음 명령으로 실행하세요:")
        click.echo("  python main.py <arxiv-id> --api-key <your-api-key>")
        return

    # arxiv_id 필수 확인
    if not arxiv_id:
        click.echo("❌ arXiv ID를 입력하세요.")
        click.echo("\n사용법: python main.py <arxiv-id> [옵션]")
        click.echo("도움말: python main.py --help")
        sys.exit(1)

    try:
        # 1. 설정 로드
        logger.info("=" * 60)
        logger.info("arXiv 논문 한글 번역기")
        logger.info("=" * 60)

        # YAML 설정 로드
        translation_config = TranslationConfig.from_yaml(config)

        # CLI 인자로 오버라이드
        translation_config.merge_cli_args(
            provider=provider,
            model=model,
            api_key=api_key,
            target_language=target_language,
            custom_instruction_file=custom_prompt,
            main_font=main_font,
            mono_font=mono_font,
            output_dir=output_dir,
            chunk_size=chunk_size,
            force_download=force,
        )

        # API 키 환경 변수 확인
        if not translation_config.api_key:
            if translation_config.provider == "openai":
                translation_config.api_key = os.getenv("OPENAI_API_KEY")
            elif translation_config.provider == "claude":
                translation_config.api_key = os.getenv("ANTHROPIC_API_KEY")

        # 설정 검증
        translation_config.validate()

        logger.info(f"LLM: {translation_config.get_provider_display_name()}")
        logger.info(f"목표 언어: {translation_config.target_language}")
        logger.info("")

        # 2. 다운로드
        logger.info("[1/4] arXiv 논문 다운로드")
        downloader = ArxivDownloader(download_dir=translation_config.download_dir)
        metadata, source_dir = downloader.download_and_extract(
            arxiv_id,
            force=translation_config.force_download
        )

        logger.info(f"✓ 논문: {metadata['title']}")
        logger.info(f"✓ 소스: {source_dir}")
        logger.info("")

        # 3. 번역
        logger.info("[2/4] LaTeX 파일 번역")

        # LLM 제공자 초기화
        if translation_config.provider == "openai":
            llm_provider = OpenAIProvider(
                api_key=translation_config.api_key,
                model=translation_config.model
            )
        elif translation_config.provider == "claude":
            llm_provider = ClaudeProvider(
                api_key=translation_config.api_key,
                model=translation_config.model
            )
        else:
            raise ValueError(f"지원하지 않는 제공자: {translation_config.provider}")

        # 번역기 초기화
        translator = LatexTranslator(
            provider=llm_provider,
            target_language=translation_config.target_language,
            chunk_size=translation_config.chunk_size,
            max_workers=translation_config.max_workers,
            custom_instruction=translation_config.custom_instruction
        )

        # 번역 실행
        translated_files = translator.translate_directory(source_dir, metadata)

        logger.info(f"✓ 번역 완료: {len(translated_files)}개 파일")
        logger.info("")

        # 4. 컴파일
        logger.info("[3/4] PDF 컴파일")

        font_manager = FontManager()
        compiler = LatexCompiler(font_manager=font_manager)

        pdf_file = compiler.compile_directory(
            directory=source_dir,
            output_dir=Path(translation_config.output_dir),
            main_font=translation_config.main_font,
            mono_font=translation_config.mono_font
        )

        if not pdf_file:
            logger.error("❌ PDF 생성 실패")
            sys.exit(1)

        logger.info(f"✓ PDF 생성: {pdf_file}")
        logger.info("")

        # 5. 완료
        logger.info("[4/4] 완료!")
        logger.info("=" * 60)
        logger.info(f"📄 논문: {metadata['title']}")
        logger.info(f"📁 출력: {pdf_file.absolute()}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.warning("\n\n중단됨")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ 오류 발생: {e}", exc_info=verbose)
        sys.exit(1)


if __name__ == '__main__':
    main()
