"""Çoklu dil desteği."""

from __future__ import annotations

import json
import os
from pathlib import Path

_AVAILABLE = {"tr": "Türkçe", "en": "English"}


def _config_language() -> str:
    lang = os.environ.get("ABREK_LANG", "").strip().lower()
    if lang in _AVAILABLE:
        return lang
    try:
        path = Path.home() / ".config" / "videoavci" / "config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            value = str(data.get("language", "") or "").strip().lower()
            if value in _AVAILABLE:
                return value
    except Exception:
        pass
    return "tr"


_current = _config_language()
_translations: dict[str, str] = {}


def _load(lang: str) -> None:
    global _current, _translations
    _current = lang if lang in _AVAILABLE else "tr"
    path = Path(__file__).resolve().parent.parent / "locales" / f"{_current}.json"
    try:
        _translations = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _translations = {}


_load(_current)


def available_languages() -> dict[str, str]:
    return dict(_AVAILABLE)


def current_language() -> str:
    return _current


def set_language(lang: str) -> None:
    _load(lang)


def t(key: str, **kwargs) -> str:
    text = _translations.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text