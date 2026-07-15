# API Reference

## app.config

### `get_settings(config_path="config.yaml") → Settings`
Returns the cached Pydantic settings singleton.

```python
from app.config import get_settings
settings = get_settings()
print(settings.ai.model)          # "gpt-4o-mini"
print(settings.profile.name)      # "Venky"
```

### `Settings.from_yaml(path: str) → Settings`
Load settings from a YAML file. Used by `get_settings()`.

### `Settings.as_legacy_dict() → dict`
Convert Pydantic settings to a plain dict for legacy modules.

### `reload_settings() → Settings`
Clear the LRU cache and reload. Use in tests.

---

## app.models

### `Job(**kwargs) → Job`
Core data model for a job posting.

Key fields:
- `id: str` — UUID
- `title: str`, `company: str`, `location: str`
- `job_url: str` — unique identifier
- `description: str`
- `score: float | None` — 0–100 LLM score
- `verdict: str | None` — STRONG_MATCH / GOOD_MATCH / WEAK_MATCH / SKIP
- `cover_letter: str | None`
- `interview_stage: str` — not_applied / applied / phone_screen / technical / offer / rejected
- `is_remote: bool`, `is_new_grad: bool`
- `salary_min: float | None`, `salary_max: float | None`
- `visa_status: str | None` — SPONSORS / NO_SPONSOR / UNKNOWN

Computed fields:
- `display_score: str` — score as string or "—"
- `is_high_match: bool` — score >= 80

Methods:
- `to_db_dict() → dict` — flatten for SQLite insert
- `from_db_dict(row: dict) → Job` — reconstruct from DB row
- `from_legacy_dict(d: dict) → Job` — upgrade from plain dict

### `PipelineRun(run_number: int) → PipelineRun`
Tracks a single pipeline execution.

Methods:
- `finish() → None` — set `elapsed_seconds`, `status="completed"`

### `ScoringResult(score, verdict, reason, ...) → ScoringResult`

### `CoverLetterResult(cover_letter, email_draft, ...) → CoverLetterResult`

---

## app.prompts.registry

### `REGISTRY: PromptRegistry`
Module-level singleton. Use this instead of creating `PromptRegistry()` yourself.

### `get_prompt(key: str, version: str | None = None) → Prompt`
Get a prompt by key. Returns latest version if `version=None`.

```python
from app.prompts.registry import get_prompt
prompt = get_prompt("scoring")
```

### `render_prompt(key: str, **kwargs) → str`
Get and render a prompt in one call.

```python
from app.prompts.registry import render_prompt
text = render_prompt("scoring", resume="...", job_title="SWE", ...)
```

### `Prompt` dataclass
- `key: str`, `version: str`, `description: str`
- `template: str` — jinja2-style `{variable}` substitution
- `tokens_in_estimate: int`, `tokens_out_estimate: int`
- `model_hint: str` — recommended model
- `render(**kwargs) → str`
- `estimated_cost_usd: float` (property)

---

## app.security

### InputGuard

```python
from app.security.input_guard import InputGuard
guard = InputGuard()
result = guard.validate_job(job_dict)
# result.valid: bool
# result.cleaned: dict  (sanitized job)
# result.warnings: list[str]
# result.blocked: bool
# result.block_reason: str | None
```

```python
valid_jobs, blocked_jobs = guard.batch_validate_jobs(jobs)
masked = InputGuard.mask_pii("email: john@example.com")
```

### ContentFilter

```python
from app.security.content_filter import ContentFilter
cf = ContentFilter()
result = cf.check_job(job_dict)
# result.passed: bool
# result.reason: str
# result.score_adjustment: float  (-5 for quality issues)
# result.tags: list[str]  ("ghost_job", "low_quality", ...)
```

### OutputFilter

```python
from app.security.output_filter import OutputFilter
result = OutputFilter.validate_cover_letter(text, company="Anthropic")
# result.valid: bool, result.reason: str

parsed = OutputFilter.validate_json(llm_output)
# Returns dict or None

dm = OutputFilter.validate_linkedin_dm(text)
# Returns truncated string (max 300 chars)
```

---

## observability

### PipelineTracer

```python
from observability.tracer import PipelineTracer
tracer = PipelineTracer(run_id="run-001")

with tracer.span("scoring", input_count=10) as span:
    span.tokens_in = 1000
    span.tokens_out = 200
    # do work

tracer.save()  # writes trace JSON

traces = PipelineTracer.load_recent(n=5)  # list of trace dicts
```

### CostTracker

```python
from observability.cost_tracker import CostTracker
tracker = CostTracker()
tracker.record("scoring", "gpt-4o-mini", tokens_in=1000, tokens_out=200, job_count=5)
stats = tracker.get_stats(days=30)
# stats.total_cost_usd, stats.by_stage, stats.projected_monthly_usd, stats.budget_warning
```

### FeedbackCapture

```python
from observability.feedback import FeedbackCapture
fb = FeedbackCapture()
fb.thumbs_up(job_id="job-001", stage="cover_letter")
fb.thumbs_down(job_id="job-002", stage="scoring", comment="Wrong industry")
rates = fb.get_acceptance_rates()
```

---

## scripts

### `migrate.py`
```bash
python scripts/migrate.py           # Apply all pending migrations
python scripts/migrate.py --status  # Show migration status
python scripts/migrate.py --dry-run # Preview without applying
```

### `healthcheck.py`
```bash
python scripts/healthcheck.py        # Full health check
python scripts/healthcheck.py --quick # Fast subset
```
Exit code 0 = healthy, 1 = unhealthy (Docker compatible).

### `seed.py`
```bash
python scripts/seed.py              # Add 20 sample jobs
python scripts/seed.py --count 50  # Add N jobs
python scripts/seed.py --clear     # Clear + reseed
```

---

## database.db

### `JobDatabase(path, dedupe_window_days=30)`

```python
from database.db import JobDatabase
db = JobDatabase("jobs.db")

new_jobs = db.filter_new(jobs)    # Dedup against DB
db.save_jobs(new_jobs)            # Insert
all_jobs = db.get_all_jobs(limit=100, min_score=70)
stats = db.stats()                # total, avg_score, by_stage, ...
db.update_stage(job_id, "applied")
db.close()
```
