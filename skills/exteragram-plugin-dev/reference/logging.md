# Logging (`log_utils`)

> **Verified on device** — exteraGram 12.10.6 / SDK **1.4.5.7**.
> `log_utils` exists as a first-class SDK module and `BasePlugin` exposes `self.logger`.
> (It is **absent** from older builds — e.g. the SDK 1.4.5.5 bundle shipped inside
> `assets/plugins_pysdk/` of some APKs. Check `_sdk_version.__version__` at runtime.)

Every plugin instance owns a `Logger` whose tag is derived from the plugin id, so its output can be
filtered in logcat without grepping the whole log:

```python
from base_plugin import BasePlugin


class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        self.logger.info("Loaded version %s", self.version)
        self.logger.debug("settings=%s", self.export_settings())
```

```bash
adb logcat -s plugin.my_plugin
```

Each entry is prefixed with the recording location:

```
I plugin.my_plugin: [my_plugin.py:on_plugin_load:6] Loaded version 1.0
```

## Relationship to the legacy `log()`

`android_utils.log()` and `BasePlugin.log()` still work, but they are the legacy path: always logged
at debug level, under tags you cannot filter per plugin. Measured tags:

| Call | logcat tag | Line shape |
|------|-----------|------------|
| `self.log(...)` | `[PyObject]` | `D [PyObject]: [callAttrThrows] [<id>] <msg>` |
| `android_utils.log(...)` | `[Python]` | `D [Python]: [getModule] <msg>` |
| `self.logger.info(...)` | `plugin.<id>` | `I plugin.<id>: [file:function:line] <msg>` |

So `adb logcat -s "[PyObject]"` shows *all* plugins' legacy output; `-s plugin.<id>` isolates one
plugin's new-style output. New code should use `self.logger`.

## Levels

| Level | Method |
|-------|--------|
| `LogLevel.VERBOSE` | `logger.verbose(...)` |
| `LogLevel.DEBUG` | `logger.debug(...)` |
| `LogLevel.INFO` | `logger.info(...)` |
| `LogLevel.WARNING` | `logger.warning(...)` |
| `LogLevel.ERROR` | `logger.error(...)`, `logger.exception(...)` |
| `LogLevel.OFF` | assign to `logger.level` to silence that logger |

Levels map onto Android log priorities, so `adb logcat *:E` shows only errors.

**Default level:** with developer mode enabled (plugin info screen → developer mode) DEBUG and above
are shown; otherwise INFO and above. Measured with developer mode on:
`self.logger.effective_level == LogLevel.DEBUG`.

**Per-logger override:**

```python
from log_utils import LogLevel

self.logger.level = LogLevel.VERBOSE   # also accepts "verbose" or the int value
self.logger.level = LogLevel.OFF       # silence this logger
self.logger.level = None               # back to inherited/default
```

`logger.level` is `None` by default (inherit); `logger.effective_level` reports the resolved level.

## Pass arguments, don't f-string

```python
self.logger.debug("chat %s: %s", chat_id, message)
```

`%`-style formatting only runs when DEBUG is enabled; an f-string is built every call — which
matters in a hook that fires thousands of times per second.

## Errors

Inside an `except` block, `exception()` attaches the traceback automatically:

```python
try:
    self.process(update)
except Exception:
    self.logger.exception("Failed to process %s", update_name)
```

Outside one, pass the exception explicitly:

```python
self.logger.error("Request failed", exc_info=error)
```

## Object inspection (`dump`)

`dump()` prints object structure — Telegram `TLRPC` objects, other Java objects, Python values:

```python
self.logger.dump(user, "user")
self.logger.dump(message.messageOwner, depth=3)
```

Signature (measured): `dump(obj, depth=2, max_items=20) -> str`. It is also a plain function and can
be used without logging:

```python
from android_utils import copy_to_clipboard
from log_utils import dump

copy_to_clipboard(dump(message.messageOwner, depth=4))
```

Behaviour:

- **Reads fields only.** Getters, Python properties and `__getattr__` are not invoked, so dumping
  has no side effects.
- Java objects are walked along their class hierarchy, **excluding static fields**. Platform classes
  in `java.*`, `android.*` etc. fall back to `toString()`.
- Lists, maps, arrays and sparse arrays show their size and the first `max_items` entries (default 20).
- Nesting stops at `depth` levels (default 2), marked `{…}`; self-referencing objects are marked
  `<cycle>`.

