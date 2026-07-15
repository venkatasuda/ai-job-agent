"""
Telegram Alert — sends instant Telegram messages for high-score job matches.
Setup: Create a bot via @BotFather, get the token, then get your chat_id
by messaging the bot and visiting https://api.telegram.org/bot<TOKEN>/getUpdates
"""

import logging
import os
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)


class TelegramAlert:
    def __init__(self, config: dict):
        self.cfg = config.get("alerts", {}).get("telegram", {})
        self.enabled = self.cfg.get("enabled", False)
        self.bot_token = self.cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = self.cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.min_score = self.cfg.get("min_score_to_alert", 75)

    def _send_message(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram: bot_token or chat_id not set.")
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def _format_job(self, job: Dict) -> str:
        score = job.get("score", 0)
        emoji = "🟢" if score >= 85 else "🔵" if score >= 70 else "🟡"
        salary = ""
        if job.get("salary_min"):
            salary = f"\n💰 ${job['salary_min']:,}"
            if job.get("salary_max"):
                salary += f" – ${job['salary_max']:,}"

        match_reasons = "\n".join(
            f"  ✓ {r}" for r in (job.get("match_reasons") or [])[:3]
        )

        return (
            f"{emoji} <b>{job['title']}</b> — <b>{score}/100</b>\n"
            f"🏢 {job['company']}\n"
            f"📍 {job['location']}"
            f"{salary}\n"
            f"🔗 {job['source'].upper()}\n"
            f"\n<i>{job.get('verdict', '')}</i>\n"
            f"\n{match_reasons}\n"
            f"\n<a href='{job.get('apply_url', job['url'])}'>👉 Apply Now</a>"
        )

    def _format_summary(self, jobs: List[Dict]) -> str:
        return (
            f"🤖 <b>AI Job Agent — {len(jobs)} New Matches!</b>\n\n"
            + "\n\n".join(self._format_job(j) for j in jobs[:5])
            + (f"\n\n...and {len(jobs) - 5} more. Check your dashboard." if len(jobs) > 5 else "")
        )

    def send(self, jobs: List[Dict]) -> bool:
        if not self.enabled:
            return False

        eligible = [j for j in jobs if (j.get("score") or 0) >= self.min_score]
        if not eligible:
            logger.info("Telegram: no jobs above threshold.")
            return False

        # Telegram has a 4096 char limit — send in batches of 5
        for i in range(0, len(eligible), 5):
            batch = eligible[i:i + 5]
            text = self._format_summary(batch) if i == 0 else "\n\n".join(
                self._format_job(j) for j in batch
            )
            self._send_message(text)

        logger.info(f"Telegram: sent {len(eligible)} job alerts.")
        return True

    def send_applied_notification(self, job: Dict) -> None:
        """Send a notification when auto-apply submits an application."""
        if not self.enabled:
            return
        text = (
            f"✅ <b>Application Submitted!</b>\n\n"
            f"<b>{job['title']}</b> @ {job['company']}\n"
            f"Score: {job.get('score', 'N/A')}/100\n"
            f"<a href='{job['url']}'>View Job</a>"
        )
        self._send_message(text)
