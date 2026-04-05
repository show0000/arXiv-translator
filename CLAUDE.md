# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**arXiv-translator** is a Python application that translates arXiv academic papers from LaTeX source to Korean (or other languages) and generates a translated PDF.

### Core Workflow

1. **Download**: Fetch arXiv paper metadata and source files (.tar.gz)
2. **Translate**: Translate LaTeX files while preserving structure using LLM (OpenAI/Claude)
3. **Compile**: Generate Korean PDF using XeLaTeX with proper font configuration

## Development Commands

### Environment Setup

```bash
# Create virtual environment with uv
uv venv --python 3.12
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
uv sync

# Or add new dependency
uv add <package-name>
```

### Running the Application

```bash
# Generate default config
python main.py --generate-config

# Translate a paper (OpenAI)
python main.py 2301.12345 --provider openai --model gpt-4 --api-key sk-...

# Translate a paper (Claude)
python main.py 2301.12345 --provider claude --model claude-3-5-sonnet-20241022 --api-key sk-ant-...

# With custom settings
python main.py 2301.12345 --main-font "Noto Sans KR" --custom-prompt custom.txt --verbose
```

### Testing Individual Modules

```bash
# Test font detection
python -c "from src.font_manager import FontManager; fm = FontManager(); print(fm.find_korean_font())"

# Test arXiv download
python -c "from src.downloader import ArxivDownloader; d = ArxivDownloader(); d.download_and_extract('2301.12345')"
```

## Architecture

### Module Structure

```
src/
├── downloader.py      # arXiv API interaction and source download
├── translator.py      # LLM provider abstraction (OpenAI, Claude)
├── compiler.py        # LaTeX compilation to PDF
├── font_manager.py    # Korean font detection and configuration
└── config.py          # Configuration management (YAML + CLI)
```

### Key Design Patterns

**1. LLM Provider Abstraction**
- `LLMProvider` abstract base class
- `OpenAIProvider` and `ClaudeProvider` implementations
- Easy to add new providers by implementing the `translate()` method

**2. Font Management**
- Automatic Korean font detection across platforms (macOS, Linux, Windows)
- Fallback chain: Noto Sans KR → Nanum Gothic → system fonts
- Generates LaTeX font configuration with CJK package conflict prevention

**3. Configuration System**
- `TranslationConfig` dataclass for type-safe configuration
- YAML file for defaults, CLI arguments for overrides
- Environment variables for API keys

### Translation Pipeline

```python
# 1. Download
downloader = ArxivDownloader()
metadata, source_dir = downloader.download_and_extract(arxiv_id)

# 2. Translate
llm_provider = OpenAIProvider(api_key, model)
translator = LatexTranslator(provider=llm_provider)
translator.translate_directory(source_dir, metadata)

# 3. Compile
font_manager = FontManager()
compiler = LatexCompiler(font_manager)
pdf_file = compiler.compile_directory(source_dir, output_dir)
```

### Critical Font Handling

**Problem**: Korean text in LaTeX requires:
- XeLaTeX compiler (not pdflatex)
- Korean font properly configured
- No CJK package conflicts

**Solution** (in `font_manager.py` and `compiler.py`):
1. Detect available Korean fonts on system
2. Remove conflicting CJK packages from .tex files
3. Insert proper `kotex` + `xeCJK` configuration
4. Use `FakeSlant` and `FakeBold` for missing font variants

## Common Development Tasks

### Adding a New LLM Provider

1. Create a new class in `src/translator.py`:

```python
class NewProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        # Initialize client
        pass

    def translate(self, text: str, paper_info: dict,
                  target_language: str, custom_instruction: str) -> str:
        # Implement translation logic
        # Must return joined translated lines
        pass
```

2. Update `main.py` to instantiate the new provider
3. Update `config.py` to add provider option

### Modifying Translation Prompt

The translation prompt is in `src/translator.py` → `_build_system_prompt()`:
- Preserves LaTeX commands (don't translate `\section{}`, `\cite{}`, etc.)
- Keeps technical terms in English
- Maintains JSON line-by-line structure
- Respects paper metadata (title, abstract) for context

### Debugging Font Issues

```bash
# Check available fonts
fc-list :lang=ko family

# Test font detection
python -c "from src.font_manager import FontManager; fm = FontManager(); fonts = fm.get_available_fonts(); ko_fonts = [f for f in fonts if any(k in f.lower() for k in ['noto', 'nanum', 'gothic'])]; print(ko_fonts)"

# Verify XeLaTeX
xelatex --version
```

### Handling LaTeX Compilation Errors

Compilation logs are in `arxiv_downloads/<arxiv-id>/<paper>.log`. Common issues:
- **Missing font**: Add `--main-font` option
- **CJK package conflict**: Check `compiler.remove_cjk_packages()` logic
- **Reference errors**: Requires `compile_twice=True` (default)

## Code Conventions

### Import Order
1. Standard library (logging, os, sys, pathlib)
2. Third-party (requests, click, yaml)
3. Local (src.*)

### Logging
- Use `logger = logging.getLogger(__name__)` in each module
- INFO: User-facing progress messages
- DEBUG: Internal state for troubleshooting
- ERROR: Failures with actionable context

### Error Handling
- Raise meaningful exceptions with context
- Use retry logic for API calls (default: 3 attempts)
- Preserve original files (backup with `_original` suffix)

### Type Hints
- Use type hints for all function signatures
- Use `Optional[T]` for nullable parameters
- Use `Path` for file paths (not `str`)

## Dependencies

### Core
- `requests`: arXiv API and file downloads
- `beautifulsoup4` + `lxml`: XML parsing (arXiv metadata)
- `openai`: OpenAI API client
- `anthropic`: Claude API client
- `pyyaml`: Configuration file parsing
- `click`: CLI framework

### System Requirements
- Python 3.12+ (uses modern type hints)
- XeLaTeX (from TeX Live, MacTeX, etc.)
- Korean fonts (Noto Sans KR recommended)

## Testing Strategy

Currently manual testing. To add automated tests:

1. Unit tests for font detection:
   - Mock `fc-list` output
   - Test fallback chain logic

2. Integration tests for translation:
   - Mock LLM API responses
   - Verify LaTeX structure preservation

3. End-to-end tests:
   - Use a small test paper
   - Verify PDF generation

## Known Limitations

1. **Parallel Translation**: Currently sequential. Future: implement with `concurrent.futures`
2. **Progress Tracking**: Basic logging. Future: add `tqdm` progress bars
3. **Translation Cache**: No caching. Future: cache translated chunks
4. **Error Recovery**: If one .tex file fails, entire process fails. Future: skip failed files

## Configuration Notes

### API Keys
Recommended order:
1. CLI argument: `--api-key`
2. Environment variable: `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
3. Config file: `api_key` in `config.yaml` (not recommended for security)

### Chunk Size
- Default: 100 lines per API call
- Smaller: More API calls, better error isolation
- Larger: Fewer calls, better context, higher failure impact

### Custom Prompts
Use for domain-specific terminology:
```
Technical terms:
- Transformer → 트랜스포머 (keep in English)
- Attention → 어텐션 메커니즘

Preserve all citations and references exactly.
```

## Future Enhancements

1. **Parallel processing**: Translate multiple .tex files concurrently
2. **Progress bars**: Visual feedback with `tqdm`
3. **Translation cache**: Avoid re-translating unchanged files
4. **Web interface**: Simple Flask/FastAPI frontend
5. **Batch processing**: Translate multiple papers in one command
6. **Quality checks**: Verify translation completeness and LaTeX validity
7. **More LLM providers**: Google Gemini, local models (Ollama)
