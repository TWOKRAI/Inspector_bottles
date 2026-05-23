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
