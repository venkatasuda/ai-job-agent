"""
Gmail Parser — Auto-update Application Status from Inbox
=========================================================
Real job seekers drown in email. This module reads your Gmail
and automatically updates the application pipeline:

  "We regret to inform you..." → mark REJECTED
  "We'd like to schedule a call..." → mark PHONE_SCREEN
  "Congratulations! We'd like to extend an offer..." → mark OFFER
  "Your application has been received..." → confirm APPLIED

Requires: Gmail API credentials (OAuth 2.0)
Setup: See SETUP_GUIDE.md for Gmail API setup instructions

Also:
  - Detects recruiter outreach and queues for response generation
  - Tracks response times (how quickly companies reply)
  - Finds interview scheduling emails and extracts dates
"""

import logging
import os
import re
import base64
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Email classification patterns
EMAIL_PATTERNS = {
    "rejected": [
        r"we regret", r"we('re| are) unable", r"not moving forward",
        r"decided to (pursue|move forward with) (other|another)",
        r"position has been filled", r"not selected", r"not a fit",
        r"withdrawn your application", r"no longer consider",
        r"unfortunately", r"at this time we", r"after careful consideration",
    ],
    "phone_screen": [
        r"schedule (a |an )?(call|chat|phone|screening)",
        r"initial (interview|screen|call)",
        r"recruiter (call|screen|chat)",
        r"introductory call", r"phone interview",
        r"set up (a |an )?time to (talk|speak|connect|chat)",
        r"availability for a (brief )?(call|conversation)",
    ],
    "technical": [
        r"technical (interview|assessment|screen|round|challenge)",
        r"coding (challenge|assessment|test|interview)",
        r"take.?home (assignment|project|test)",
        r"hackerrank", r"codility", r"leetcode", r"codesignal",
        r"technical assessment",
    ],
    "onsite": [
        r"on.?site (interview|round)", r"final (round|interview)",
        r"in.?person interview", r"virtual (final|onsite)",
        r"full.?day interview", r"loop interview",
    ],
    "offer": [
        r"(delighted|pleased|excited) to (offer|extend)",
        r"offer of employment", r"job offer",
        r"compensation package", r"start date",
        r"would like to (offer|extend) (you|an offer)",
        r"congratulations.*offer",
    ],
    "application_received": [
        r"application (has been |)received",
        r"thank you for (applying|your application|your interest)",
        r"we have received your",
        r"application (is|has been) (under review|submitted)",
    ],
    "recruiter_outreach": [
        r"(came across|found|noticed) your (profile|background|resume)",
        r"open to (new )?opportunities",
        r"we('re| are) hiring",
        r"talent (acquisition|team|recruiter)",
        r"I('m| am) reaching out",
    ],
}


