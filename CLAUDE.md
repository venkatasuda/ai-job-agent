# CLAUDE.md — AI Job Agent Codebase Guide

This file is for AI coding agents (Claude Code, Cursor, Copilot, etc.) working on this project.
Read this before modifying any code.

---

## What This Project Does

An autonomous job search agent that:
1. Scrapes jobs every hour from LinkedIn, Indeed, Glassdoor, Greenhouse, Lever, Ashby, and GitHub boards
2. Scores each job against a resume using LLMs (0–100)
3. Writes cover letters, researches companies, preps interview questions
4. Tracks applications in SQLite, sends alerts via email/WhatsApp
5. Shows everything in a Streamlit dashboard

---

## Project Layout

```
ai-job-agent/
├── app/                    # Production-grade core (NEW)
│   ├── config.py           # Pydantic Settings v2 — single source of truth for config
│   ├── models.py           # Pydantic data models (Job, PipelineRun, ScoringResult, …)
│   ├── Dockerfile          # Multi-stage Docker build
│   ├── prompts/
│   │   ├── templates.py    # Prompt dataclasses with version + cost estimate
│   │   └── registry.py     # REGISTRY singleton — get_prompt(), render_prompt()
│   └── security/
│       ├── input_guard.py  # Layer 1: injection, scam, PII detection
│       ├── content_filter.py # Layer 2: ghost jobs, quality scoring
│       └── output_filter.py  # Layer 3: placeholder/hallucination check
│
├── ai/                     # Intelligence modules (original)
│   ├── job_scorer.py       # LLM scoring (main pipeline step 4)
│   ├── cover_letter.py     # Drafter–Reviewer 3-pass pipeline (step 5)
│   ├── company_researcher.py
│   ├── ats_scanner.py
│   ├── interview_prep.py
│   ├── repost_detector.py
│   ├── visa_filter.py
│   ├── hiring_signal.py    # GREEN/YELLOW/RED company health signals
│   ├── market_pulse.py     # Weekly trend analysis
│   ├── freeze_detector.py  # FROZEN/HIRING/SURGE classification
│   ├── jd_summarizer.py    # TL;DR + red/green flags (no LLM needed)
│   ├── personal_scorer.py  # Thompson sampling preference tracker
│   ├── ab_testing.py       # A/B cover letter opening styles
│   ├── timing_optimizer.py # Best day/hour to apply
│   ├── leetcode_recommender.py
│   ├── system_design_plan.py
│   ├── voice_interview.py
│   ├── resume_version_control.py
│   ├── reference_manager.py
│   ├── event_finder.py
│   ├── alumni_mapper.py
│   ├── study_group.py
│   └── jobboard_subscriber.py  # RSS + HN Who's Hiring
│
├── scrapers/               # Data ingestion
│   ├── jobspy_scraper.py   # JobSpy wrapper (LinkedIn/Indeed/Glassdoor/…)
│   ├── ats_scraper.py      # Greenhouse/Lever/Ashby JSON APIs (45+ companies)
│   ├── newgrad_scraper.py  # PittCSC/Simplify GitHub boards
│   └── discord_monitor.py  # Discord job channel reader
│
├── alerts/
│   ├── email_alert.py
│   └── whatsapp_alert.py
│
├── integrations/
│   └── notion_sync.py      # Notion + Airtable sync
│
├── database/
│   └── db.py               # JobDatabase wrapper around SQLite
│
├── dashboard/
│   ├── app.py              # 8-tab Streamlit app
│   └── pwa/                # Progressive Web App (manifest + service worker)
│
├── observability/          # Production telemetry (NEW)
│   ├── tracer.py           # PipelineTracer with per-stage spans
│   ├── cost_tracker.py     # LLM cost log (append-only JSONL)
│   └── feedback.py         # Thumbs up/down feedback capture
│
├── evaluation/             # Quality assurance (NEW)
│   ├── golden_dataset.json # Ground-truth test cases
│   ├── offline_eval.py     # pytest-compatible eval runner
│   └── online_monitor.py   # Live quality monitoring
│
├── scripts/                # Ops tooling (NEW)
│   ├── migrate.py          # DB migration runner (10 migrations)
│   ├── seed.py             # Populate DB with 20 sample jobs
│   └── healthcheck.py      # Docker-compatible health check
│
├── tests/                  # CI test suite (NEW)
│   ├── conftest.py
│   ├── test_scrapers.py
│   ├── test_scoring.py
│   └── test_pipeline.py
│
├── docs/
├── .claude/rules/
├── main.py                 # Entry point + APScheduler pipeline
├── config.yaml             # User-editable configuration
├── pyproject.toml          # Python packaging + tool config
└── docker-compose.yml
```

---

## Key Conventions

### Config
- **Never** import `config.yaml` directly with `yaml.safe_load` in new code.
- Use `from app.config import get_settings` → returns a cached `Settings` Pydantic object.
- Existing modules that take a `config: dict` param are fine — use `settings.as_legacy_dict()` to pass.

### Models
- New code should use `from app.models import Job, PipelineRun, ScoringResult, …`
- Existing modules return plain dicts — use `Job.from_legacy_dict(d)` to upgrade.
- `Job` has `extra='allow'` so adding unknown fields never breaks anything.

### Prompts
- **Never** hardcode prompt strings inline. Use `from app.prompts.registry import render_prompt`.
- Add new prompts to `app/prompts/templates.py` with a key, version, and token estimate.

### Security
- Every scraped job must pass through `InputGuard.validate_job()` before LLM processing.
- Output filter `OutputFilter.validate_cover_letter()` must run before saving or sending any cover letter.

### Observability
- Wrap each pipeline stage with `tracer.span(name, input_count=n)`.
- Call `cost_tracker.record(stage, model, tokens_in, tokens_out)` after every LLM call.

### Database
- Add new columns via `scripts/migrate.py` — never raw `ALTER TABLE` in application code.
- `db.filter_new(jobs)` handles dedup; always call before `db.save_jobs()`.

---

## LLM Cost Budget

| Provider | Model | Cost/1K tokens | Monthly est. |
|---|---|---|---|
| OpenAI | gpt-4o-mini | $0.15/$0.60 | ~$1–2 |
| Google | gemini-1.5-flash | free (15 RPM) | $0 |
| Ollama | llama3.1:8b | free | $0 |

**Default:** gpt-4o-mini. Switch to Gemini Flash in `config.yaml` → `ai.provider: gemini` for zero cost.

---

## Running Locally

```bash
# Install
pip install -e ".[dev]"

# Setup
cp config.yaml.example config.yaml
nano config.yaml            # Add resume path, API key

# Migrate DB
python scripts/migrate.py

# Health check
python scripts/healthcheck.py

# Run once
python main.py --once

# Dashboard
streamlit run dashboard/app.py

# Tests
pytest tests/ -v
```

---

## Common Gotchas

1. **`jobs.db` path**: Configured in `config.yaml → database.path`. Default is `./jobs.db` in the project root.
2. **Resume file**: Must exist at the path set in `config.yaml → profile.resume_path`. Min 100 bytes.
3. **Ollama**: Start with `ollama serve` + `ollama pull llama3.1:8b` before using local LLM.
4. **Discord scraper**: Needs a bot token in `config.yaml → scrapers.discord.bot_token`.
5. **WhatsApp**: CallMeBot (free) needs one-time WhatsApp message to activate. See alerts/whatsapp_alert.py.
6. **Windows paths**: All file paths in code use `pathlib.Path` — safe on Windows.
