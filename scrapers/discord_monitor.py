"""
Discord Job Board Monitor
==========================
Monitors Discord servers known to post job opportunities:
  - Simplify / New Grad Discord communities
  - Tech job boards posted in Discord channels
  - Remote work communities
  - SWE prep / CS career servers

Uses discord.py webhook reading (bot token required).
Also supports webhook-based passive listening without scraping.

FREE to use — no API costs beyond Discord bot.

Setup:
  1. Create a Discord bot at https://discord.com/developers/applications
  2. Enable: Server Members Intent + Message Content Intent
  3. Add bot to relevant servers
  4. Set discord_bot_token in config
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Regex to detect job postings in Discord messages
JOB_PATTERNS = [
    r"(?i)(hiring|we.re hiring|job opening|open position|looking for)",
    r"(?i)(software engineer|data engineer|ml engineer|backend|frontend)",
    r"(?i)(apply (here|now|at)|application link|job link)",
    r"(?i)(full.?time|contract|remote|hybrid|onsite)",
]

SALARY_PATTERN = re.compile(r"\$[\d,]+[kK]?(?:\s*[-–]\s*\$?[\d,]+[kK]?)?")
URL_PATTERN = re.compile(r"https?://[^\s]+")

# Known Discord servers with job channels (name, invite, channel name)
KNOWN_JOB_SERVERS = [
    {"name": "CS Careers", "description": "CS career community with #job-postings"},
    {"name": "New Grad Jobs", "description": "New grad focused job board"},
    {"name": "Remote Work Community", "description": "Remote job postings daily"},
    {"name": "SWE Interview Prep", "description": "#opportunities channel"},
]


class DiscordJobMonitor:
    def __init__(self, config: dict):
        self.cfg = config.get("scrapers", {}).get("discord", {})
        self.enabled = self.cfg.get("enabled", False)
        self.bot_token = self.cfg.get("bot_token", "")
        self.channels = self.cfg.get("channel_ids", [])  # List of channel IDs to monitor
        self._seen_path = Path("discord_seen_messages.json")
        self._seen = self._load_seen()

    def _load_seen(self) -> set:
        if self._seen_path.exists():
            try:
                data = json.loads(self._seen_path.read_text())
                return set(data)
            except Exception:
                pass
        return set()

    def _save_seen(self):
        self._seen_path.write_text(json.dumps(list(self._seen)))

    def _is_job_post(self, message: str) -> bool:
        return any(re.search(p, message) for p in JOB_PATTERNS)

    def _parse_job_from_message(self, message: str, channel: str,
                                author: str, msg_id: str) -> Optional[Dict]:
        if not self._is_job_post(message):
            return None

        # Extract URL
        urls = URL_PATTERN.findall(message)
        job_url = next((u for u in urls if any(
            s in u for s in ["linkedin", "greenhouse", "lever", "ashby",
                             "indeed", "jobs.", "/careers", "/jobs"]
        )), urls[0] if urls else "")

        # Extract salary
        salary = ""
        m = SALARY_PATTERN.search(message)
        if m:
            salary = m.group()

        # Try to extract title / company from message
        lines = [l.strip() for l in message.split("\n") if l.strip()]
        title = lines[0][:100] if lines else "Discord Job Post"
        company = ""
        for line in lines[:3]:
            if "@" not in line and "http" not in line and len(line) < 60:
                company = line
                break

        return {
            "title": title,
            "company": company or "Unknown (Discord)",
            "location": "See posting",
            "source": f"discord_{channel}",
            "job_url": job_url,
            "description": message[:2000],
            "salary_range": salary,
            "is_remote": bool(re.search(r"(?i)remote", message)),
            "discord_channel": channel,
            "discord_author": author,
            "discord_msg_id": msg_id,
            "date_posted": datetime.utcnow().isoformat(),
        }

    def scrape(self) -> List[Dict]:
        """Fetch recent messages from configured Discord channels."""
        if not self.enabled:
            logger.info("Discord monitor disabled")
            return []
        if not self.bot_token:
            logger.warning("Discord monitor: no bot_token set in config")
            return []

        try:
            import requests
            headers = {
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json",
            }
            jobs = []
            since = (datetime.utcnow() - timedelta(hours=24)).isoformat()

            for channel_id in self.channels:
                try:
                    resp = requests.get(
                        f"https://discord.com/api/v10/channels/{channel_id}/messages",
                        headers=headers,
                        params={"limit": 100},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        logger.warning(f"Discord channel {channel_id}: HTTP {resp.status_code}")
                        continue

                    messages = resp.json()
                    for msg in messages:
                        msg_id = msg.get("id", "")
                        if msg_id in self._seen:
                            continue
                        content = msg.get("content", "")
                        # Also check embeds
                        for embed in msg.get("embeds", []):
                            content += " " + (embed.get("description") or "")
                            content += " " + (embed.get("title") or "")
                        author = msg.get("author", {}).get("username", "unknown")
                        channel_name = str(channel_id)

                        job = self._parse_job_from_message(content, channel_name, author, msg_id)
                        if job:
                            jobs.append(job)
                        self._seen.add(msg_id)
                except Exception as e:
                    logger.error(f"Discord channel {channel_id} error: {e}")

            self._save_seen()
            logger.info(f"Discord: found {len(jobs)} job posts")
            return jobs
        except ImportError:
            logger.warning("Discord monitor: pip install requests")
            return []

    @staticmethod
    def get_setup_instructions() -> str:
        return """
Discord Job Monitor Setup:
==========================
1. Go to https://discord.com/developers/applications
2. Click "New Application" → name it "Job Agent"
3. Click "Bot" tab → "Add Bot" → copy the Token
4. Enable Privileged Intents: Message Content Intent
5. Generate OAuth2 URL with scopes: bot + applications.commands
6. Permissions: Read Messages/View Channels, Read Message History
7. Add bot to your target servers using the OAuth2 URL
8. Get channel IDs: Enable Developer Mode in Discord settings,
   right-click any channel → "Copy ID"
9. In config.yaml:
   scrapers:
     discord:
       enabled: true
       bot_token: "YOUR_BOT_TOKEN"
       channel_ids:
         - "123456789"  # #job-postings channel ID
         - "987654321"  # #opportunities channel ID
"""

    def send_webhook_notification(self, webhook_url: str, job: Dict) -> bool:
        """Send a job notification to a Discord channel via webhook."""
        try:
            import requests
            score = job.get("score") or 0
            color = 0x00FF00 if score >= 85 else (0xFFFF00 if score >= 70 else 0xFF0000)
            payload = {
                "embeds": [{
                    "title": f"🎯 {job.get('title', 'Unknown')}",
                    "description": (f"**Company:** {job.get('company')}\n"
                                   f"**Location:** {job.get('location')}\n"
                                   f"**Match Score:** {score}%\n"
                                   f"**Salary:** {job.get('salary_range') or 'N/A'}"),
                    "url": job.get("job_url", ""),
                    "color": color,
                    "footer": {"text": f"Source: {job.get('source')} | AI Job Agent"},
                }]
            }
            resp = requests.post(webhook_url, json=payload, timeout=8)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Discord webhook error: {e}")
            return False
