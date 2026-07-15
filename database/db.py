"""
SQLite database layer.
- Stores all scraped + scored jobs
- Deduplicates by URL within a configurable window
- Tracks application status
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    description     TEXT,
    apply_url       TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    job_type        TEXT,
    date_posted     TEXT,
    source          TEXT,
    is_remote       INTEGER DEFAULT 0,
    is_new_grad     INTEGER DEFAULT 0,
    visa_status     TEXT,
    visa_reason     TEXT,
    score           INTEGER,
    ats_score       INTEGER,
    ats_verdict     TEXT,
    verdict         TEXT,
    match_reasons   TEXT,   -- JSON array
    gap_reasons     TEXT,   -- JSON array
    cover_letter    TEXT,
    tailored_resume TEXT,
    email_draft     TEXT,
    outreach_linkedin_dm  TEXT,
    outreach_cold_email   TEXT,
    applied         INTEGER DEFAULT 0,
    applied_at      TEXT,
    interview_stage TEXT DEFAULT 'not_applied',
    interview_stage_updated_at TEXT,
    interview_dates TEXT,   -- JSON array of {date, round, notes}
    response_received INTEGER DEFAULT 0,
    response_date   TEXT,
    rejection_reason TEXT,
    thankyou_sent   INTEGER DEFAULT 0,
    scraped_at      TEXT,
    notified        INTEGER DEFAULT 0
);
"""

# Migration: add new columns to existing DBs
MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN is_new_grad INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN visa_status TEXT",
    "ALTER TABLE jobs ADD COLUMN visa_reason TEXT",
    "ALTER TABLE jobs ADD COLUMN ats_score INTEGER",
    "ALTER TABLE jobs ADD COLUMN ats_verdict TEXT",
    "ALTER TABLE jobs ADD COLUMN tailored_resume TEXT",
    "ALTER TABLE jobs ADD COLUMN email_draft TEXT",
    "ALTER TABLE jobs ADD COLUMN outreach_linkedin_dm TEXT",
    "ALTER TABLE jobs ADD COLUMN outreach_cold_email TEXT",
    "ALTER TABLE jobs ADD COLUMN interview_stage TEXT DEFAULT 'not_applied'",
    "ALTER TABLE jobs ADD COLUMN interview_stage_updated_at TEXT",
    "ALTER TABLE jobs ADD COLUMN interview_dates TEXT",
    "ALTER TABLE jobs ADD COLUMN response_received INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN response_date TEXT",
    "ALTER TABLE jobs ADD COLUMN rejection_reason TEXT",
    "ALTER TABLE jobs ADD COLUMN thankyou_sent INTEGER DEFAULT 0",
]

CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied);
CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(interview_stage);
"""

# Interview pipeline stages in order
INTERVIEW_STAGES = [
    "not_applied", "applied", "phone_screen", "technical",
    "system_design", "onsite", "offer", "negotiating",
    "accepted", "rejected", "withdrawn",
]


class JobDatabase:
    def __init__(self, db_path: str = "jobs.db", dedupe_window_days: int = 30):
        self.db_path = db_path
        self.dedupe_window_days = dedupe_window_days
        # In-memory DBs exist only for the life of their connection, so hold one
        # open for this object; file DBs open a fresh connection per call.
        self._shared_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._shared_conn = sqlite3.connect(db_path, check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(CREATE_TABLE)
            for stmt in CREATE_INDEX.strip().split("\n"):
                if stmt.strip():
                    conn.execute(stmt.strip())
            # Run migrations for existing DBs (ignore errors for existing columns)
            for migration in MIGRATIONS:
                try:
                    conn.execute(migration)
                except Exception:
                    pass

    def is_seen(self, url: str) -> bool:
        """Return True if this URL was seen within the dedupe window."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.dedupe_window_days)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE url = ? AND scraped_at > ?", (url, cutoff)
            ).fetchone()
        return row is not None

    def filter_new(self, jobs: List[Dict]) -> List[Dict]:
        """Return only jobs not already in the DB within the dedupe window."""
        return [j for j in jobs if not self.is_seen(j.get("url") or j.get("job_url") or "")]

    def save_jobs(self, jobs: List[Dict]) -> int:
        """Insert or replace jobs. Returns count saved."""
        saved = 0
        with self._conn() as conn:
            for job in jobs:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO jobs
                        (url, title, company, location, description, apply_url,
                         salary_min, salary_max, job_type, date_posted, source,
                         is_remote, score, verdict, match_reasons, gap_reasons,
                         cover_letter, applied, applied_at, scraped_at, notified)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            job.get("url") or job.get("job_url") or "",
                            job.get("title", ""),
                            job.get("company", ""),
                            job.get("location", ""),
                            job.get("description", ""),
                            job.get("apply_url", ""),
                            job.get("salary_min"),
                            job.get("salary_max"),
                            job.get("job_type", ""),
                            job.get("date_posted", ""),
                            job.get("source", ""),
                            1 if job.get("is_remote") else 0,
                            job.get("score"),
                            job.get("verdict", ""),
                            json.dumps(job.get("match_reasons") or []),
                            json.dumps(job.get("gap_reasons") or []),
                            job.get("cover_letter", ""),
                            1 if job.get("applied") else 0,
                            job.get("applied_at", ""),
                            job.get("scraped_at", datetime.now(timezone.utc).isoformat()),
                            0,
                        ),
                    )
                    saved += 1
                except Exception as e:
                    logger.error(f"DB insert error for {job.get('url')}: {e}")
        return saved

    def get_all_jobs(self, limit: int = 500) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY score DESC, scraped_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_unnotified(self) -> List[Dict]:
        """Get jobs that haven't been sent as alerts yet."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE notified = 0 AND score IS NOT NULL ORDER BY score DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_notified(self, urls: List[str]):
        with self._conn() as conn:
            conn.executemany("UPDATE jobs SET notified = 1 WHERE url = ?", [(u,) for u in urls])

    def mark_applied(self, url: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET applied = 1, applied_at = ?, interview_stage = 'applied', "
                "interview_stage_updated_at = ? WHERE url = ?",
                (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), url),
            )

    def update_stage(self, url: str, stage: str, notes: str = ""):
        """Update interview pipeline stage."""
        import json
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            # Append to interview_dates log
            row = conn.execute("SELECT interview_dates FROM jobs WHERE url = ?", (url,)).fetchone()
            dates = json.loads((row[0] if row and row[0] else None) or "[]")
            dates.append({"date": now[:10], "round": stage, "notes": notes})
            conn.execute(
                "UPDATE jobs SET interview_stage = ?, interview_stage_updated_at = ?, "
                "interview_dates = ? WHERE url = ?",
                (stage, now, json.dumps(dates), url),
            )
            # Auto-mark response_received for anything past 'applied'
            if stage not in ("not_applied", "applied"):
                conn.execute(
                    "UPDATE jobs SET response_received = 1, response_date = ? WHERE url = ? AND response_received = 0",
                    (now[:10], url),
                )

    def mark_rejected(self, url: str, reason: str = ""):
        self.update_stage(url, "rejected")
        with self._conn() as conn:
            conn.execute("UPDATE jobs SET rejection_reason = ? WHERE url = ?", (reason, url))

    def mark_response(self, url: str, response_type: str = "positive"):
        """Record that a response was received."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET response_received = 1, response_date = ? WHERE url = ?",
                (now[:10], url),
            )

    def get_by_stage(self, stage: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE interview_stage = ? ORDER BY interview_stage_updated_at DESC",
                (stage,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_pipeline(self) -> Dict[str, List[Dict]]:
        """Get all jobs grouped by interview stage."""
        pipeline = {stage: [] for stage in INTERVIEW_STAGES}
        all_jobs = self.get_all_jobs(limit=1000)
        for job in all_jobs:
            stage = job.get("interview_stage") or "not_applied"
            if stage in pipeline:
                pipeline[stage].append(job)
        return pipeline

    def get_response_stats(self) -> Dict:
        """Stats for response rate analysis."""
        with self._conn() as conn:
            total_applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied=1").fetchone()[0]
            got_response = conn.execute("SELECT COUNT(*) FROM jobs WHERE response_received=1").fetchone()[0]
            by_source = conn.execute(
                "SELECT source, COUNT(*) as total, SUM(response_received) as responses "
                "FROM jobs WHERE applied=1 GROUP BY source"
            ).fetchall()
        return {
            "total_applied": total_applied,
            "got_response": got_response,
            "response_rate": round(got_response / total_applied * 100, 1) if total_applied else 0,
            "by_source": [dict(r) for r in by_source],
        }

    def get_daily_stats(self, date: str = None) -> Dict:
        """Get applications sent on a specific date (default today)."""
        if date is None:
            date = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            applied_today = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE applied=1 AND applied_at LIKE ?",
                (f"{date}%",)
            ).fetchone()[0]
            scraped_today = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE scraped_at LIKE ?",
                (f"{date}%",)
            ).fetchone()[0]
        return {"date": date, "applied_today": applied_today, "scraped_today": scraped_today}

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        d["is_remote"] = bool(d.get("is_remote"))
        d["applied"] = bool(d.get("applied"))
        d["notified"] = bool(d.get("notified"))
        for field in ("match_reasons", "gap_reasons"):
            try:
                d[field] = json.loads(d[field] or "[]")
            except Exception:
                d[field] = []
        return d

    def stats(self) -> Dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied=1").fetchone()[0]
            high = conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 80").fetchone()[0]
            avg = conn.execute("SELECT AVG(score) FROM jobs WHERE score IS NOT NULL").fetchone()[0]
        return {"total": total, "applied": applied, "high_match": high, "avg_score": round(avg or 0, 1)}
