"""
Resume Version Control
========================
Track multiple resume versions (tailored per role/company) and
measure which versions get the best response rates.

Features:
  - Store N tailored resume versions with metadata
  - Tag each version with what job it was used for
  - Track which version got callbacks vs. rejections
  - Suggest the best-performing version for new applications
  - Diff two versions to see what changed

No external tools needed — all stored in resumes/ directory + SQLite.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ResumeVersionControl:
    def __init__(self, config: dict):
        self.cfg = config
        self.base_dir = Path("resumes")
        self.base_dir.mkdir(exist_ok=True)
        self._index_path = self.base_dir / "index.json"
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                pass
        return {"versions": {}, "base": None}

    def _save_index(self):
        self._index_path.write_text(json.dumps(self._index, indent=2))

    def _hash(self, content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def save_version(self, content: str, label: str = "",
                     company: str = "", job_id: str = "",
                     is_base: bool = False) -> str:
        """Save a resume version. Returns version ID."""
        version_id = f"v_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self._hash(content)}"
        path = self.base_dir / f"{version_id}.txt"
        path.write_text(content, encoding="utf-8")

        meta = {
            "version_id": version_id,
            "label": label or (f"Tailored for {company}" if company else "Resume"),
            "company": company,
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "word_count": len(content.split()),
            "callbacks": 0,
            "rejections": 0,
            "applications": 0,
            "response_rate": 0.0,
            "is_base": is_base,
        }
        self._index["versions"][version_id] = meta
        if is_base:
            self._index["base"] = version_id
        self._save_index()
        logger.info(f"Resume saved: {version_id} ({meta['label']})")
        return version_id

    def get_version(self, version_id: str) -> Optional[str]:
        path = self.base_dir / f"{version_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def get_base(self) -> Optional[str]:
        base_id = self._index.get("base")
        if base_id:
            return self.get_version(base_id)
        # Fall back to config resume_path
        resume_path = self.cfg.get("profile", {}).get("resume_path", "resume.txt")
        if Path(resume_path).exists():
            return Path(resume_path).read_text(encoding="utf-8")
        return None

    def record_callback(self, version_id: str):
        if version_id in self._index["versions"]:
            self._index["versions"][version_id]["callbacks"] += 1
            self._index["versions"][version_id]["applications"] += 1
            self._update_response_rate(version_id)
            self._save_index()

    def record_rejection(self, version_id: str):
        if version_id in self._index["versions"]:
            self._index["versions"][version_id]["rejections"] += 1
            self._index["versions"][version_id]["applications"] += 1
            self._update_response_rate(version_id)
            self._save_index()

    def _update_response_rate(self, version_id: str):
        v = self._index["versions"][version_id]
        apps = v.get("applications", 0)
        if apps > 0:
            v["response_rate"] = round(v["callbacks"] / apps * 100, 1)

    def get_best_version(self, min_applications: int = 3) -> Optional[Dict]:
        """Return the version with highest callback rate (min N applications)."""
        candidates = [
            v for v in self._index["versions"].values()
            if v.get("applications", 0) >= min_applications
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: v.get("response_rate", 0))

    def diff(self, version_id_a: str, version_id_b: str) -> str:
        """Simple line diff between two versions."""
        content_a = self.get_version(version_id_a) or ""
        content_b = self.get_version(version_id_b) or ""
        lines_a = set(content_a.split("\n"))
        lines_b = set(content_b.split("\n"))
        added = [f"+ {l}" for l in lines_b - lines_a if l.strip()]
        removed = [f"- {l}" for l in lines_a - lines_b if l.strip()]
        return "\n".join(removed[:20] + added[:20]) or "No significant differences"

    def list_versions(self) -> List[Dict]:
        return sorted(
            self._index["versions"].values(),
            key=lambda v: v.get("created_at", ""),
            reverse=True,
        )

    def get_stats(self) -> Dict:
        versions = list(self._index["versions"].values())
        total_apps = sum(v.get("applications", 0) for v in versions)
        total_callbacks = sum(v.get("callbacks", 0) for v in versions)
        best = self.get_best_version()
        return {
            "total_versions": len(versions),
            "total_applications": total_apps,
            "total_callbacks": total_callbacks,
            "overall_response_rate": round(total_callbacks / total_apps * 100, 1) if total_apps else 0,
            "best_version": best.get("label") if best else None,
            "best_version_rate": best.get("response_rate") if best else None,
        }
