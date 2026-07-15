"""
AI Job Agent — Main Orchestrator (v3)
======================================
Merges: JobSpy + career-ops + MadsLorentzen/ai-job-search + 20 new features

Full pipeline every hour:
  1. Scrape  → JobSpy + ATS (45+ companies) + New Grad boards + RSS feeds
  1b. Visa filter
  1c. Freeze detector (skip companies with hiring freezes)
  2. Filter  → Repost + scam + ghost job detector
  3. Dedup   → SQLite database
  4. Score   → AI resume matching 0-100 + personalized scoring
  5. Salary  → Estimate compensation + new grad salary benchmarks
  5b. JD Summarizer → TL;DR for each job
  6. Cover   → Drafter-reviewer two-pass cover letters + A/B testing
  7. Research→ Company research + hiring signals + culture analysis
  8. Prep    → Interview prep + LeetCode recommendations + system design
  8b. ATS scan + resume tailoring + cold outreach
  9. Save    → SQLite + Notion/Airtable sync
  10. Alerts → Email + Telegram + WhatsApp
  11. Apply  → LinkedIn Easy Apply auto-submit (top matches)
  12. Housekeeping → Gmail status sync + morning briefing + timing
  13. Upskill → Weekly skill gap + market pulse analysis

Usage:
  python main.py                  # Hourly agent + dashboard
  python main.py --once           # Run pipeline once and exit
  python main.py --upskill        # Run upskill analysis now
  python main.py --dashboard-only # Dashboard only
  python main.py --career-advice "Staff Engineer"
  python main.py --market-pulse   # Run market pulse now
  python main.py --leetcode COMPANY  # Get LeetCode recommendations
"""

import argparse
import logging
import os
import sys
import subprocess
import threading
import yaml
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from apscheduler.schedulers.blocking import BlockingScheduler

from scrapers.jobspy_scraper import JobSpyScraper
from scrapers.ats_scraper import ATSScraper
from ai.repost_detector import RepostDetector
from ai.scorer import JobScorer
from ai.cover_letter import CoverLetterGenerator
from ai.company_research import CompanyResearcher
from ai.salary_estimator import SalaryEstimator
from ai.interview_prep import InterviewPrep
from ai.followup_tracker import FollowUpTracker
from ai.upskill import UpskillAnalyzer
from ai.auto_apply import AutoApplier
from ai.resume_tailor import ResumeTailor
from ai.ats_scanner import ATSScanner
from ai.cold_outreach import ColdOutreachGenerator
from ai.culture_analyzer import CultureAnalyzer
from ai.career_advisor import CareerAdvisor
from ai.visa_filter import VisaFilter
from ai.academic_highlighter import AcademicHighlighter
from ai.rejection_analyzer import RejectionAnalyzer
from ai.gmail_parser import GmailParser
from ai.newgrad_salary import NewGradSalary
from ai.daily_routine import DailyRoutine
from scrapers.newgrad_scraper import NewGradScraper
from alerts.email_alert import EmailAlert
from alerts.telegram_alert import TelegramAlert
from database.db import JobDatabase
from app.security.input_guard import InputGuard

# Round 3 imports
from ai.hiring_signals import HiringSignalMonitor
from ai.freeze_detector import FreezeDetector
from ai.market_pulse import MarketPulse
from ai.jd_summarizer import JDSummarizer
from ai.personal_scorer import PersonalScoringModel
from ai.timing_optimizer import TimingOptimizer
from ai.ab_testing import ABTestingEngine
from ai.jobboard_subscriber import JobBoardSubscriber
from ai.leetcode_recommender import LeetCodeRecommender
from ai.system_design_plan import SystemDesignPlan
try:
    from alerts.whatsapp_alert import WhatsAppAlert
    _whatsapp_available = True
except ImportError:
    _whatsapp_available = False
try:
    from integrations.notion_sync import NotionSync, AirtableSync
    _notion_available = True
except ImportError:
    _notion_available = False

logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(rich_tracebacks=True, show_time=True)])
logger = logging.getLogger("job_agent")
console = Console()
_run_counter = 0


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    env_map = {
        "OPENAI_API_KEY":     ("ai", "openai_api_key"),
        "GEMINI_API_KEY":     ("ai", "gemini_api_key"),
        "EMAIL_PASSWORD":     ("alerts", "email", "sender_password"),
        "TELEGRAM_BOT_TOKEN": ("alerts", "telegram", "bot_token"),
        "TELEGRAM_CHAT_ID":   ("alerts", "telegram", "chat_id"),
    }
    for env_key, path_parts in env_map.items():
        val = os.environ.get(env_key)
        if val:
            node = cfg
            for part in path_parts[:-1]:
                node = node.setdefault(part, {})
            node[path_parts[-1]] = val
    return cfg


def load_resume(path: str) -> str:
    p = Path(path)
    if not p.exists():
        logger.warning(f"Resume not found at '{path}'. Scores will be unreliable.")
        return ""
    suffix = p.suffix.lower()
    if suffix == ".txt":
        return p.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        import pdfplumber
        text = ""
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    elif suffix in (".docx", ".doc"):
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    return p.read_text(encoding="utf-8", errors="ignore")


def run_pipeline(config: dict, resume: str):
    global _run_counter
    _run_counter += 1
    start = datetime.now(timezone.utc)
    console.print(Panel(
        f"🤖 [bold green]AI Job Agent — Run #{_run_counter}[/bold green]  {start.strftime('%Y-%m-%d %H:%M UTC')}",
        style="green"))

    db_cfg = config.get("database", {})
    db = JobDatabase(db_cfg.get("path", "jobs.db"), db_cfg.get("dedupe_window_days", 30))
    ai_cfg = config.get("ai", {})

    # 1. Scrape
    logger.info("📡 [1/11] Scraping job boards...")
    jobspy_jobs = JobSpyScraper(config).scrape()
    ats_jobs = ATSScraper(config).scrape()
    newgrad_jobs = NewGradScraper(config).scrape()
    rss_jobs = JobBoardSubscriber(config).scrape()
    all_scraped = jobspy_jobs + ats_jobs + newgrad_jobs + rss_jobs
    logger.info(f"Total scraped: {len(all_scraped)} ({len(newgrad_jobs)} new grad, {len(rss_jobs)} RSS)")

    # 1b. Visa filter
    visa_cfg = config.get("visa_filter", {})
    if visa_cfg.get("exclude_no_sponsor", False):
        logger.info("🛂 [1b] Visa sponsorship filter...")
        vf = VisaFilter(config)
        all_scraped, visa_filtered = vf.filter_jobs(all_scraped)
        logger.info(f"Visa filter: removed {len(visa_filtered)} no-sponsorship jobs")
    else:
        VisaFilter(config).enrich_jobs(all_scraped)  # tag only, don't remove

    # 1c. Hiring Freeze Detector
    intel_cfg = config.get("intelligence", {})
    if intel_cfg.get("freeze_detector", {}).get("enabled", True):
        logger.info("🥶 [1c] Freeze detector — skipping frozen companies...")
        try:
            fd = FreezeDetector(config)
            all_scraped, frozen_jobs = fd.filter_frozen(all_scraped, db)
            if frozen_jobs:
                logger.info(f"Freeze filter: skipped {len(frozen_jobs)} jobs at frozen companies")
        except Exception as e:
            logger.warning(f"Freeze detector error: {e}")

    # 2. Repost/Scam Filter
    logger.info("🔍 [2/11] Filtering reposts, scams, ghost jobs...")
    clean_jobs, filtered_jobs = RepostDetector(config).filter_jobs(all_scraped)

    # 3. Dedup
    logger.info("🗄️  [3/11] Deduplicating...")
    new_jobs = db.filter_new(clean_jobs)
    logger.info(f"New jobs: {len(new_jobs)}")

    if not new_jobs:
        console.print("[yellow]No new jobs this run.[/yellow]")
        _check_followups(config, db)
        _print_stats(db)
        return

    # 3b. Input Guard — sanitize + block injection/scam BEFORE any LLM sees the text
    new_jobs, guard_blocked = InputGuard().batch_validate_jobs(new_jobs)
    if guard_blocked:
        logger.info(f"🛡️  [3b] InputGuard blocked {len(guard_blocked)} jobs (scam/injection)")
    if not new_jobs:
        console.print("[yellow]All new jobs blocked by InputGuard this run.[/yellow]")
        _print_stats(db)
        return

    # 4. AI Score
    logger.info("🧠 [4/11] AI scoring...")
    scored_jobs = JobScorer(config, resume).score_jobs(new_jobs)

    # 4b. Personalized scoring re-rank
    try:
        scorer = PersonalScoringModel(config)
        scored_jobs = scorer.re_rank(scored_jobs)
    except Exception as e:
        logger.debug(f"Personal scorer: {e}")

    # 5. Salary Estimation
    if ai_cfg.get("salary_estimate", True) and scored_jobs:
        logger.info("💰 [5/11] Estimating salaries...")
        SalaryEstimator(config, resume).enrich_jobs(scored_jobs)

    # 5b. JD Summarizer
    jd_cfg = config.get("jd_summarizer", {})
    if jd_cfg.get("enabled", True):
        logger.info("📋 [5b] Summarizing job descriptions...")
        try:
            JDSummarizer(config).summarize_batch(scored_jobs, threshold=jd_cfg.get("min_score", 60))
        except Exception as e:
            logger.warning(f"JD summarizer error: {e}")

    # 6. Cover Letters (Drafter-Reviewer)
    cl_threshold = ai_cfg.get("cover_letter_threshold", 70)
    cl_jobs = [j for j in scored_jobs if (j.get("score") or 0) >= cl_threshold]
    if cl_jobs:
        logger.info(f"✍️  [6/11] Cover letters (drafter-reviewer) for {len(cl_jobs)} jobs...")
        CoverLetterGenerator(config, resume).generate_batch(cl_jobs)

    # 7. Company Research + Contact Discovery + Hiring Signals
    if scored_jobs:
        logger.info("🔬 [7/11] Company research + contact discovery...")
        CompanyResearcher(config, resume).enrich_jobs(scored_jobs)
        # Hiring signals for high-score jobs
        if intel_cfg.get("hiring_signals", {}).get("enabled", True):
            try:
                signal_threshold = intel_cfg.get("hiring_signals", {}).get("threshold_score", 70)
                HiringSignalMonitor(config).enrich_jobs(scored_jobs, threshold=signal_threshold)
            except Exception as e:
                logger.warning(f"Hiring signals error: {e}")

    # 8. Interview Prep
    prep_threshold = ai_cfg.get("interview_prep_threshold", 80)
    if scored_jobs:
        logger.info("🎯 [8/11] Interview prep...")
        InterviewPrep(config, resume).enrich_jobs(scored_jobs, threshold=prep_threshold)

    # 8b. ATS Scanner
    logger.info("🤖 [8b] ATS resume scan...")
    ATSScanner(config, resume).enrich_jobs(scored_jobs, threshold=60)

    # 8c. Resume Optimizer (AI-tailored resume per job)
    tailor_threshold = ai_cfg.get("cover_letter_threshold", 70)
    logger.info(f"📄 [8c] Optimizing resumes for jobs >= {tailor_threshold}...")
    try:
        from ai.resume_optimizer import ResumeOptimizer
        optimizer = ResumeOptimizer(config, resume)
        top_jobs = [j for j in scored_jobs if (j.get("score") or 0) >= tailor_threshold]
        opt_results = optimizer.batch_optimize(top_jobs, min_score=tailor_threshold)
        for r in opt_results:
            # Attach tailored resume back to job dict for saving
            for j in scored_jobs:
                if (j.get("job_url") or j.get("url")) == r.job_url:
                    j["tailored_resume"] = r.tailored_resume
                    j["resume_optimization_summary"] = r.summary()
                    break
        logger.info(f"  ✅ Optimized {len(opt_results)} resumes → resumes/tailored/")
    except Exception as e:
        logger.warning(f"Resume optimizer error: {e}")

    # 8d. Cold Outreach
    outreach_threshold = ai_cfg.get("company_research_threshold", 78)
    logger.info(f"📨 [8d] Cold outreach messages for jobs >= {outreach_threshold}...")
    ColdOutreachGenerator(config, resume).enrich_jobs(scored_jobs, threshold=outreach_threshold)

    # 8e. Culture Analysis
    logger.info("🏢 [8e] Company culture analysis...")
    CultureAnalyzer(config).enrich_jobs(scored_jobs, threshold=70)

    # 8f. Academic Highlighter (Masters grad feature)
    logger.info("🎓 [8f] Academic project matching...")
    AcademicHighlighter(config, resume).enrich_jobs(scored_jobs, threshold=65)

    # 8g. New Grad Salary Research
    logger.info("💰 [8g] New grad salary benchmarking...")
    NewGradSalary(config, resume).enrich_jobs(scored_jobs)

    # 9. Save
    logger.info("💾 [9/11] Saving to database...")
    db.save_jobs(new_jobs)

    # 9b. Notion / Airtable sync
    if _notion_available:
        try:
            notion_cfg = config.get("integrations", {}).get("notion", {})
            if notion_cfg.get("enabled"):
                NotionSync(config).sync_batch(new_jobs, min_score=notion_cfg.get("min_score_to_sync", 70))
            airtable_cfg = config.get("integrations", {}).get("airtable", {})
            if airtable_cfg.get("enabled"):
                AirtableSync(config).sync_batch(new_jobs)
        except Exception as e:
            logger.warning(f"Notion/Airtable sync error: {e}")

    # 10. Alerts
    logger.info("📬 [10/11] Sending alerts...")
    min_score = ai_cfg.get("min_match_score", 70)
    unnotified = db.get_unnotified()
    qualifying = [j for j in unnotified if (j.get("score") or 0) >= min_score]
    if qualifying:
        EmailAlert(config).send(qualifying)
        TelegramAlert(config).send(qualifying)
        # WhatsApp alert
        if _whatsapp_available:
            try:
                WhatsAppAlert(config).send_batch(qualifying)
            except Exception as e:
                logger.debug(f"WhatsApp alert error: {e}")
        db.mark_notified([j["url"] for j in qualifying])
    _check_followups(config, db)

    # 11. Auto-Apply (ACT) — apply to the very top matches for this run
    logger.info("🚀 [11] Auto-apply (top matches)...")
    telegram = TelegramAlert(config)
    for job in AutoApplier(config).apply_jobs(scored_jobs, db):
        telegram.send_applied_notification(job)

    # 12. Housekeeping — side tasks that aren't about this run's new jobs
    #   a) Gmail sync: update the status of PAST applications from the inbox
    if config.get("gmail_parser", {}).get("enabled"):
        try:
            logger.info("📧 [12a] Parsing Gmail for status updates...")
            GmailParser(config).process_and_update(db)
        except Exception as e:
            logger.warning(f"Gmail parser error: {e}")

    #   b) Morning briefing (first run of the day only)
    daily = DailyRoutine(config)
    quota = daily.get_quota_status(db)
    if quota["applied_today"] == 0 and _run_counter == 1:
        briefing = daily.generate_morning_briefing(db)
        logger.info(f"\n{briefing}")
        if config.get("alerts", {}).get("telegram", {}).get("enabled"):
            TelegramAlert(config)._send_message(briefing)
        if _whatsapp_available:
            try:
                WhatsAppAlert(config).send_morning_briefing(briefing[:500])
            except Exception:
                pass

    #   c) Timing optimizer: log the optimal application window
    timing_cfg = config.get("timing", {})
    if timing_cfg.get("warn_if_suboptimal", True):
        try:
            to = TimingOptimizer(config)
            from datetime import datetime as _dt
            t_score = to._score_current_time(_dt.utcnow())
            if t_score < 40:
                logger.warning(f"⏰ Suboptimal application time (score {t_score}/100). "
                               f"Best time: {to.get_optimal_time()['optimal_window']}")
        except Exception:
            pass

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    _print_run_summary(all_scraped, filtered_jobs, new_jobs, scored_jobs, qualifying, elapsed)
    _print_stats(db)

    # Weekly Upskill
    upskill_cfg = ai_cfg.get("upskill", {})
    every_n = upskill_cfg.get("run_every_n_runs", 168)
    if upskill_cfg.get("enabled", True) and _run_counter % every_n == 0:
        run_upskill(config, resume, db)

    # Weekly Market Pulse
    pulse_cfg = intel_cfg.get("market_pulse", {})
    pulse_every = pulse_cfg.get("run_every_n_runs", 168)
    if pulse_cfg.get("enabled", True) and _run_counter % pulse_every == 0:
        try:
            report = MarketPulse(config).generate_report(db)
            logger.info("📈 Market pulse report generated")
            if config.get("alerts", {}).get("telegram", {}).get("enabled"):
                TelegramAlert(config)._send_message(f"📈 Weekly Market Pulse\n\n{report[:1000]}")
        except Exception as e:
            logger.warning(f"Market pulse error: {e}")


