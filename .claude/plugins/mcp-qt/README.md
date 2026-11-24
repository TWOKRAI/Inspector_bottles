# qt-mcp — runtime inspection for PyQt/PySide GUI apps

Optional MCP module. Activate only in projects that build a PyQt5/PySide6 desktop application.

> Upstream: <https://github.com/0xCarbon/qt-mcp>

## When to enable

✅ **Enable if your project:**
- Builds a desktop GUI on PyQt5 or PySide6
- Needs the agent to inspect a running app: widget tree, properties, QGraphicsScene, VTK/PyVista canvases
- Wants automated UI smoke-tests via Claude (click button, type text, take screenshot)

❌ **Skip if your project:**
- Is backend/CLI only (no Qt)
- Uses Tkinter / Kivy / wxPython / web UI — qt-mcp won't help
- Uses Qt but you already have a mature pytest-qt suite and don't need agent-level inspection

## Architecture

Two-process design:

```
Your PyQt/PySide app
        │
        ▼ (in-process probe — qt_mcp.probe)
  qt-mcp probe    ←──── JSON-RPC over TCP (localhost:9142) ────→  qt-mcp MCP server
  QObject walk                                                    (separate process)
  property R/W                                                         │
  event injection                                                      ▼
                                                              Claude Code (MCP client)
```

- **Probe** (`qt_mcp.probe`) — imported by your app, runs in-process. Walks the QObject tree, reads/writes properties, captures widget screenshots, injects events.
- **MCP server** — separate process. Translates MCP tool calls (`take_screenshot`, `click_widget`, `get_property`) into JSON-RPC requests on `:9142`.
- **MCP client** — Claude Code, connected via `.mcp.json`.

## How it differs from related tools

- **vs `pytest-qt`**: pytest-qt drives Qt from a test script; qt-mcp gives Claude **runtime, interactive** access to a long-running app.
- **vs `qt-pilot`** (<https://github.com/neatobandit0/qt-pilot>): qt-pilot focuses on **headless** Qt testing for CI; qt-mcp is for **inspection of a running app** during development. Pick qt-pilot if you want Claude to drive a Qt test runner; pick qt-mcp if you want Claude to "look at" what your app is doing right now.
- **vs Playwright MCP**: same idea (browser automation) but for desktop Qt instead of web.

## Status

- Maintained, active development as of 2026.
- Reported to work on Windows, macOS, Linux.
- PySide6 is primary target; PyQt5 support — verify with upstream before adopting on a PyQt5-only codebase.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for the platform-specific install steps. Then copy the snippet from [templates/mcp-config.json.snippet](templates/mcp-config.json.snippet) into your project's `.mcp.json`.

## Tool routing

When qt-mcp is active in a project, prefer it over hand-written Qt introspection:

| Task | Tool |
|------|------|
| "Find the button labelled 'Save' and click it" | qt-mcp |
| "What's the current `enabled` state of the OK button?" | qt-mcp |
| "Take a screenshot of the main window" | qt-mcp |
| "Walk the widget tree and find all `QLabel` instances" | qt-mcp |
| Refactoring widget code (rename method, move class) | qex / Serena / Grep (qt-mcp only sees runtime, not source) |
## Launcher options

**Default** (used automatically by `claude-kit add qt-mcp`): see `.claude-plugin/plugin.json` → `mcpServers.qt-mcp`.
In this project the manifest pins the launcher (since 2026-11-22):

```
command: uvx
args: ["--from", "git+https://github.com/0xCarbon/qt-mcp@24303a69d498417dfcec0223bfaa95964f788c17", "--with", "mcp<2", "qt-mcp"]
```

Why: `qt-mcp` is not on the package registry, so plain `uvx qt-mcp` fails with "not found in the package registry";
`mcp<2` is needed because the 0.1.0 server imports `mcp.server.fastmcp`, which `mcp 2.x` removed. The pin lives in the
versioned `plugin.json`; `.mcp.json` is git-ignored and regenerated from the manifest, so a hand edit of `.mcp.json`
does not survive a regeneration. Bump the pinned commit deliberately, in `plugin.json`.

**Probe in the app** (the part that makes the window visible to the server): the probe is installed inside the `gui`
process by `multiprocess_prototype/frontend/qt_mcp_probe.py`, one call from `frontend/app.py:run_gui`. The app's Python
needs `pip install "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp@24303a69d498417dfcec0223bfaa95964f788c17"`.

One pair of env knobs, the same names the `qt_mcp` package and its MCP server read:

| Variable | Meaning |
|----------|---------|
| `QT_MCP_PROBE=1` | install the probe; unset / empty / `0` = off. Any other value (`1:9142`, `true`) is a typo: one warning in the `gui` log, probe not installed |
| `QT_MCP_PORT` | probe port, default 9142 |

A broken `QT_MCP_PORT` (not an integer in 1..65535) or any other failure (package missing, port busy, no
`QApplication`) gives one warning in the `gui` log and no probe; the window keeps running. Exception: an integer
outside 1..65535 while `qt_mcp_probe.pth` is active in the venv: `QApplication()` fails earlier than our code
(`OverflowError` in `qt_mcp.probe._patched_init`), so never set such a port. On success the log line
`qt-mcp probe installed on localhost:<port>` is written at WARNING level on purpose (see Security).
The server reads `QT_MCP_PORT` too: for a non-default port set `QT_MCP_PORT` in the `env` of the server entry in
`.mcp.json` (or in the manifest) as well, otherwise the server looks at 9142 and finds nothing.

**Security (required reading):** the probe has no authentication, reads password fields and listens on 127.0.0.1 only.
Do not enable it with foreign OS users on the machine or with an open untrusted browser (any local process can talk to the
port; a web page reaching it is not excluded, not verified).

**Alternative** (pip-installed): see `templates/mcp-config.json.snippet`.

Switching: edit `.claude-plugin/plugin.json` (the source of truth); `.mcp.json` is regenerated from it.
