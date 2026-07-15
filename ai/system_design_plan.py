"""
System Design Study Plan Generator
=====================================
Generates a personalized system design study plan based on:
  - Target company / role (different companies test different depths)
  - JD keywords (URL shortener vs. recommendation engine vs. streaming)
  - Interview stage (phone screen brief vs. onsite deep dive)

Outputs:
  - Specific system design topics to study
  - Step-by-step design framework to use in interviews
  - Common follow-up questions per topic
  - Resources (free, no paywall)
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_DESIGN_PLAN_PROMPT = """You are a senior software engineer helping someone prepare for system design interviews.

Target company: {company}
Role: {role}
Interview stage: {stage}
JD keywords: {keywords}

Generate a focused 1-week system design study plan. Format:

## System Design Study Plan — {company}

### Core Concepts to Master (in order)
1. ...

### Top 5 Design Topics for This Role
For each: what they test, 3 key design decisions, 1 follow-up question

### Interview Framework (use this structure every time)
Step 1: Clarify requirements (2 min)
...

### Resources
- [Free resource name]: URL
...

### Mock Design Prompts to Practice
1. ...

Keep it practical. Focus on {company}'s known interview style if you know it."""

# Company-specific design focus areas
COMPANY_DESIGN_FOCUS = {
    "google": {
        "topics": ["Search Engine", "YouTube Streaming", "Google Maps", "Distributed File System",
                   "Web Crawler", "Gmail", "Google Drive"],
        "depth": "Very deep — expects scalability math (QPS, storage estimates)",
        "style": "Whiteboard, 45 min, interviewer asks probing follow-ups",
    },
    "meta": {
        "topics": ["Facebook News Feed", "Instagram Stories", "WhatsApp Messaging",
                   "Social Graph", "Notification System", "Live Video"],
        "depth": "High — social graph and real-time focus",
        "style": "45 min, expects API design + database schema",
    },
    "amazon": {
        "topics": ["Amazon Product Page", "Order Fulfillment", "S3 Storage", "DynamoDB Design",
                   "Rate Limiter", "Shopping Cart", "Recommendation System"],
        "depth": "Medium-High — focus on availability and reliability",
        "style": "Leadership principles woven in, expects trade-off discussion",
    },
    "stripe": {
        "topics": ["Payment Processing", "Idempotency", "Rate Limiter", "Webhook System",
                   "Fraud Detection", "Financial Ledger", "API Design"],
        "depth": "High — financial correctness, exactly-once semantics",
        "style": "Conversational, expects deep API design",
    },
    "uber": {
        "topics": ["Ride Matching", "Surge Pricing", "GPS Tracking", "Maps Service",
                   "Trip History", "Notification Service"],
        "depth": "High — geo-spatial and real-time systems",
        "style": "Whiteboard, geo-distributed systems focus",
    },
    "databricks": {
        "topics": ["Distributed Query Engine", "Data Lake", "Streaming Pipeline",
                   "ML Feature Store", "Job Scheduler", "Metadata Service"],
        "depth": "Very deep — data engineering and distributed computing",
        "style": "Coding + design, Apache Spark internals expected",
    },
    "default": {
        "topics": ["URL Shortener", "Rate Limiter", "Chat System", "File Storage",
                   "News Feed", "Notification System", "Search Autocomplete"],
        "depth": "Medium — focus on core concepts and trade-offs",
        "style": "Standard 45-min whiteboard",
    },
}