def _check_followups(config, db):
    tracker = FollowUpTracker(config)
    due = tracker.get_due_followups(db)
    if due:
        msg = tracker.format_followup_alert(due)
        if config.get("alerts", {}).get("telegram", {}).get("enabled"):
            TelegramAlert(config)._send_message(msg)
        logger.info(f"Follow-up reminders: {len(due)} applications need attention")


def run_upskill(config: dict, resume: str, db=None):
    console.print(Panel("📚 [bold]Running upskill analysis...[/bold]", style="blue"))
    if db is None:
        db = JobDatabase(config.get("database", {}).get("path", "jobs.db"))
    jobs = db.get_all_jobs(limit=200)
    analyzer = UpskillAnalyzer(config, resume)
    report = analyzer.analyze(jobs)
    path = f"upskill_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md"
    analyzer.save_report(report, path)
    console.print(f"[green]Upskill report saved: {path}[/green]")


def _print_run_summary(scraped, filtered, new, scored, alerted, elapsed):
    t = Table(title=f"Run Summary ({elapsed:.1f}s)")
    t.add_column("Stage", style="bold")
    t.add_column("Count", justify="right")
    t.add_row("Scraped", str(len(scraped)))
    t.add_row("Filtered (scam/ghost/repost)", str(len(filtered)))
    t.add_row("New", str(len(new)))
    t.add_row("High Match", str(len(scored)))
    t.add_row("Alerts Sent", str(len(alerted)))
    console.print(t)


