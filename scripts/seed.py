"""
scripts/seed.py — Seed the database with demo data
====================================================
Populates the DB with realistic sample jobs so you can:
  - Test the dashboard without running the full scraper
  - Develop new features with real-looking data
  - Demo the agent to others

Run:
  python scripts/seed.py              # Add 20 sample jobs
  python scripts/seed.py --count 50   # Add N jobs
  python scripts/seed.py --clear      # Clear DB first, then seed
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_JOBS = [
    # AI/ML Companies
    {"title": "Machine Learning Engineer", "company": "Anthropic", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": False, "salary_min": 180000, "salary_max": 280000,
     "description": "Work on safety research, RLHF, and constitutional AI. Python, PyTorch, distributed training required. PhD or Masters preferred.",
     "job_url": "https://jobs.ashbyhq.com/anthropic/ml-engineer-001"},
    {"title": "AI Research Engineer", "company": "OpenAI", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": False, "salary_min": 200000, "salary_max": 350000,
     "description": "Build and scale foundation models. Deep expertise in PyTorch, CUDA, distributed systems. Publications in top venues preferred.",
     "job_url": "https://openai.com/careers/research-engineer-001"},
    {"title": "ML Platform Engineer", "company": "Scale AI", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": True, "salary_min": 160000, "salary_max": 220000,
     "description": "Build ML infrastructure at scale. Python, Kubernetes, Spark, Ray. 3+ years experience.",
     "job_url": "https://scale.com/careers/ml-platform-001"},
    # Dev Tools
    {"title": "Backend Engineer", "company": "Vercel", "location": "Remote",
     "source": "greenhouse", "is_remote": True, "salary_min": 150000, "salary_max": 200000,
     "description": "Build the infrastructure that powers millions of deployments. Go, Rust, Node.js, distributed systems.",
     "job_url": "https://vercel.com/careers/backend-001"},
    {"title": "Software Engineer - Infrastructure", "company": "Linear", "location": "Remote",
     "source": "ashby", "is_remote": True, "salary_min": 140000, "salary_max": 190000,
     "description": "Small team, big impact. PostgreSQL, TypeScript, React. You'll own entire systems.",
     "job_url": "https://jobs.ashbyhq.com/linear/swe-infra-001"},
    # Data/ML Platforms
    {"title": "Data Engineer", "company": "Databricks", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": True, "salary_min": 155000, "salary_max": 230000,
     "description": "Build data pipelines with Apache Spark, Delta Lake, Kafka. Python, Scala, SQL expertise required.",
     "job_url": "https://databricks.com/careers/data-engineer-001"},
    {"title": "MLOps Engineer", "company": "Weights & Biases", "location": "Remote",
     "source": "lever", "is_remote": True, "salary_min": 140000, "salary_max": 195000,
     "description": "Help ML teams ship better models faster. Python, Docker, Kubernetes, ML frameworks.",
     "job_url": "https://wandb.ai/careers/mlops-001"},
    # Fintech
    {"title": "Software Engineer - Payments", "company": "Stripe", "location": "Remote",
     "source": "greenhouse", "is_remote": True, "salary_min": 165000, "salary_max": 250000,
     "description": "Build reliable payment infrastructure. Ruby, Go, Python. Distributed systems, high reliability.",
     "job_url": "https://stripe.com/jobs/swe-payments-001"},
    {"title": "Backend Engineer", "company": "Ramp", "location": "New York, NY",
     "source": "greenhouse", "is_remote": False, "salary_min": 150000, "salary_max": 210000,
     "description": "Build fintech products used by thousands of companies. Python, React, PostgreSQL.",
     "job_url": "https://ramp.com/careers/backend-001"},
    # New Grad specific
    {"title": "Software Engineer - New Grad", "company": "Glean", "location": "Palo Alto, CA",
     "source": "greenhouse", "is_remote": False, "is_new_grad": True, "salary_min": 130000, "salary_max": 170000,
     "description": "New grad role! Build enterprise search with LLMs. Python, Go. Masters/PhD preferred.",
     "job_url": "https://glean.com/careers/new-grad-001"},
    {"title": "ML Engineer - University Grad", "company": "Cohere", "location": "Remote",
     "source": "greenhouse", "is_remote": True, "is_new_grad": True, "salary_min": 120000, "salary_max": 160000,
     "description": "Entry level role for recent graduates. NLP, transformers, Python, PyTorch. Masters required.",
     "job_url": "https://cohere.com/careers/ml-grad-001"},
    # Big Tech
    {"title": "Software Engineer L4", "company": "Google", "location": "Mountain View, CA",
     "source": "linkedin", "is_remote": False, "salary_min": 170000, "salary_max": 290000,
     "description": "Design and implement large-scale distributed systems. Strong CS fundamentals required.",
     "job_url": "https://careers.google.com/swe-l4-001"},
    {"title": "Software Engineer - AI/ML", "company": "Meta", "location": "Menlo Park, CA",
     "source": "linkedin", "is_remote": False, "salary_min": 175000, "salary_max": 300000,
     "description": "Work on AI products at scale. Python, C++, PyTorch. Ranking and recommendation systems.",
     "job_url": "https://metacareers.com/ai-ml-swe-001"},
    # Startups
    {"title": "Full Stack Engineer", "company": "Cursor", "location": "San Francisco, CA",
     "source": "ashby", "is_remote": False, "salary_min": 140000, "salary_max": 200000,
     "description": "Build the AI-native code editor. TypeScript, React, Electron, LLM APIs.",
     "job_url": "https://jobs.ashbyhq.com/anysphere/fullstack-001"},
    {"title": "Backend Engineer", "company": "Perplexity AI", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": False, "salary_min": 160000, "salary_max": 240000,
     "description": "Build the AI search engine backend. Python, Go, distributed systems, LLMs.",
     "job_url": "https://perplexity.ai/careers/backend-001"},
    # Remote/other
    {"title": "Platform Engineer", "company": "Dagster Labs", "location": "Remote",
     "source": "greenhouse", "is_remote": True, "salary_min": 145000, "salary_max": 195000,
     "description": "Build data orchestration platform. Python, Kubernetes, cloud infrastructure.",
     "job_url": "https://dagster.io/careers/platform-001"},
    {"title": "AI Engineer", "company": "Harvey AI", "location": "San Francisco, CA",
     "source": "ashby", "is_remote": False, "salary_min": 175000, "salary_max": 270000,
     "description": "Build AI legal products. LLMs, RAG, Python. Legal tech background a plus.",
     "job_url": "https://harvey.ai/careers/ai-engineer-001"},
    # Mixed
    {"title": "Senior Data Scientist", "company": "Airbnb", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": True, "salary_min": 160000, "salary_max": 230000,
     "description": "Drive data insights for marketplace. Python, SQL, A/B testing, causal inference.",
     "job_url": "https://airbnb.com/careers/data-science-001"},
    {"title": "Site Reliability Engineer", "company": "Notion", "location": "Remote",
     "source": "greenhouse", "is_remote": True, "salary_min": 150000, "salary_max": 210000,
     "description": "Keep Notion reliable at scale. Python, Go, Kubernetes, observability tools.",
     "job_url": "https://notion.so/careers/sre-001"},
    {"title": "Infrastructure Engineer", "company": "Discord", "location": "San Francisco, CA",
     "source": "greenhouse", "is_remote": False, "salary_min": 155000, "salary_max": 220000,
     "description": "Scale Discord's infrastructure. Go, Rust, Kubernetes, distributed systems.",
     "job_url": "https://discord.com/careers/infra-001"},
]

SCORES = [95, 88, 82, 79, 75, 72, 68, 91, 84, 77, 73, 86, 80, 70, 93, 76, 88, 74, 83, 71]
STAGES = ["not_applied", "applied", "phone_screen", "technical", "applied", "applied",
          "not_applied", "applied", "phone_screen", "rejected"]


def seed(count: int = 20, clear: bool = False):
    import sqlite3
    import yaml

    cfg = yaml.safe_load(Path("config.yaml").read_text()) if Path("config.yaml").exists() else {}
    db_path = cfg.get("database", {}).get("path", "jobs.db")

    # Run migrations first
    from scripts.migrate import MigrationRunner
    runner = MigrationRunner(Path(db_path))
    runner.run_pending()
    runner.close()

    conn = sqlite3.connect(db_path)

    if clear:
        conn.execute("DELETE FROM jobs")
        conn.commit()
        print("🗑️  Cleared existing jobs")

    now = datetime.now(timezone.utc)
    inserted = 0

    for i, job_template in enumerate(SAMPLE_JOBS[:count]):
        job = {**job_template}
        job["id"] = str(uuid4())
        job["fingerprint"] = f"seed_{i:04d}"
        job["scraped_at"] = (now - timedelta(hours=random.randint(0, 48))).isoformat()
        job["date_posted"] = (now - timedelta(days=random.randint(0, 7))).isoformat()
        job["score"] = SCORES[i % len(SCORES)]
        job["interview_stage"] = STAGES[i % len(STAGES)]
        job["is_remote"] = int(job.get("is_remote", False))
        job["is_new_grad"] = int(job.get("is_new_grad", False))
        if job["score"] >= 80:
            job["cover_letter"] = f"Dear Hiring Team at {job['company']},\n\nI am excited to apply for the {job['title']} position..."
            job["email_draft"] = f"Subject: {job['title']} Application\n\nHi, I'm applying for..."

        try:
            cols = list(job.keys())
            placeholders = ", ".join(["?" for _ in cols])
            col_str = ", ".join(cols)
            conn.execute(
                f"INSERT OR IGNORE INTO jobs ({col_str}) VALUES ({placeholders})",
                [job[c] for c in cols]
            )
            inserted += 1
        except Exception as e:
            print(f"  Skip {job['title']}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ Seeded {inserted} jobs into {db_path}")
    print(f"   → Run: python main.py --dashboard-only to view them")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed database with sample jobs")
    parser.add_argument("--count", type=int, default=20, help="Number of jobs to seed")
    parser.add_argument("--clear", action="store_true", help="Clear DB before seeding")
    args = parser.parse_args()
    seed(args.count, args.clear)
