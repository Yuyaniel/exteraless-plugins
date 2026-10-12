# Additional SDK modules

> **Verified on device** — exteraGram 12.10.6 / SDK **1.4.5.7**, by importing each module inside a
> probe plugin and dumping its public surface. The module list below is what the device actually
> ships; entries marked *observed* were enumerated but not exercised.

The SDK installs to `<app files>/chaquopy/plugins-sdk/` and is put on `sys.path` at plugin start.
On 1.4.5.7 that directory contains:

```
_sdk_version.so   android_utils.so  base_plugin.so   client_utils.so  dev_server.so
file_utils.so     hook_utils.so     intents.so       log_utils.so     markdown_utils.so
plugin_settings.so
elyxcore/{__init__.py,_dev_server,_engine,_importer,_install,_plugin,_plugin_engine,
          assets,localization,settings,utils}.so
extera_utils/{__init__.py,classes,get_caller,metadata_parser,text_formatting}.so
ui/{__init__.py,alert,bulletin,settings}.so
```

## `_sdk_version`

Reports the SDK version actually loaded and drives safe mode.

```python
import _sdk_version

_sdk_version.__version__     # '1.4.5.7'  (str)
_sdk_version.version         # (1, 4, 5, 7)  (tuple)
```

Public names (measured): `version`, `version_str`, `beta`, `check_safemode`, `setup_hooks`,
`SafeModeImporter`, `Path`, `importlib`, `inspect`, `java`, `sys`.

Use this to detect the runtime SDK rather than trusting a build-time assumption — the SDK bundle
inside the APK can be older than the one the app has installed.

## `plugin_settings`

Module-level access to the same persisted settings that `BasePlugin.get_setting` / `set_setting`
use, without needing a plugin instance.

```python
import plugin_settings as ps

value = ps.get_setting(key, default)          # read one key
ps.set_setting(key, value)                    # write one key
all_values = ps.get_all_settings()            # dict of every key for this plugin
ps.set_all_settings(mapping)
ps.clear_settings()
```

Public names (measured): `init`, `get_setting`, `set_setting`, `get_all_settings`,
`set_all_settings`, `clear_settings`.

> *Observed, not exercised:* the exact keyword arguments of each function (e.g. whether
> `set_setting` accepts `reload_settings`) were not probed. `BasePlugin.set_setting(key, value,
> reload_settings=False)` remains the documented path for rebuilding an open settings screen.

## `markdown_utils`

A Markdown-only parser returning a structured result.

```python
import markdown_utils as mu

parsed = mu.parse_markdown("**bold** and `code`")   # parse_markdown(markdown: str) -> ParsedMessage
```

Public names (measured): `parse_markdown`, `ParsedMessage`, `RawEntity`, `TLEntityType`,
`TLRPC_ENTITIES_MAP`, `to_utf16_len`, `count_chars_until`.

> **Two different `TLEntityType` enums exist.** The one in `markdown_utils` has:
> `BOLD, CODE, CUSTOM_EMOJI, ITALIC, PRE, SPOILER, STRIKETHROUGH, TEXT_LINK, UNDERLINE` —
> **no `BLOCKQUOTE`**. The one in `extera_utils.text_formatting` additionally supports blockquotes.
> Pick the module that matches the syntax you feed it:
> `extera_utils.text_formatting.parse_text` handles HTML **and** Markdown (see
> [text-formatting.md](text-formatting.md)); `markdown_utils.parse_markdown` is Markdown-only.

## `extera_utils.get_caller`

```python
from extera_utils.get_caller import get_plugin_id

plugin_id = get_plugin_id()
```

Public names (measured): `get_plugin_id`, `ELYX_PLUGIN_NAMESPACE`. Useful in shared helper code that
needs to know which plugin is calling it.

## `extera_utils.metadata_parser`

```python
from extera_utils.metadata_parser import get_metadata
```

Public names (measured): `get_metadata`. This is the AST-based reader behind the "metadata must be a
plain top-level literal" rule — the same machinery that makes parenthesised string concatenation
fail (see [plugin-class.md](plugin-class.md)).

## `dev_server`

The built-in development server. Public names (measured): `DevServer`, `DebuggerEventListener`,
`DebuggerPlatform`, plus handler plumbing (`_handle_ping`, `_handle_get_plugins`,
`_handle_write_plugin`, `_handle_enable_plugin`, `_handle_disable_plugin`, `_handle_reload_plugin`,
`_handle_remove_plugin`, `_handle_start_debugger`, `_handle_stop_debugger`).

The command set is the one described in [dev-workflow.md](dev-workflow.md) (`ping`, `get_plugins`,
`enable_plugin`, `disable_plugin`, `reload_plugin`, `write_plugin`, `remove_plugin`,
`start_debugger`, `stop_debugger`).

> *Observed:* the server was listening on `127.0.0.1:42690` on the test device, but raw socket
> requests (`{"@":"ping","#":"1"}` with and without a trailing newline, LF or CRLF) received **no
> response**. Treat the wire format in the official docs as unverified until a client is confirmed
> working; for pushing code during development the deterministic path is:
> copy the file into the plugins directory, set `plugin_enabled_<id>` in
> `shared_prefs/plugin_settings.xml`, then restart the app.

## `elyx` and `elyxcore`

`import elyx` resolves to a dynamic module (`__file__` is `None`); `elyxcore` is the on-disk
package. Measured `elyx` public surface — **18 names**, not 19:

```
Asset, AssetNotFoundException, Assets, AssetsDirNotFoundException, Callback, Callback2,
Callback3, CallbackReturn, LazyDict, OnClickListener, Runnable, SettingsController,
Strings, gen, gen2, get_environment, import_module, mvel_execute
```

`assets`, `metainfo`, `refmap`, `settings`, `strings` are plugin-bound and deliberately excluded
from star-imports. See [elyx.md](elyx.md).
