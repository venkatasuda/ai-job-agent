"""
scripts/healthcheck.py — System health verification
====================================================
Checks all dependencies and connections before starting the agent.
Exit code 0 = healthy, 1 = unhealthy (Docker HEALTHCHECK compatible).

Run:
  python scripts/healthcheck.py           # Full check
  python scripts/healthcheck.py --quick   # Fast subset only
  python scripts/healthcheck.py --fix     # Auto-fix common issues
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    critical: bool = True
    fix: Optional[str] = None


class HealthChecker:
    def __init__(self):
        self.results: List[CheckResult] = []

    def check(self, name: str, fn, critical: bool = True, fix: str = "") -> bool:
        try:
            msg = fn()
            self.results.append(CheckResult(name, True, msg or "OK", critical, fix))
            return True
        except Exception as e:
            self.results.append(CheckResult(name, False, str(e), critical, fix))
            return False

    # ── Checks ────────────────────────────────────────────────────────────────

    def check_python_version(self):
        v = sys.version_info
        assert v >= (3, 10), f"Python 3.10+ required, got {v.major}.{v.minor}"
        return f"Python {v.major}.{v.minor}.{v.micro}"

    def check_config(self):
        config_path = Path("config.yaml")
        assert config_path.exists(), "config.yaml not found. Copy config.yaml.example and fill in."
        import yaml
        cfg = yaml.safe_load(config_path.read_text())
        assert isinstance(cfg, dict), "config.yaml is invalid YAML"
        return f"config.yaml loaded ({len(cfg)} sections)"

    def check_resume(self):
        import yaml
        cfg = yaml.safe_load(Path("config.yaml").read_text()) if Path("config.yaml").exists() else {}
        resume_path = cfg.get("profile", {}).get("resume_path", "resume.txt")
        p = Path(resume_path)
        if not p.exists():
            raise Exception(f"Resume not found at '{resume_path}'. Create it first.")
        size = p.stat().st_size
        assert size > 100, f"Resume file too small ({size} bytes) — might be empty"
        return f"{resume_path} ({size} bytes)"

    def check_database(self):
        from database.db import JobDatabase
        db = JobDatabase("jobs.db")
        stats = db.stats()
        return f"SQLite OK — {stats.get('total', 0)} jobs"

    def check_openai(self):
        import yaml
        cfg = yaml.safe_load(Path("config.yaml").read_text()) if Path("config.yaml").exists() else {}
        provider = cfg.get("ai", {}).get("provider", "openai")
        if provider != "openai":
            return f"Skipped (provider={provider})"
        key = cfg.get("ai", {}).get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
        assert key, "OPENAI_API_KEY not set in config.yaml or env"
        assert key.startswith("sk-"), "OpenAI key looks invalid (should start with sk-)"
        return f"OpenAI key found (sk-...{key[-4:]})"

    def check_gemini(self):
        import yaml
        cfg = yaml.safe_load(Path("config.yaml").read_text()) if Path("config.yaml").exists() else {}
        provider = cfg.get("ai", {}).get("provider", "openai")
        if provider != "gemini":
            return f"Skipped (provider={provider})"
        key = cfg.get("ai", {}).get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        assert key, "GEMINI_API_KEY not set"
        return "Gemini key found"

    def check_required_packages(self):
        required = [
            "yaml", "jobspy", "openai", "pydantic",
            "apscheduler", "requests", "rich",
        ]
        missing = []
        for pkg in required:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)
        if missing:
            raise Exception(f"Missing packages: {missing}. Run: pip install -r requirements.txt")
        return f"All {len(required)} required packages present"

    def check_optional_packages(self):
        optional = {
            "streamlit": "dashboard",
            "pdfplumber": "PDF resume support",
            "twilio": "WhatsApp alerts",
            "speech_recognition": "Voice interview",
        }
        missing = [k for k in optional if not self._can_import(k)]
        if missing:
            return f"Optional packages not installed: {missing} (non-critical)"
        return "All optional packages present"

    def check_disk_space(self):
        import shutil
        total, used, free = shutil.disk_usage(".")
        free_gb = free / (1024 ** 3)
        assert free_gb >= 0.5, f"Low disk space: {free_gb:.1f}GB free (need 500MB+)"
        return f"{free_gb:.1f}GB free"

    def check_network(self):
        import socket
        socket.setdefaulttimeout(5)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return "Network reachable"

    def check_env_file(self):
        env_path = Path(".env")
        if not env_path.exists():
            return "No .env file (using config.yaml — OK)"
        return f".env file found ({env_path.stat().st_size} bytes)"

    def check_data_dirs(self):
        dirs = ["data/raw", "data/processed", "resumes", "observability/traces", "evaluation/eval_results"]
        created = []
        for d in dirs:
            p = Path(d)
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                created.append(d)
        if created:
            return f"Created directories: {created}"
        return f"All {len(dirs)} data directories present"

    @staticmethod
    def _can_import(pkg: str) -> bool:
        try:
            importlib.import_module(pkg)
            return True
        except ImportError:
            return False

    def run_all(self, quick: bool = False) -> bool:
        print(f"\n{'='*55}")
        print(f"  🔍 AI Job Agent — Health Check   {datetime.now():%Y-%m-%d %H:%M}")
        print(f"{'='*55}")

        self.check("Python version",     self.check_python_version)
        self.check("Required packages",  self.check_required_packages,
                   fix="pip install -r requirements.txt")
        self.check("config.yaml",        self.check_config,
                   fix="cp config.yaml.example config.yaml && nano config.yaml")
        self.check("Resume file",        self.check_resume, critical=False,
                   fix="Create resume.txt with your resume text")
        self.check("Database",           self.check_database)
        self.check("Disk space",         self.check_disk_space)
        self.check("Data directories",   self.check_data_dirs)

        if not quick:
            self.check("Network",            self.check_network)
            self.check("OpenAI API key",     self.check_openai, critical=False,
                       fix="Set OPENAI_API_KEY in .env or config.yaml")
            self.check("Gemini API key",     self.check_gemini, critical=False)
            self.check("Optional packages",  self.check_optional_packages, critical=False)
            self.check("Env file",           self.check_env_file, critical=False)

        # Print results
        print()
        critical_failures = 0
        for r in self.results:
            icon = "✅" if r.passed else ("❌" if r.critical else "⚠️")
            print(f"  {icon}  {r.name:<30} {r.message}")
            if not r.passed and r.critical:
                critical_failures += 1
                if r.fix:
                    print(f"       Fix: {r.fix}")

        print(f"\n{'='*55}")
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)

        if critical_failures == 0:
            print(f"  ✅ Health: PASS ({passed}/{total} checks passed)")
        else:
            print(f"  ❌ Health: FAIL ({critical_failures} critical issue(s))")

        print(f"{'='*55}\n")
        return critical_failures == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run fast subset only")
    parser.add_argument("--fix", action="store_true", help="Auto-fix common issues")
    args = parser.parse_args()

    checker = HealthChecker()
    healthy = checker.run_all(quick=args.quick)
    sys.exit(0 if healthy else 1)
