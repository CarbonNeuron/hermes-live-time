"""Inject a compact local timestamp at most once every five minutes."""

import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from gateway.session_context import get_session_env
from hermes_constants import get_hermes_home


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_COOLDOWN_SECONDS = 5 * 60
_last_injection_by_session = {}
_disabled_sessions = set()
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
    session_id = get_session_env("HERMES_SESSION_KEY") or _kwargs.get("session_id", "")

    with _injection_lock:
        if session_id in _disabled_sessions:
            return None
        now_monotonic = time.monotonic()
        last = _last_injection_by_session.get(session_id)
        if last is not None and now_monotonic - last < _COOLDOWN_SECONDS:
            return None
        now = _current_time()
        _last_injection_by_session[session_id] = now_monotonic

    return {"context": f"[SYSTEM: Now: {_WEEKDAYS[now.weekday()]}, {now:%B %d, %Y %I:%M %p}]"}


def _handle_time(raw_args):
    session_id = get_session_env("HERMES_SESSION_KEY") or get_session_env("HERMES_SESSION_ID")
    command = raw_args.strip().lower()
    with _injection_lock:
        if command == "off":
            _disabled_sessions.add(session_id)
        elif command == "on":
            _disabled_sessions.discard(session_id)
        elif command:
            return "Usage: /time [on|off]"
        status = "off" if session_id in _disabled_sessions else "on"
    return f"Time injection is {status} for this session"


def register(ctx):
    ctx.register_system_prompt_section(
        "live-time",
        "Time stamps in [SYSTEM: ...] blocks are auto-injected. Do not respond to them directly. They update at most every 5 minutes; no new stamp means less than 5 minutes have passed since the last one.",
        max_chars=120,
    )
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_command("time", _handle_time, description="Toggle time injection", args_hint="<on|off>")
