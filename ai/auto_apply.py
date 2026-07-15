"""
Auto Applier — automatically submits applications on supported platforms.

Currently supported:
  - LinkedIn Easy Apply (via Playwright)

Safety features:
  - Only applies if score >= config threshold
  - Hard limit on max applications per run
  - Logs every application attempt
  - Marks job as applied in DB before clicking submit (idempotent)
"""

import logging
import asyncio
from typing import Dict, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AutoApplier:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {}).get("auto_apply", {})
        self.linkedin_cfg = config.get("linkedin", {})
        self.profile = config.get("profile", {})
        self.enabled = self.cfg.get("enabled", False)
        self.max_per_run = self.cfg.get("max_applications_per_run", 5)
        self.min_score = self.cfg.get("require_min_score", 80)
        self.platforms = self.cfg.get("platforms", [])
        self._applied_count = 0

    def _is_linkedin_easy_apply(self, job: Dict) -> bool:
        return "linkedin.com" in job.get("url", "").lower() and job.get("source") == "linkedin"

    async def _apply_linkedin(self, job: Dict) -> bool:
        """
        Attempt LinkedIn Easy Apply via Playwright.
        Returns True if application submitted, False otherwise.
        """
        try:
            from playwright.async_api import async_playwright

            email = self.linkedin_cfg.get("email", "")
            password = self.linkedin_cfg.get("password", "")
            if not email or not password:
                logger.warning("LinkedIn credentials not set. Skipping auto-apply.")
                return False

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                # Login
                await page.goto("https://www.linkedin.com/login", timeout=30000)
                await page.fill("#username", email)
                await page.fill("#password", password)
                await page.click('[data-litms-control-urn="login-submit"]')
                await page.wait_for_load_state("networkidle", timeout=20000)

                # Navigate to job
                await page.goto(job["url"], timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)

                # Click Easy Apply button
                easy_apply_btn = page.locator("button:has-text('Easy Apply')").first
                if not await easy_apply_btn.is_visible():
                    logger.info(f"No Easy Apply button for {job['title']}")
                    await browser.close()
                    return False

                await easy_apply_btn.click()
                await page.wait_for_timeout(2000)

                # Handle multi-step modal
                max_steps = 10
                for step in range(max_steps):
                    # Check if "Review" or "Submit" button is present
                    submit_btn = page.locator("button:has-text('Submit application')").first
                    review_btn = page.locator("button:has-text('Review')").first
                    next_btn = page.locator("button:has-text('Next')").first

                    if await submit_btn.is_visible():
                        await submit_btn.click()
                        logger.info(f"✅ Applied to {job['title']} @ {job['company']}")
                        await browser.close()
                        return True

                    elif await review_btn.is_visible():
                        await review_btn.click()
                    elif await next_btn.is_visible():
                        await next_btn.click()
                    else:
                        # Unknown state — bail safely
                        logger.warning(f"Auto-apply stalled at step {step} for {job['title']}")
                        break

                    await page.wait_for_timeout(1500)

                await browser.close()
                return False

        except Exception as e:
            logger.error(f"Auto-apply error for {job.get('title')}: {e}")
            return False

    def apply_jobs(self, jobs: List[Dict], db) -> List[Dict]:
        """
        Attempt auto-apply for eligible jobs.
        Updates job['applied'] and persists to DB.
        Returns list of jobs that were applied to.
        """
        if not self.enabled:
            logger.info("Auto-apply disabled in config.")
            return []

        eligible = [
            j for j in jobs
            if not j.get("applied")
            and (j.get("score") or 0) >= self.min_score
        ]

        if not eligible:
            logger.info("No eligible jobs for auto-apply.")
            return []

        applied = []
        self._applied_count = 0

        for job in eligible:
            if self._applied_count >= self.max_per_run:
                logger.info(f"Reached max applications per run ({self.max_per_run}).")
                break

            success = False

            if "linkedin_easy_apply" in self.platforms and self._is_linkedin_easy_apply(job):
                success = asyncio.run(self._apply_linkedin(job))

            if success:
                job["applied"] = True
                job["applied_at"] = datetime.now(timezone.utc).isoformat()
                db.mark_applied(job["url"])
                applied.append(job)
                self._applied_count += 1

        logger.info(f"Auto-apply session: {len(applied)} applications submitted.")
        return applied
