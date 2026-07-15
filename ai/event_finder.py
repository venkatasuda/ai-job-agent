"""
Networking Event Finder
========================
Finds relevant networking events, tech meetups, and career fairs
where new grad job seekers can meet recruiters and engineers.

Sources:
  - Meetup.com (tech meetups via RSS/API)
  - Eventbrite (career fairs, tech events)
  - Luma.ai (tech community events)
  - LinkedIn Events (via search)
  - University career center events (custom URLs)
  - Remote events / webinars

Output: Ranked list of events with:
  - Relevance to job search
  - Estimated attendance (big = more networking, small = better conversations)
  - Whether target companies have representatives
  - Preparation tips
"""

import json
import logging
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

EVENT_ANALYSIS_PROMPT = """Analyze these networking events and rank them for a job seeker.

Seeker profile: Masters in CS, looking for {roles}
Location: {location}
Target companies: {companies}

Events:
{events_text}

Rank and analyze top 5 events. Return JSON:
{{
  "ranked_events": [
    {{
      "name": "...",
      "score": <1-10>,
      "why_attend": "<one sentence>",
      "prep_tip": "<specific action to take before/at event>",
      "companies_likely": ["..."]
    }}
  ]
}}"""

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}


class EventFinder:
    def __init__(self, config: dict):
        self.cfg = config
        self.ai_cfg = config.get("ai", {})
        self.provider = self.ai_cfg.get("provider", "openai")
        self.model = self.ai_cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache_path = Path("events_cache.json")
        self._cache = self._load_cache()
        self.target_companies = [
            c[0] for c in config.get("sources", {}).get("ats_companies", {}).get("targets", [])
        ]

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.ai_cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text())
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
                if data.get("_fetched_at", "") > cutoff:
                    return data
            except Exception:
                pass
        return {"events": [], "_fetched_at": ""}

    def _save_cache(self, events: List[Dict]):
        self._cache_path.write_text(json.dumps({
            "events": events, "_fetched_at": datetime.now(timezone.utc).isoformat()
        }, indent=2))

    def _search_eventbrite(self, location: str, keywords: List[str]) -> List[Dict]:
        """Search Eventbrite for tech events (no API key needed for basic search)."""
        events = []
        for keyword in keywords[:2]:
            try:
                url = (
                    f"https://www.eventbrite.com/d/{quote(location)}/"
                    f"{quote(keyword.lower().replace(' ', '-'))}/"
                )
                resp = requests.get(url, headers=HEADERS, timeout=10)
                # Parse titles from response
                titles = re.findall(r'"name"\s*:\s*"([^"]+)"', resp.text)
                event_urls = re.findall(r'href="(https://www\.eventbrite\.com/e/[^"]+)"', resp.text)
                dates = re.findall(r'"startDate"\s*:\s*"([^"]+)"', resp.text)
                for i, title in enumerate(titles[:5]):
                    events.append({
                        "name": title,
                        "url": event_urls[i] if i < len(event_urls) else url,
                        "date": dates[i] if i < len(dates) else "",
                        "source": "eventbrite",
                        "location": location,
                        "keywords": keyword,
                    })
            except Exception as e:
                logger.debug(f"Eventbrite search error: {e}")
        return events

    def _search_meetup_rss(self, topics: List[str], location: str) -> List[Dict]:
        """Search Meetup.com via DuckDuckGo (no API key)."""
        events = []
        for topic in topics[:2]:
            query = f"site:meetup.com {topic} {location} tech meetup"
            try:
                resp = requests.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1},
                    headers=HEADERS, timeout=8,
                )
                data = resp.json()
                for topic_result in data.get("RelatedTopics", [])[:5]:
                    text = topic_result.get("Text", "")
                    url = topic_result.get("FirstURL", "")
                    if "meetup" in url:
                        events.append({
                            "name": text[:100] if text else "Meetup Event",
                            "url": url,
                            "source": "meetup",
                            "location": location,
                            "date": "",
                        })
            except Exception:
                pass
        return events

    def _search_luma(self, keywords: List[str]) -> List[Dict]:
        """Search Luma.ai for tech community events."""
        events = []
        try:
            resp = requests.get(
                "https://lu.ma/discover",
                headers=HEADERS, timeout=10,
            )
            titles = re.findall(r'<title[^>]*>([^<]+)</title>', resp.text)
            # Fall back to DuckDuckGo search for luma events
            for kw in keywords[:1]:
                resp2 = requests.get(
                    "https://api.duckduckgo.com/",
                    params={"q": f"site:lu.ma {kw} tech event", "format": "json"},
                    headers=HEADERS, timeout=8,
                )
                data = resp2.json()
                for result in data.get("RelatedTopics", [])[:3]:
                    if "lu.ma" in result.get("FirstURL", ""):
                        events.append({
                            "name": result.get("Text", "Luma Event")[:100],
                            "url": result.get("FirstURL", "https://lu.ma"),
                            "source": "luma",
                            "location": "Online/In-person",
                            "date": "",
                        })
        except Exception:
            pass
        return events

    def find_events(self, location: str = "United States",
                    keywords: Optional[List[str]] = None) -> List[Dict]:
        """Find networking events relevant to tech job seekers."""
        if self._cache.get("events"):
            return self._cache["events"]

        keywords = keywords or ["software engineer career fair", "tech networking", "startup hiring"]
        all_events = []
        all_events.extend(self._search_eventbrite(location, keywords))
        all_events.extend(self._search_meetup_rss(["machine learning", "software engineering"], location))
        all_events.extend(self._search_luma(["AI", "tech career"]))

        # Add always-relevant online events
        all_events.extend([
            {
                "name": "Grace Hopper Celebration (Virtual Components)",
                "url": "https://ghc.anitab.org/",
                "source": "manual",
                "location": "Virtual + In-person",
                "description": "Huge tech conference with major company recruiting",
                "date": "October",
            },
            {
                "name": "MLConf / NeurIPS Career Fair",
                "url": "https://neurips.cc/",
                "source": "manual",
                "location": "Virtual + In-person",
                "description": "Top AI companies recruiting at NeurIPS career expo",
                "date": "December",
            },
            {
                "name": "Handshake Virtual Career Fairs",
                "url": "https://joinhandshake.com/events/",
                "source": "manual",
                "location": "Virtual",
                "description": "New grad focused, 100s of companies per fair",
                "date": "Monthly",
            },
        ])

        self._save_cache(all_events)
        return all_events

    def rank_events(self, events: List[Dict]) -> List[Dict]:
        """Score events by relevance to job search."""
        scored = []
        target_company_names = {c.lower() for c in self.target_companies}
        search_keywords = [kw.lower() for kw in self.cfg.get("search", {}).get("keywords", [])]

        for event in events:
            score = 50
            name_lower = event.get("name", "").lower()
            desc_lower = event.get("description", "").lower()
            text = name_lower + " " + desc_lower

            # Boost for relevant keywords
            for kw in search_keywords:
                if kw.lower() in text:
                    score += 10

            # Boost if target companies mentioned
            for company in target_company_names:
                if company in text:
                    score += 20
                    break

            # Boost for career/hiring events
            if any(w in text for w in ["career", "hiring", "recruiting", "job fair"]):
                score += 15

            # Boost for new grad
            if any(w in text for w in ["new grad", "entry level", "campus", "university"]):
                score += 20

            event["relevance_score"] = min(score, 100)
            scored.append(event)

        return sorted(scored, key=lambda e: e.get("relevance_score", 0), reverse=True)

    def get_preparation_tips(self, event: Dict) -> List[str]:
        """Return event-specific preparation tips."""
        name = event.get("name", "").lower()
        tips = [
            "Bring 20 copies of your resume (even for virtual — have PDF ready)",
            "Research the companies attending ahead of time",
            "Prepare your 30-second elevator pitch",
            "Wear business casual",
        ]
        if "virtual" in name or "online" in name:
            tips[0] = "Have your LinkedIn profile optimized before the event"
            tips.append("Join 5 minutes early to test your audio/video")
        if "hackathon" in name:
            tips.append("Come with a team or be ready to join one")
            tips.append("Bring laptop + charger")
        return tips
