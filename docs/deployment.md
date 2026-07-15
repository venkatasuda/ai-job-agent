# Deployment Guide

## Option 1: Local Python (Recommended for personal use)

The simplest setup — runs directly on your machine.

```bash
# 1. Clone / copy to your machine
cd E:\ai_job_agent

# 2. Install Python deps
pip install -e ".[dev]"

# 3. Configure
cp config.yaml.example config.yaml
# Edit config.yaml:
#   profile.name, profile.resume_path
#   ai.provider + API key
#   search.keywords, search.locations

# 4. Create resume.txt
echo "Your resume text here..." > resume.txt

# 5. Run migrations
python scripts/migrate.py

# 6. Health check
python scripts/healthcheck.py

# 7. Seed sample data (optional)
python scripts/seed.py

# 8. Run pipeline once
python main.py --run-once

# 9. Start dashboard
streamlit run dashboard/app.py
# → Opens http://localhost:8501

# 10. Start hourly scheduler
python main.py --schedule
```

---

## Option 2: Docker (Recommended for servers/cloud)

```bash
# Build image
docker-compose build

# Run migrations
docker-compose run --rm migrate

# Run pipeline once
docker-compose --profile agent run --rm agent

# Start scheduled pipeline + dashboard
docker-compose --profile scheduler --profile dashboard up -d

# View logs
docker-compose logs -f agent-scheduler

# Open dashboard
# → http://localhost:8501
```

### With local Ollama (zero API cost)
```bash
# Pull llama3.1:8b first (one-time, ~5GB)
docker-compose --profile ollama up -d ollama
docker exec ollama ollama pull llama3.1:8b

# Set in config.yaml:
#   ai.provider: ollama
#   ai.model: llama3.1:8b

# Start everything
docker-compose --profile full up -d
```

---

## Option 3: Windows Task Scheduler (Hourly, no Docker)

Run the agent automatically on Windows without keeping a terminal open.

```powershell
# Create a scheduled task (runs every hour)
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "E:\ai_job_agent\main.py --run-once" `
    -WorkingDirectory "E:\ai_job_agent"

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date)

Register-ScheduledTask `
    -TaskName "AI Job Agent" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest
```

Or use the built-in APScheduler:
```bash
python main.py --schedule  # Runs in foreground, every hour
```

---

## Environment Variables

All config can be set via environment variables with `__` as delimiter.
This overrides `config.yaml` values.

```bash
export OPENAI_API_KEY=sk-...
export AI__MODEL=gpt-4o-mini         # maps to settings.ai.model
export DATABASE__PATH=./jobs.db
export PROFILE__NAME="Venky"
```

Or use a `.env` file (auto-loaded by Pydantic Settings):
```
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
```

---

## Switching AI Providers

### OpenAI (default, ~$1-2/month)
```yaml
ai:
  provider: openai
  model: gpt-4o-mini
  openai_api_key: sk-...
```

### Google Gemini (free tier, 15 RPM)
```yaml
ai:
  provider: gemini
  model: gemini-1.5-flash
  gemini_api_key: AIza...
```

### Ollama (local, zero cost)
```bash
ollama serve
ollama pull llama3.1:8b
```
```yaml
ai:
  provider: ollama
  model: llama3.1:8b
  ollama_host: http://localhost:11434
```

---

## Production Checklist

- [ ] `resume.txt` — realistic, 500+ words
- [ ] `config.yaml` — keywords include your target roles + locations
- [ ] API key set (OpenAI or Gemini)
- [ ] `python scripts/healthcheck.py` passes
- [ ] `python scripts/migrate.py` applied all 10 migrations
- [ ] Dashboard loads at `localhost:8501`
- [ ] First pipeline run: `python main.py --run-once` — sees at least 5 jobs
- [ ] Alerts configured (email or WhatsApp)
- [ ] Scheduler running (Task Scheduler or `python main.py --schedule`)

---

## Backup

```bash
# Backup the database (all your job data)
cp jobs.db jobs_backup_$(date +%Y%m%d).db

# Backup config
cp config.yaml config_backup.yaml

# Full backup
tar -czf job_agent_backup_$(date +%Y%m%d).tar.gz \
    jobs.db config.yaml resume.txt \
    observability/ evaluation/
```

---

## Monitoring

View system health:
```bash
python scripts/healthcheck.py          # System check
python evaluation/offline_eval.py --feature scoring  # Eval accuracy
python -c "from observability.cost_tracker import CostTracker; print(CostTracker().get_cost_breakdown_md())"
```

Dashboard tabs:
- **Jobs** — browse, filter, track stages
- **Stats** — score distribution, source breakdown
- **Pipeline** — last run timing, cost
- **Health** — system monitor metrics
- **Feedback** — cover letter acceptance rates
- **Market** — weekly market pulse
- **LeetCode** — company-specific prep
- **Settings** — live config editor
