# arXiv Translator

arXiv 학술 논문의 LaTeX 소스를 다운로드하여 한국어(또는 지정 언어)로 번역하고, 원본 레이아웃을 유지한 PDF를 생성하는 CLI 도구입니다.

## 목적

영어로 작성된 arXiv 논문을 빠르게 한국어로 읽기 위한 도구입니다. 원본 논문의 그림, 표, 수식, 참고문헌 구조를 그대로 유지하면서 본문 텍스트만 번역합니다.

## 주요 기능

- arXiv 논문 자동 다운로드 및 LaTeX 소스 추출
- OpenAI / Anthropic Claude LLM을 이용한 학술 번역
- 문단 기반 동적 청크 분할로 번역 품질 최적화
- 수식, 인용(`\citep`), 참조(`\ref`), 그림/표 구조 자동 보호
- 논문 구조 및 핵심 용어를 LLM에 사전 제공하여 청크 간 일관성 유지
- 캡션 별도 후처리 번역 (figure/table 구조 보존)
- XeLaTeX + xeCJK 기반 한글 PDF 컴파일
- bibtex 자동 실행으로 참고문헌 정상 렌더링
- 번역 완전성 검증 및 누락 줄 자동 재번역
- 컴파일 전 LaTeX 구조 자동 복원 (잘못된 명령어, 중괄호 불균형 등)
- 토큰 사용량 요약 출력
- Claude API 프롬프트 캐싱 지원 (90% 토큰 할인)

## 워크플로우

```
[1] 다운로드          arXiv API → 메타데이터 조회 → 소스(.tar.gz) 다운로드 → 압축 해제
        ↓
[2] 번역              논문 구조/용어 추출 → 문단 기반 청크 분할 → LLM 번역 → 캡션 후처리
        ↓
[3] 후처리 검증       중괄호 균형 · 환경 명령어 · 잘못된 제어 시퀀스 자동 수정
        ↓
[4] PDF 컴파일        충돌 패키지 제거 → 폰트 설정 삽입 → bibtex → xelatex × 2
        ↓
[5] 출력              output/{arxiv_id}_{title}.pdf
```

## 실행 환경

### 공통 요구사항

| 항목 | 요구사항 |
|------|----------|
| Python | 3.12 이상 |
| LLM API 키 | OpenAI 또는 Anthropic API 키 |
| XeLaTeX | TeX Live 또는 MacTeX |
| 한글 폰트 | Noto Sans KR (권장) 또는 NanumGothic 등 |
| 인터넷 | arXiv 다운로드 및 API 호출에 필요 |

---

### macOS 환경 설정

#### 1. Python 설치

```bash
# Homebrew로 설치
brew install python@3.14

# 또는 miniconda 사용
conda create -n arxiv-translator python=3.14
conda activate arxiv-translator
```

#### 2. XeLaTeX 설치

```bash
brew install --cask mactex
```

설치 후 터미널을 재시작하고 확인:
```bash
xelatex --version
```

#### 3. 한글 폰트 설치

macOS에 기본 포함된 `AppleSDGothicNeo`로도 동작하지만, **Noto Sans KR**을 권장합니다:

