"""LaTeX 문서 번역 모듈

LLM API를 사용하여 LaTeX 문서를 번역하면서 구조와 형식을 보존합니다.
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_newline_replace(text: str) -> str:
    """리터럴 \\n을 실제 줄바꿈으로 안전하게 변환

    LaTeX 명령어(\\newcommand, \\noindent 등)의 \\n은 보존하고,
    줄 끝이나 독립적인 \\n만 실제 줄바꿈으로 변환합니다.
    """
    # \n 뒤에 알파벳이 오면 LaTeX 명령어이므로 보존
    # \n 뒤에 알파벳이 없으면 (줄 끝, 공백, 다른 특수문자) 줄바꿈으로 변환
    return re.sub(r'\\n(?![a-zA-Z])', '\n', text)


class LatexContentFilter:
    """LaTeX 파일에서 번역 가능한 콘텐츠만 필터링"""

    def __init__(self):
        # 번역 제외 환경 (수학, 코드 등)
        # 주의: figure, table은 캡션 번역을 위해 제외하지 않음
        self.skip_environments = [
            'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
            'multline', 'multline*', 'eqnarray', 'eqnarray*',
            'lstlisting', 'verbatim', 'verbatim*', 'minted',
            'tikzpicture', 'algorithm', 'algorithmic',
            'tabular', 'tabularx',
        ]

        # figure/table 내부에서 캡션만 번역하고 나머지는 건너뛰는 환경
        self.caption_environments = ['figure', 'figure*', 'table', 'table*']

        # 번역 대상 명령어 (인자를 번역해야 하는 명령어)
        self.translatable_commands = [
            'section', 'subsection', 'subsubsection', 'paragraph',
            'title', 'author', 'caption', 'captionof',
            'textbf', 'textit', 'emph', 'item',
            'chapter', 'part'
        ]

        # 상태 추적
        self.current_env = None
        self.in_reference_section = False
        self.env_stack = []

    def reset(self):
        """상태 초기화"""
        self.current_env = None
        self.in_reference_section = False
        self.env_stack = []

    def should_translate_line(self, line: str) -> bool:
        """라인을 번역해야 하는지 판단

        Args:
            line: 검사할 LaTeX 라인

        Returns:
            번역 필요 여부
        """
        stripped = line.strip()

        # 빈 줄이나 주석은 건너뛰기
        if not stripped or stripped.startswith('%'):
            return False

        # References 섹션 감지
        if re.match(r'\\bibliography\{|\\begin\{thebibliography\}|\\bibliographystyle\{', stripped):
            self.in_reference_section = True
            logger.info("References 섹션 감지 - 이후 내용 번역 건너뛰기")
            return False

        if self.in_reference_section:
            return False

        # 환경 종료 감지 (시작보다 먼저 체크 - 같은 줄에 begin/end 있을 수 있음)
        end_match = re.search(r'\\end\{([^}]+)\}', stripped)
        if end_match:
            env_name = end_match.group(1)
            # 스택에서 매칭되는 환경 이름을 찾아서 제거
            if self.env_stack and self.env_stack[-1] == env_name:
                self.env_stack.pop()
            elif env_name in self.env_stack:
                # 중첩이 꼬인 경우: 해당 환경까지 pop
                while self.env_stack and self.env_stack[-1] != env_name:
                    self.env_stack.pop()
                if self.env_stack:
                    self.env_stack.pop()
            return False

        # 환경 시작 감지
        begin_match = re.search(r'\\begin\{([^}]+)\}', stripped)
        if begin_match:
            env_name = begin_match.group(1)
            self.env_stack.append(env_name)
            if env_name in self.skip_environments:
                return False

        # 번역 제외 환경 내부인 경우
        if self.env_stack and self.env_stack[-1] in self.skip_environments:
            return False

        # figure/table 내부: 캡션(\caption{...})이 포함된 줄만 번역
        if self.env_stack and any(env in self.caption_environments for env in self.env_stack):
            if re.search(r'\\caption(\[.*?\])?\{', stripped):
                return True
            return False

        # 인라인 수학 모드 체크 ($ ... $ 또는 \[ ... \])
        if re.search(r'\$\$.*\$\$|\\\[.*\\\]', stripped):
            return False

        # LaTeX 명령어만 있는 라인 (번역할 텍스트가 없음)
        # 전략: 번역 불필요한 명령어(\label, \usepackage, \ref 등)를 통째로 제거하고,
        #       번역 필요한 명령어(\textbf 등)는 이름만 제거하여 인자 텍스트를 보존
        non_translatable_cmds = (
            r'\\(?:label|ref|eqref|cref|cite|citep|citet|bibliography|bibliographystyle'
            r'|usepackage|RequirePackage|input|include|includegraphics'
            r'|documentclass|setlength|setcounter|newcommand|renewcommand'
            r'|def|let|vspace|hspace|vskip|hskip|phantom|vphantom|hphantom'
            r'|rule|url|href|hyperref|pageref|footnoteref)(?:\[.*?\])?(?:\{[^}]*\})*'
        )
        text_check = re.sub(non_translatable_cmds, '', line)
        # 번역 대상 명령어는 이름만 제거 (인자 텍스트 보존)
        text_check = re.sub(r'\\[a-zA-Z]+', '', text_check)
        # 특수문자, 숫자만 있는 잔여물 제거
        text_check = re.sub(r'[{}%$\\\[\]*=.,;:0-9]', '', text_check).strip()

        # 의미있는 텍스트(공백 포함 2자 이상의 단어)가 없으면 건너뛰기
        if len(text_check) < 2:
            return False

        return True

    def extract_translatable_text(self, line: str) -> Optional[str]:
        """라인에서 번역 가능한 텍스트만 추출

        Args:
            line: LaTeX 라인

        Returns:
            번역 가능한 텍스트 (없으면 None)
        """
        if not self.should_translate_line(line):
            return None

        # 번역 대상 명령어의 인자 추출
        # 예: \section{Introduction} -> "Introduction"
        translatable_parts = []

        for cmd in self.translatable_commands:
            pattern = rf'\\{cmd}\{{([^}}]+)\}}'
            matches = re.finditer(pattern, line)
            for match in matches:
                translatable_parts.append(match.group(1))

        # 일반 텍스트 추출 (명령어 외부의 텍스트)
        # 이 부분은 복잡하므로 간단히 전체 라인 반환
        # 향후 개선 가능

        if translatable_parts:
            return ' '.join(translatable_parts)

        # 명령어 인자가 없으면 전체 라인 반환 (일반 텍스트)
        return line


class LLMProvider(ABC):
    """LLM 제공자 추상 클래스"""

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    @abstractmethod
    def translate(
        self,
        text: str,
        paper_info: dict,
        target_language: str,
        custom_instruction: Optional[str] = None
    ) -> dict[int, str]:
        """텍스트 번역

        Args:
            text: 번역할 텍스트 (ID 기반 JSON 형식)
            paper_info: 논문 메타데이터
            target_language: 목표 언어
            custom_instruction: 추가 번역 지침

        Returns:
            {line_id: translated_text} 딕셔너리
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """사용 모델명 반환"""
        pass

    def get_usage_summary(self) -> dict:
        """토큰 사용량 요약 반환"""
        return {
            "model": self.get_model_name(),
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }


