"""
observability/tracer.py — Per-stage pipeline tracing
======================================================
Traces every pipeline stage with timing, token counts, and outcomes.

Produces structured logs that can be:
  - Viewed in the dashboard (Observability tab)
  - Exported to Datadog / CloudWatch / Grafana (optional)
  - Analyzed to find bottlenecks (which stage takes longest)

Usage:
    tracer = PipelineTracer(run_id="abc123")
    with tracer.span("scoring"):
        jobs = scorer.score_jobs(jobs)
    tracer.save()
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single timed pipeline stage."""
    name: str
    run_id: str
    span_id: str = field(default_factory=lambda: str(uuid4())[:8])
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "running"  # running | completed | error | skipped

    # Payload
    input_count: int = 0
    output_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def complete(self, output_count: int = 0):
        self.finished_at = time.monotonic()
        self.duration_ms = round((self.finished_at - self.started_at) * 1000, 3)
        self.status = "completed"
        self.output_count = output_count

    def fail(self, error: str):
        self.finished_at = time.monotonic()
        self.duration_ms = round((self.finished_at - self.started_at) * 1000, 3)
        self.status = "error"
        self.error = error

    def to_dict(self) -> Dict:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "run_id": self.run_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
            "error": self.error,
        }


class PipelineTracer:
    """
    Traces a single pipeline run.
    One tracer per run, multiple spans per tracer.
    """

    TRACES_DIR = Path("observability/traces")

    def __init__(self, run_id: Optional[str] = None, trace_dir: Optional[Path] = None):
        self.run_id = run_id or str(uuid4())[:12]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.spans: List[Span] = []
        self._active: Optional[Span] = None
        self.traces_dir = Path(trace_dir) if trace_dir else self.TRACES_DIR
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def span(self, name: str, input_count: int = 0) -> Generator[Span, None, None]:
        """
        Context manager for a pipeline stage.

        Usage:
            with tracer.span("cover_letters", input_count=len(jobs)) as s:
                results = generator.generate_batch(jobs)
                s.output_count = len(results)
        """
        s = Span(name=name, run_id=self.run_id, input_count=input_count)
        self.spans.append(s)
        self._active = s
        logger.debug(f"[{self.run_id}] → {name} started")
        try:
            yield s
            s.complete()
            logger.debug(
                f"[{self.run_id}] ✓ {name} {s.duration_ms}ms "
                f"({s.input_count}→{s.output_count})"
            )
        except Exception as e:
            s.fail(str(e))
            logger.error(f"[{self.run_id}] ✗ {name} failed: {e}")
            raise
        finally:
            self._active = None

    def add_tokens(self, tokens_in: int, tokens_out: int, model: str = "gpt-4o-mini"):
        """Record token usage for the active span."""
        if self._active:
            self._active.tokens_in += tokens_in
            self._active.tokens_out += tokens_out
            self._active.cost_usd += self._estimate_cost(tokens_in, tokens_out, model)

    def skip(self, name: str, reason: str = ""):
        """Mark a stage as skipped."""
        s = Span(name=name, run_id=self.run_id)
        s.status = "skipped"
        s.metadata["reason"] = reason
        s.duration_ms = 0
        self.spans.append(s)

    def summary(self) -> Dict:
        """Get run summary."""
        total_ms = sum(s.duration_ms or 0 for s in self.spans)
        total_cost = sum(s.cost_usd for s in self.spans)
        slowest = max(self.spans, key=lambda s: s.duration_ms or 0, default=None)
        errors = [s for s in self.spans if s.status == "error"]
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "total_stages": len(self.spans),
            "total_duration_ms": round(total_ms, 1),
            "total_cost_usd": round(total_cost, 5),
            "errors": len(errors),
            "slowest_stage": slowest.name if slowest else None,
            "slowest_ms": slowest.duration_ms if slowest else None,
            "spans": [s.to_dict() for s in self.spans],
        }

    def save(self):
        """Save trace to disk."""
        data = self.summary()
        path = self.traces_dir / f"trace_{self.run_id}.json"
        path.write_text(json.dumps(data, indent=2))
        return path

    @staticmethod
    def _estimate_cost(tokens_in: int, tokens_out: int, model: str) -> float:
        """Estimate cost based on model pricing."""
        pricing = {
            "gpt-4o-mini": (0.00000015, 0.0000006),
            "gpt-4o": (0.0000025, 0.00001),
            "gemini-1.5-flash": (0.000000075, 0.0000003),
            "gemini-1.5-pro": (0.00000125, 0.000005),
        }
        in_price, out_price = pricing.get(model, pricing["gpt-4o-mini"])
        return tokens_in * in_price + tokens_out * out_price

    def get_bottlenecks(self, top_n: int = 3) -> List[Dict]:
        """Return the slowest stages."""
        completed = [s for s in self.spans if s.status == "completed"]
        return sorted(
            [s.to_dict() for s in completed],
            key=lambda s: s.get("duration_ms") or 0,
            reverse=True,
        )[:top_n]

    @classmethod
    def load_recent(cls, n: int = 10) -> List[Dict]:
        """Load the N most recent traces for the dashboard."""
        traces_dir = cls.TRACES_DIR
        if not traces_dir.exists():
            return []
        files = sorted(traces_dir.glob("trace_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        results = []
        for f in files[:n]:
            try:
                results.append(json.loads(f.read_text()))
            except Exception:
                pass
        return results
