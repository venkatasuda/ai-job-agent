"""
Application Timing Optimizer
==============================
Analyzes the best time to submit job applications for maximum visibility.

Research-backed insights:
  - Applications submitted Tuesday–Thursday get 40% more callbacks
  - 8-10am and 2-4pm in the recruiter's timezone are peak review times
  - Applications submitted within 24h of posting get 3x more interviews
  - Avoid Mondays (inbox overload) and Fridays (not reviewed until Monday)
  - AI/Tech companies: Tuesday morning PST is optimal for most
  - Finance/Consulting: Wednesday morning EST

Tracks your own application timing vs. callback data to personalize.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Day scores (0=Mon, 6=Sun)
DAY_SCORES = {0: 60, 1: 95, 2: 90, 3: 85, 4: 55, 5: 30, 6: 20}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Hour scores (24h, local time)
HOUR_SCORES = {
    0: 10, 1: 5, 2: 5, 3: 5, 4: 10, 5: 20,
    6: 40, 7: 70, 8: 95, 9: 100, 10: 90, 11: 80,
    12: 60, 13: 65, 14: 85, 15: 90, 16: 75, 17: 55,
    18: 40, 19: 30, 20: 25, 21: 20, 22: 15, 23: 10,
}

# Industry-specific timezone preferences
INDUSTRY_TIMEZONES = {
    "tech": "PST",
    "finance": "EST",
    "healthcare": "CST",
    "default": "EST",
}

# Company timezone guesses by HQ
COMPANY_TIMEZONES = {
    "google": "PST", "meta": "PST", "apple": "PST", "netflix": "PST",
    "amazon": "PST", "microsoft": "PST", "uber": "PST", "airbnb": "PST",
    "stripe": "PST", "databricks": "PST", "openai": "PST",
    "goldman sachs": "EST", "jpmorgan": "EST", "bloomberg": "EST",
    "two sigma": "EST", "citadel": "CST",
}


class TimingOptimizer:
    def __init__(self, config: dict):
        self.cfg = config
        self._history_path = Path("timing_history.json")
        self._history = self._load_history()

    def _load_history(self) -> List[Dict]:
        if self._history_path.exists():
            try:
                return json.loads(self._history_path.read_text())
            except Exception:
                pass
        return []

    def _save_history(self):
        self._history_path.write_text(json.dumps(self._history[-500:], indent=2))

    def record_application(self, job_id: str, company: str,
                           submitted_at: Optional[datetime] = None):
        """Record when an application was submitted."""
        submitted_at = submitted_at or datetime.now(timezone.utc)
        self._history.append({
            "job_id": job_id,
            "company": company,
            "submitted_at": submitted_at.isoformat(),
            "day_of_week": submitted_at.weekday(),
            "hour": submitted_at.hour,
            "got_callback": None,
            "callback_date": None,
        })
        self._save_history()

    def record_callback(self, job_id: str):
        for entry in self._history:
            if entry.get("job_id") == job_id:
                entry["got_callback"] = True
                entry["callback_date"] = datetime.now(timezone.utc).isoformat()
        self._save_history()

    def record_no_response(self, job_id: str):
        for entry in self._history:
            if entry.get("job_id") == job_id and entry.get("got_callback") is None:
                entry["got_callback"] = False
        self._save_history()

    def get_optimal_time(self, company: str = "") -> Dict:
        """Return the optimal day/time to submit this application."""
        company_lower = company.lower()
        tz = COMPANY_TIMEZONES.get(company_lower, "EST")

        # Get personal best from history
        personal_best_day, personal_best_hour = self._get_personal_best()

        now = datetime.now(timezone.utc)
        # Find next optimal window
        best_window = self._find_next_window(now, target_day=personal_best_day or 1,
                                              target_hour=personal_best_hour or 9)
        days_until = (best_window - now).days
        hours_until = int((best_window - now).total_seconds() / 3600)

        return {
            "optimal_window": best_window.strftime("%A %B %d at %I:%M %p"),
            "hours_from_now": hours_until,
            "days_from_now": days_until,
            "company_timezone": tz,
            "reason": self._explain_timing(best_window),
            "current_score": self._score_current_time(now),
            "should_apply_now": self._score_current_time(now) >= 70,
        }

    def _score_current_time(self, dt: datetime) -> int:
        day_score = DAY_SCORES.get(dt.weekday(), 50)
        hour_score = HOUR_SCORES.get(dt.hour, 50)
        return (day_score + hour_score) // 2

    def _find_next_window(self, from_dt: datetime,
                          target_day: int = 1, target_hour: int = 9) -> datetime:
        """Find next occurrence of target day+hour."""
        dt = from_dt.replace(minute=0, second=0, microsecond=0)
        for _ in range(14):  # search 2 weeks
            dt += timedelta(hours=1)
            if dt.weekday() == target_day and dt.hour == target_hour:
                return dt
        # Fallback: next Tuesday 9am
        days_ahead = (1 - from_dt.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return from_dt.replace(hour=9, minute=0, second=0) + timedelta(days=days_ahead)

    def _get_personal_best(self) -> Tuple[Optional[int], Optional[int]]:
        """From history, which day+hour had highest callback rate?"""
        qualified = [h for h in self._history if h.get("got_callback") is not None]
        if len(qualified) < 10:
            return None, None
        day_callbacks = {}
        day_total = {}
        for entry in qualified:
            day = entry["day_of_week"]
            day_total[day] = day_total.get(day, 0) + 1
            if entry.get("got_callback"):
                day_callbacks[day] = day_callbacks.get(day, 0) + 1
        if not day_callbacks:
            return None, None
        best_day = max(day_callbacks, key=lambda d: day_callbacks[d] / day_total.get(d, 1))

        hour_callbacks = {}
        hour_total = {}
        for entry in qualified:
            h = entry["hour"]
            hour_total[h] = hour_total.get(h, 0) + 1
            if entry.get("got_callback"):
                hour_callbacks[h] = hour_callbacks.get(h, 0) + 1
        best_hour = max(hour_callbacks, key=lambda h: hour_callbacks[h] / hour_total.get(h, 1)) if hour_callbacks else None
        return best_day, best_hour

    def _explain_timing(self, dt: datetime) -> str:
        day = DAY_NAMES[dt.weekday()]
        hour = dt.hour
        am_pm = "AM" if hour < 12 else "PM"
        h12 = hour if hour <= 12 else hour - 12
        return (
            f"{day} at {h12}{am_pm} is optimal: recruiters review applications "
            f"first thing in the morning after the weekend. "
            f"Tuesday-Thursday morning applications get 40% more callbacks."
        )

    def get_posting_age_factor(self, date_posted: str) -> Dict:
        """Jobs posted recently should be applied to immediately."""
        if not date_posted:
            return {"age_days": -1, "urgency": "Unknown", "apply_now": False}
        try:
            posted = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
            posted = posted.replace(tzinfo=None)
            age = (datetime.now(timezone.utc) - posted).days
        except Exception:
            return {"age_days": -1, "urgency": "Unknown", "apply_now": False}

        if age == 0:
            urgency = "🔥 Apply within hours! Posted today."
            apply_now = True
        elif age <= 1:
            urgency = "⚡ Apply today — posted yesterday."
            apply_now = True
        elif age <= 3:
            urgency = "📅 Apply this week — still fresh."
            apply_now = False
        elif age <= 7:
            urgency = "⚠️ Apply ASAP — 1 week old."
            apply_now = False
        else:
            urgency = f"⛔ {age} days old — may be stale or filled."
            apply_now = False

        return {"age_days": age, "urgency": urgency, "apply_now": apply_now}

    def get_stats(self) -> Dict:
        total = len(self._history)
        callbacks = sum(1 for h in self._history if h.get("got_callback"))
        best_day_idx, best_hour = self._get_personal_best()
        return {
            "total_applications_tracked": total,
            "total_callbacks": callbacks,
            "overall_callback_rate": round(callbacks / total * 100, 1) if total else 0,
            "personal_best_day": DAY_NAMES[best_day_idx] if best_day_idx is not None else "Not enough data",
            "personal_best_hour": f"{best_hour}:00" if best_hour is not None else "Not enough data",
        }
