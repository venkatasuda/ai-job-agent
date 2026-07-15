"""
Daily Routine Engine
=====================
Real job seekers who land jobs fast have ONE thing in common:
they treat job searching like a job. Daily routine, quota, tracking.

This module runs automatically:
  - 8:00 AM — Morning Briefing (new jobs, follow-ups, today's quota)
  - 6:00 PM — Evening Summary (what got done, responses received, tomorrow's plan)
  - Continuous — Quota tracker (applied today vs target)
  - Daily — Fatigue tracker + streak counter (accountability without burnout)
  - Weekly — Win/loss analysis

Sends via:
  - Telegram (instant)
  - Email (formatted digest)
  - Dashboard widget
"""

import json
import logging
import os
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MORNING_BRIEFING_PROMPT = """You are a supportive but no-nonsense job search assistant.
Generate an encouraging morning briefing for a Masters grad job seeker.

Today's stats:
{stats}

New jobs found overnight (top 5 by score):
{top_jobs}

Follow-ups due today:
{followups}

Pending responses (companies that haven't replied in 5+ days):
{pending}

Write a motivating but concise morning briefing:
- 3-4 sentences
- Acknowledge what's going well + what needs attention
- One specific tip or encouragement for today
- Keep it energetic but realistic
- NOT generic — reference the actual numbers"""

EVENING_SUMMARY_PROMPT = """Write a brief evening job search summary.

Today's accomplishments:
{accomplished}

Response rate this week: {response_rate}
Current streak: {streak} days of consistent applications

Write 2-3 sentences:
- What was achieved today
- One positive observation from the data
- What to prioritize tomorrow
- Keep it encouraging but honest"""


