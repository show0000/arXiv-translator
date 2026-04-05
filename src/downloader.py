"""arXiv 논문 다운로드 모듈

arXiv API를 통해 논문 메타데이터를 가져오고, 소스 파일을 다운로드합니다.
"""

import logging
import os
import re
import shutil
import tarfile
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ArxivDownloader:
    """arXiv 논문 다운로드 및 압축 해제"""

    ARXIV_API_URL = "https://export.arxiv.org/api/query"
    ARXIV_SOURCE_URL = "https://arxiv.org/src"

    def __init__(self, download_dir: str = "arxiv_downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def extract_arxiv_id(self, url_or_id: str) -> str:
        """URL 또는 arXiv ID에서 순수 ID 추출

        Args:
            url_or_id: arXiv URL 또는 ID
                예: https://arxiv.org/abs/2301.12345
                    arxiv.org/pdf/2301.12345.pdf
                    2301.12345

        Returns:
            arXiv ID (예: 2301.12345)
        """
        logger.debug(f"arXiv ID 추출: {url_or_id}")

        # URL인 경우 ID 추출
        if 'arxiv.org' in url_or_id:
            # URL 패턴 매칭
            match = re.search(r'(\d{4}\.\d{4,5})(v\d+)?', url_or_id)
            if match:
                arxiv_id = match.group(1)
                logger.debug(f"추출된 ID: {arxiv_id}")
                return arxiv_id

        # 이미 ID 형식인 경우
        arxiv_id = url_or_id.strip()
        logger.debug(f"입력이 ID 형식: {arxiv_id}")
        return arxiv_id

    def fetch_paper_metadata(self, arxiv_id: str) -> dict:
        """arXiv API를 통해 논문 메타데이터 가져오기

        Args:
            arxiv_id: arXiv 논문 ID

        Returns:
            논문 메타데이터 (title, abstract, authors 등)

        Raises:
            requests.RequestException: API 호출 실패
            ValueError: 논문을 찾을 수 없음
        """
        logger.info(f"논문 메타데이터 조회: {arxiv_id}")

        api_url = f"{self.ARXIV_API_URL}?id_list={arxiv_id}"

        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"arXiv API 호출 실패: {e}")
            raise

        # XML 파싱
        soup = BeautifulSoup(response.content, 'xml')
        entry = soup.find('entry')

        if not entry:
            logger.error(f"논문을 찾을 수 없음: {arxiv_id}")
            raise ValueError(f"arXiv에서 논문을 찾을 수 없습니다: {arxiv_id}")

        # 메타데이터 추출
        metadata = {
            'id': arxiv_id,
            'title': entry.find('title').text.strip(),
            'abstract': entry.find('summary').text.strip(),
            'authors': [author.find('name').text for author in entry.find_all('author')],
            'published': entry.find('published').text if entry.find('published') else None,
            'updated': entry.find('updated').text if entry.find('updated') else None,
        }

        logger.info(f"논문 정보: {metadata['title']}")
        logger.debug(f"저자: {', '.join(metadata['authors'][:3])}...")
        return metadata

    def download_source(self, arxiv_id: str, force: bool = False) -> Path:
        """arXiv 소스 파일 다운로드

        Args:
            arxiv_id: arXiv 논문 ID
            force: 기존 파일이 있어도 다시 다운로드

        Returns:
            다운로드된 tar.gz 파일 경로

        Raises:
            requests.RequestException: 다운로드 실패
        """
        tar_file_path = self.download_dir / f"{arxiv_id}.tar.gz"

        if tar_file_path.exists() and not force:
            logger.info(f"이미 다운로드된 파일 사용: {tar_file_path}")
            return tar_file_path

        logger.info(f"소스 파일 다운로드 중: {arxiv_id}")

        source_url = f"{self.ARXIV_SOURCE_URL}/{arxiv_id}"

        try:
            with requests.get(source_url, stream=True, timeout=60) as r:
                r.raise_for_status()

                # 파일 크기 확인
                total_size = int(r.headers.get('content-length', 0))
                logger.info(f"파일 크기: {total_size / 1024 / 1024:.2f} MB")

                # 다운로드
                with open(tar_file_path, 'wb') as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                        # 진행률 표시 (10% 단위)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if int(progress) % 10 == 0:
                                logger.debug(f"다운로드 진행: {progress:.1f}%")

            logger.info(f"✓ 다운로드 완료: {tar_file_path}")
            return tar_file_path

        except requests.RequestException as e:
            logger.error(f"소스 파일 다운로드 실패: {e}")
            if tar_file_path.exists():
                tar_file_path.unlink()  # 불완전한 파일 삭제
            raise

    def extract_source(self, tar_file_path: Path, extract_dir: Optional[Path] = None) -> Path:
        """tar.gz 파일 압축 해제

        Args:
            tar_file_path: tar.gz 파일 경로
            extract_dir: 압축 해제 디렉토리 (없으면 자동 생성)

        Returns:
            압축 해제된 디렉토리 경로

        Raises:
            tarfile.TarError: 압축 해제 실패
        """
        if extract_dir is None:
            # 파일명에서 arXiv ID 추출
            arxiv_id = tar_file_path.stem.replace('.tar', '')
            extract_dir = self.download_dir / arxiv_id

        # 기존 디렉토리 삭제
        if extract_dir.exists():
            logger.info(f"기존 디렉토리 삭제: {extract_dir}")
            shutil.rmtree(extract_dir)

        extract_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"압축 해제 중: {tar_file_path} → {extract_dir}")

        try:
            with tarfile.open(tar_file_path, 'r:gz') as tar_ref:
                tar_ref.extractall(path=extract_dir)

            # 압축 해제된 파일 개수 확인
            file_count = sum(1 for _ in extract_dir.rglob('*') if _.is_file())
            logger.info(f"✓ 압축 해제 완료: {file_count}개 파일")

            return extract_dir

        except tarfile.TarError as e:
            logger.error(f"압축 해제 실패: {e}")
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            raise

    def download_and_extract(self, url_or_id: str, force: bool = False) -> tuple[dict, Path]:
        """논문 다운로드 및 압축 해제 (통합 메서드)

        Args:
            url_or_id: arXiv URL 또는 ID
            force: 기존 파일이 있어도 다시 다운로드

        Returns:
            (메타데이터, 압축 해제된 디렉토리 경로)
        """
        # ID 추출
        arxiv_id = self.extract_arxiv_id(url_or_id)

        # 메타데이터 가져오기
        metadata = self.fetch_paper_metadata(arxiv_id)

        # 소스 다운로드
        tar_file = self.download_source(arxiv_id, force=force)

        # 압축 해제
        source_dir = self.extract_source(tar_file)

        return metadata, source_dir
