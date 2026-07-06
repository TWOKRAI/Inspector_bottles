# playwright — Setup Guide

Cross-platform install + MCP wire-up + smoke test. ~5-10 minutes including Chromium download.

> Two options: **Microsoft official** (recommended, stable) or **community fork** (more flexibility).
> Defer to upstream if instructions diverge.

---

## Prerequisites

- **Node.js 18+** on PATH. Verify: `node --version`.
- ~500 MB disk for Chromium browser (more if Firefox/WebKit added).
- For headless mode: no display server needed (works on CI).
- For headed mode (visible browser): display server required.

> If your machine has no Node yet:
> - **macOS:** `brew install node`
> - **Windows:** `winget install OpenJS.NodeJS.LTS`
> - **Linux:** distro package or `nvm install --lts`

---

## 1. Install — pick one path

### Option A: Microsoft official (recommended)

```bash
npm install -g @playwright/mcp
npx playwright install chromium    # download browser binary
```

Verify:

```bash
npx @playwright/mcp --version
```

### Option B: Community fork (`executeautomation/playwright-mcp-server`)

More features, multi-browser support out of the box:

```bash
npm install -g @executeautomation/playwright-mcp-server
npx playwright install chromium firefox webkit    # all three
```

### Option C: Zero-install (npx)

Skip global install; MCP snippet uses `npx -y`. Slower first run, no system footprint:

```json
{
  "playwright": {
    "command": "npx",
    "args": ["-y", "@playwright/mcp@latest"]
  }
}
```

---

## 2. Wire the MCP server

Append the snippet from [`templates/mcp-config.json.snippet`](templates/mcp-config.json.snippet)
to project's `.mcp.json` under `mcpServers`.

**Microsoft official:**
```json
{
  "playwright": {
    "command": "npx",
    "args": ["-y", "@playwright/mcp@latest"]
  }
}
```

**Community fork:**
```json
{
  "playwright": {
    "command": "npx",
    "args": ["-y", "@executeautomation/playwright-mcp-server"]
  }
}
```

---

## 3. Restart Claude Code and smoke-test

1. Reload Claude Code: `Cmd/Ctrl + Shift + P` → `Developer: Reload Window` (or restart terminal).
2. `/mcp` should show `playwright` as connected.
3. Run the 5-question smoke test:

   ```
   1. Navigate to https://example.com and screenshot the page.
   2. Open https://example.com, capture all console messages.
   3. Click the first link on https://example.com and verify the new URL.
   4. Fill a search form on https://duckduckgo.com with "playwright mcp" and submit.
   5. List all network requests made when loading https://example.com.
   ```

   If the agent goes through `browser_navigate` / `browser_screenshot` / `browser_click` —
   wire-up works. If it falls back to `curl` — see § Tool routing in [README.md](README.md).

---

## 4. Verify-done integration (web projects)

If `verify-done` skill is active in this project, it will now use playwright tools when the
golden path is browser-based:

```
**Affected entry point exercised:**
- browser_navigate https://localhost:8000/dashboard
- browser_screenshot → screenshots/dashboard-2026-05-22.png
- Verified: title contains "Dashboard", no console errors
```

No additional config — the skill checks if playwright is in `.mcp.json` and uses it conditionally.

---

## 5. Headless vs headed mode

By default playwright runs **headless** (no visible browser). For debugging:

```bash
# In one-off invocation
PLAYWRIGHT_HEADLESS=false npx @playwright/mcp@latest
```

Or pass `headless: false` to `browser_navigate` if upstream supports per-call override.
Useful when:
- E2E test fails and you want to see what happened visually.
- Multi-step interaction needs human inspection.

---

## Troubleshooting

### `/mcp` shows playwright as failed

```bash
# Is the package installed?
npm list -g @playwright/mcp

# Is Node accessible from Claude Code's PATH?
node --version
npx --version
```

If the agent's shell doesn't see `npx` — add Node bin to PATH in Claude Code env.

### "Browser executable not found"

Browser binaries weren't downloaded:

```bash
npx playwright install chromium
# Or all browsers:
npx playwright install
```

Browsers cached in `~/.cache/ms-playwright/` (Linux/macOS) or `%LOCALAPPDATA%\ms-playwright\` (Windows).

### Headless mode hangs on CI

Some CI environments (Docker without `--ipc=host`) need:

```bash
npx playwright install --with-deps chromium
```

This installs Linux system libs (libgbm, libdrm, etc.) needed by headless Chromium.

### Screenshots are blank / dark

Page hadn't finished loading before `browser_screenshot`. Add a wait:
- `browser_evaluate` to wait for a specific element.
- Use `browser_navigate` with a wait condition (`networkidle` or specific selector).

---

## Uninstall

```bash
# Global
npm uninstall -g @playwright/mcp

# Browser binaries (if you want disk back)
npx playwright uninstall    # or: rm -rf ~/.cache/ms-playwright/
```

Remove the `playwright` block from `.mcp.json` and restart Claude Code.

---

## Security notes

- playwright drives a **real browser** — it can navigate to any URL, run arbitrary JS in page
  context, capture screenshots. Treat any URL the agent navigates to as untrusted (do not
  put credentials in URLs visible to the agent).
- For local development on `localhost` — safe.
- For navigation to external URLs — be aware that the agent's actions leave a trace
  (network requests from your IP, possibly cookies from previous sessions if browser state
  is reused).
- Headless mode in CI is generally safe; headed mode requires display server access.