- [Noto Sans KR 다운로드](https://fonts.google.com/noto/specimen/Noto+Sans+KR)
- 다운로드 후 `.otf` 파일을 더블 클릭하여 설치

설치 확인:
```bash
fc-list | grep "Noto Sans KR"
```

#### 4. 프로젝트 설치

```bash
git clone https://github.com/your-username/arXiv-translator.git
cd arXiv-translator

# 의존성 설치 (conda 환경 사용 시)
pip install pyyaml requests beautifulsoup4 lxml openai anthropic click

# 또는 uv 사용 시
uv sync
```

---

### Windows 환경 설정

#### 1. Python 설치

[python.org](https://www.python.org/downloads/)에서 Python 3.12+ 다운로드 후 설치.
설치 시 **"Add Python to PATH"** 체크 필수.

```cmd
python --version
```

#### 2. XeLaTeX 설치

[TeX Live](https://www.tug.org/texlive/) 설치:

1. https://www.tug.org/texlive/acquire-netinstall.html 에서 `install-tl-windows.exe` 다운로드
2. 설치 실행 (전체 설치 권장, 약 5GB)
3. 설치 완료 후 명령 프롬프트에서 확인:

```cmd
xelatex --version
```

> 또는 [MiKTeX](https://miktex.org/download)도 사용 가능합니다.

#### 3. 한글 폰트 설치

Windows에 기본 포함된 `Malgun Gothic`으로도 동작하지만, **Noto Sans KR**을 권장합니다:

- [Noto Sans KR 다운로드](https://fonts.google.com/noto/specimen/Noto+Sans+KR)
- 다운로드 후 `.otf` 파일을 우클릭 → "모든 사용자용으로 설치"

#### 4. 프로젝트 설치

```cmd
git clone https://github.com/your-username/arXiv-translator.git
cd arXiv-translator

pip install pyyaml requests beautifulsoup4 lxml openai anthropic click
```

---

## 실행 방법

### 1단계: 설정 파일 준비

```bash
python main.py --generate-config
```

`config.yaml`이 생성됩니다. 편집기로 열어 아래 항목을 설정합니다:

```yaml
# LLM 설정
provider: openai                    # openai 또는 claude
model: gpt-4                        # 사용할 모델
api_key: sk-your-api-key-here       # API 키

# 번역 설정
target_language: Korean              # 번역 대상 언어
dynamic_chunking: true               # true: 문단 기반 분할(권장), false: 전체 한번에
```

> API 키는 `config.yaml` 대신 환경변수로 설정하는 것을 권장합니다.

### 2단계: 환경변수로 API 키 설정 (권장)

**macOS / Linux:**
```bash
export OPENAI_API_KEY=sk-your-api-key
# 또는
export ANTHROPIC_API_KEY=sk-ant-your-api-key
```

**Windows (cmd):**
```cmd
set OPENAI_API_KEY=sk-your-api-key
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY = "sk-your-api-key"
```

### 3단계: 번역 실행

```bash
# arXiv ID로 실행
python main.py 2301.12345

# arXiv URL로 실행
python main.py https://arxiv.org/abs/2301.12345

# CLI에서 직접 옵션 지정
python main.py 2301.12345 --provider openai --model gpt-4 --api-key sk-...

# 상세 로그 출력
python main.py 2301.12345 --verbose

# 기존 다운로드 무시하고 재번역
python main.py 2301.12345 --force
```

### 4단계: 결과 확인

번역된 PDF는 `output/` 디렉토리에 생성됩니다:
```
output/2301.12345_Paper_Title_Here.pdf
```

### 실행 예시 (전체 출력)

```
============================================================
arXiv 논문 한글 번역기
============================================================
LLM: Openai/gpt-4
목표 언어: Korean

[1/4] arXiv 논문 다운로드
✓ 논문: Faster R-CNN: Towards Real-Time Object Detection...
✓ 소스: arxiv_downloads/1506.01497

[2/4] LaTeX 파일 번역
📋 논문 구조 추출: 15개 섹션
🔑 핵심 용어 추출: 20개
📊 번역 통계: 전체 721줄 중 239줄 번역 (33%)
총 16개 청크 생성 (문단 기반 동적 분할)
  번역 진행: [━━━━━━━━━━━━━━━━] 16/16
✓ 번역 완전성: 239/239줄 모두 번역됨
📝 캡션 18개 번역 완료

📊 토큰 사용량 요약
  모델: OpenAI/gpt-4
  API 호출: 17회
  Input 토큰: 41,893
  Output 토큰: 22,899
  총 토큰: 64,792

[3/4] PDF 컴파일
✓ PDF 생성

[4/4] 완료!
📄 논문: Faster R-CNN: Towards Real-Time Object Detection...
📁 출력: output/1506.01497_Faster_R-CNN_Towards_Real-Time_Object_Detection_with_Region_Proposal_Networks.pdf
============================================================
```

## CLI 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `ARXIV_ID` | arXiv 논문 ID 또는 URL (필수) | - |
| `--config`, `-c` | 설정 파일 경로 | `config.yaml` |
| `--provider` | LLM 제공자 (`openai` / `claude`) | config 값 |
| `--model`, `-m` | 사용할 모델명 | config 값 |
| `--api-key` | API 키 | 환경변수 또는 config 값 |
| `--target-language`, `-l` | 번역 대상 언어 | `Korean` |
| `--custom-prompt` | 커스텀 번역 지침 파일 경로 | - |
| `--main-font` | 주 폰트 지정 | 자동 감지 |
| `--mono-font` | 고정폭 폰트 지정 | 자동 감지 |
| `--output-dir`, `-o` | PDF 출력 디렉토리 | `output` |
| `--force` | 기존 파일 무시하고 재다운로드 | `false` |
| `--verbose`, `-v` | 상세 로그 출력 | `false` |
| `--generate-config` | 기본 config.yaml 생성 후 종료 | - |

## 설정 파일 (config.yaml)

```yaml
# LLM 설정
provider: openai              # openai 또는 claude
model: gpt-4                  # 모델명
api_key: null                 # API 키 (환경변수 권장)

# 번역 설정
target_language: Korean       # 번역 대상 언어
dynamic_chunking: true        # true: 문단 기반 동적 분할, false: 전체 한번에
custom_instruction: null      # 추가 번역 지침 (인라인)
custom_instruction_file: null # 추가 번역 지침 파일 경로

# 폰트 설정
main_font: null               # 주 폰트 (null이면 자동 감지)
mono_font: null               # 고정폭 폰트 (null이면 자동 감지)

# 출력 설정
output_dir: output            # PDF 출력 디렉토리
download_dir: arxiv_downloads # 다운로드 디렉토리

# 기타
force_download: false         # 기존 파일 무시하고 재다운로드
compile_twice: true           # 참조 해결을 위해 2번 컴파일
```

## 커스텀 번역 지침

특정 도메인 용어의 번역 규칙을 지정할 수 있습니다:

```bash
python main.py 2301.12345 --custom-prompt my_instructions.txt
```

`my_instructions.txt` 예시:
```
기술 용어 번역 규칙:
- Transformer → 트랜스포머 (영문 병기)
- Attention → 어텐션
- Embedding → 임베딩
- Fine-tuning → 파인튜닝

모든 인용과 참조를 원문 그대로 유지하세요.
```

## 프로젝트 구조

```
arXiv-translator/
├── main.py              # CLI 엔트리포인트
├── config.yaml          # 설정 파일
├── pyproject.toml       # 프로젝트 메타데이터 및 의존성
├── src/
│   ├── downloader.py    # arXiv API 연동 및 소스 다운로드
│   ├── translator.py    # LLM 번역 (OpenAI, Claude), 청크 분할, 구조 보호
│   ├── compiler.py      # LaTeX → PDF 컴파일, 구조 검증 및 자동 복원
│   ├── font_manager.py  # 한글 폰트 감지 및 XeLaTeX 설정 생성
│   └── config.py        # 설정 관리 (YAML + CLI 병합)
├── arxiv_downloads/     # 다운로드된 소스 (자동 생성)
└── output/              # 번역된 PDF 출력 (자동 생성)
```

## 문제 해결

### XeLaTeX를 찾을 수 없음

```
RuntimeError: XeLaTeX 컴파일러를 찾을 수 없습니다.
```

XeLaTeX 설치 후 터미널을 재시작하세요. `xelatex --version`으로 확인합니다.

### 한글 폰트를 찾을 수 없음

```
RuntimeError: 사용 가능한 한글 폰트가 없습니다.
```

Noto Sans KR 또는 NanumGothic을 설치하세요. 특정 폰트를 지정하려면:
```bash
python main.py 2301.12345 --main-font "Malgun Gothic"  # Windows
python main.py 2301.12345 --main-font "AppleSDGothicNeo"  # macOS
```

### API 키 오류

```
ValueError: OPENAI API 키가 설정되지 않았습니다.
```

환경변수 설정 또는 `--api-key` 옵션을 확인하세요.

### 컴파일 경고/에러

PDF는 정상 생성되지만 경고가 표시될 수 있습니다:
- **Font Warning**: 원본 논문이 사용하는 폰트가 시스템에 없는 경우 (PDF 생성에 영향 없음)
- **Citation undefined**: 1차 컴파일에서 발생하며 2차 컴파일에서 해결됩니다
- **Missing $**: LLM 번역 시 간헐적으로 발생하는 수식 구조 오류 (PDF 생성에 영향 미미)

## 크레딧

이 프로젝트는 [GENEXIS-AI/arXiv-PDF-Translator](https://github.com/GENEXIS-AI/arXiv-PDF-Translator)를 참조하여 개선한 프로젝트입니다.

## 라이선스

MIT License
