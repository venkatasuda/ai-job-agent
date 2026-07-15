"""
Personalized Scoring Model
============================
Learns YOUR preferences over time and re-ranks jobs accordingly.

Standard AI scoring uses generic criteria. This module learns:
  - Which companies you like (clicked/saved)
  - Which role types lead to interviews for you
  - What salary range you actually want
  - Which locations/remote setups work for you
  - What company sizes you prefer (startup vs. big tech)

After ~20 interactions, it adds a "personalized_score" to each job
that blends AI match score + your learned preferences.

No ML frameworks needed — uses simple weighted scoring.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PersonalScoringModel:
    def __init__(self, config: dict):
        self.cfg = config
        self._prefs_path = Path("personal_preferences.json")
        self._prefs = self._load_prefs()
        self._interaction_count = len(self._prefs.get("interactions", []))

    def _load_prefs(self) -> dict:
        if self._prefs_path.exists():
            try:
                return json.loads(self._prefs_path.read_text())
            except Exception:
                pass
        return {
            "interactions": [],
            "company_affinity": {},
            "source_affinity": {},
            "location_affinity": {},
            "title_affinity": {},
            "salary_preference": {"min": 0, "max": 999999, "ideal": 150000},
            "remote_preference": 0.5,  # 0=office-only, 1=remote-only
            "company_size_preference": "any",  # startup | midsize | bigtech | any
        }

    def _save_prefs(self):
        self._prefs_path.write_text(json.dumps(self._prefs, indent=2))

    def record_interaction(self, job: Dict, action: str):
        """
        action: 'view' | 'save' | 'apply' | 'skip' | 'callback' | 'reject_by_them'
        """
        weights = {
            "view": 1, "save": 3, "apply": 5,
            "skip": -2, "callback": 10, "reject_by_them": 0,
        }
        weight = weights.get(action, 0)

        # Update company affinity
        company = job.get("company", "")
        if company:
            self._prefs["company_affinity"][company] = (
                self._prefs["company_affinity"].get(company, 0) + weight
            )

        # Update source affinity
        source = job.get("source", "")
        if source:
            self._prefs["source_affinity"][source] = (
                self._prefs["source_affinity"].get(source, 0) + weight
            )

        # Update location affinity
        location = job.get("location", "")
        if location:
            self._prefs["location_affinity"][location] = (
                self._prefs["location_affinity"].get(location, 0) + weight
            )

        # Update title keyword affinity
        title = job.get("title", "").lower()
        for keyword in title.split():
            if len(keyword) > 3:
                self._prefs["title_affinity"][keyword] = (
                    self._prefs["title_affinity"].get(keyword, 0) + weight
                )

        # Update remote preference
        if action in ("apply", "save"):
            is_remote = bool(job.get("is_remote"))
            current = self._prefs.get("remote_preference", 0.5)
            # Smooth update toward preference
            self._prefs["remote_preference"] = current * 0.9 + (1.0 if is_remote else 0.0) * 0.1

        # Log interaction
        self._prefs.setdefault("interactions", []).append({
            "job_id": job.get("id"),
            "company": company,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
        })
        # Keep last 1000 interactions
        self._prefs["interactions"] = self._prefs["interactions"][-1000:]
        self._interaction_count = len(self._prefs["interactions"])
        self._save_prefs()

    def compute_personal_score(self, job: Dict) -> float:
        """
        Compute personalized score adjustment (−20 to +20 points).
        Only meaningful after 20+ interactions.
        """
        if self._interaction_count < 10:
            return 0.0

        score = 0.0
        company = job.get("company", "")
        source = job.get("source", "")
        location = job.get("location", "")

        # Company affinity
        if company:
            ca = self._prefs["company_affinity"].get(company, 0)
            score += max(-10, min(10, ca * 0.5))

        # Source affinity
        if source:
            sa = self._prefs["source_affinity"].get(source, 0)
            score += max(-5, min(5, sa * 0.2))

        # Location affinity
        if location:
            la = self._prefs["location_affinity"].get(location, 0)
            score += max(-5, min(5, la * 0.3))

        # Title keyword match
        title = job.get("title", "").lower()
        title_score = 0
        for keyword, affinity in self._prefs.get("title_affinity", {}).items():
            if keyword in title:
                title_score += affinity
        score += max(-10, min(10, title_score * 0.1))

        # Remote preference match
        is_remote = bool(job.get("is_remote"))
        remote_pref = self._prefs.get("remote_preference", 0.5)
        if is_remote and remote_pref > 0.7:
            score += 3
        elif not is_remote and remote_pref < 0.3:
            score += 3
        elif is_remote and remote_pref < 0.3:
            score -= 3

        return round(max(-20, min(20, score)), 1)

    def re_rank(self, jobs: List[Dict]) -> List[Dict]:
        """Apply personalized scoring and re-rank jobs."""
        if self._interaction_count < 10:
            return jobs

        for job in jobs:
            base_score = job.get("score") or 0
            personal_adj = self.compute_personal_score(job)
            job["personal_score_adjustment"] = personal_adj
            job["personalized_score"] = round(base_score + personal_adj, 1)

        return sorted(jobs, key=lambda j: j.get("personalized_score", 0), reverse=True)

    def get_preferences_summary(self) -> Dict:
        if self._interaction_count < 5:
            return {"status": "learning", "interactions": self._interaction_count,
                    "message": f"Need {10 - self._interaction_count} more interactions to personalize"}

        top_companies = sorted(
            self._prefs.get("company_affinity", {}).items(),
            key=lambda x: x[1], reverse=True
        )[:5]
        top_sources = sorted(
            self._prefs.get("source_affinity", {}).items(),
            key=lambda x: x[1], reverse=True
        )[:3]
        top_keywords = sorted(
            self._prefs.get("title_affinity", {}).items(),
            key=lambda x: x[1], reverse=True
        )[:5]

        remote_pref = self._prefs.get("remote_preference", 0.5)
        if remote_pref > 0.7:
            remote_label = "Prefers Remote"
        elif remote_pref < 0.3:
            remote_label = "Prefers In-Office"
        else:
            remote_label = "Flexible (Hybrid OK)"

        return {
            "status": "active",
            "interactions": self._interaction_count,
            "favorite_companies": [c for c, _ in top_companies],
            "best_sources": [s for s, _ in top_sources],
            "role_keywords": [k for k, _ in top_keywords],
            "work_style": remote_label,
        }
