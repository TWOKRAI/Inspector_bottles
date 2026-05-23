# playwright — browser automation + UI verification

Optional MCP module. Where qt-mcp covers PyQt5/PySide6 runtime inspection, **playwright** covers
**browser-based UI** (web apps, SPAs, static sites). Browser navigate, click, fill, screenshot,
console-log capture — all via MCP tools the agent can call directly.

> Upstream: <https://github.com/microsoft/playwright-mcp> (Microsoft official)
> Alternative: <https://github.com/executeautomation/playwright-mcp-server> (community fork with more browsers)
> **License:** Apache 2.0 (Microsoft) · **Status as of 2026-05:** stable, official Microsoft package, multi-browser

## When to enable

✅ **Enable when:**
- Project is a **web application** (FastAPI/Django/Flask/Next.js/Vue/Svelte/etc.) with a frontend.
- You want the agent to **verify changes visually** — not just "tests pass", but "the page actually renders".
- `verify-done` skill should screenshot the golden path before declaring "done".
- E2E test debugging — let the agent step through a failing scenario in a real browser.

❌ **Skip when:**
- Backend-only project (API, CLI, library) — no UI to verify.
- GUI is PyQt/PySide → use `qt-mcp` instead.
- TUI / terminal-only UI — playwright doesn't help.
- No-display CI runners and you don't need browser automation locally.

## How it differs from the rest of the seed

| Task | Best tool | Why |
|------|-----------|-----|
| "Navigate to /dashboard and screenshot" | **playwright** | Real browser, real rendering |
| "Fill login form, submit, verify next page" | **playwright** | Multi-step browser interaction |
| "Check API returns 200 on /api/users" | `curl` / Bash | No browser needed |
| "Find component code that renders Dashboard" | **qex** or **codegraph** | Code search, not runtime |
| "Inspect PyQt widget state at runtime" | **qt-mcp** | Different stack (Qt, not browser) |
| "Browser e2e test fails — why?" | **playwright** | Step through in interactive mode |

**Bottom line:** playwright fills the **web-UI verification** gap that no other MCP in this seed
covers. It is the natural companion to the `verify-done` skill for web projects.

## Supported browsers

- **Chromium** (default — fastest install, bundled).
- **Firefox** (optional install).
- **WebKit** (optional install — Safari equivalent).

Cross-browser testing is opt-in; default Chromium covers 95% of UI-verify cases.

## MCP tools exposed (key ones)

| Tool | Purpose |
|------|---------|
| `browser_navigate` | Open URL in a browser tab |
| `browser_screenshot` | PNG of current page (full page or viewport) |
| `browser_click` | Click a selector or element |
| `browser_fill` | Fill an input/textarea |
| `browser_press_key` | Keyboard input (Tab, Enter, etc.) |
| `browser_evaluate` | Run JS in page context, return result |
| `browser_console_logs` | Capture console.log / errors from the page |
| `browser_network_requests` | List of HTTP requests made by the page |
| `browser_close` | Close the tab / session |

Exact tool surface depends on the version — see upstream README for the current list.

## Storage and footprint

- Browser binaries: ~300-500 MB (Chromium alone), more if Firefox/WebKit added.
- No project-local index — playwright is **stateless** (each `browser_navigate` opens fresh).
- Screenshots are returned as base64 or saved to a path you pass in.

## Tool routing snippet (paste into project `CLAUDE.md`)

> When playwright is enabled in this project:
> - **Browser-based UI verify / screenshot / interact** → **playwright**
> - **PyQt/PySide GUI runtime** → **qt-mcp** (different stack)
> - **API testing (HTTP, no browser)** → `curl` / Bash
> - **Code search ("where is component X")** → **qex** / **codegraph**
> - `verify-done` skill on web projects → use `browser_navigate` + `browser_screenshot` on the golden-path URL.

## Conflicts / overlap

- **No overlap** with qex / sentrux / graphify / codegraph / serena / ast-grep (different domain — runtime browser vs code analysis).
- **Complements** `verify-done` skill — that skill explicitly references `playwright:browser_navigate` for web projects.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for install (Microsoft package vs community fork), MCP wire-up, and smoke test.
