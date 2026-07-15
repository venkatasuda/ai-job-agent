"""
observability/cost_tracker.py — LLM cost tracking
====================================================
Tracks every LLM call's token usage and dollar cost.

Dashboard shows:
  - Cost per run
  - Cost per day / week / month
  - Cost by stage (cover letters cost most?)
  - Projected monthly bill
  - Alert if cost exceeds budget threshold

Storage: cost_log.jsonl (one JSON line per call, append-only)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Cost per million tokens (as of 2025)
MODEL_PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},          # $0.15/$0.60 per 1M
    "gpt-4o": {"input": 2.50, "output": 10.00},               # $2.50/$10.00 per 1M
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},     # Free tier available
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "llama3": {"input": 0.0, "output": 0.0},                   # Local/free
    "mistral": {"input": 0.0, "output": 0.0},
}


class CostTracker:
    """
    Tracks and reports LLM token costs.
    Thread-safe (each call appends to JSONL, no concurrent writes needed for SQLite).
    """

    BUDGET_ALERT_USD = 5.0  # Alert if projected monthly cost exceeds this

    def __init__(self, log_path: str = "observability/cost_log.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_cost: float = 0.0
        self._session_calls: int = 0

    def record(
        self,
        model: str,
        stage: str,
        tokens_in: int,
        tokens_out: int,
        job_count: int = 0,
        run_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> float:
        """Record a single LLM call. Returns cost in USD."""
        cost = self._calculate_cost(model, tokens_in, tokens_out)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "model": model,
            "stage": stage,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "job_count": job_count,
            "cost_usd": round(cost, 7),
            **(metadata or {}),
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._session_cost += cost
        self._session_calls += 1
        return cost

    def _calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4o-mini"])
        cost = (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000
        return cost

    def get_session_summary(self) -> Dict:
        return {
            "session_cost_usd": round(self._session_cost, 5),
            "session_calls": self._session_calls,
        }

    def load_log(self, days: int = 30) -> List[Dict]:
        """Load cost log for the past N days."""
        if not self.log_path.exists():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        entries = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("ts", "") >= cutoff:
                        entries.append(entry)
                except Exception:
                    pass
        return entries

    def get_stats(self, days: int = 30) -> Dict:
        """Aggregate cost statistics."""
        entries = self.load_log(days)
        if not entries:
            return {
                "total_cost_usd": 0.0,
                "total_calls": 0,
                "by_stage": {},
                "by_model": {},
                "daily_avg_usd": 0.0,
                "projected_monthly_usd": 0.0,
                "budget_warning": False,
            }

        total = sum(e.get("cost_usd", 0) for e in entries)
        by_stage: Dict[str, float] = {}
        by_model: Dict[str, float] = {}

        for e in entries:
            stage = e.get("stage", "unknown")
            model = e.get("model", "unknown")
            cost = e.get("cost_usd", 0)
            by_stage[stage] = by_stage.get(stage, 0) + cost
            by_model[model] = by_model.get(model, 0) + cost

        daily_avg = total / max(days, 1)
        projected_monthly = daily_avg * 30

        # Sort by cost descending
        by_stage = dict(sorted(by_stage.items(), key=lambda x: x[1], reverse=True))
        by_model = dict(sorted(by_model.items(), key=lambda x: x[1], reverse=True))

        return {
            "total_cost_usd": round(total, 4),
            "total_calls": len(entries),
            "by_stage": {k: round(v, 4) for k, v in by_stage.items()},
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
            "daily_avg_usd": round(daily_avg, 4),
            "projected_monthly_usd": round(projected_monthly, 2),
            "budget_warning": projected_monthly > self.BUDGET_ALERT_USD,
            "period_days": days,
        }

    def get_cost_breakdown_md(self) -> str:
        """Markdown-formatted cost report."""
        stats = self.get_stats(30)
        lines = [
            "## 💰 LLM Cost Report (Last 30 Days)",
            f"",
            f"**Total:** ${stats['total_cost_usd']:.4f} | "
            f"**Daily avg:** ${stats['daily_avg_usd']:.4f} | "
            f"**Projected/month:** ${stats['projected_monthly_usd']:.2f}",
            f"**Total LLM calls:** {stats['total_calls']}",
            f"",
            f"### By Stage",
        ]
        for stage, cost in stats["by_stage"].items():
            pct = (cost / stats["total_cost_usd"] * 100) if stats["total_cost_usd"] else 0
            lines.append(f"- {stage}: ${cost:.4f} ({pct:.0f}%)")
        lines += ["", "### By Model"]
        for model, cost in stats["by_model"].items():
            lines.append(f"- {model}: ${cost:.4f}")
        if stats["budget_warning"]:
            lines += [
                "",
                f"⚠️ **Budget Alert:** Projected ${stats['projected_monthly_usd']:.2f}/month "
                f"exceeds ${self.BUDGET_ALERT_USD:.2f} threshold. "
                "Consider switching to `gemini-1.5-flash` (free tier).",
            ]
        return "\n".join(lines)

    def suggest_cheaper_model(self, current_model: str) -> Optional[str]:
        """Suggest a cheaper model if budget is tight."""
        if "gpt-4o" in current_model and "mini" not in current_model:
            return "gpt-4o-mini"
        if "gpt-4o-mini" in current_model:
            return "gemini-1.5-flash (free tier)"
        return None
