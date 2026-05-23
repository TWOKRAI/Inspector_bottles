# qt-mcp — Setup Guide

Cross-platform install + activation. ~10 minutes end-to-end.

> Source: <https://github.com/0xCarbon/qt-mcp>. If upstream instructions diverge from this guide, upstream wins.

---

## Prerequisites

- Python 3.10+ already in your project (`uv` venv recommended).
- Your project depends on **PyQt5** or **PySide6** (`uv add PyQt5` or `uv add PySide6`).
- TCP port `9142` free on `localhost` (qt-mcp probe listens here).

---

## 1. Install qt-mcp

### macOS / Linux

```bash
# Inside the project's venv (recommended):
uv add --group dev qt-mcp

# Or as a global tool:
uv tool install qt-mcp
```

### Windows (Git Bash, PowerShell, or CMD)

```powershell
# Project-scoped (recommended):
uv add --group dev qt-mcp

# Or global:
uv tool install qt-mcp
```

> If `qt-mcp` is not yet published to PyPI when you read this, fall back to:
> `uv add --group dev "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp"`

---

## 2. Wire the probe into your app

Add this line **once, early** in your app's startup (before `app.exec()`):

```python
# main.py
import qt_mcp.probe  # noqa: F401  — starts the JSON-RPC probe on :9142
```

The probe is a no-op if `QT_MCP_DISABLE=1` is set (use this in production builds).

---

## 3. Register the MCP server in `.mcp.json`

Copy the snippet from [templates/mcp-config.json.snippet](templates/mcp-config.json.snippet) into your project's `.mcp.json` (created by `claude-kit new` / `claude-kit add qt-mcp`).

The snippet uses **portable invocation** — no absolute paths to your machine:

```json
{
  "mcpServers": {
    "qt-mcp": {
      "command": "uv",
      "args": ["run", "--", "python", "-m", "qt_mcp.server"],
      "env": {
        "QT_MCP_PROBE_HOST": "127.0.0.1",
        "QT_MCP_PROBE_PORT": "9142"
      }
    }
  }
}
```

Works the same on Windows, macOS, Linux — `uv run` resolves the project venv automatically.

---

## 4. Restart Claude Code and verify

```
> /mcp
```

Expected: `qt-mcp` is listed and green. If red, see Troubleshooting below.

---

## 5. Run your app + use qt-mcp

```bash
# Start the app:
uv run python -m your_package

# In Claude Code, ask:
# "Take a screenshot of the main window"
# "Walk the widget tree and list all QPushButton names"
# "Click the button with text 'Save'"
```

---

## Troubleshooting

### `Connection refused on :9142`

- App not running, or `import qt_mcp.probe` not added to startup. Verify with:
  ```bash
  # macOS / Linux
  lsof -iTCP:9142 -sTCP:LISTEN
  # Windows
  netstat -ano | findstr :9142
  ```

### `qt-mcp tool calls hang`

- Probe is blocked by Qt's event loop. Make sure `import qt_mcp.probe` happens **before** `app.exec()` and **after** `QApplication` is created.
- Heavy synchronous work in event handlers will block the probe — same as any Qt code.

### `Cannot find PyQt5 / PySide6 at runtime`

- qt-mcp's probe auto-detects which binding your app uses. If you have **both** installed, set `QT_API=pyside6` or `QT_API=pyqt5` in the `env` block of `.mcp.json`.

### Windows: probe fails to bind to `127.0.0.1:9142`

- Antivirus / firewall sometimes blocks localhost TCP for ad-hoc Python processes. Allow `python.exe` in the firewall rule, or change port via `QT_MCP_PROBE_PORT=9143`.

### Want to disable in production builds

```bash
QT_MCP_DISABLE=1 python -m your_package
```

---

## Uninstall / disable per project

1. Remove `import qt_mcp.probe` from your app startup.
2. Remove the `qt-mcp` block from `.mcp.json`.
3. `uv remove qt-mcp` (project-scoped) or `uv tool uninstall qt-mcp` (global).
4. Restart Claude Code.

---

## Security notes

- The probe binds to `127.0.0.1` only by default — not reachable from network.
- Property writes / event injection means the agent can **modify app state** at runtime. Don't enable in a production binary that handles user data.
- Consider `readonly: true` mode if upstream offers it (check release notes).
