# Architecture Overview

## System Design

The AI Job Agent is a local-first, single-machine application with an optional Docker deployment.
It runs an 11-step hourly pipeline, stores everything in SQLite, and exposes a Streamlit dashboard.

```
┌─────────────────────────────────────────────────────────┐
│                    PIPELINE (hourly)                     │
│                                                         │
│  1. Scrape ──→ 2. Filter ──→ 3. Dedup ──→ 4. Score     │
│      ↓              ↓              ↓           ↓        │
│  [JobSpy]     [InputGuard]   [DB dedup]   [LLM 0-100]  │
│  [ATS APIs]   [VisaFilter]   [Fingerprint] [Pydantic]  │
│  [RSS feeds]  [FreezeDetect] [URL dedup]               │
│  [Discord]                                              │
│                                                         │
│  5. Cover Letter ──→ 6. Research ──→ 7. Prep           │
│         ↓                 ↓              ↓             │
│  [3-pass LLM]      [Company intel]  [ATS scan]         │
│  [OutputFilter]    [HiringSignal]   [LeetCode]         │
│                    [MarketPulse]    [SysDesign]         │
│                                                         │
│  8. Save ──→ 9. Alerts ──→ 10. Apply ──→ 11. Learn     │
│      ↓            ↓              ↓           ↓         │
│  [SQLite]   [Email/WhatsApp] [Auto-apply] [Feedback]   │
│  [Notion]   [Dashboard]     [Timing opt] [A/B test]   │
│  [Airtable]                              [PersonalScore]│
└─────────────────────────────────────────────────────────┘
```

## Layer Architecture

```
┌──────────────────────────────────────────┐
│  Presentation: Streamlit (8 tabs)        │
│  + PWA (manifest + service worker)       │
├──────────────────────────────────────────┤
│  Orchestration: main.py + APScheduler   │
├────────────────┬─────────────────────────┤
│  AI Agents     │  Security              │
│  ai/*.py       │  app/security/         │
│  (20+ modules) │  (3 layers)            │
├────────────────┼─────────────────────────┤
│  Prompts       │  Observability         │
│  app/prompts/  │  observability/        │
│  (12 versioned)│  (tracer, cost, fbk)   │
├────────────────┴─────────────────────────┤
│  Data Models: app/models.py (Pydantic)  │
├──────────────────────────────────────────┤
│  Config: app/config.py (Pydantic v2)    │
├──────────────────────────────────────────┤
│  Storage: SQLite (10 migrations)        │
│  + JSONL logs (cost, feedback, traces)  │
└──────────────────────────────────────────┘
```

## Data Flow

### Job Lifecycle
```
raw_dict (from scraper)
  → InputGuard.validate_job() → ValidationResult
  → Job.from_legacy_dict()    → Job (Pydantic model)
  → scorer.score_job()        → Job with score, verdict
  → cover_letter.write()      → Job with cover_letter
  → OutputFilter.validate()   → validated cover_letter
  → db.save_jobs()            → persisted to SQLite
  → NotionSync.upsert_job()   → synced to Notion
```

### Config Flow
```
config.yaml
  → Settings.from_yaml()     → Settings (Pydantic)
  → get_settings()           → cached singleton
  → settings.as_legacy_dict() → dict for legacy modules
```

### Observability Flow
```
pipeline stage runs
  → tracer.span("stage", n)  → Span (timing, tokens, cost)
  → cost_tracker.record()    → appended to cost_log.jsonl
  → tracer.save()            → traces/trace_{run_id}.json
  → online_monitor.snapshot() → evaluation/metrics_history.jsonl
```

## Key Design Decisions

### SQLite over PostgreSQL
- Simpler deployment — no server needed
- Sufficient for single-user job tracking (< 10K rows)
- Easy backup (copy one file)
- Migration-based schema evolution via `scripts/migrate.py`

### Pydantic Settings v2 over raw YAML
- Type safety + IDE autocomplete
- Env var overrides (`OPENAI_API_KEY` → `settings.ai.openai_api_key`)
- `.env` file support
- `as_legacy_dict()` for backward compatibility

### 3-Pass Cover Letter (Drafter–Reviewer–Reviser)
- Single-pass LLMs write generic letters
- Reviewer catches missing company references, wrong tone
- Only revises if `REWRITE_NEEDED:YES` — saves cost on good first drafts
- OutputFilter as final safety net

### Thompson Sampling for Personalization
- Starts uniform (no bias)
- Learns company/location/source/remote preferences from interactions
- Adjusts score ±20 points after 10+ interactions
- Separate from main LLM score — additive, transparent

### Prompt Registry (Hot-swappable)
- Prompts versioned in `app/prompts/templates.py`
- `REGISTRY.get("scoring")` returns latest version
- Override at runtime: `REGISTRY.register(my_prompt)`
- Cost estimates per prompt for budget planning

## Scaling Limits

| Dimension | Current limit | How to scale |
|---|---|---|
| Jobs/hour | ~500 (API rate limits) | Add more scraper sources |
| LLM cost | ~$0.10/run | Switch to Gemini Flash (free) |
| Storage | ~100MB/year | Purge old jobs with `db.cleanup()` |
| Dashboard | Single-user Streamlit | Add auth or deploy to server |
| Scheduling | APScheduler (in-process) | Move to Celery + Redis for multi-worker |
