"""
Internationalisation (i18n) module.

Language files live in  <repo-root>/language/{locale}.json
Each file must contain:
  {
    "version":     "1.0.0",   # semver — bump patch for text fixes,
                               #   minor for additions, major for key renames
    "locale":      "da",
    "name":        "Dansk",    # English display name
    "nativeName":  "Dansk",    # Name in the language itself
    "fallback":    null,       # locale to fall back to (null = no fallback)
    "translations": { "key.sub": "value", ... }
  }

Keys use dot-notation namespacing:  nav.cameras, schedule.ntp.title, …
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LANG_DIR = Path(__file__).parent.parent / "language"
LANG_DIR = _LANG_DIR  # public alias for use by main.py

# In-memory cache:  locale → {"meta": {...}, "translations": {...}}
_cache: dict[str, dict] = {}


def _load(locale: str) -> dict | None:
    """Load and cache a language file. Returns None if not found."""
    if locale in _cache:
        return _cache[locale]
    path = _LANG_DIR / f"{locale}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[locale] = data
        return data
    except Exception as exc:
        logger.error("Sprog: kunne ikke læse %s: %s", path, exc)
        return None


def available_languages() -> list[dict]:
    """Return list of {locale, name, nativeName, version} for all installed lang files."""
    result = []
    if not _LANG_DIR.exists():
        return result
    for f in sorted(_LANG_DIR.glob("*.json")):
        data = _load(f.stem)
        if data:
            result.append({
                "locale":     data.get("locale", f.stem),
                "name":       data.get("name", f.stem),
                "nativeName": data.get("nativeName", data.get("name", f.stem)),
                "version":    data.get("version", "?"),
            })
    return result


def get_translator(locale: str):
    """
    Return a translation function  t(key, **kwargs) → str  for the given locale.
    Falls back through the locale's 'fallback' chain, then returns the key itself.
    """
    def _resolve(key: str, loc: str, visited: set) -> str | None:
        if loc in visited:
            return None
        visited.add(loc)
        data = _load(loc)
        if data is None:
            return None
        val = data.get("translations", {}).get(key)
        if val is not None:
            return val
        fb = data.get("fallback")
        if fb:
            return _resolve(key, fb, visited)
        return None

    def t(key: str, **kwargs) -> str:
        val = _resolve(key, locale, set())
        if val is None:
            logger.debug("i18n: missing key '%s' for locale '%s'", key, locale)
            val = key  # graceful degradation: show the key
        if kwargs:
            try:
                val = val.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return val

    return t


def invalidate_cache(locale: str) -> None:
    """Remove a locale from the in-memory cache so it reloads from disk on next access."""
    _cache.pop(locale, None)


def day_key(day: str) -> str:
    """Convert a weekday slug to its i18n key."""
    return f"day.{day}" if day != "all" else "day.all"
