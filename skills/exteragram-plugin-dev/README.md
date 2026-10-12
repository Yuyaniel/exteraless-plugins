# exteragram-plugin-dev

> A [Cursor](https://cursor.com) / agent skill for building **exteraGram** plugins (Python on `BasePlugin`, SDK `1.4.4.3`, exteraGram `12.5.1+`, Python 3.11 via Chaquopy v16).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Skill](https://img.shields.io/badge/Agent-Skill-blueviolet)](https://skills.sh)

Distilled from the full [plugins.exteragram.app/docs](https://plugins.exteragram.app/docs) (all 32 pages) into a single installable skill that teaches an AI agent how to write, edit, and ship exteraGram plugins — including the repository conventions from [`makarworld/awesome-telegram-plugins`](https://github.com/makarworld/awesome-telegram-plugins) (`.plugin` as source, `docs.md`, `releases/`, Ruff, Pluggy only on release).

## Install

```powershell
npx skills add makarworld/exteragram-plugin-skill -g -y
```

`-g` installs globally (all projects), `-y` skips prompts. Browse on [skills.sh](https://skills.sh).

## What it covers

| Area | Reference |
|------|-----------|
| Metadata, `BasePlugin` lifecycle, hooks, menu items, `HookResult`/`HookStrategy` | [reference/plugin-class.md](reference/plugin-class.md) |
| `ui.settings` (`Header`/`Switch`/`Selector`/`Input`/`Text`/`Custom`, `SimpleSettingFactory`) | [reference/settings.md](reference/settings.md) |
| Queues, `send_text`/`send_photo`/`send_document`/`send_video`/`send_audio`, `edit_message`, controllers | [reference/client-utils.md](reference/client-utils.md) |
| `run_on_ui_thread`, `R`, click listeners, `log`, clipboard | [reference/android-utils.md](reference/android-utils.md) |
| Reflection: `find_class`, `get/set_private_field` | [reference/hook-utils.md](reference/hook-utils.md) |
| Xposed-style method hooking: `MethodHook`, `MethodReplacement`, `HookFilter` | [reference/xposed-hooking.md](reference/xposed-hooking.md) |
| Java class proxy: `@java_subclass`, `@joverride`/`@joverload`/`@jmethod`/`jfield`, MVEL, `JA`/`JGS`/`JIR`/`JS` modifiers | [reference/class-proxy.md](reference/class-proxy.md) |
| File utilities: directories, read/write, `FilesController` | [reference/file-utils.md](reference/file-utils.md) |
| `BulletinHelper` + `AlertDialogBuilder` | [reference/ui-helpers.md](reference/ui-helpers.md) |
| `IntentsManager`: before/after handlers, scheme/host/path filters | [reference/intents.md](reference/intents.md) |
| `parse_text` HTML/Markdown, entity types | [reference/text-formatting.md](reference/text-formatting.md) |
| Multi-account scoping (`account=`, `self.client(account)`) | [reference/multi-account.md](reference/multi-account.md) |
| Elyx structured plugins: `refmap`, `metainfo`, `assets`, `strings`, bundled wheels, `ElyxBuilder` | [reference/elyx.md](reference/elyx.md) |
| Setup, first plugin, dev server (`42690`), PIP, pre-installed libs, common classes | [reference/dev-workflow.md](reference/dev-workflow.md) |
| `awesome-plugins` repo conventions (`.plugin` = source, Ruff, `secure.md` on release) | [reference/repo-conventions.md](reference/repo-conventions.md) |
| `log_utils` / `self.logger` — per-plugin logger, `plugin.<id>` tag, handlers, `dump` | [reference/logging.md](reference/logging.md) |
| SDK modules absent from the official docs (`plugin_settings`, `markdown_utils`, `_sdk_version`, `dev_server`, …) | [reference/undocumented-modules.md](reference/undocumented-modules.md) |

> **Note on this copy**: the last two references above were **added locally** — they cover SDK
> features the official docs do not describe. Several statements were also corrected against a real
> device (SDK `1.4.5.7`); look for the *verified on device* markers. See the top-level `README.md`
> of this bundle for the list of corrections.

Plus 4 ready-to-copy examples in [examples/](examples/):

- [`minimal.py`](examples/minimal.py) — bare skeleton
- [`hello_command.py`](examples/hello_command.py) — `.hello` command + settings + `on_send_message_hook`
- [`ghost_mode.py`](examples/ghost_mode.py) — `pre_request_hook` CANCEL/MODIFY + settings
- [`custom_setting.py`](examples/custom_setting.py) — `SimpleSettingFactory` + custom Java view

## When the agent loads it

The skill auto-triggers when the agent sees: `.plugin` files, `BasePlugin`, `on_send_message_hook`, `ui.settings`, `send_text`, `Xposed`, `class proxy`, `Elyx`, `FilesController`, `BulletinHelper`, `IntentsManager`, `hook_utils`, or is asked to build/debug an exteraGram plugin.

## Source

Generated from a full scrape of [plugins.exteragram.app/docs](https://plugins.exteragram.app/docs) (32 pages, SDK `1.4.4.3`). When the live docs disagree with this skill on SDK behavior, the live docs win; for `awesome-plugins` repo conventions, this skill wins.

## License

MIT — see [LICENSE](LICENSE).
