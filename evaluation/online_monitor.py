"""
evaluation/online_monitor.py — Live quality monitoring
========================================================
Monitors real pipeline runs in production for quality drift.

Metrics tracked:
  - Callback rate (% of applications that got a response) → is the agent effective?
  - Score distribution (is scoring well-calibrated?)
  - Cover letter acceptance rate (feedback thumbs up %)
  - Alert relevance (are alerts for jobs worth applying to?)
  - Pipeline success rate (did it complete without errors?)
  - Cost per job (is it staying cheap?)

Runs alongside the main pipeline — hooks into existing data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OnlineMonitor:
    """
    Reads from existing data files to compute live quality metrics.
    No external service needed — pure local analysis.
    """

    METRICS_PATH = Path("evaluation/metrics_history.jsonl")

    def __init__(self, db=None):
        self.db = db
        self.METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> Dict:
        """Take a snapshot of current system quality metrics."""
        metrics = {
            "ts": datetime.utcnow().isoformat(),
            **self._score_distribution_metrics(),
            **self._callback_rate_metrics(),
            **self._cost_metrics(),
            **self._pipeline_health_metrics(),
        }
        # Append to history
        with open(self.METRICS_PATH, "a") as f:
            f.write(json.dumps(metrics) + "\n")
        return metrics

    def _score_distribution_metrics(self) -> Dict:
        """Are scores well-distributed? (Not all 70s or all 90s)"""
        if not self.db:
            return {}
        try:
            jobs = self.db.get_all_jobs(limit=500)
            scores = [j.get("score") or 0 for j in jobs if j.get("score")]
            if not scores:
                return {"score_count": 0}
            avg = sum(scores) / len(scores)
            high = sum(1 for s in scores if s >= 80)
            mid = sum(1 for s in scores if 60 <= s < 80)
            low = sum(1 for s in scores if s < 60)
            return {
                "score_count": len(scores),
                "score_avg": round(avg, 1),
                "high_match_count": high,
                "mid_match_count": mid,
                "low_match_count": low,
                "score_distribution_healthy": 5 <= high <= len(scores) * 0.4,
            }
        except Exception as e:
            logger.debug(f"Score metrics error: {e}")
            return {}

    def _callback_rate_metrics(self) -> Dict:
        """What % of applications got any response?"""
        if not self.db:
            return {}
        try:
            stats = self.db.get_response_stats() if hasattr(self.db, "get_response_stats") else {}
            return {
                "callback_rate": stats.get("callback_rate", 0),
                "total_applied": stats.get("total_applied", 0),
                "total_callbacks": stats.get("total_callbacks", 0),
            }
        except Exception:
            return {}

    def _cost_metrics(self) -> Dict:
        """Current session cost from cost tracker."""
        try:
            from observability.cost_tracker import CostTracker
            tracker = CostTracker()
            stats = tracker.get_stats(days=1)
            return {
                "cost_today_usd": stats.get("total_cost_usd", 0),
                "calls_today": stats.get("total_calls", 0),
                "budget_warning": stats.get("budget_warning", False),
            }
        except Exception:
            return {}

    def _pipeline_health_metrics(self) -> Dict:
        """Load recent trace data to compute error rates."""
        try:
            from observability.tracer import PipelineTracer
            traces = PipelineTracer.load_recent(n=5)
            if not traces:
                return {}
            error_rates = [
                t.get("errors", 0) / max(t.get("total_stages", 1), 1)
                for t in traces
            ]
            avg_error_rate = sum(error_rates) / len(error_rates)
            avg_duration = sum(t.get("total_duration_ms", 0) for t in traces) / len(traces)
            return {
                "pipeline_error_rate": round(avg_error_rate * 100, 1),
                "avg_pipeline_duration_ms": round(avg_duration),
                "recent_runs": len(traces),
            }
        except Exception:
            return {}

    def check_alerts(self) -> List[str]:
        """Return list of quality alerts that need attention."""
        alerts = []
        metrics = self.snapshot()

        if metrics.get("budget_warning"):
            alerts.append("💰 Budget: Projected monthly cost exceeds $5. Switch to Gemini Flash.")

        if (metrics.get("pipeline_error_rate") or 0) > 20:
            alerts.append(f"⚠️ Pipeline: {metrics['pipeline_error_rate']}% error rate in last 5 runs")

        callback_rate = metrics.get("callback_rate") or 0
        if callback_rate < 5 and (metrics.get("total_applied") or 0) > 20:
            alerts.append(
                f"📉 Low callback rate: {callback_rate}% "
                "(Review cover letter quality and score thresholds)"
            )

        score_healthy = metrics.get("score_distribution_healthy")
        if score_healthy is False:
            alerts.append("📊 Score distribution off: Too many jobs scoring 80+ (lower threshold?)")

        return alerts

    def load_history(self, days: int = 7) -> List[Dict]:
        """Load metrics history for trend analysis."""
        if not self.METRICS_PATH.exists():
            return []
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        history = []
        with open(self.METRICS_PATH) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("ts", "") >= cutoff:
                        history.append(entry)
                except Exception:
                    pass
        return history

    def format_dashboard_summary(self) -> str:
        """One-page health summary for dashboard."""
        m = self.snapshot()
        alerts = self.check_alerts()
        lines = [
            "## 🔍 System Health Monitor",
            "",
            f"**Last snapshot:** {m.get('ts', 'N/A')[:19]}",
            "",
            "### Scoring",
            f"- Jobs scored: {m.get('score_count', 0)} | Avg: {m.get('score_avg', 0)}",
            f"- High match (80+): {m.get('high_match_count', 0)} | Mid: {m.get('mid_match_count', 0)}",
            "",
            "### Application Performance",
            f"- Applied: {m.get('total_applied', 0)} | Callbacks: {m.get('total_callbacks', 0)}",
            f"- Callback rate: {m.get('callback_rate', 0)}%",
            "",
            "### Cost",
            f"- Today: ${m.get('cost_today_usd', 0):.4f} | Calls: {m.get('calls_today', 0)}",
            "",
            "### Pipeline",
            f"- Error rate: {m.get('pipeline_error_rate', 0):.1f}% | Avg duration: {m.get('avg_pipeline_duration_ms', 0):.0f}ms",
        ]
        if alerts:
            lines += ["", "### ⚠️ Alerts"] + [f"- {a}" for a in alerts]
        else:
            lines.append("\n✅ All systems healthy")
        return "\n".join(lines)
