"""
Localization module for SheetPilot.
Loads saved language preference on import.
Usage:
    from src.localization import _, set_language, refresh_ui

    label.setText(_("Import"))
"""
import json
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_LANG_DIR = Path(__file__).parent.parent / "lang"
_CONFIG_PATH = Path.home() / "sheetpilot_db" / "lang_config.json"
_current_lang = "pt_BR"
_cache = {}
_refresh_callbacks: list[Callable] = []


def _load_lang(lang: str) -> dict:
    path = _LANG_DIR / f"{lang}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _load_saved_preference() -> str:
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            return data.get("lang", "pt_BR")
    except Exception:
        pass
    return "pt_BR"


def set_language(lang: str):
    global _current_lang, _cache
    _current_lang = lang
    _cache = _load_lang(lang)
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps({"lang": lang}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _(text: str) -> str:
    if text not in _cache:
        logger.warning("Traducao faltando para: %s", text)
    return _cache.get(text, text)


def current_language() -> str:
    return _current_lang


def available_languages() -> list[tuple[str, str]]:
    langs = []
    for f in sorted(_LANG_DIR.glob("*.json")):
        code = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("__language__", code)
        except Exception:
            name = code
        langs.append((code, name))
    return langs or [("pt_BR", "Portugu\u00eas (Brasil)")]


def on_language_change(callback: Callable):
    """Register a callback to be called when the language changes.
    The callback receives no arguments. Use this for UI hot-reload."""
    _refresh_callbacks.append(callback)


def trigger_refresh():
    """Call all registered refresh callbacks after language change."""
    for cb in _refresh_callbacks:
        try:
            cb()
        except Exception:
            pass


# Load saved preference on import
set_language(_load_saved_preference())
