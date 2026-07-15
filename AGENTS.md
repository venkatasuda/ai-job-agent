# AGENTS.md — Agent Definitions

This file defines the autonomous agents that make up the AI Job Agent system.
Each agent has a specific role, inputs, outputs, and cost profile.

---

## Agent 1: ScraperAgent

**Role:** Collect raw job postings from all sources every hour.

**Inputs:** `config.yaml` (keywords, locations, sources)
**Outputs:** List of raw job dicts

**Sources:**
- JobSpy: LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter
- ATS APIs: Greenhouse, Lever, Ashby (45+ companies)
- New Grad boards: PittCSC GitHub, Simplify.jobs
- RSS feeds: RemoteOK, WeWorkRemotely, Indeed RSS
- HN Who's Hiring: Monthly Algolia scrape
- Discord: Job channels via bot token

**Cost:** $0 (no LLM calls — pure HTTP scraping)
**Frequency:** Hourly via APScheduler

---

## Agent 2: FilterAgent

**Role:** Remove duplicates, scams, frozen companies, and irrelevant postings.

**Inputs:** Raw job list from ScraperAgent
**Outputs:** Cleaned job list

**Steps:**
1. `InputGuard.validate_job()` — injection/scam/PII detection
2. `RepostDetector.filter_jobs()` — URL + fingerprint dedup
3. `db.filter_new()` — DB-level dedup (30-day window)
4. `VisaFilter.classify()` — sponsorship check
5. `FreezeDetector.filter_frozen()` — hiring freeze removal
6. `ContentFilter.check_job()` — ghost job / quality filter

**Cost:** $0 (all rule-based)

---

## Agent 3: ScoringAgent

**Role:** Score each job 0–100 against the user's resume.

**Inputs:** Cleaned job list + resume text
**Outputs:** Jobs with `score`, `verdict`, `reason` fields

**Prompt:** `REGISTRY.get("scoring")` (versioned, hot-swappable)
**Model:** gpt-4o-mini (or Gemini Flash free tier)
**Cost:** ~$0.002 per job scored
**Filter:** Only jobs with score ≥ `config.scoring.min_score` continue to next stage.

---

## Agent 4: CoverLetterAgent

**Role:** Write a tailored cover letter using a 3-pass drafter–reviewer pipeline.

**Inputs:** High-scoring job + resume
**Outputs:** `cover_letter` (3-pass revised), `email_draft`

**Pipeline:**
1. **Drafter**: Write initial cover letter (prompt: `cover_letter_draft`)
2. **Reviewer**: Critique it — returns `REWRITE_NEEDED:YES/NO` + feedback (prompt: `cover_letter_review`)
3. **Reviser**: If `REWRITE_NEEDED:YES`, revise with feedback (prompt: `cover_letter_revise`)
4. **OutputFilter**: Validate no placeholders, company name present, min length

**Cost:** ~$0.008 per cover letter (3 LLM calls)

---

## Agent 5: ResearchAgent

**Role:** Gather company intelligence to personalize applications.

**Inputs:** Job (company name + URL)
**Outputs:** Company summary, culture score, hiring signals, interview tips

**Sub-agents:**
- `CompanyResearcher`: funding, culture, tech stack (prompt: `company_research`)
- `HiringSignalMonitor`: DuckDuckGo + Layoffs.fyi → GREEN/YELLOW/RED
- `MarketPulse`: Weekly industry trend analysis
- `FreezeDetector`: FROZEN/HIRING/SURGE classification

**Cost:** ~$0.003 per company researched (cached 24h)

---

## Agent 6: PrepAgent

**Role:** Generate interview preparation materials.

**Inputs:** Job + company research
**Outputs:** Interview questions, system design plan, LeetCode problems, ATS report

**Sub-agents:**
- `InterviewPrep`: Role-specific questions (prompt: `interview_prep`)
- `ATSScanner`: Resume keyword gap analysis (prompt: `ats_scan`)
- `LeetCodeRecommender`: Company-specific problem sets
- `SystemDesignPlan`: Design topic study plan

**Cost:** ~$0.005 per job prepped

---

## Agent 7: OutreachAgent

**Role:** Generate personalized cold outreach messages.

**Inputs:** Job + company research + alumni data
**Outputs:** LinkedIn DM variants, cold email, referral request

**Sub-agents:**
- `AlumniMapper`: LinkedIn search URL + outreach message templates
- `ReferenceManager`: Reference request emails + briefings

**Cost:** $0 (template-based, no LLM)

---

## Agent 8: ApplicationAgent

**Role:** Track applications and optionally auto-apply.

**Inputs:** Approved jobs with cover letters
**Outputs:** Updated DB records, Notion/Airtable sync, alerts sent

**Actions:**
- Save to SQLite (`database/db.py`)
- Sync to Notion (`integrations/notion_sync.py`)
- Sync to Airtable (`integrations/notion_sync.AirtableSync`)
- Send email alert (`alerts/email_alert.py`)
- Send WhatsApp alert (`alerts/whatsapp_alert.py`)
- Auto-apply if score ≥ `config.scoring.auto_apply_threshold` (default: 90)

**Cost:** $0 (no LLM calls)

---

## Agent 9: LearningAgent

**Role:** Continuously improve recommendations based on feedback.

**Inputs:** User interactions (view, save, apply, skip, callback)
**Outputs:** Updated preference weights, better re-ranking

**Components:**
- `PersonalScoringModel`: Thompson sampling preference tracker
- `ABTestingEngine`: Cover letter style A/B test
- `TimingOptimizer`: Best day/hour to apply
- `ResumeVersionControl`: Track which resume version gets callbacks

**Cost:** $0 (local only)

---

## Pipeline Orchestration

```
ScraperAgent
    ↓
FilterAgent (dedup + security)
    ↓
ScoringAgent (LLM)
    ↓ (score ≥ threshold)
CoverLetterAgent (LLM, 3-pass)
    ↓
ResearchAgent (LLM + DuckDuckGo)
    ↓
PrepAgent (LLM)
    ↓
OutreachAgent (templates)
    ↓
ApplicationAgent (DB + alerts)
    ↓
LearningAgent (feedback loop)
```

Total cost per pipeline run: ~$0.02–0.10 depending on job count.
Monthly cost (hourly runs): ~$1–3 on gpt-4o-mini, $0 on Gemini Flash free tier.

---

## Adding a New Agent

1. Create `ai/my_agent.py` with a class that has a `run(jobs, config) → jobs` method.
2. Add import to `ai/__init__.py`.
3. Add config section to `config.yaml`.
4. Wire into `main.py` pipeline at the appropriate step.
5. Add prompt to `app/prompts/templates.py` if LLM is needed.
6. Add tests to `tests/`.
7. Update this file.
