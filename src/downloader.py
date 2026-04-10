"""arXiv 논문 다운로드 모듈

arXiv API를 통해 논문 메타데이터를 가져오고, 소스 파일을 다운로드합니다.
"""

import logging
import os
import re
import shutil
import tarfile
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ArxivDownloader:
    """arXiv 논문 다운로드 및 압축 해제"""

    ARXIV_API_URL = "https://export.arxiv.org/api/query"
    ARXIV_SOURCE_URL = "https://arxiv.org/src"

    # arXiv API 이용 약관: contact 정보를 포함한 User-Agent 필수
    # https://info.arxiv.org/help/api/tou.html
    USER_AGENT = (
        "arxiv-translator/1.0 "
        "(+https://github.com/show0000/arXiv-translator)"
    )
    # arXiv 권장: API 호출 간 최소 3초 간격
    MIN_REQUEST_INTERVAL = 3.0
    MAX_RETRIES = 5

    def __init__(self, download_dir: str = "arxiv_downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """API 호출 간 최소 간격 보장"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            sleep_time = self.MIN_REQUEST_INTERVAL - elapsed
            logger.debug(f"rate limit 준수를 위해 {sleep_time:.1f}초 대기")
            time.sleep(sleep_time)
        self._last_request_time = time.monotonic()

    def _request_with_retry(
        self,
        url: str,
        stream: bool = False,
        timeout: int = 30,
    ) -> requests.Response:
        """429 및 일시적 오류에 대해 재시도하는 GET 요청

        Args:
            url: 요청 URL
            stream: 스트림 모드 (대용량 다운로드용)
            timeout: 요청 타임아웃 (초)

        Returns:
            성공한 응답 객체 (stream=True면 호출자가 닫아야 함)

        Raises:
            requests.RequestException: 재시도 소진 후에도 실패한 경우
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            try:
                response = self.session.get(url, stream=stream, timeout=timeout)

                # 429: Too Many Requests — Retry-After 헤더 존중
                if response.status_code == 429:
                    retry_after_header = response.headers.get('Retry-After')
                    if retry_after_header:
                        try:
                            retry_after = int(retry_after_header)
                        except ValueError:
                            retry_after = 30
                    else:
                        # 지수 백오프: 10s, 20s, 40s, 80s, 최대 120s
                        retry_after = min(10 * (2 ** attempt), 120)
                    logger.warning(
                        f"arXiv rate limit (429). {retry_after}초 대기 후 재시도 "
                        f"({attempt + 1}/{self.MAX_RETRIES})"
                    )
                    response.close()
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response

            except requests.HTTPError as e:
                last_exc = e
                # 4xx (429 제외)는 재시도해도 의미 없으므로 즉시 포기
                status = e.response.status_code if e.response is not None else 0
                if 400 <= status < 500 and status != 429:
                    raise
                if attempt == self.MAX_RETRIES - 1:
                    raise
                wait = min(5 * (2 ** attempt), 60)
                logger.warning(
                    f"HTTP 에러: {e}. {wait}초 대기 후 재시도 "
                    f"({attempt + 1}/{self.MAX_RETRIES})"
                )
                time.sleep(wait)

            except requests.RequestException as e:
                last_exc = e
                if attempt == self.MAX_RETRIES - 1:
                    raise
                wait = min(5 * (2 ** attempt), 60)
                logger.warning(
                    f"네트워크 에러: {e}. {wait}초 대기 후 재시도 "
                    f"({attempt + 1}/{self.MAX_RETRIES})"
                )
                time.sleep(wait)

        # 재시도 루프를 모두 소진한 경우 (모두 429였던 경우)
        raise requests.RequestException(
            f"최대 재시도 횟수 초과: {url} (마지막 오류: {last_exc})"
        )

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
            response = self._request_with_retry(api_url, timeout=30)
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
            response = self._request_with_retry(source_url, stream=True, timeout=60)
            with response:
                # 파일 크기 확인
                total_size = int(response.headers.get('content-length', 0))
                logger.info(f"파일 크기: {total_size / 1024 / 1024:.2f} MB")

                # 다운로드
                with open(tar_file_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
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