> `android_utils.dump` exists as well (the SDK re-exports it there) — both resolve to the same helper.

## Child loggers

Split a large plugin by area and set levels independently:

```python
self.net_log = self.logger.child("net")    # tag: plugin.my_plugin.net
self.net_log.level = LogLevel.VERBOSE
```

Measured: `self.logger.child("net").tag == "plugin.<id>.net"`. Child loggers inherit the parent's
level until they set their own.

In helper modules, get a logger without threading the plugin object through:

```python
from log_utils import get_logger

logger = get_logger(__name__)
```

`get_logger()` resolves the owning plugin **from the calling file**: in the plugin's main file it
returns the same logger as `self.logger`; in an Elyx plugin module it returns a child logger named
after that module. Measured inside a plugin: `get_logger("probe.sub").tag == "plugin.<id>.probe.sub"`.
Signature: `get_logger(name: Optional[str] = None) -> Logger`.

## Measuring time

```python
with self.logger.timed("Load stickers"):
    self.load_stickers()
# D plugin.my_plugin: [my_plugin.py:on_plugin_load:21] Load stickers took 12.4 ms
```

If the block raises, the entry ends with `(failed)` and the exception keeps propagating.

## Handlers

A handler receives every entry of one logger and all its children (after level filtering):

```python
from android_utils import run_on_ui_thread
from log_utils import LogLevel, LogRecord
from ui.bulletin import BulletinHelper


class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        self.logger.add_handler(self.show_errors)

    def show_errors(self, record: LogRecord):
        if record.level >= LogLevel.ERROR:
            run_on_ui_thread(lambda: BulletinHelper.show_error(record.message))
```

`LogRecord` fields (measured): `level`, `tag`, `message`, `location` (`file:function:line` or
`None`), `traceback` (`str` or `None`), `created` (Unix time), `text` (the exact entry written to
logcat).

- Handlers run **synchronously on the logging thread** — keep them fast.
- Logging inside a handler does **not** re-trigger handlers.
- Exceptions raised by a handler are logged under the `pysdk` tag and do not affect your plugin.
- On unload the SDK removes the plugin's handlers and resets levels.

## Custom helpers and `stacklevel`

If you wrap the logger in your own helper, pass `stacklevel=2` so the location points at the helper's
caller instead of the helper itself:

```python
def warn_once(self, key, text):
    if key not in self.warned:
        self.warned.add(key)
        self.logger.warning(text, stacklevel=2)
```

## Long messages

logcat caps a single entry at about 4 KB. The logger splits longer messages (big dumps, tracebacks)
**on line boundaries** into several entries so nothing is lost.

## Migrating from `log()`

| Before | After |
|--------|-------|
| `self.log("Loaded")` | `self.logger.info("Loaded")` |
| `log(f"Value: {x}")` | `logger.debug("Value: %s", x)` |
| `log(user)` | `logger.dump(user)` |
| `log(f"Error: {e}\n{traceback.format_exc()}")` | `logger.exception("Error")` |

The old functions keep working. `log(obj)` with a non-text value now prints the same output as
`dump()`. If your plugin already assigns `self.logger` itself, that assignment is respected.

## Reference

```python
class LogLevel:            # VERBOSE, DEBUG, INFO, WARNING, ERROR, OFF
class Logger:
    tag: str
    level: LogLevel | None            # None: inherit parent/default
    effective_level: LogLevel

    def verbose(msg, *args, exc_info=None, stacklevel=1)
    def debug(msg, *args, exc_info=None, stacklevel=1)
    def info(msg, *args, exc_info=None, stacklevel=1)
    def warning(msg, *args, exc_info=None, stacklevel=1)
    def error(msg, *args, exc_info=None, stacklevel=1)
    def exception(msg, *args, stacklevel=1)
    def log(level, msg, *args, exc_info=None, stacklevel=1)
    def dump(obj, label=None, *, level=LogLevel.DEBUG, depth=2, max_items=20, stacklevel=1)
    def timed(label, level=LogLevel.DEBUG)   # context manager
    def is_enabled_for(level) -> bool
    def child(name) -> Logger
    def add_handler(handler)
    def remove_handler(handler) -> bool

def get_logger(name: str | None = None) -> Logger
def dump(obj, depth=2, max_items=20) -> str
```

`Logger(tag)` can be constructed directly for a standalone logger outside the plugin hierarchy.
