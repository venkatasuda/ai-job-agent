"""
Study Group / Multi-User Mode
==============================
Enables multiple job seekers to collaborate on their job search:
  - Share job leads with each other
  - Coordinate on which companies each person is applying to
  - Avoid applying to the same position (to not compete)
  - Share interview experiences and questions
  - Accountability partner features (daily check-ins)

Data sharing: Via shared JSON file on cloud storage (Google Drive, Dropbox)
or a simple shared SQLite on a network drive.

Also works solo as a personal accountability tracker.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class StudyGroup:
    def __init__(self, config: dict):
        self.cfg = config.get("study_group", {})
        self.enabled = self.cfg.get("enabled", False)
        self.user_name = config.get("profile", {}).get("name", "Anonymous")
        self.mode = self.cfg.get("mode", "solo")  # solo | shared_file | api
        self._data_path = Path(self.cfg.get("shared_file", "study_group.json"))
        self._data = self._load_data()

    def _load_data(self) -> dict:
        if self._data_path.exists():
            try:
                return json.loads(self._data_path.read_text())
            except Exception:
                pass
        return {
            "members": {},
            "job_leads": [],
            "interview_experiences": [],
            "daily_checkins": [],
            "claimed_companies": {},
        }

    def _save_data(self):
        self._data_path.write_text(json.dumps(self._data, indent=2))

    def join_group(self, role_target: str = "Software Engineer", location: str = "") -> bool:
        self._data.setdefault("members", {})[self.user_name] = {
            "name": self.user_name,
            "role_target": role_target,
            "location": location,
            "joined_at": datetime.utcnow().isoformat(),
            "applications_today": 0,
            "applications_total": 0,
            "interviews": 0,
            "offers": 0,
            "last_active": datetime.utcnow().isoformat(),
        }
        self._save_data()
        logger.info(f"Joined study group as {self.user_name}")
        return True

    def share_job_lead(self, job: Dict, comment: str = "") -> bool:
        """Share a job discovery with the group."""
        lead = {
            "shared_by": self.user_name,
            "shared_at": datetime.utcnow().isoformat(),
            "title": job.get("title"),
            "company": job.get("company"),
            "url": job.get("job_url"),
            "score": job.get("score"),
            "comment": comment,
            "claimed_by": None,
        }
        self._data.setdefault("job_leads", []).append(lead)
        self._save_data()
        return True

    def claim_company(self, company: str) -> Dict:
        """Claim a company to avoid competing with group members."""
        claimed = self._data.setdefault("claimed_companies", {})
        if company in claimed:
            existing = claimed[company]
            if existing["claimer"] == self.user_name:
                return {"status": "already_yours", "message": f"You already claimed {company}"}
            return {
                "status": "claimed",
                "claimer": existing["claimer"],
                "claimed_at": existing["claimed_at"],
                "message": f"{existing['claimer']} is already applying to {company}",
            }
        claimed[company] = {
            "claimer": self.user_name,
            "claimed_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=14)).isoformat(),
        }
        self._save_data()
        return {"status": "success", "message": f"You've claimed {company} for 14 days"}

    def check_company_claimed(self, company: str) -> Optional[str]:
        """Return who claimed this company, or None if free."""
        claimed = self._data.get("claimed_companies", {})
        if company in claimed:
            entry = claimed[company]
            if entry.get("expires_at", "") > datetime.utcnow().isoformat():
                claimer = entry["claimer"]
                if claimer != self.user_name:
                    return claimer
        return None

    def share_interview_experience(self, company: str, round_type: str,
                                    questions: List[str], outcome: str = "",
                                    tips: str = "") -> bool:
        """Share interview questions/experience with the group."""
        experience = {
            "shared_by": self.user_name,
            "shared_at": datetime.utcnow().isoformat(),
            "company": company,
            "round_type": round_type,
            "questions": questions,
            "outcome": outcome,
            "tips": tips,
        }
        self._data.setdefault("interview_experiences", []).append(experience)
        self._save_data()
        return True

    def get_interview_intel(self, company: str) -> List[Dict]:
        """Get shared interview experiences for a specific company."""
        return [
            e for e in self._data.get("interview_experiences", [])
            if e.get("company", "").lower() == company.lower()
        ]

    def daily_checkin(self, applications_today: int, mood: int = 5,
                      wins: str = "", blockers: str = "") -> Dict:
        """Daily accountability check-in."""
        # Update member stats
        members = self._data.setdefault("members", {})
        if self.user_name in members:
            members[self.user_name]["applications_today"] = applications_today
            members[self.user_name]["applications_total"] = (
                members[self.user_name].get("applications_total", 0) + applications_today
            )
            members[self.user_name]["last_active"] = datetime.utcnow().isoformat()

        checkin = {
            "user": self.user_name,
            "date": datetime.utcnow().date().isoformat(),
            "applications_today": applications_today,
            "mood": mood,
            "wins": wins,
            "blockers": blockers,
        }
        self._data.setdefault("daily_checkins", []).append(checkin)
        self._save_data()

        # Build response
        today_total = sum(
            c.get("applications_today", 0)
            for c in self._data["daily_checkins"]
            if c.get("date") == datetime.utcnow().date().isoformat()
        )
        member_count = len(members)
        return {
            "your_apps": applications_today,
            "group_apps_today": today_total,
            "member_count": member_count,
            "message": self._get_encouragement(applications_today, mood),
        }

    def _get_encouragement(self, apps: int, mood: int) -> str:
        if apps >= 10:
            return "🔥 Amazing — 10+ applications today! You're crushing it."
        elif apps >= 5:
            return "💪 Great day! 5+ applications in the bag."
        elif apps >= 1:
            return "✅ Progress made! Every application counts."
        elif mood < 3:
            return "💙 Tough day — that's normal. Rest, then come back stronger."
        return "📝 Set a timer for 25 minutes and submit one application. Just one!"

    def get_leaderboard(self) -> List[Dict]:
        """Group leaderboard by total applications."""
        members = list(self._data.get("members", {}).values())
        return sorted(members, key=lambda m: m.get("applications_total", 0), reverse=True)

    def get_job_leads(self, limit: int = 20) -> List[Dict]:
        """Get recent job leads shared by the group."""
        leads = self._data.get("job_leads", [])
        return sorted(leads, key=lambda l: l.get("shared_at", ""), reverse=True)[:limit]

    def get_group_stats(self) -> Dict:
        members = self._data.get("members", {})
        total_apps = sum(m.get("applications_total", 0) for m in members.values())
        total_interviews = sum(m.get("interviews", 0) for m in members.values())
        return {
            "member_count": len(members),
            "total_applications": total_apps,
            "total_interviews": total_interviews,
            "job_leads_shared": len(self._data.get("job_leads", [])),
            "interview_experiences": len(self._data.get("interview_experiences", [])),
        }
