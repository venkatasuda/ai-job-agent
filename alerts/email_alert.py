"""
Email Alert — sends an HTML digest email with top job matches.
Uses Gmail SMTP by default (App Password required).
"""

import smtplib
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import List, Dict

logger = logging.getLogger(__name__)

SCORE_COLOR = {
    range(90, 101): "#22c55e",   # green
    range(75, 90):  "#3b82f6",   # blue
    range(60, 75):  "#f59e0b",   # amber
    range(0, 60):   "#ef4444",   # red
}


def _score_badge_color(score: int) -> str:
    for r, color in SCORE_COLOR.items():
        if score in r:
            return color
    return "#6b7280"


def _build_html(jobs: List[Dict], run_time: str) -> str:
    rows = ""
    for job in jobs:
        score = job.get("score", 0)
        color = _score_badge_color(score)
        salary = ""
        if job.get("salary_min"):
            salary = f"${job['salary_min']:,}"
            if job.get("salary_max"):
                salary += f" – ${job['salary_max']:,}"

        match_html = ""
        for reason in (job.get("match_reasons") or [])[:3]:
            match_html += f"<li style='color:#16a34a'>✓ {reason}</li>"

        gap_html = ""
        for reason in (job.get("gap_reasons") or [])[:2]:
            gap_html += f"<li style='color:#dc2626'>✗ {reason}</li>"

        rows += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:16px;font-family:Arial,sans-serif;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
              <h3 style="margin:0 0 4px;font-size:18px;">
                <a href="{job['url']}" style="color:#1d4ed8;text-decoration:none;">{job['title']}</a>
              </h3>
              <p style="margin:0;color:#374151;font-size:14px;">
                🏢 {job['company']} &nbsp;|&nbsp; 📍 {job['location']} &nbsp;|&nbsp; 🔗 {job['source'].upper()}
                {f"&nbsp;|&nbsp; 💰 {salary}" if salary else ""}
              </p>
            </div>
            <div style="background:{color};color:white;font-weight:bold;font-size:20px;
                        border-radius:50%;width:52px;height:52px;display:flex;
                        align-items:center;justify-content:center;flex-shrink:0;margin-left:12px;">
              {score}
            </div>
          </div>
          <p style="color:#6b7280;font-size:13px;margin:8px 0 0;font-style:italic;">{job.get('verdict','')}</p>
          <div style="margin-top:10px;display:flex;gap:24px;">
            <ul style="margin:0;padding-left:18px;font-size:13px;">{match_html}</ul>
            <ul style="margin:0;padding-left:18px;font-size:13px;">{gap_html}</ul>
          </div>
          <div style="margin-top:12px;">
            <a href="{job.get('apply_url', job['url'])}"
               style="background:#1d4ed8;color:white;padding:8px 16px;border-radius:6px;
                      text-decoration:none;font-size:13px;font-weight:bold;">
              Apply Now →
            </a>
          </div>
        </div>
        """

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
      <h1 style="color:#111827;border-bottom:2px solid #e5e7eb;padding-bottom:12px;">
        🤖 AI Job Agent — {len(jobs)} New Matches
      </h1>
      <p style="color:#6b7280;font-size:13px;">Scanned at {run_time} UTC &nbsp;|&nbsp; Sorted by AI match score</p>
      {rows}
      <hr style="border:none;border-top:1px solid #e5e7eb;margin-top:24px;">
      <p style="color:#9ca3af;font-size:11px;text-align:center;">
        AI Job Agent • Powered by JobSpy + OpenAI • Running locally
      </p>
    </body></html>
    """


class EmailAlert:
    def __init__(self, config: dict):
        self.cfg = config.get("alerts", {}).get("email", {})
        self.enabled = self.cfg.get("enabled", False)
        self.min_score = self.cfg.get("min_score_to_alert", 70)

    def send(self, jobs: List[Dict]) -> bool:
        if not self.enabled:
            return False

        eligible = [j for j in jobs if (j.get("score") or 0) >= self.min_score]
        if not eligible:
            logger.info("Email: no jobs above threshold, skipping.")
            return False

        smtp_host = self.cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = self.cfg.get("smtp_port", 587)
        sender = self.cfg.get("sender_email", "")
        password = self.cfg.get("sender_password") or os.environ.get("EMAIL_PASSWORD", "")
        recipient = self.cfg.get("recipient_email", sender)
        run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🤖 {len(eligible)} New Job Matches — AI Agent ({run_time})"
        msg["From"] = sender
        msg["To"] = recipient

        html = _build_html(eligible, run_time)
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, recipient, msg.as_string())
            logger.info(f"Email digest sent: {len(eligible)} jobs → {recipient}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False