class DailyRoutine:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.profile = config.get("profile", {})
        self.routine_cfg = config.get("daily_routine", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._state_path = Path("daily_state.json")
        self._state = self._load_state()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str, max_tokens: int = 300) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=max_tokens,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
            elif self.provider == "ollama":
                import requests
                resp = requests.post("http://localhost:11434/api/generate",
                    json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=60)
                return resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"LLM call failed in daily routine: {e}")
            return ""

    # ── State Management ─────────────────────────────────────────────────────

    def _load_state(self) -> Dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {
            "streak": 0,
            "last_active_date": "",
            "total_applications": 0,
            "total_responses": 0,
            "milestones_celebrated": [],
            "daily_history": [],
        }

    def _save_state(self):
        self._state_path.write_text(json.dumps(self._state, indent=2))

    def _update_streak(self, applied_today: int):
        today = date.today().isoformat()
        last = self._state.get("last_active_date", "")
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        if last == today:
            return  # already updated today

        if applied_today > 0:
            if last == yesterday:
                self._state["streak"] += 1
            elif last != today:
                self._state["streak"] = 1
            self._state["last_active_date"] = today
        else:
            # No applications today — don't break streak if it's early
            hour = datetime.now().hour
            if hour >= 20:  # after 8pm with no apps = streak broken
                if last not in (today, yesterday):
                    self._state["streak"] = 0

        self._save_state()

    # ── Quota Tracker ─────────────────────────────────────────────────────────

    def get_daily_quota(self) -> int:
        return self.routine_cfg.get("daily_application_target", 10)

    def get_quota_status(self, db) -> Dict:
        """Check today's application progress vs quota."""
        daily = db.get_daily_stats()
        applied_today = daily.get("applied_today", 0)
        quota = self.get_daily_quota()
        remaining = max(0, quota - applied_today)
        pct = min(100, int(applied_today / quota * 100)) if quota else 0

        self._update_streak(applied_today)

        return {
            "applied_today": applied_today,
            "quota": quota,
            "remaining": remaining,
            "percentage": pct,
            "streak": self._state.get("streak", 0),
            "on_track": applied_today >= quota * 0.7,  # 70% = on track
        }

    # ── Fatigue Tracker ───────────────────────────────────────────────────────

    def get_fatigue_score(self, db) -> Dict:
        """
        Calculate job search fatigue score 0-10.
        High fatigue → recommend taking a break or changing strategy.
        """
        stats = db.stats()
        total = stats.get("total", 0)
        applied = stats.get("applied", 0)
        response_rate = self._state.get("response_rate_7d", 0)
        streak = self._state.get("streak", 0)

        # Signals of burnout
        fatigue = 0
        reasons = []

        if streak > 20:
            fatigue += 2
            reasons.append("20+ day streak without a break")
        if applied > 50 and response_rate < 5:
            fatigue += 3
            reasons.append(f"Only {response_rate:.0f}% response rate after {applied} applications")
        if applied > 30 and applied == total:
            fatigue += 1
            reasons.append("High application volume with low quality filtering")

        fatigue = min(10, fatigue)

        recommendations = []
        if fatigue >= 7:
            recommendations = [
                "Take 1-2 days completely off job searching",
                "Review and improve your resume before applying more",
                "Quality over quantity — apply to 3 great jobs vs 15 mediocre ones",
            ]
        elif fatigue >= 4:
            recommendations = [
                "Consider targeting fewer, higher-quality applications",
                "Review your rejection patterns to identify what to improve",
            ]

        return {
            "fatigue_score": fatigue,
            "fatigue_level": "High" if fatigue >= 7 else "Medium" if fatigue >= 4 else "Low",
            "reasons": reasons,
            "recommendations": recommendations,
            "streak": streak,
        }

    # ── Milestone Celebrations ────────────────────────────────────────────────

    def check_milestones(self, db) -> Optional[str]:
        """Check if any milestone was just hit. Returns celebration message or None."""
        stats = db.stats()
        applied = stats.get("applied", 0)
        streak = self._state.get("streak", 0)
        celebrated = set(self._state.get("milestones_celebrated", []))

        milestones = [
            (f"first_app", applied >= 1, "🎉 First application submitted! The journey begins."),
            (f"apps_10", applied >= 10, "💪 10 applications done! You're building momentum."),
            (f"apps_25", applied >= 25, "🔥 25 applications! You're more active than 90% of job seekers."),
            (f"apps_50", applied >= 50, "🚀 50 applications! Seriously impressive. Keep going."),
            (f"apps_100", applied >= 100, "👑 100 applications! You've outworked almost everyone."),
            (f"streak_7", streak >= 7, "📅 7-day streak! Consistency is your superpower."),
            (f"streak_14", streak >= 14, "🔥 14-day streak! Two weeks of consistency."),
            (f"streak_30", streak >= 30, "🏆 30-day streak! You're a machine. Take a day off, you earned it."),
        ]

        new_messages = []
        for key, condition, message in milestones:
            if condition and key not in celebrated:
                new_messages.append(message)
                self._state.setdefault("milestones_celebrated", []).append(key)
                self._save_state()

        return "\n".join(new_messages) if new_messages else None

    # ── Morning Briefing ──────────────────────────────────────────────────────

    def generate_morning_briefing(self, db, jobs: List[Dict] = None) -> str:
        """Generate the daily morning briefing."""
        quota_status = self.get_quota_status(db)
        stats = db.stats()
        daily = db.get_daily_stats()
        response_stats = db.get_response_stats()

        # Top new jobs from last 24h
        all_jobs = db.get_all_jobs(limit=200)
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        new_jobs = [j for j in all_jobs if (j.get("scraped_at") or "") > yesterday and not j.get("applied")]
        top_new = sorted(new_jobs, key=lambda j: j.get("score") or 0, reverse=True)[:5]

        top_jobs_text = "\n".join(
            f"  - {j.get('title')} @ {j.get('company')} | Score: {j.get('score')} | {j.get('visa_status','?')}"
            for j in top_new
        ) or "  No new jobs since yesterday"

        # Follow-ups due
        from ai.followup_tracker import FollowUpTracker
        tracker = FollowUpTracker({"profile": self.profile})
        followups = tracker.get_due_followups(db)
        followup_text = "\n".join(
            f"  - {f['job'].get('title')} @ {f['job'].get('company')} ({f['days_since']}d ago)"
            for f in followups[:3]
        ) or "  None due"

        # Pending responses (applied but no response in 7+ days)
        pending = [
            j for j in all_jobs
            if j.get("applied") and not j.get("response_received")
            and j.get("applied_at", "") < (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        ]
        pending_text = f"  {len(pending)} applications with no response yet (7+ days)"

        stats_text = (
            f"Total applied: {stats.get('applied', 0)} | "
            f"Response rate: {response_stats.get('response_rate', 0)}% | "
            f"Streak: {quota_status['streak']} days | "
            f"Applied today: {quota_status['applied_today']}/{quota_status['quota']}"
        )

        # LLM-generated message
        llm_msg = self._llm(MORNING_BRIEFING_PROMPT.format(
            stats=stats_text,
            top_jobs=top_jobs_text,
            followups=followup_text,
            pending=pending_text,
        ), max_tokens=200)

        # Build full briefing
        lines = [
            f"🌅 Good morning, {self.profile.get('name', 'there')}!",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 Today's Dashboard",
            f"  Applied today: {quota_status['applied_today']}/{quota_status['quota']} ({quota_status['percentage']}%)",
            f"  Streak: {quota_status['streak']} days 🔥",
            f"  Total applied: {stats.get('applied', 0)} | Response rate: {response_stats.get('response_rate', 0)}%",
            f"",
            f"🆕 New Jobs (last 24h): {len(new_jobs)} found",
        ]
        for j in top_new[:3]:
            lines.append(f"  ⭐ {j.get('title')} @ {j.get('company')} [{j.get('score', '?')}]")

        if followups:
            lines += [f"", f"📬 Follow-ups Due: {len(followups)}"]
            for f in followups[:2]:
                lines.append(f"  → {f['job'].get('title')} @ {f['job'].get('company')}")

        # Milestone check
        milestone = self.check_milestones(db)
        if milestone:
            lines += [f"", f"🏆 MILESTONE!", milestone]

        if llm_msg:
            lines += [f"", f"💬 {llm_msg}"]

        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Target today: {quota_status['quota']} applications. You've got this! 💪",
        ]

        return "\n".join(lines)

    # ── Evening Summary ───────────────────────────────────────────────────────

    def generate_evening_summary(self, db) -> str:
        """Generate end-of-day summary."""
        daily = db.get_daily_stats()
        quota_status = self.get_quota_status(db)
        response_stats = db.get_response_stats()
        fatigue = self.get_fatigue_score(db)

        accomplished = (
            f"Applied to {daily.get('applied_today', 0)} jobs, "
            f"found {daily.get('scraped_today', 0)} new postings"
        )
        llm_msg = self._llm(EVENING_SUMMARY_PROMPT.format(
            accomplished=accomplished,
            response_rate=f"{response_stats.get('response_rate', 0)}%",
            streak=quota_status["streak"],
        ), max_tokens=150)

        lines = [
            f"🌙 Evening Summary — {date.today().isoformat()}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"✅ Applied today: {daily.get('applied_today', 0)}/{quota_status['quota']}",
            f"📨 Response rate: {response_stats.get('response_rate', 0)}%",
            f"🔥 Streak: {quota_status['streak']} days",
        ]

        if fatigue["fatigue_score"] >= 6:
            lines += [f"", f"⚠️ Fatigue detected: {fatigue['fatigue_level']}"]
            for rec in fatigue["recommendations"][:2]:
                lines.append(f"  → {rec}")

        if llm_msg:
            lines += [f"", f"💬 {llm_msg}"]

        # Tomorrow's focus
        lines += [f"", f"📋 Tomorrow: apply to {quota_status['quota']} jobs. Sleep well! 🌟"]
        return "\n".join(lines)

    def get_dashboard_widgets(self, db) -> Dict:
        """Return all data needed for dashboard quota/fatigue widgets."""
        return {
            "quota": self.get_quota_status(db),
            "fatigue": self.get_fatigue_score(db),
            "milestone": self.check_milestones(db),
            "daily_stats": db.get_daily_stats(),
            "response_stats": db.get_response_stats(),
        }