class OpenAIProvider(LLMProvider):
    """OpenAI API 제공자"""

    def __init__(self, api_key: str, model: str = "gpt-4"):
        super().__init__()
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model
        logger.info(f"OpenAI Provider 초기화: {model}")

    def get_model_name(self) -> str:
        return f"OpenAI/{self.model}"

    def translate(
        self,
        text: str,
        paper_info: dict,
        target_language: str,
        custom_instruction: Optional[str] = None
    ) -> dict[int, str]:
        """OpenAI API로 번역"""
        system_prompt = self._build_system_prompt(
            paper_info,
            target_language,
            custom_instruction
        )

        retry_attempts = 3
        for attempt in range(retry_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ]
                )

                # 토큰 사용량 수집
                if response.usage:
                    self.total_input_tokens += response.usage.prompt_tokens
                    self.total_output_tokens += response.usage.completion_tokens
                    self.total_requests += 1

                translated_content = response.choices[0].message.content
                translation_result = json.loads(translated_content)
                translation_lines = translation_result["translate"]["lines"]

                # ID 기반 딕셔너리로 변환
                result = {}
                for line_obj in translation_lines:
                    line_id = line_obj["id"]
                    line_text = line_obj["text"]
                    # 줄 끝의 리터럴 \n만 실제 줄바꿈으로 변환
                    # (LaTeX 명령어 \newcommand, \noindent 등을 보호)
                    line_text = _safe_newline_replace(line_text)

                    # 같은 ID가 여러 개 있을 수 있음 (라인 분할된 경우)
                    if line_id in result:
                        result[line_id] += line_text
                    else:
                        result[line_id] = line_text

                return result

            except Exception as error:
                logger.error(f"❌ 번역 시도 {attempt + 1}/{retry_attempts} 실패: {error}")
                if attempt == retry_attempts - 1:
                    raise
                time.sleep(1)

        raise Exception("번역 실패: 모든 재시도 소진")

    def _build_system_prompt(
        self,
        paper_info: dict,
        target_language: str,
        custom_instruction: Optional[str] = None
    ) -> str:
        """시스템 프롬프트 생성"""
        paper_title = paper_info.get('title', '')
        paper_abstract = paper_info.get('abstract', '')

        base_prompt = f"""
You are an AI assistant specialized in translating academic papers in LaTeX format to {target_language}. Your task is to translate the content accurately while preserving the LaTeX structure and formatting. Pay close attention to technical terms and follow these guidelines meticulously.

Translation Instructions:

1. Translate the main content into {target_language}, preserving the structure and flow of the original text. Use an academic and formal tone appropriate for scholarly publications in {target_language}. Do not insert any arbitrary line breaks in the translated content.

2. Technical Terms:
   a. Retain well-known technical terms, product names, or specialized concepts (e.g., Few-Shot Learning) in English.
   b. Do not translate examples, especially if they contain technical content or are essential for context.

3. LaTeX Commands:
   - Do not translate LaTeX commands, functions, environments, or specific LaTeX-related keywords (e.g., \\section{{}}, \\begin{{}}, \\end{{}}, \\cite{{}}, \\ref{{}}, or TikZ syntax such as /tikz/fill, /tikz/draw, etc.) into {target_language}. They must be output exactly as they are.
   - Only translate the provided text without making any additional modifications.

4. Citation and Reference Keys:
   - Ensure all citation keys within \\cite{{}} and reference keys within \\ref{{}} remain unchanged. Do not translate or modify these keys.

5. URLs and DOIs:
   - Do not translate URLs, DOIs, or any other links. Keep them in their original form.
   - Do not convert space into %20 in URLs.

6. Mathematical Equations and Formulas:
   - Maintain all mathematical equations and formulas as they are in the original LaTeX. Do not translate code or LaTeX mathematical notation.

7. Names:
   - Do not translate author names, personal names, or any other individual names. Keep these in their original English form.

8. Consistency:
   - Ensure consistent terminology throughout the translation.

9. Protection of LaTeX Commands:
    - Preserve line breaks (\\\\) and other formatting commands exactly as they appear in the original text.

10. Avoid Misleading Translations:
    - Do not translate technical terms, product names, specialized concepts, examples, or personal names where translation could lead to a loss of meaning or context.

11. JSON Structure:
    - Each line has a unique ID for accurate matching after translation.
    - You MUST preserve the ID of each line in your response.
    - You can merge multiple lines (concatenate text with same or sequential IDs) or split one line (create multiple entries with same ID), but IDs must be preserved.
    - Output format:
      ```json
      {{
        "translate": {{
          "lines": [
            {{"id": 0, "text": "Translated Line 1"}},
            {{"id": 1, "text": "Translated Line 2"}}
          ]
        }}
      }}
      ```

### Paper Info:
- Title : {paper_title}
- Abstract : {paper_abstract}

### Response Example:
#INPUT:
{{
  "lines": [
    {{"id": 0, "text": "\\n"}},
    {{"id": 1, "text": "\\documentclass{{article}} % For LaTeX2e\\n"}},
    {{"id": 2, "text": "\\usepackage{{colm2024_conference}}\\n"}},
    {{"id": 3, "text": "\\n"}},
    {{"id": 4, "text": "\\usepackage{{microtype}}\\n"}}
  ]
}}

#OUTPUT:
{{
  "translate": {{
    "lines": [
      {{"id": 0, "text": "\\n"}},
      {{"id": 1, "text": "\\documentclass{{article}} % For LaTeX2e\\n"}},
      {{"id": 2, "text": "\\usepackage{{colm2024_conference}}\\n"}},
      {{"id": 3, "text": "\\n"}},
      {{"id": 4, "text": "\\usepackage{{microtype}}\\n"}}
    ]
  }}
}}

### VERY IMPORTANT
- ALWAYS preserve line IDs in your response - this is critical for correct reassembly.
- DO NOT translate comments starting with "%" by arbitrarily merging them.
- You may merge or split lines if it improves translation quality, but preserve IDs.
- Output the translated result in JSON format, without any other explanation.
- Translate and output even single characters like '\\n', '{{', '/', '%', etc.
- DO NOT forget which language you must translate.
"""

        # 커스텀 지침 추가
        if custom_instruction:
            base_prompt += f"\n\n### Additional Instructions:\n{custom_instruction}\n"

        return base_prompt


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API 제공자"""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        super().__init__()
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self._cache_read_tokens = 0
        self._cache_create_tokens = 0
        logger.info(f"Claude Provider 초기화: {model}")

    def get_model_name(self) -> str:
        return f"Claude/{self.model}"

    def get_usage_summary(self) -> dict:
        summary = super().get_usage_summary()
        summary["cache_read_tokens"] = self._cache_read_tokens
        summary["cache_create_tokens"] = self._cache_create_tokens
        return summary

    def translate(
        self,
        text: str,
        paper_info: dict,
        target_language: str,
        custom_instruction: Optional[str] = None
    ) -> dict[int, str]:
        """Claude API로 번역"""
        system_prompt = self._build_system_prompt(
            paper_info,
            target_language,
            custom_instruction
        )

        retry_attempts = 3
        for attempt in range(retry_attempts):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=16384,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
                    messages=[
                        {"role": "user", "content": text}
                    ]
                )

                # 토큰 사용량 수집
                if response.usage:
                    self.total_input_tokens += response.usage.input_tokens
                    self.total_output_tokens += response.usage.output_tokens
                    self.total_requests += 1
                    # 캐시 히트 토큰 추적
                    cache_read = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
                    cache_create = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
                    self._cache_read_tokens += cache_read
                    self._cache_create_tokens += cache_create

                # Claude는 JSON 응답을 텍스트로 반환
                translated_content = response.content[0].text

                # JSON 파싱
                # ```json ... ``` 형식이면 제거
                if translated_content.startswith("```json"):
                    translated_content = re.sub(r'^```json\s*|\s*```$', '', translated_content, flags=re.MULTILINE)

                translation_result = json.loads(translated_content)
                translation_lines = translation_result["translate"]["lines"]

                # ID 기반 딕셔너리로 변환
                result = {}
                for line_obj in translation_lines:
                    line_id = line_obj["id"]
                    line_text = line_obj["text"]
                    # 줄 끝의 리터럴 \n만 실제 줄바꿈으로 변환
                    line_text = _safe_newline_replace(line_text)

                    # 같은 ID가 여러 개 있을 수 있음 (라인 분할된 경우)
                    if line_id in result:
                        result[line_id] += line_text
                    else:
                        result[line_id] = line_text

                return result

            except Exception as error:
                logger.error(f"❌ 번역 시도 {attempt + 1}/{retry_attempts} 실패: {error}")
                if attempt == retry_attempts - 1:
                    raise
                time.sleep(1)

        raise Exception("번역 실패: 모든 재시도 소진")

    def _build_system_prompt(
        self,
        paper_info: dict,
        target_language: str,
        custom_instruction: Optional[str] = None
    ) -> str:
        """시스템 프롬프트 생성 (OpenAI와 동일)"""
        # OpenAI 프롬프트 재사용
        openai_provider = OpenAIProvider(api_key="dummy", model="dummy")
        return openai_provider._build_system_prompt(
            paper_info,
            target_language,
            custom_instruction
        )


class LatexTranslator:
    """LaTeX 문서 번역기"""

    def __init__(
        self,
        provider: LLMProvider,
        target_language: str = "Korean",
        max_workers: int = 8,
        custom_instruction: Optional[str] = None
    ):
        self.provider = provider
        self.target_language = target_language
        self.max_workers = max_workers
        self.custom_instruction = custom_instruction
        self.content_filter = LatexContentFilter()

    def remove_latex_commands(self, text: str) -> str:
        """불필요한 LaTeX 명령 제거"""
        # CJK* 관련 내용을 자동으로 대체
        text = re.sub(r'\\begin{CJK\*}\{.*?\}\{.*?\}', '', text)
        text = re.sub(r'\\end{CJK\*}', '', text)
        return text

    def _is_section_boundary(self, line_text: str) -> bool:
        """섹션 경계인지 판단 (강제 분할 지점)"""
        stripped = line_text.strip()
        return bool(re.match(r'\\(section|subsection|subsubsection|chapter|part)\b', stripped))

    def _is_paragraph_boundary(self, line_text: str) -> bool:
        """문단 경계인지 판단 (선호 분할 지점)"""
        stripped = line_text.strip()
        if not stripped:
            return True
        if re.match(r'\\(section|subsection|subsubsection|chapter|part|paragraph)\b', stripped):
            return True
        if re.match(r'\\end\{', stripped):
            return True
        if re.match(r'\\(vspace|bigskip|medskip|smallskip)\b', stripped):
            return True
        if re.match(r'\\noindent\\textbf\{', stripped):
            return True
        return False

    # 인접 문단 병합 시 청크 최대 줄 수
    MAX_CHUNK_LINES = 50

    def chunk_lines(self, lines: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
        """줄을 문단 기반으로 동적 분할

        1단계: 문단 그룹으로 분리 (빈 줄, 섹션 명령어 등 기준)
        2단계: 인접 문단을 병합하여 API 호출 최소화 (섹션 경계에서 강제 분할)

        Args:
            lines: (line_id, line_text) 튜플 리스트

        Returns:
            청크 리스트 (각 청크는 (line_id, line_text) 튜플의 리스트)
        """
        # 1단계: 문단 그룹으로 분리
        paragraphs = []
        current_para = []

        for line in lines:
            # 섹션 경계는 새 문단 시작 (이전 문단 먼저 저장)
            if self._is_section_boundary(line[1]) and current_para:
                paragraphs.append(current_para)
                current_para = []

            current_para.append(line)

            # 문단 경계에서 분리
            if self._is_paragraph_boundary(line[1]):
                paragraphs.append(current_para)
                current_para = []

        if current_para:
            paragraphs.append(current_para)

        # 2단계: 인접 문단을 병합 (섹션 경계에서 강제 분할)
        chunks = []
        current_chunk = []

        for para in paragraphs:
            # 섹션 경계 문단이면 이전 청크를 강제 마감
            starts_with_section = para and self._is_section_boundary(para[0][1])
            if starts_with_section and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []

            # 병합 시 상한 초과하면 현재 청크 마감
            if current_chunk and len(current_chunk) + len(para) > self.MAX_CHUNK_LINES:
                chunks.append(current_chunk)
                current_chunk = []

            # 단일 문단이 상한보다 큰 경우 독립 청크로 분리
            if len(para) > self.MAX_CHUNK_LINES:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                chunks.append(para)
            else:
                current_chunk.extend(para)

        if current_chunk:
            chunks.append(current_chunk)

        # 통계 로그
        chunk_sizes = [len(c) for c in chunks]
        logger.info(
            f"총 {len(chunks)}개 청크 생성 (문단 기반 동적 분할, "
            f"크기: {min(chunk_sizes)}~{max(chunk_sizes)}줄, "
            f"평균: {sum(chunk_sizes)/len(chunk_sizes):.0f}줄)"
        )
        return chunks

    def translate_chunk(
        self,
        chunk: list[tuple[int, str]],
        paper_info: dict
    ) -> dict[int, str]:
        """단일 청크 번역

        Args:
            chunk: 번역할 (line_id, line_text) 튜플 리스트
            paper_info: 논문 메타데이터

        Returns:
            {line_id: translated_text} 딕셔너리
        """
        # ID 기반 JSON 형식으로 변환
        chunk_data = {
            "lines": [
                {"id": line_id, "text": text}
                for line_id, text in chunk
            ]
        }
        chunk_json = json.dumps(chunk_data, ensure_ascii=False)

        # LaTeX 명령 정리
        cleaned_text = self.remove_latex_commands(chunk_json)

        # 번역
        translated_text = self.provider.translate(
            cleaned_text,
            paper_info,
            self.target_language,
            self.custom_instruction
        )

        return translated_text

    def translate_file(
        self,
        tex_file: Path,
        paper_info: dict,
        backup: bool = True
    ) -> None:
        """.tex 파일 번역

        Args:
            tex_file: 번역할 .tex 파일 경로
            paper_info: 논문 메타데이터
            backup: 원본 파일 백업 여부
        """
        logger.info(f"파일 번역 시작: {tex_file}")

        # 파일 읽기
        with open(tex_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 백업
        if backup:
            backup_file = tex_file.with_suffix('.tex_original')
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.debug(f"원본 백업: {backup_file}")

        # 필터 초기화
        self.content_filter.reset()

        # 번역 필요한 라인과 불필요한 라인 분리 (ID 기반)
        line_info = []  # (original_index, original_line, should_translate, translatable_id)
        translatable_lines_with_id = []  # [(translatable_id, line_text), ...]
        translatable_id = 0

        for original_idx, line in enumerate(lines):
            should_translate = self.content_filter.should_translate_line(line)

            if should_translate:
                line_info.append((original_idx, line, True, translatable_id))
                translatable_lines_with_id.append((translatable_id, line))
                translatable_id += 1
            else:
                line_info.append((original_idx, line, False, None))

        total_lines = len(lines)
        translatable_count = len(translatable_lines_with_id)

        if translatable_count == 0:
            logger.info("번역할 내용이 없습니다.")
            return

        logger.info(f"📊 번역 통계: 전체 {total_lines}줄 중 {translatable_count}줄 번역 ({translatable_count*100//total_lines}%)")

        # 번역 대상 라인을 청크로 분할
        chunks = self.chunk_lines(translatable_lines_with_id)

        # 번역 (순차 처리) - 결과는 {id: translated_text} 딕셔너리
        all_translations = {}
        for i, chunk in enumerate(chunks):
            logger.info(f"청크 {i+1}/{len(chunks)} 번역 중...")

            try:
                translated_dict = self.translate_chunk(chunk, paper_info)

                # 번역 완전성 검증: 누락된 ID 체크
                chunk_ids = {line_id for line_id, _ in chunk}
                returned_ids = set(translated_dict.keys())
                missing_ids = chunk_ids - returned_ids

                if missing_ids:
                    missing_ratio = len(missing_ids) / len(chunk_ids)
                    logger.warning(
                        f"⚠ 청크 {i+1}: {len(missing_ids)}/{len(chunk_ids)}개 "
                        f"라인 ID 누락 ({missing_ratio:.0%})"
                    )
                    # 누락된 ID는 원문으로 채움
                    for line_id, line_text in chunk:
                        if line_id not in translated_dict:
                            translated_dict[line_id] = line_text

                all_translations.update(translated_dict)

            except Exception as e:
                logger.error(f"❌ 청크 {i+1} 번역 실패: {e}")
                # 실패 시 원문 유지
                for line_id, line_text in chunk:
                    all_translations[line_id] = line_text

        # 최종 결과 조립 (ID 기반)
        result_lines = []
        fallback_count = 0
        for original_idx, original_line, should_translate, trans_id in line_info:
            if should_translate and trans_id is not None:
                # 번역된 내용 가져오기
                translated_text = all_translations.get(trans_id)
                if translated_text is None:
                    translated_text = original_line
                    fallback_count += 1
                # 줄바꿈이 없으면 추가 (LaTeX 구조 보존)
                if translated_text and not translated_text.endswith('\n'):
                    translated_text += '\n'
                result_lines.append(translated_text)
            else:
                # 번역 불필요한 라인은 원본 그대로
                result_lines.append(original_line)

        # 번역 완전성 리포트
        if fallback_count > 0:
            logger.warning(
                f"⚠ 번역 완전성: {translatable_count - fallback_count}/{translatable_count}줄 번역됨 "
                f"({fallback_count}줄 원문 유지)"
            )
        else:
            logger.info(f"✓ 번역 완전성: {translatable_count}/{translatable_count}줄 모두 번역됨")

        # 번역된 내용 저장
        with open(tex_file, 'w', encoding='utf-8') as f:
            f.writelines(result_lines)

        logger.info(f"✓ 파일 번역 완료: {tex_file}")

    def translate_directory(
        self,
        directory: Path,
        paper_info: dict
    ) -> list[Path]:
        """디렉토리 내 모든 .tex 파일 번역

        Args:
            directory: 번역할 디렉토리
            paper_info: 논문 메타데이터

        Returns:
            번역된 파일 경로 리스트
        """
        logger.info(f"디렉토리 번역 시작: {directory}")

        # .tex 파일 찾기 (백업 파일 제외)
        tex_files = [
            f for f in directory.rglob("*.tex")
            if "_original" not in f.name
        ]

        if not tex_files:
            logger.warning("번역할 .tex 파일이 없습니다.")
            return []

        logger.info(f"총 {len(tex_files)}개 파일 번역 예정")

        # 각 파일 번역
        translated_files = []
        for i, tex_file in enumerate(tex_files):
            logger.info(f"\n[{i+1}/{len(tex_files)}] {tex_file.name}")
            try:
                self.translate_file(tex_file, paper_info)
                translated_files.append(tex_file)
            except Exception as e:
                logger.error(f"파일 번역 실패: {e}")

        logger.info(f"\n✓ 번역 완료: {len(translated_files)}/{len(tex_files)}개 파일")

        # 토큰 사용량 요약 출력
        usage = self.provider.get_usage_summary()
        logger.info("")
        logger.info("📊 토큰 사용량 요약")
        logger.info(f"  모델: {usage['model']}")
        logger.info(f"  API 호출: {usage['total_requests']}회")
        logger.info(f"  Input 토큰: {usage['total_input_tokens']:,}")
        logger.info(f"  Output 토큰: {usage['total_output_tokens']:,}")
        logger.info(f"  총 토큰: {usage['total_tokens']:,}")
        # Claude 캐시 정보 (있는 경우)
        if usage.get('cache_read_tokens', 0) > 0 or usage.get('cache_create_tokens', 0) > 0:
            logger.info(f"  캐시 생성: {usage['cache_create_tokens']:,} 토큰")
            logger.info(f"  캐시 히트: {usage['cache_read_tokens']:,} 토큰 (90% 할인 적용)")

        return translated_files
