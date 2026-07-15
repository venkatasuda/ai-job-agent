"""
WhatsApp Alert Module
======================
Sends job alerts via WhatsApp using Twilio's WhatsApp API (free sandbox).

Setup:
  1. pip install twilio
  2. Go to https://console.twilio.com → Messaging → Try WhatsApp
  3. Join Twilio sandbox (send "join <code>" to +1-415-523-8886)
  4. Set config: alerts.whatsapp.account_sid, auth_token, to_number

Cost: ~$0.005/message. For daily alerts, ~$1.50/month.
Alternative: Set provider: "callmebot" for truly free WhatsApp via CallMeBot API.
"""

import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)


class WhatsAppAlert:
    def __init__(self, config: dict):
        self.cfg = config.get("alerts", {}).get("whatsapp", {})
        self.enabled = self.cfg.get("enabled", False)
        self.provider = self.cfg.get("provider", "twilio")  # twilio | callmebot
        self.min_score = self.cfg.get("min_score_to_alert", 80)

    def _send_twilio(self, message: str) -> bool:
        """Send via Twilio WhatsApp API."""
        try:
            from twilio.rest import Client
            account_sid = (self.cfg.get("account_sid") or
                          os.environ.get("TWILIO_ACCOUNT_SID", ""))
            auth_token = (self.cfg.get("auth_token") or
                         os.environ.get("TWILIO_AUTH_TOKEN", ""))
            from_number = self.cfg.get("from_number", "whatsapp:+14155238886")
            to_number = (self.cfg.get("to_number") or
                        os.environ.get("WHATSAPP_TO_NUMBER", ""))
            if not all([account_sid, auth_token, to_number]):
                logger.warning("WhatsApp Twilio: missing credentials")
                return False
            client = Client(account_sid, auth_token)
            client.messages.create(
                body=message,
                from_=from_number,
                to=f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
            )
            return True
        except Exception as e:
            logger.error(f"WhatsApp Twilio error: {e}")
            return False

    def _send_callmebot(self, message: str) -> bool:
        """Send via CallMeBot (free). Requires one-time setup."""
        try:
            import requests
            phone = (self.cfg.get("phone_number") or
                    os.environ.get("CALLMEBOT_PHONE", ""))
            api_key = (self.cfg.get("callmebot_api_key") or
                      os.environ.get("CALLMEBOT_API_KEY", ""))
            if not all([phone, api_key]):
                logger.warning("CallMeBot: missing phone or api_key")
                return False
            resp = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": phone, "text": message, "apikey": api_key},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"CallMeBot error: {e}")
            return False

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        if self.provider == "callmebot":
            return self._send_callmebot(message)
        return self._send_twilio(message)

    def _format_job_message(self, job: Dict) -> str:
        score = job.get("score") or 0
        signal = job.get("hiring_signal", "")
        signal_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(signal, "⚪")
        return (
            f"🎯 *Job Alert* {signal_emoji}\n"
            f"*{job.get('title', 'Unknown')}*\n"
            f"🏢 {job.get('company', 'Unknown')}\n"
            f"📍 {job.get('location', 'Unknown')}\n"
            f"💯 Match: {score}%\n"
            f"💰 {job.get('salary_range') or 'Not listed'}\n"
            f"🔗 {job.get('job_url', '')}"
        )

    def send_job_alert(self, job: Dict) -> bool:
        if (job.get("score") or 0) < self.min_score:
            return False
        return self.send(self._format_job_message(job))

    def send_batch(self, jobs: List[Dict]) -> int:
        """Send alert for each high-score job. Returns count sent."""
        high_score = [j for j in jobs if (j.get("score") or 0) >= self.min_score]
        if not high_score:
            return 0
        # Send summary if too many
        if len(high_score) > 5:
            summary = (
                f"📬 *Job Digest*\n"
                f"Found *{len(high_score)}* new high-match jobs!\n\n"
            )
            for job in high_score[:3]:
                summary += (f"• {job.get('title')} @ {job.get('company')} "
                           f"({job.get('score')}%)\n")
            if len(high_score) > 3:
                summary += f"\n...and {len(high_score) - 3} more. Check dashboard."
            return 1 if self.send(summary) else 0
        count = 0
        for job in high_score:
            if self.send_job_alert(job):
                count += 1
        return count

    def send_morning_briefing(self, briefing_text: str) -> bool:
        msg = f"☀️ *Morning Job Briefing*\n\n{briefing_text[:1000]}"
        return self.send(msg)

    def send_interview_reminder(self, company: str, date: str, interview_type: str) -> bool:
        msg = (
            f"🎤 *Interview Reminder*\n"
            f"Company: *{company}*\n"
            f"Type: {interview_type}\n"
            f"Date: {date}\n\n"
            f"Good luck! Review your story bank before this."
        )
        return self.send(msg)
