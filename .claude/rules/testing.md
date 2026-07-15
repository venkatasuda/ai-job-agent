# Testing Rules

## Test Structure
```
tests/
├── conftest.py          # Shared fixtures, pytest config
├── test_scrapers.py     # Scraper output format, dedup, security
├── test_scoring.py      # Prompt registry, output filter, scoring accuracy
└── test_pipeline.py     # Models, config, observability, migrations
```

## Running Tests
```bash
pytest tests/ -v                    # All unit tests
pytest tests/ -v --integration      # Include integration tests (needs API keys)
pytest tests/ -v --slow             # Include slow tests
pytest tests/test_scoring.py -v     # Single file
pytest -k "TestOutputFilter"        # Single class
pytest --cov=ai --cov-report=html   # Coverage report
```

## Fixtures
Shared fixtures are in `conftest.py`. Don't duplicate — add to conftest if used across files.

Key fixtures:
- `minimal_config` — minimal config dict for testing modules that take `config`
- `sample_job` — a single clean Anthropic ML job dict
- `two_jobs` — two clean jobs for pipeline tests
- `sample_resume` — realistic ML resume text

## Mocking LLM Calls
All LLM calls must be mocked in unit tests. Use:

```python
from unittest.mock import patch, MagicMock

with patch("openai.OpenAI") as MockOpenAI:
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"score": 85}'))]
    )
    MockOpenAI.return_value = mock_client
    # ... test code
```

## Markers
- `@pytest.mark.unit` — pure unit test, no I/O
- `@pytest.mark.slow` — takes >5s (DB migration, file I/O heavy)
- `@pytest.mark.integration` — needs real API keys or network

## Coverage Requirements
- Minimum: 40% (enforced in pyproject.toml)
- Target: 70% for `app/`, `ai/` core modules
- Excluded: `scripts/seed.py`, `data/`, `resumes/`

## Golden Dataset Eval
Run the full offline eval against the golden dataset:
```bash
python evaluation/offline_eval.py --feature scoring
python evaluation/offline_eval.py --feature cover_letters
python evaluation/offline_eval.py --feature scam
python evaluation/offline_eval.py --save   # Save results to eval_results/
```

## CI
Tests run on every push via GitHub Actions (`.github/workflows/test.yml`).
The pipeline:
1. `pip install -e ".[dev]"`
2. `python scripts/healthcheck.py --quick`
3. `pytest tests/ -v`
4. `ruff check .`

PRs blocked if tests fail.
