"""
Follow-Up Cadence Tracker — from career-ops' followup-cadence module

Tracks when to follow up on submitted applications.
Cadence: Day 5 (first follow-up), Day 10 (second / mark ghosted), Day 14 (archive)
"""

import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

FOLLOWUP_CADENCE = [
    {"day": 5,  "action": "first_followup",  "label": "First follow-up due"},
    {"day": 10, "action": "second_followup", "label": "Second follow-up or mark ghosted"},
    {"day": 14, "action": "archive",         "label": "Archive or final check"},
]


class FollowUpTracker:
    def __init__(self, config: dict):
        self.cfg = config
        self.profile = config.get("profile", {})

    def get_due_followups(self, db) -> List[Dict]:
        jobs = db.get_all_jobs()
        applied = [j for j in jobs if j.get("applied") and j.get("applied_at")]
        due = []
        now = datetime.utcnow()
        for job in applied:
            try:
                applied_at = datetime.fromisoformat(job["applied_at"])
            except Exception:
                continue
            days_since = (now - applied_at).days
            for step in FOLLOWUP_CADENCE:
                if days_since >= step["day"] and not job.get(f"followup_{step['action']}_sent"):
                    due.append({
                        "job": job, "days_since": days_since,
                        "action": step["action"], "label": step["label"],
                        "followup_num": FOLLOWUP_CADENCE.index(step) + 1,
                    })
                    break
        logger.info(f"Follow-up tracker: {len(due)} applications need follow-up")
        return due

    def format_followup_alert(self, due_items: List[Dict]) -> str:
        if not due_items:
            return ""
        lines = ["📬 <b>Follow-Up Reminders</b>\n"]
        for item in due_items:
            job = item["job"]
            lines.append(
                f"• <b>{job['title']}</b> @ {job['company']}\n"
                f"  Applied {item['days_since']} days ago — {item['label']}"
            )
        return "\n".join(lines)

    def generate_followup_email(self, job: Dict, followup_num: int, days: int,
                                 llm_fn=None) -> str:
        if llm_fn:
            try:
                prompt = (
                    f"Write a brief professional follow-up email for a job application.\n"
                    f"Candidate: {self.profile.get('name', '')}\n"
                    f"Applied to: {job.get('title', '')} at {job.get('company', '')}\n"
                    f"Days since application: {days}, Follow-up #{followup_num}\n"
                    f"Under 100 words. Polite, not desperate. Ask for status update.\n"
                    f"Write only the email body."
                )
                return llm_fn(prompt)
            except Exception:
                pass
        name = self.profile.get("name", "Your Name")
        return (
            f"Hi there,\n\nI wanted to follow up on my application for the "
            f"{job.get('title', 'position')} role at {job.get('company', 'your company')}. "
            f"I remain very interested and would love to hear about next steps.\n\n"
            f"Happy to provide any additional information.\n\nBest,\n{name}"
        )
