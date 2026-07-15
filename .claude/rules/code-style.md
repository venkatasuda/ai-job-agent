# Code Style Rules

Rules enforced by ruff. Run `ruff check .` and `ruff format .` before committing.

## Python Version
- Target: Python 3.10+
- Use `match/case` for multi-branch dispatch where appropriate
- Use `X | Y` union types instead of `Optional[X]`
- Use `from __future__ import annotations` in every new file

## Imports
Order: stdlib → third-party → local. One blank line between groups.
Never use `import *`. Always use explicit imports.

## Naming
- `snake_case` for functions, variables, modules
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for module-level constants
- Prefix private methods with `_`

## Functions
- Max function length: 50 lines. Extract helpers if longer.
- Max line length: 100 characters.
- All public functions must have a one-line docstring minimum.
- Use `-> ReturnType` annotations on all public functions.

## Error Handling
- Never use bare `except:`. Always catch specific exceptions.
- Log errors with `logger.error(f"...: {e}")` before re-raising or swallowing.
- Use `logger.debug()` for verbose tracing, `logger.info()` for milestone events.

## LLM Calls
- Always use `REGISTRY.get("prompt_key")` — never hardcode prompts inline.
- Always call `cost_tracker.record(stage, model, tokens_in, tokens_out)` after each LLM call.
- Wrap LLM calls with `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`.
- Always pass response through the appropriate `OutputFilter` method before using.

## Config
- Never read `config.yaml` directly with `yaml.safe_load` in new code.
- Use `get_settings()` from `app.config` for type-safe access.
- Pass `settings.as_legacy_dict()` to older modules that expect a plain dict.

## Models
- New data structures must be Pydantic `BaseModel` subclasses, not plain dicts.
- Use `model_config = {"extra": "allow"}` on Job-adjacent models for forward compatibility.

## Tests
- Every new module must have at least one corresponding test in `tests/`.
- Tests must not make real network calls — use `unittest.mock.patch`.
- Use `pytest.fixture` for shared test data, never module-level globals.
- Mark slow/integration tests with `@pytest.mark.slow` / `@pytest.mark.integration`.
