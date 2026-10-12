# awesome-plugins Repository Conventions

Source: `.cursor/rules/plugin-workflow.mdc` + `.cursor/rules/structure-docs-security.mdc` in the awesome-plugins repo.

These conventions are repo-specific and **override** generic plugin-authoring habits when working in `awesome-plugins`.

## `.plugin` is the Source

- The `.plugin` file is a Python file with a different extension — it is the **only source file in git** for a plugin.
- **No build step.** Edit code directly in `.plugin`. Do not generate `.py`, do not run `build_plugin.bat`.
- `__version__` lives inside the `.plugin` as a top-level constant.

## Directory Structure

```
PluginName/
  plugin_name.plugin        # source (Python, only file in git for code)
  README.md                 # users — download, usage, risks
  docs.md                   # developers — hooks, settings, architecture (READ BEFORE EDITS)
  secure.md                 # current security report (only on release)
  releases/vX.Y.Z/
    plugin_name_vX.Y.Z.plugin   # release copy
    secure_X.Y.Z.md            # archived security report for this version
    CHANGELOG.md               # changelog (from user message or diff)
```

## Tools (only in `.tools/`)

- `.tools/pluggy_analyze.ps1` — calls the Pluggy API to generate `secure_*.md`. Requires `PLUGGY_SESSION` and `PLUGGY_CSRF` env vars.

## Code Quality (the only mandatory check before commit)

```powershell
ruff check PluginName/plugin_name.plugin
```

Ruff runs on the `.plugin` file directly (it's Python with another extension).

If Ruff complains about `# pyright: ignore` or SDK imports (`ui.settings`, `android_utils`, `base_plugin`, etc.), suppress those **specific lines** with `# noqa`, not the whole file.

## Pluggy — Only on Release

Do **not** run Pluggy during ordinary development (code edits, bugfixes, drafts, `__version__` bumps in catalog). Uploads land in **their database** — an unfinished version is not wanted there.

| Situation | Pluggy |
|-----------|--------|
| Development, iterations, "fix this hook" | **No** — only local Security Review if needed |
| Explicit **release** (triggers below) | **Yes** — once on the final `.plugin` in `releases/vX.Y.Z/` |

## External Publications — Only via git

**Forbidden**: publishing code/`.plugin` to external hosts and gist services (`gh gist create`, `gh gist edit`, `0x0.st`, `file.io`, `tmpfiles.org`, `catbox.moe`, `litterbox`, etc.) — not in drafts, not "to send as a file", not when sending to Telegram. Reasons:
- GitHub gists sync to the GitHub Profile and pollute account history
- third-party hosts = unmanageable plugin copies outside git
- the user/agent takes the file from the repo or from a sent local file

**Allowed**:
- commit `.plugin` to the repo (`git push` to `main`/branch)
- send a **local** file via MCP `telegram-notifier` (`send_telegram_document`)
- use a raw link **from the repo** (`raw.githubusercontent.com/.../main/...`) — only after the file is already in git

## "Оформить релиз" Triggers

Any one of these triggers the full release flow **without asking for clarification**:
- attached `.plugin` + words: *релиз*, *оформить релиз*, *выпустить*, *publish*, *release*
- several `.plugin` files of different versions + the author's text (changelog)
- "сделай релиз для @Plugin/file.plugin"

### Full release flow

1. Read `PluginFolder/docs.md`.
2. From the `.plugin`, take `__version__`, `__id__`, `__name__`.
3. Determine the plugin folder (by file path or by `__id__` in the `docs.md` catalog).
4. `releases/vX.Y.Z/{id}_vX.Y.Z.plugin` — copy of the release file.
5. If this is the **latest** version — update `{id}.plugin` in the plugin folder root.
6. `releases/vX.Y.Z/CHANGELOG.md` — from the user's message or a diff with the previous version.
7. Audit **only here**: `.\.tools\pluggy_analyze.ps1` → `secure_X.Y.Z.md` (not earlier). Run Security Review + "Дополнительный анализ (репозиторий)".
8. Update `PluginFolder/README.md`, `PluginFolder/docs.md`, root `README.md`, root `docs.md` (version, risk, links).
9. Delete drafts like `name-X.Y.Z.plugin` from the plugin folder root (they live only in `releases/`).

For multiple versions at once: separate `releases/` folder per version; in catalogs, show the **maximum** version.

## Before Any Edit

1. **`PluginFolder/docs.md`** — required reading.
2. If needed — the plugin's `README.md` and the root `docs.md`.

## Documentation Split

| File | Audience |
|------|----------|
| `PluginFolder/README.md` | Users |
| `PluginFolder/docs.md` | Developers |
| `docs.md` (root) | Common SDK, build, catalog |

## What to Update (in the same task)

| Change | Where to edit |
|--------|---------------|
| Plugin folder, `.plugin` name | `docs.md` — metadata, files; `README.md` — "Download" link |
| New/deleted plugin | root `README.md`, root `docs.md`, `PluginFolder/docs.md` + `README.md` |
| Version, path in `releases/` | `docs.md` (root + plugin) — **only on release publication** |
| Hooks, architecture, settings keys | `PluginFolder/docs.md` |
| UX, how to use | `PluginFolder/README.md` |
| Raw download link | plugin's `README.md` |

Do **not** complete the task until documentation reflects current paths and names.

## Release vs Draft

- Do **not** create `releases/vX.Y.Z/` and do **not** bump the version in `docs.md` / root `README.md` on every code iteration.
- `releases/` and the catalog version bump happen **once**, when the release is ready to go to `main`.
- Before pushing a release: `.plugin`, `README.md`, `docs.md`, `__version__` in the plugin file, and Ruff checks passing are enough.

## Security Reports

Pluggy — **only when publishing a release** to `releases/vX.Y.Z/`. During development, do not send it — the version lands in the Pluggy DB.

After release, if no report exists:
- `PluginFolder/secure.md` — current version
- `PluginFolder/releases/vX.Y.Z/secure_X.Y.Z.md` — version archive

Generation: `.\.tools\pluggy_analyze.ps1` (Pluggy API) or **[Pluggy Bot](https://t.me/pluggy_robot)**. The agent **never fakes** reports — only via API/bot.

## Pre-Completion Checklist

```
[ ] PluginFolder/README.md — download, usage, risks
[ ] PluginFolder/docs.md — hooks, settings, architecture
[ ] README.md (root) — table and plugin section
[ ] docs.md (root) — version catalog
[ ] Reminder about secure.md / secure_*.md
[ ] secure via .tools/pluggy_analyze.ps1 — only on release, not every edit
```

## Examples

- Renamed `foo.plugin` → `bar.plugin`: update `docs.md` and the plugin's `README.md`, the raw URL.
- Added `NewPlugin/`: create `README.md` + `docs.md`, rows in root `README.md` and `docs.md`, remind about `secure.md`.
