"""
scripts/migrate.py — Database schema migration runner
======================================================
Applies pending DB migrations safely.
- Idempotent: safe to run multiple times
- Tracks applied migrations in schema_versions table
- Each migration is a pure SQL ALTER TABLE / CREATE TABLE

Run:
  python scripts/migrate.py              # Apply all pending
  python scripts/migrate.py --status     # Show what's applied
  python scripts/migrate.py --dry-run    # Preview without applying
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ── Migration definitions ─────────────────────────────────────────────────────
# Each migration: (id, description, sql_statements)
MIGRATIONS: List[Tuple[str, str, List[str]]] = [
    (
        "001_initial_schema",
        "Create core jobs table",
        ["""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            job_url TEXT UNIQUE,
            description TEXT,
            source TEXT,
            date_posted TEXT,
            scraped_at TEXT,
            salary_min REAL,
            salary_max REAL,
            salary_range TEXT,
            is_remote INTEGER DEFAULT 0,
            score REAL,
            notified INTEGER DEFAULT 0
        )
        """]
    ),
    (
        "002_add_cover_letter_fields",
        "Add cover letter and email draft columns",
        [
            "ALTER TABLE jobs ADD COLUMN cover_letter TEXT",
            "ALTER TABLE jobs ADD COLUMN cover_letter_review TEXT",
            "ALTER TABLE jobs ADD COLUMN email_draft TEXT",
        ]
    ),
    (
        "003_add_company_research",
        "Add company research and contact fields",
        [
            "ALTER TABLE jobs ADD COLUMN company_research TEXT",
            "ALTER TABLE jobs ADD COLUMN contact_name TEXT",
            "ALTER TABLE jobs ADD COLUMN contact_linkedin TEXT",
            "ALTER TABLE jobs ADD COLUMN interview_prep TEXT",
        ]
    ),
    (
        "004_add_interview_pipeline",
        "Add interview stage tracking",
        [
            "ALTER TABLE jobs ADD COLUMN interview_stage TEXT DEFAULT 'not_applied'",
            "ALTER TABLE jobs ADD COLUMN interview_stage_updated_at TEXT",
            "ALTER TABLE jobs ADD COLUMN response_received INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN response_date TEXT",
            "ALTER TABLE jobs ADD COLUMN rejection_reason TEXT",
            "ALTER TABLE jobs ADD COLUMN thankyou_sent INTEGER DEFAULT 0",
        ]
    ),
    (
        "005_add_ats_resume",
        "Add ATS scan and resume tailoring fields",
        [
            "ALTER TABLE jobs ADD COLUMN ats_score REAL",
            "ALTER TABLE jobs ADD COLUMN ats_verdict TEXT",
            "ALTER TABLE jobs ADD COLUMN ats_report TEXT",
            "ALTER TABLE jobs ADD COLUMN tailored_resume TEXT",
        ]
    ),
    (
        "006_add_outreach_visa",
        "Add cold outreach and visa filter fields",
        [
            "ALTER TABLE jobs ADD COLUMN outreach_linkedin_dm TEXT",
            "ALTER TABLE jobs ADD COLUMN outreach_cold_email TEXT",
            "ALTER TABLE jobs ADD COLUMN visa_status TEXT",
            "ALTER TABLE jobs ADD COLUMN visa_reason TEXT",
            "ALTER TABLE jobs ADD COLUMN is_new_grad INTEGER DEFAULT 0",
        ]
    ),
    (
        "007_add_culture_hiring_signals",
        "Add culture score and hiring intelligence fields",
        [
            "ALTER TABLE jobs ADD COLUMN culture_score REAL",
            "ALTER TABLE jobs ADD COLUMN culture_summary TEXT",
            "ALTER TABLE jobs ADD COLUMN hiring_signal TEXT",
            "ALTER TABLE jobs ADD COLUMN hiring_signal_reason TEXT",
            "ALTER TABLE jobs ADD COLUMN freeze_status TEXT",
        ]
    ),
    (
        "008_add_personalization",
        "Add personalized scoring fields",
        [
            "ALTER TABLE jobs ADD COLUMN personalized_score REAL",
            "ALTER TABLE jobs ADD COLUMN personal_score_adjustment REAL",
            "ALTER TABLE jobs ADD COLUMN jd_summary TEXT",
            "ALTER TABLE jobs ADD COLUMN filter_reason TEXT",
            "ALTER TABLE jobs ADD COLUMN fingerprint TEXT",
        ]
    ),
    (
        "009_add_indexes",
        "Add performance indexes",
        [
            "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(interview_stage)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)",
        ]
    ),
    (
        "010_add_pipeline_runs_table",
        "Create pipeline runs tracking table",
        ["""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            run_number INTEGER,
            started_at TEXT,
            finished_at TEXT,
            elapsed_seconds REAL,
            scraped INTEGER DEFAULT 0,
            new_jobs INTEGER DEFAULT 0,
            scored INTEGER DEFAULT 0,
            alerts_sent INTEGER DEFAULT 0,
            auto_applied INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            status TEXT DEFAULT 'completed',
            error TEXT
        )
        """]
    ),
]


def get_db_path() -> Path:
    """Find the DB path from config or default."""
    try:
        import yaml
        cfg = yaml.safe_load(Path("config.yaml").read_text()) if Path("config.yaml").exists() else {}
        return Path(cfg.get("database", {}).get("path", "jobs.db"))
    except Exception:
        return Path("jobs.db")


class MigrationRunner:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._ensure_versions_table()

    def _ensure_versions_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                migration_id TEXT PRIMARY KEY,
                description TEXT,
                applied_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def get_applied(self) -> set:
        cursor = self.conn.execute("SELECT migration_id FROM schema_versions")
        return {row[0] for row in cursor.fetchall()}

    def apply(self, migration_id: str, description: str, statements: List[str]) -> bool:
        """Apply a single migration. Returns True if applied, False if skipped."""
        try:
            for sql in statements:
                try:
                    self.conn.execute(sql.strip())
                except sqlite3.OperationalError as e:
                    # Column already exists = idempotent, skip
                    if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                        continue
                    raise
            self.conn.execute(
                "INSERT INTO schema_versions (migration_id, description, applied_at) VALUES (?, ?, ?)",
                (migration_id, description, datetime.utcnow().isoformat())
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Migration {migration_id} failed: {e}")
            raise

    def run_pending(self, dry_run: bool = False) -> int:
        applied = self.get_applied()
        pending = [(mid, desc, stmts) for mid, desc, stmts in MIGRATIONS if mid not in applied]

        if not pending:
            logger.info("✅ No pending migrations.")
            return 0

        logger.info(f"Found {len(pending)} pending migrations:")
        for mid, desc, _ in pending:
            logger.info(f"  • {mid}: {desc}")

        if dry_run:
            logger.info("Dry run — no changes made.")
            return len(pending)

        applied_count = 0
        for mid, desc, stmts in pending:
            logger.info(f"Applying: {mid} — {desc}")
            self.apply(mid, desc, stmts)
            logger.info(f"  ✅ Applied")
            applied_count += 1

        logger.info(f"\n✅ Applied {applied_count} migration(s).")
        return applied_count

    def status(self):
        applied = self.get_applied()
        print(f"\nMigration Status — {self.db_path}")
        print(f"{'─'*50}")
        for mid, desc, _ in MIGRATIONS:
            status = "✅ Applied" if mid in applied else "⏳ Pending"
            print(f"  {status}  {mid}: {desc}")
        print(f"{'─'*50}")
        print(f"  {len(applied)}/{len(MIGRATIONS)} applied\n")

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DB Migration Runner")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without applying")
    parser.add_argument("--db", help="Database path (default: from config.yaml)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_db_path()
    runner = MigrationRunner(db_path)

    try:
        if args.status:
            runner.status()
        else:
            runner.run_pending(dry_run=args.dry_run)
    finally:
        runner.close()
