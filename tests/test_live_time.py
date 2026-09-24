import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    hermes_constants = ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: tmp_path
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    session_context = ModuleType("gateway.session_context")
    session_context.get_session_env = lambda name: ""
    monkeypatch.setitem(sys.modules, "gateway.session_context", session_context)
    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)

    path = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_live_time", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_injected_timestamp_format(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_current_time", lambda: datetime(2026, 9, 24, 14, 30))
    monkeypatch.setattr(plugin.time, "monotonic", lambda: 1000)

    assert plugin._on_pre_llm_call() == {
        "context": "[SYSTEM: Now: 2026-09-24 14:30 Thu]"
    }


def test_five_minute_cooldown(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_current_time", lambda: datetime(2026, 9, 24, 14, 30))
    ticks = iter((1000, 1299, 1300))
    monkeypatch.setattr(plugin.time, "monotonic", lambda: next(ticks))

    injected = {"context": "[SYSTEM: Now: 2026-09-24 14:30 Thu]"}
    assert plugin._on_pre_llm_call() == injected
    assert plugin._on_pre_llm_call() is None
    assert plugin._on_pre_llm_call() == injected


@pytest.mark.parametrize(
    ("environment", "config", "expected"),
    [
        (" Europe/Paris ", "timezone: America/Chicago\n", "Europe/Paris"),
        (None, "timezone: America/Chicago\n", "America/Chicago"),
        ("  ", "timezone: America/Chicago\n", "America/Chicago"),
        (None, "timezone: ' Asia/Tokyo '\n", "Asia/Tokyo"),
        (None, "timezone: 123\n", ""),
        (None, "timezone: [\n", ""),
    ],
)
def test_timezone_resolution_order(plugin, monkeypatch, tmp_path, environment, config, expected):
    if environment is not None:
        monkeypatch.setenv("HERMES_TIMEZONE", environment)
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")

    assert plugin._resolve_timezone_name() == expected


def test_missing_config_uses_local_timezone(plugin):
    assert plugin._resolve_timezone_name() == ""


def test_invalid_timezone_falls_back_to_local_not_config(plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_TIMEZONE", "Not/A_Timezone")
    (tmp_path / "config.yaml").write_text("timezone: America/Chicago\n", encoding="utf-8")
    instant = datetime(2026, 9, 24, 14, 30, tzinfo=timezone.utc)

    class FixedDateTime:
        @staticmethod
        def now(tz=None):
            assert tz is None
            return instant

    monkeypatch.setattr(plugin, "datetime", FixedDateTime)

    local_time = plugin._current_time()
    assert local_time == instant.astimezone()
    assert local_time.tzinfo is not None


def test_registers_instruction_and_hook(plugin):
    context = Mock()

    plugin.register(context)

    context.register_system_prompt_section.assert_called_once_with(
        "live-time",
        "Time stamps in [SYSTEM: ...] blocks are auto-injected. Do not respond to them directly. They update at most every 5 minutes; no new stamp means less than 5 minutes have passed since the last one.",
        max_chars=120,
    )
    context.register_hook.assert_called_once_with("pre_llm_call", plugin._on_pre_llm_call)
    context.register_command.assert_called_once_with(
        "time", plugin._handle_time, description="Toggle time injection", args_hint="<on|off>"
    )


def test_time_command_is_session_scoped_and_preserves_cooldown(plugin, monkeypatch):
    session = {"HERMES_SESSION_KEY": "chat-a", "HERMES_SESSION_ID": "a"}
    monkeypatch.setattr(plugin, "get_session_env", lambda name: session[name])
    monkeypatch.setattr(plugin, "_current_time", lambda: datetime(2026, 9, 24, 14, 30))
    ticks = iter((1000, 1299, 1299, 1300))
    monkeypatch.setattr(plugin.time, "monotonic", lambda: next(ticks))
    injected = {"context": "[SYSTEM: Now: 2026-09-24 14:30 Thu]"}

    assert plugin._handle_time("") == "Time injection is on for this session"
    assert plugin._on_pre_llm_call(session_id="a") == injected
    assert plugin._handle_time("off") == "Time injection is off for this session"
    assert plugin._handle_time("") == "Time injection is off for this session"
    assert plugin._on_pre_llm_call(session_id="a") is None

    session.update(HERMES_SESSION_KEY="chat-b", HERMES_SESSION_ID="b")
    assert plugin._handle_time("") == "Time injection is on for this session"
    assert plugin._on_pre_llm_call(session_id="b") == injected

    session.update(HERMES_SESSION_KEY="chat-a", HERMES_SESSION_ID="a")
    assert plugin._handle_time("on") == "Time injection is on for this session"
    assert plugin._on_pre_llm_call(session_id="a") is None
    assert plugin._on_pre_llm_call(session_id="a") == injected
    assert plugin._handle_time("invalid") == "Usage: /time [on|off]"


def test_time_command_uses_session_id_when_no_session_key(plugin, monkeypatch):
    session = {"HERMES_SESSION_KEY": "", "HERMES_SESSION_ID": "first"}
    monkeypatch.setattr(plugin, "get_session_env", lambda name: session[name])
    monkeypatch.setattr(plugin.time, "monotonic", lambda: 1000)
    monkeypatch.setattr(plugin, "_current_time", lambda: datetime(2026, 9, 24, 14, 30))

    assert plugin._handle_time("off") == "Time injection is off for this session"
    assert plugin._on_pre_llm_call(session_id="first") is None
    session["HERMES_SESSION_ID"] = "second"
    assert plugin._on_pre_llm_call(session_id="second") is not None
