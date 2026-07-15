# AI Job Agent

**Autonomous job search agent** — scrapes every job board hourly, scores each posting against your resume with AI, writes tailored cover letters, researches companies, and tracks your entire pipeline in a dashboard.

Built for Masters/PhD students and new grads targeting AI/ML and software engineering roles.

---

## What It Does

```
Every Hour →  Scrape 500+ jobs from LinkedIn, Indeed, Glassdoor,
              Greenhouse, Lever, Ashby, GitHub boards, RSS feeds

              Filter  →  Remove scams, duplicates, frozen companies,
                         sponsorship mismatches

              Score   →  LLM scores each job 0–100 against your resume
                         (costs ~$0.002/job with gpt-4o-mini)

              Write   →  3-pass cover letter (draft → review → revise)
                         + personalized email draft

              Research →  Company intel, hiring signals (GREEN/YELLOW/RED),
                          freeze detection, culture score

              Prep    →  Interview questions, ATS scan, LeetCode problems,
                         system design study plan

              Track   →  SQLite + Streamlit dashboard + Notion/Airtable sync
                         + WhatsApp/email alerts
```

**Monthly AI cost: ~$1–2 on gpt-4o-mini | $0 on Gemini Flash free tier**

---

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
cp config.yaml.example config.yaml
# Fill in: your name, resume path, keywords, API key

# 3. Add your resume
echo "Your resume text" > resume.txt

# 4. Setup DB
python scripts/migrate.py

# 5. Run
python main.py --run-once

# 6. Dashboard
streamlit run dashboard/app.py
```

---

## Features (20 Modules)

| Feature | What it does |
|---|---|
| **JobSpy scraping** | LinkedIn, Indeed, Glassdoor, ZipRecruiter |
| **ATS scraping** | Greenhouse/Lever/Ashby APIs for 45+ companies |
| **New Grad boards** | PittCSC, Simplify, Handshake GitHub lists |
| **RSS feeds** | RemoteOK, WeWorkRemotely, HN Who's Hiring |
| **Hiring signals** | GREEN/YELLOW/RED company health via DuckDuckGo |
| **Freeze detector** | FROZEN/HIRING/SURGE classification |
| **Market pulse** | Weekly industry trend analysis |
| **JD summarizer** | TL;DR + red/green flags (rule-based, free) |
| **Cover letter** | 3-pass drafter–reviewer–reviser pipeline |
| **A/B testing** | Story/direct/question/data opening styles |
| **Personal scoring** | Thompson sampling preference tracker |
| **Timing optimizer** | Best day/hour to apply per company |
| **LeetCode recommender** | Company-specific problem sets + study plan |
| **System design plan** | Company-tailored design study guide |
| **Voice interview** | Practice with AI feedback + filler word detection |
| **Resume versioning** | Track which version gets callbacks |
| **Reference manager** | Request emails + briefing docs |
| **Event finder** | Conferences, meetups, career fairs |
| **Alumni mapper** | LinkedIn outreach + referral emails |
| **Study group** | Multi-user company claim + leaderboard |

---

## Project Structure

```
ai-job-agent/
├── app/              # Core: config, models, prompts, security
├── ai/               # 20+ intelligence modules
├── scrapers/         # Data ingestion (JobSpy, ATS, RSS, Discord)
├── alerts/           # Email + WhatsApp notifications
├── database/         # SQLite wrapper
├── dashboard/        # 8-tab Streamlit UI + PWA
├── observability/    # Tracing, cost tracking, feedback
├── evaluation/       # Golden dataset + quality monitoring
├── scripts/          # migrate.py, seed.py, healthcheck.py
├── tests/            # pytest test suite
├── docs/             # Architecture, API reference, deployment
├── main.py           # Entry point + scheduler
├── config.yaml       # Your configuration
└── pyproject.toml    # Dependencies + tool config
```

---

## Configuration

Edit `config.yaml`:

```yaml
profile:
  name: "Your Name"
  resume_path: "resume.txt"
  target_roles: ["ML Engineer", "Software Engineer", "Data Scientist"]
  target_companies: ["Anthropic", "OpenAI", "Google DeepMind"]

search:
  keywords: ["Machine Learning Engineer", "AI Engineer"]
  locations: ["Remote", "San Francisco, CA", "New York, NY"]
  excluded_keywords: ["unpaid", "commission only", "sales"]

ai:
  provider: openai         # openai | gemini | ollama
  model: gpt-4o-mini
  openai_api_key: sk-...   # or use OPENAI_API_KEY env var

scoring:
  min_score: 70            # Only process jobs scoring ≥70
  auto_apply_threshold: 90 # Auto-apply if score ≥90

alerts:
  email:
    enabled: true
    to: your@email.com
  whatsapp:
    enabled: false         # See alerts/whatsapp_alert.py
```

---

## AI Cost Breakdown

| Stage | Model | Cost/job | Monthly (500 jobs/day) |
|---|---|---|---|
| Scoring | gpt-4o-mini | $0.002 | $30 |
| Cover letter | gpt-4o-mini | $0.008 | — (only high scores) |
| Company research | gpt-4o-mini | $0.003 | — (cached 24h) |
| **Total** | | | **~$1–2/month** |

**Free alternative:** Set `ai.provider: gemini` to use Gemini 1.5 Flash free tier (15 requests/minute).

---

## Running Tests

```bash
pytest tests/ -v                    # Unit tests
pytest tests/ -v --integration      # Integration tests (needs API keys)
pytest --cov=ai --cov-report=html   # Coverage report
python evaluation/offline_eval.py --feature scoring  # Eval golden dataset
```

---

## Docker

```bash
docker-compose --profile scheduler --profile dashboard up -d
# Dashboard: http://localhost:8501
```

---

## CLI Commands

```bash
python main.py --run-once           # Run pipeline once
python main.py --schedule           # Start hourly scheduler
python main.py --market-pulse       # Weekly market analysis
python main.py --leetcode Google    # LeetCode plan for company
python main.py --system-design Meta # System design plan

python scripts/migrate.py           # Run DB migrations
python scripts/healthcheck.py       # System health check
python scripts/seed.py              # Seed sample jobs
```

---

## License

MIT — use freely, modify freely, attribution appreciated.