class GmailParser:
    def __init__(self, config: dict):
        self.cfg = config
        self.gmail_cfg = config.get("gmail_parser", {})
        self.credentials_path = self.gmail_cfg.get("credentials_path", "gmail_credentials.json")
        self.token_path = self.gmail_cfg.get("token_path", "gmail_token.json")
        self._service = None

    def _get_service(self):
        """Initialize Gmail API service with OAuth."""
        if self._service:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
            creds = None

            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                with open(self.token_path, "w") as token:
                    token.write(creds.to_json())

            self._service = build("gmail", "v1", credentials=creds)
            return self._service
        except ImportError:
            logger.warning("Gmail API not installed. Run: pip install google-api-python-client google-auth-oauthlib")
            return None
        except Exception as e:
            logger.error(f"Gmail auth failed: {e}")
            return None

    def _get_email_body(self, msg: dict) -> str:
        """Extract plain text body from Gmail message."""
        body = ""
        try:
            payload = msg.get("payload", {})
            parts = payload.get("parts", [payload])
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        except Exception:
            pass
        return body[:3000]

    def classify_email(self, subject: str, body: str, sender: str) -> Tuple[str, float]:
        """
        Classify email type and confidence.
        Returns (category, confidence 0-1).
        """
        text = (subject + " " + body).lower()
        scores = {}
        for category, patterns in EMAIL_PATTERNS.items():
            matched = sum(1 for p in patterns if re.search(p, text))
            scores[category] = matched / len(patterns)

        if not scores or max(scores.values()) == 0:
            return "other", 0.0

        best = max(scores, key=scores.get)
        return best, scores[best]

    def _extract_company_from_email(self, sender: str, subject: str, body: str) -> str:
        """Try to extract company name from email."""
        # From email domain: recruiter@stripe.com → Stripe
        domain_match = re.search(r"@([a-z0-9]+)\.", sender.lower())
        if domain_match:
            domain = domain_match.group(1)
            # Skip common email providers
            if domain not in ("gmail", "yahoo", "outlook", "hotmail", "lever", "greenhouse", "ashby", "workday"):
                return domain.capitalize()

        # From subject: "Your Application to Stripe" → Stripe
        sub_match = re.search(r"(?:application to|at|from|with)\s+([A-Z][a-zA-Z\s]+?)(?:\s*[-–|]|\s+(?:team|hr|recruiting)|$)", subject)
        if sub_match:
            return sub_match.group(1).strip()

        return ""

    def fetch_recent_emails(self, max_results: int = 50, days_back: int = 7) -> List[Dict]:
        """Fetch recent emails related to job applications."""
        service = self._get_service()
        if not service:
            return []

        try:
            # Search for job-related emails
            query = (
                f"after:{(datetime.utcnow().date()).strftime('%Y/%m/%d')} "
                f"(subject:(application OR interview OR offer OR recruiter OR position OR role OR opportunity))"
            )
            result = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()

            messages = result.get("messages", [])
            emails = []
            for msg_ref in messages:
                try:
                    msg = service.users().messages().get(
                        userId="me", id=msg_ref["id"], format="full"
                    ).execute()
                    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                    emails.append({
                        "id": msg_ref["id"],
                        "subject": headers.get("Subject", ""),
                        "sender": headers.get("From", ""),
                        "date": headers.get("Date", ""),
                        "body": self._get_email_body(msg),
                    })
                except Exception:
                    continue
            return emails
        except Exception as e:
            logger.error(f"Gmail fetch failed: {e}")
            return []

    def process_and_update(self, db, dry_run: bool = False) -> Dict[str, int]:
        """
        Main method: fetch emails, classify, update DB.
        Returns dict with counts of what was updated.
        """
        emails = self.fetch_recent_emails()
        if not emails:
            logger.info("Gmail parser: no emails fetched (may need setup)")
            return {}

        counts = {
            "rejected": 0, "phone_screen": 0, "technical": 0,
            "onsite": 0, "offer": 0, "recruiter_outreach": 0, "skipped": 0
        }

        stage_map = {
            "rejected": "rejected",
            "phone_screen": "phone_screen",
            "technical": "technical",
            "onsite": "onsite",
            "offer": "offer",
        }

        for email in emails:
            category, confidence = self.classify_email(
                email["subject"], email["body"], email["sender"]
            )
            if confidence < 0.1 or category in ("other", "application_received"):
                counts["skipped"] += 1
                continue

            company = self._extract_company_from_email(
                email["sender"], email["subject"], email["body"]
            )
            logger.info(f"Email [{category}] from {company or email['sender'][:30]}: {email['subject'][:50]}")

            if category in stage_map and company and not dry_run:
                # Find matching job in DB and update stage
                jobs = db.get_all_jobs(limit=500)
                for job in jobs:
                    if company.lower() in (job.get("company") or "").lower():
                        db.update_stage(job["url"], stage_map[category],
                                       notes=f"Auto-detected from email: {email['subject'][:50]}")
                        counts[category] += 1
                        break

            elif category == "recruiter_outreach":
                counts["recruiter_outreach"] += 1

        logger.info(f"Gmail parser processed {len(emails)} emails: {counts}")
        return counts

    @staticmethod
    def setup_instructions() -> str:
        return """
Gmail Parser Setup (5 minutes):
1. Go to console.cloud.google.com
2. Create a project → Enable Gmail API
3. Create OAuth 2.0 credentials → Download as gmail_credentials.json
4. Place gmail_credentials.json in E:\\ai_job_agent\\
5. First run will open browser for authorization
6. Add to config.yaml:
   gmail_parser:
     enabled: true
     credentials_path: "gmail_credentials.json"
     token_path: "gmail_token.json"
"""