def _print_stats(db):
    s = db.stats()
    console.print(f"[bold]DB:[/bold] {s['total']} total | {s['applied']} applied | "
                  f"{s['high_match']} high-match | avg score {s['avg_score']}")


def launch_dashboard():
    def _run():
        subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
                        "--server.port", "8501", "--server.headless", "true"], check=False)
    threading.Thread(target=_run, daemon=True).start()
    console.print("[bold blue]Dashboard → http://localhost:8501[/bold blue]")


def main():
    parser = argparse.ArgumentParser(description="AI Job Agent v2")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--upskill", action="store_true")
    parser.add_argument("--dashboard-only", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--career-advice", metavar="TARGET_ROLE",
                        help="Generate career path strategy for TARGET_ROLE")
    parser.add_argument("--market-pulse", action="store_true",
                        help="Run weekly market pulse analysis now")
    parser.add_argument("--leetcode", metavar="COMPANY",
                        help="Get LeetCode problem recommendations for COMPANY")
    parser.add_argument("--system-design", metavar="COMPANY",
                        help="Generate system design study plan for COMPANY")
    parser.add_argument("--optimize-resume", metavar="JOB_URL",
                        help="Optimize your resume for a specific job URL in the DB")
    parser.add_argument("--optimize-top", type=int, metavar="N", default=0,
                        help="Optimize resumes for top N scored jobs in the DB")
    args = parser.parse_args()

    config = load_config(args.config)
    resume = load_resume(config.get("profile", {}).get("resume_path", "resume.txt"))

    console.print(Panel(
        "[bold]🤖 AI Job Agent v2[/bold]\n"
        "Sources:  LinkedIn · Indeed · Glassdoor · Google · ZipRecruiter + 45 Company ATS pages\n"
        "Features: Scam Filter · AI Scoring · Drafter-Reviewer Cover Letters · Company Research\n"
        "          Contact Discovery · Interview Prep · Salary Estimation · Follow-Up Cadence\n"
        "          Email + Telegram Alerts · LinkedIn Auto-Apply · Weekly Upskill Analysis",
        style="blue"))

    if args.upskill:
        run_upskill(config, resume)
        return

    if args.market_pulse:
        db = JobDatabase(config.get("database", {}).get("path", "jobs.db"))
        report = MarketPulse(config).generate_report(db)
        console.print(report)
        return

    if args.leetcode:
        recs = LeetCodeRecommender(config).recommend(company=args.leetcode, count=10)
        console.print(Panel(f"[bold]LeetCode recs for {args.leetcode}[/bold]", style="green"))
        for p in recs["problems"]:
            console.print(f"  [{p['difficulty']}] {p['name']} → {p['url']}")
        console.print(f"\n[bold]Study Plan:[/bold]\n{recs['study_plan']}")
        return

    if args.system_design:
        plan = SystemDesignPlan(config).generate_plan(company=args.system_design)
        console.print(Panel(f"[bold]System Design Plan — {args.system_design}[/bold]", style="cyan"))
        console.print(f"Topics: {', '.join(plan['company_topics'][:5])}")
        console.print(f"Style: {plan['company_style']}")
        if plan.get("llm_plan"):
            console.print(plan["llm_plan"])
        return

    if args.optimize_resume:
        from ai.resume_optimizer import ResumeOptimizer
        db = JobDatabase(config.get("database", {}).get("path", "jobs.db"))
        jobs = db.get_all_jobs(limit=500)
        target = next((j for j in jobs if (j.get("job_url") or j.get("url")) == args.optimize_resume), None)
        if not target:
            console.print(f"[red]Job URL not found in DB: {args.optimize_resume}[/red]")
            return
        result = ResumeOptimizer(config, resume).optimize(target, force=True)
        console.print(result.console_summary())
        return

    if args.optimize_top:
        from ai.resume_optimizer import ResumeOptimizer
        db = JobDatabase(config.get("database", {}).get("path", "jobs.db"))
        jobs = sorted(db.get_all_jobs(limit=200), key=lambda j: j.get("score") or 0, reverse=True)
        top_jobs = jobs[:args.optimize_top]
        console.print(f"[bold]Optimizing resumes for top {len(top_jobs)} jobs...[/bold]")
        results = ResumeOptimizer(config, resume).batch_optimize(top_jobs, min_score=0)
        console.print(f"\n✅ Done — {len(results)} resumes saved to resumes/tailored/")
        return

    if args.career_advice:
        console.print(Panel(f"🧭 [bold]Career Path Advisor — Target: {args.career_advice}[/bold]", style="cyan"))
        advisor = CareerAdvisor(config, resume)
        advice = advisor.get_advice(target_role=args.career_advice, force_refresh=True)
        report = CareerAdvisor.format_report(advice)
        path = "career_advice.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        console.print(report)
        console.print(f"[green]Saved to {path}[/green]")
        return

    if args.dashboard_only:
        launch_dashboard()
        import time
        while True: time.sleep(60)

    if not args.no_dashboard:
        launch_dashboard()

    if args.once:
        run_pipeline(config, resume)
        return

    interval = config.get("schedule", {}).get("interval_minutes", 60)
    run_immediately = config.get("schedule", {}).get("run_immediately", True)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_pipeline, "interval", minutes=interval,
                      args=[config, resume], id="job_pipeline", replace_existing=True)

    if run_immediately:
        run_pipeline(config, resume)

    console.print(f"[bold green]Scheduler: every {interval} minutes. Ctrl+C to stop.[/bold green]")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("[yellow]Agent stopped.[/yellow]")


if __name__ == "__main__":
    main()
