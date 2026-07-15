# 🤖 AI Job Agent — Setup Guide

## What This Does

Every hour, this agent:
1. **Scrapes** LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter + direct company career pages
2. **Scores** each job 0–100 against your resume using AI
3. **Generates** a personalized cover letter for each high-match job
4. **Alerts** you via email digest + Telegram instant message
5. **Auto-applies** to LinkedIn Easy Apply jobs scoring above your threshold
6. Shows everything in a **Streamlit dashboard** at http://localhost:8501

---

## Quick Start (5 Steps)

### Step 1 — Install dependencies
```bash
cd ai_job_agent
pip install -r requirements.txt
playwright install chromium   # For auto-apply
```

### Step 2 — Add your resume
Save your resume as **`resume.txt`** (plain text) in the `ai_job_agent/` folder.
PDF and DOCX also work — just update `resume_path` in `config.yaml`.

### Step 3 — Configure `config.yaml`
Open `config.yaml` and fill in:

| Field | What to put |
|---|---|
| `profile.name` | Your full name |
| `profile.email` | Your email |
| `search.keywords` | Job titles you want |
| `search.locations` | Where you want to work |
| `ai.provider` | `openai` (recommended) or `gemini` or `ollama` (free) |
| `ai.openai_api_key` | Your OpenAI API key (get from platform.openai.com) |
| `alerts.email.sender_email` | Your Gmail address |
| `alerts.email.sender_password` | Gmail App Password (not your regular password) |
| `alerts.email.recipient_email` | Where to send alerts (can be same as sender) |

### Step 4 — (Optional) Telegram alerts
1. Message @BotFather on Telegram → `/newbot` → get your `bot_token`
2. Message your new bot, then visit:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   to find your `chat_id`
3. Set both in `config.yaml` and set `telegram.enabled: true`

### Step 5 — Run it
```bash
# Full agent (hourly pipeline + dashboard)
python main.py

# Run once and exit
python main.py --once

# Dashboard only (browse existing results)
python main.py --dashboard-only
```

Dashboard opens at → **http://localhost:8501**

---

## Free AI Option (No API Key Needed)

Use Ollama to run AI locally for free:
```bash
# Install Ollama from https://ollama.ai
ollama pull llama3

# In config.yaml:
# ai:
#   provider: ollama
#   model: llama3
```

Scoring will be slower but completely free.

---

## Gmail App Password Setup

Regular Gmail passwords won't work. You need an App Password:
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search "App passwords" → Create one for "Mail"
4. Use that 16-character password in `config.yaml`

---

## Auto-Apply Setup

By default, auto-apply is **disabled** for safety. To enable:
```yaml
ai:
  auto_apply:
    enabled: true
    max_applications_per_run: 5   # Start low!
    require_min_score: 85         # Only apply to great matches

linkedin:
  email: "your@email.com"
  password: "yourpassword"
```

> ⚠️ Start with `max_applications_per_run: 2` and watch the first few runs.
> LinkedIn may require CAPTCHA occasionally — the bot will skip those gracefully.

---

## Adding More Companies (ATS)

Edit the `ats_companies.targets` section in `config.yaml`:
```yaml
- ["Company Name", "greenhouse", "company-token"]
- ["Startup", "lever", "https://jobs.lever.co/startup"]
- ["Another", "ashby", "https://jobs.ashbyhq.com/another"]
```

Find the token by visiting the company's careers page — the URL usually contains it.

---

## Project Structure

```
ai_job_agent/
├── main.py              # Entry point / orchestrator
├── config.yaml          # Your configuration
├── resume.txt           # Your resume (add this!)
├── requirements.txt
├── scrapers/
│   ├── jobspy_scraper.py   # LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter
│   └── ats_scraper.py      # Greenhouse, Lever, Ashby company pages
├── ai/
│   ├── scorer.py           # AI match scoring (0-100)
│   ├── cover_letter.py     # Personalized cover letter generation
│   └── auto_apply.py       # LinkedIn Easy Apply automation
├── alerts/
│   ├── email_alert.py      # HTML email digest
│   └── telegram_alert.py   # Telegram bot alerts
├── database/
│   └── db.py               # SQLite storage + deduplication
└── dashboard/
    └── app.py              # Streamlit web dashboard
```

---

## Estimated Costs (OpenAI)

Using `gpt-4o-mini` (cheapest model):
- Scoring 50 jobs: ~$0.02
- 50 cover letters: ~$0.05
- **Running hourly for a month: ~$2–5 total**

Set `ai.model: gpt-4o-mini` to keep costs minimal.
