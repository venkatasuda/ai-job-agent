"""
observability/feedback.py — User feedback capture
===================================================
Captures thumbs up/down on:
  - Cover letters ("was this good enough to send?")
  - Job scores ("was this score accurate?")
  - Company research ("was this useful?")
  - Interview prep ("did these questions match the actual interview?")

Feedback drives two things:
  1. Personalized scoring model (personal_scorer.py) — re-rank based on preferences
  2. Prompt tuning — which prompt versions get best feedback scores

Storage: feedback_log.jsonl (append-only)
Dashboard: Feedback tab shows acceptance rates per feature
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

FeedbackType = Literal[
    "cover_letter", "job_score", "company_research",
    "interview_prep", "ats_scan", "salary_estimate", "jd_summary"
]

Rating = Literal["thumbs_up", "thumbs_down", "neutral"]


class FeedbackCapture:
    """
    Lightweight feedback system for pipeline output quality.
    No external service needed — pure JSONL storage.
    """

    def __init__(self, log_path: str = "observability/feedback_log.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        feature: FeedbackType,
        rating: Rating,
        job_id: Optional[str] = None,
        company: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """Record a piece of feedback."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "feature": feature,
            "rating": rating,
            "job_id": job_id,
            "company": company,
            "notes": notes,
            **(metadata or {}),
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return True
        except Exception as e:
            logger.error(f"Feedback record failed: {e}")
            return False

    def thumbs_up(self, feature: FeedbackType, job_id: str = "", company: str = "") -> bool:
        return self.record(feature, "thumbs_up", job_id=job_id, company=company)

    def thumbs_down(self, feature: FeedbackType, job_id: str = "",
                    company: str = "", notes: str = "") -> bool:
        return self.record(feature, "thumbs_down", job_id=job_id, company=company, notes=notes)

    def load_log(self, days: int = 30) -> List[Dict]:
        if not self.log_path.exists():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        entries = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("ts", "") >= cutoff:
                        entries.append(e)
                except Exception:
                    pass
        return entries

    def get_acceptance_rates(self, days: int = 30) -> Dict[str, Dict]:
        """Calculate thumbs up rate per feature."""
        entries = self.load_log(days)
        rates: Dict[str, Dict[str, int]] = {}
        for e in entries:
            feature = e.get("feature", "unknown")
            rating = e.get("rating", "neutral")
            if feature not in rates:
                rates[feature] = {"thumbs_up": 0, "thumbs_down": 0, "neutral": 0}
            rates[feature][rating] = rates[feature].get(rating, 0) + 1

        result = {}
        for feature, counts in rates.items():
            total = sum(counts.values())
            up = counts.get("thumbs_up", 0)
            result[feature] = {
                "total": total,
                "thumbs_up": up,
                "thumbs_down": counts.get("thumbs_down", 0),
                "acceptance_rate": round(up / total * 100, 1) if total else 0,
                "needs_improvement": up / total < 0.6 if total >= 5 else False,
            }
        return result

    def get_worst_features(self) -> List[str]:
        """Return features with acceptance rate < 60%."""
        rates = self.get_acceptance_rates()
        return [
            f for f, data in rates.items()
            if data.get("needs_improvement") and data.get("total", 0) >= 5
        ]

    def format_report(self) -> str:
        """Markdown feedback report for dashboard."""
        rates = self.get_acceptance_rates()
        if not rates:
            return "No feedback recorded yet. Use thumbs up/down in the dashboard."
        lines = ["## 👍 Feature Acceptance Rates (Last 30 Days)", ""]
        for feature, data in sorted(rates.items()):
            bar = "█" * int(data["acceptance_rate"] / 10) + "░" * (10 - int(data["acceptance_rate"] / 10))
            status = "✅" if data["acceptance_rate"] >= 70 else ("⚠️" if data["acceptance_rate"] >= 50 else "❌")
            lines.append(
                f"{status} **{feature}**: {bar} {data['acceptance_rate']}% "
                f"({data['thumbs_up']}👍 / {data['thumbs_down']}👎)"
            )
        worst = self.get_worst_features()
        if worst:
            lines += ["", f"⚠️ **Needs improvement:** {', '.join(worst)}"]
        return "\n".join(lines)