# Core system design components everyone should know
CORE_CONCEPTS = {
    "load_balancing": {
        "name": "Load Balancing",
        "subtopics": ["Round Robin", "Least Connections", "Consistent Hashing", "L4 vs L7"],
        "resource": "https://aws.amazon.com/what-is/load-balancing/",
    },
    "caching": {
        "name": "Caching (Redis/Memcached)",
        "subtopics": ["Cache-aside", "Write-through", "TTL", "Cache invalidation", "CDN"],
        "resource": "https://redis.io/docs/manual/",
    },
    "databases": {
        "name": "SQL vs NoSQL Trade-offs",
        "subtopics": ["ACID vs BASE", "Sharding", "Replication", "Indexing", "CAP theorem"],
        "resource": "https://www.mongodb.com/nosql-explained",
    },
    "message_queues": {
        "name": "Message Queues (Kafka/SQS)",
        "subtopics": ["Topics/partitions", "Consumer groups", "At-least-once delivery",
                      "Dead letter queues"],
        "resource": "https://kafka.apache.org/documentation/",
    },
    "api_design": {
        "name": "API Design (REST/gRPC/GraphQL)",
        "subtopics": ["Pagination", "Rate limiting", "Versioning", "Authentication"],
        "resource": "https://swagger.io/specification/",
    },
    "distributed_systems": {
        "name": "Distributed Systems Fundamentals",
        "subtopics": ["CAP theorem", "Consensus (Raft/Paxos)", "Idempotency",
                      "Eventual consistency"],
        "resource": "https://martin.kleppmann.com/2020/11/18/distributed-systems-and-elliptic-curves.html",
    },
}


class SystemDesignPlan:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._plans_path = Path("system_design_plans.json")

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm(self, prompt: str) -> str:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=1000,
                ).choices[0].message.content.strip()
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                return genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
        except Exception as e:
            logger.warning(f"System design LLM error: {e}")
        return ""

    def generate_plan(self, company: str, role: str = "Software Engineer",
                      stage: str = "onsite", job_description: str = "") -> Dict:
        """Generate a personalized system design study plan."""
        company_lower = company.lower().split()[0] if company else "default"
        focus = COMPANY_DESIGN_FOCUS.get(company_lower, COMPANY_DESIGN_FOCUS["default"])

        # Extract JD keywords
        jd_keywords = []
        if job_description:
            tech_words = re.findall(
                r"\b(streaming|real-time|distributed|machine learning|recommendation|"
                r"search|payments|messaging|notifications|analytics|pipeline|api)\b",
                job_description.lower()
            )
            jd_keywords = list(set(tech_words))[:8]

        # LLM plan (if available)
        llm_plan = self._llm(SYSTEM_DESIGN_PLAN_PROMPT.format(
            company=company, role=role, stage=stage,
            keywords=", ".join(jd_keywords) or "general software engineering",
        ))

        plan = {
            "company": company,
            "role": role,
            "stage": stage,
            "company_topics": focus["topics"],
            "company_depth": focus["depth"],
            "company_style": focus["style"],
            "core_concepts": list(CORE_CONCEPTS.values()),
            "jd_keywords": jd_keywords,
            "llm_plan": llm_plan,
            "interview_framework": self._get_framework(),
            "mock_prompts": self._get_mock_prompts(company_lower),
        }

        # Save plan
        plans = {}
        if self._plans_path.exists():
            try:
                plans = json.loads(self._plans_path.read_text())
            except Exception:
                pass
        plans[f"{company}_{stage}"] = plan
        self._plans_path.write_text(json.dumps(plans, indent=2))
        return plan

    def _get_framework(self) -> List[str]:
        return [
            "1. **Clarify Requirements** (2 min): Functional vs non-functional, scale estimates",
            "2. **High-Level Design** (5 min): Draw main components, data flow",
            "3. **API Design** (5 min): Define endpoints, request/response format",
            "4. **Database Design** (5 min): Schema, SQL vs NoSQL choice, why",
            "5. **Detailed Design** (15 min): Deep dive into 2-3 critical components",
            "6. **Scale & Bottlenecks** (10 min): Where does this break? How to fix?",
            "7. **Trade-offs** (3 min): What did you choose and why?",
        ]

    def _get_mock_prompts(self, company: str) -> List[str]:
        company_topics = COMPANY_DESIGN_FOCUS.get(company, COMPANY_DESIGN_FOCUS["default"])["topics"]
        prompts = [f"Design {topic}" for topic in company_topics[:3]]
        prompts += [
            "Design a rate limiter that handles 10,000 requests/second",
            "Design a distributed cache system",
            "Design a real-time notification system",
        ]
        return prompts[:6]

    def get_daily_topic(self) -> Dict:
        """Return today's system design topic to study."""
        from datetime import datetime
        topics = list(CORE_CONCEPTS.values())
        idx = datetime.utcnow().timetuple().tm_yday % len(topics)
        return topics[idx]
