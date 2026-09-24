# hermes-live-time

A small [Hermes](https://github.com/NousResearch/hermes-agent) plugin that gives the model a fresh local timestamp on the next turn, then at most once every five minutes. It uses the `pre_llm_call` hook; no background process or external time service is needed.

## Why?

A date or time embedded in a session's system prompt can go stale while the conversation stays open. This plugin adds a new timestamp to the current user-message context when its cooldown expires, so the model can answer time-sensitive questions using the current local clock instead of an old session timestamp.

**Before (long-running session):**

```text
User: What day is it now?
Model: It's Wednesday, September 23. (The timestamp from session start is stale.)
```

**After (with this plugin, on an eligible turn):**

```text
User: What day is it now?
Injected context: [SYSTEM: Now: 2026-09-24 14:30 Thu]
Model: It's Thursday, September 24.
```

## Install

```sh
hermes plugins install CarbonNeuron/hermes-live-time --enable
```

## What the model sees

On an eligible turn, the hook returns a short context string appended to the user message:

```text
[SYSTEM: Now: 2026-09-24 14:30 Thu]
```

The format is `YYYY-MM-DD HH:MM Ddd` (24-hour clock, three-letter weekday); it has no seconds or timezone suffix. The `[SYSTEM: ...]` marker is **not** a separate system-role message. The plugin also registers a brief system-prompt instruction telling the model not to reply to these injected markers directly.

## Configuration

Timezone selection, in priority order:

1. A nonempty `HERMES_TIMEZONE` environment variable, such as `America/Chicago`.
2. The `timezone` value in the Hermes home `config.yaml` (normally `~/.hermes/config.yaml`; a custom `HERMES_HOME` changes this path), for example:

   ```yaml
   timezone: America/Chicago
   ```

3. The machine's local timezone if neither is set, or if the selected timezone is invalid.

Timezone values use IANA names. An invalid environment value falls back to the machine's local timezone, **not** to the config-file value. Missing, unreadable, or malformed config files also fall back to local time.

The cooldown is fixed at five minutes (300 seconds), measured between injections with a monotonic clock. The first eligible hook call injects immediately; calls during the cooldown return nothing. The cooldown is shared by calls in the running plugin process, not maintained separately per conversation, and resets when the process restarts. There is currently no setting to change it.

## Development

With Python, PyYAML, and pytest available, run:

```sh
python -m pytest tests/
```

The tests stub Hermes's `hermes_constants` module, so they do not require a running agent.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 CarbonNeuron.
