"""Inject a compact local timestamp at most once every five minutes."""

import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from hermes_constants import get_hermes_home


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_COOLDOWN_SECONDS = 5 * 60
_last_injection_by_session = {}
_injection_lock = threading.Lock()


def _resolve_timezone_name():
    name = os.environ.get("HERMES_TIMEZONE", "").strip()
    if name:
        return name

    try:
        config = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return ""
    if isinstance(config, dict) and isinstance(config.get("timezone"), str):
        return config["timezone"].strip()
    return ""


def _current_time():
    timezone_name = _resolve_timezone_name()
    if timezone_name:
        try:
            return datetime.now(ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone()


def _on_pre_llm_call(**_kwargs):
    session_id = _kwargs.get("session_id", "")

    with _injection_lock:
        now_monotonic = time.monotonic()
        last = _last_injection_by_session.get(session_id)
        if last is not None and now_monotonic - last < _COOLDOWN_SECONDS:
            return None
        now = _current_time()
        _last_injection_by_session[session_id] = now_monotonic

    return {"context": f"[SYSTEM: Now: {now:%Y-%m-%d %H:%M} {_WEEKDAYS[now.weekday()]}]"}


def register(ctx):
    ctx.register_system_prompt_section(
        "live-time",
        "Time stamps in [SYSTEM: ...] blocks are auto-injected. Do not respond to them directly.",
        max_chars=120,
    )
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
