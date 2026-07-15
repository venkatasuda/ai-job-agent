"""
app/prompts/registry.py — Prompt version registry
===================================================
Hot-swappable, versioned prompt lookup.

Features:
  - `get_prompt(key)` → returns latest version
  - `get_prompt(key, version="v1")` → returns specific version
  - Override any prompt at runtime via env var or config
  - Lists all prompts with cost estimates

Usage:
    registry = PromptRegistry()
    prompt = registry.get("cover_letter.draft")
    text = prompt.render(job_title="ML Engineer", company="Anthropic", ...)
    print(f"Estimated cost: ${prompt.estimated_cost_usd}")
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.prompts.templates import ALL_PROMPTS, Prompt

logger = logging.getLogger(__name__)


class PromptRegistry:
    """
    Central registry for all versioned prompts.
    Thread-safe, singleton-friendly (use module-level REGISTRY instance).
    """

    def __init__(self):
        self._store: Dict[str, Dict[str, Prompt]] = {}
        self._load_all()

    def _load_all(self):
        """Load all prompts from templates.py."""
        for prompt in ALL_PROMPTS:
            key = prompt.key
            if key not in self._store:
                self._store[key] = {}
            self._store[key][prompt.version] = prompt
        logger.debug(f"Prompt registry loaded: {len(self._store)} prompts")

    def get(self, key: str, version: Optional[str] = None) -> Prompt:
        """
        Get a prompt by key. Returns latest version if version=None.

        Args:
            key: e.g. "cover_letter.draft"
            version: e.g. "v2" (optional, defaults to latest)

        Raises:
            KeyError: If key or version not found
        """
        if key not in self._store:
            raise KeyError(
                f"Prompt '{key}' not found. "
                f"Available: {', '.join(sorted(self._store.keys()))}"
            )
        versions = self._store[key]
        if version is None:
            # Return latest (highest version string)
            latest = sorted(versions.keys())[-1]
            return versions[latest]
        if version not in versions:
            raise KeyError(f"Prompt '{key}' version '{version}' not found. "
                           f"Available versions: {list(versions.keys())}")
        return versions[version]

    def register(self, prompt: Prompt):
        """Register a custom prompt at runtime (useful for testing/overrides)."""
        if prompt.key not in self._store:
            self._store[prompt.key] = {}
        self._store[prompt.key][prompt.version] = prompt
        logger.info(f"Registered prompt: {prompt.key}@{prompt.version}")

    def list_all(self) -> List[Dict]:
        """List all prompts with metadata."""
        result = []
        for key, versions in sorted(self._store.items()):
            for ver, prompt in sorted(versions.items()):
                result.append({
                    "key": key,
                    "version": ver,
                    "description": prompt.description,
                    "tags": prompt.tags,
                    "estimated_cost_usd": prompt.estimated_cost_usd,
                    "model_hint": prompt.model_hint,
                })
        return result

    def total_estimated_cost(self) -> float:
        """Estimate total cost per pipeline run (all latest prompts)."""
        total = 0.0
        seen = set()
        for key, versions in self._store.items():
            if key not in seen:
                latest = sorted(versions.keys())[-1]
                total += versions[latest].estimated_cost_usd
                seen.add(key)
        return round(total, 5)

    def render(self, key: str, version: Optional[str] = None, **kwargs) -> str:
        """Convenience: get prompt + render in one call."""
        return self.get(key, version).render(**kwargs)

    def __repr__(self) -> str:
        return f"PromptRegistry({len(self._store)} prompts)"


# ── Module-level singleton ─────────────────────────────────────────────────────
REGISTRY = PromptRegistry()


def get_prompt(key: str, version: Optional[str] = None) -> Prompt:
    """Module-level shortcut: from app.prompts.registry import get_prompt"""
    return REGISTRY.get(key, version)


def render_prompt(key: str, version: Optional[str] = None, **kwargs) -> str:
    """Module-level shortcut: get + render in one call."""
    return REGISTRY.render(key, version, **kwargs)
