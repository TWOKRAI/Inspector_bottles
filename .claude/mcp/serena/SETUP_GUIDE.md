# Serena — Setup Guide

Cross-platform install + per-language LSP setup. Plan for 20-30 minutes the first time.

> Source: <https://github.com/oraios/serena>. **Status: experimental** in this seed — see "Known Issues" in [README.md](README.md) before adopting for production refactoring.

---

## Prerequisites

- Python **3.10+** on PATH.
- `uv` installed.
- Project has a recognizable manifest: `pyproject.toml` (Python), `tsconfig.json` (TS/JS), `Cargo.toml` (Rust), `go.mod` (Go), etc. **Without one, Serena cannot resolve imports** and references will be incomplete.
- The Language Server for your project's primary language. See "Step 2" below.

---

## 1. Install Serena

### macOS / Linux

```bash
uv tool install serena-agent
serena --version
```

### Windows (PowerShell, Git Bash, or CMD)

```powershell
uv tool install serena-agent
serena --version
```

> **Known issue on Windows:** if your project path contains spaces or Cyrillic characters, Serena may fail to start. Move the project to an ASCII-only path (e.g. `D:\projects\my_app`).

---

## 2. Install the Language Server for your project

Serena does not bundle LSPs. Install the one(s) for languages you use.

### Python — Pyright (recommended)

```bash
# Cross-platform via npm (Pyright is Node-based)
npm install -g pyright
pyright --version
```

If you don't have Node, install via uv:
```bash
uv tool install pyright
```

### TypeScript / JavaScript — typescript-language-server

```bash
npm install -g typescript typescript-language-server
```

### Rust — rust-analyzer

```bash
# macOS / Linux
rustup component add rust-analyzer

# Windows (PowerShell)
rustup component add rust-analyzer
```

### Go — gopls

```bash
go install golang.org/x/tools/gopls@latest
```

### Java — JDT Language Server (jdtls)

Heavyweight install — see Eclipse JDT.LS docs. Consider whether Serena's value matches the setup cost.

### C / C++ — clangd

```bash
# macOS
brew install llvm

# Linux (Debian/Ubuntu)
sudo apt install clangd

# Windows
winget install LLVM.LLVM
```

---

## 3. Register Serena in `.mcp.json`

Copy the snippet from [templates/mcp-config.json.snippet](templates/mcp-config.json.snippet) into your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "serena": {
      "command": "uvx",
      "args": [
        "--from", "serena-agent",
        "serena-mcp-server",
        "--context", "claude-code",
        "--project", "."
      ]
    }
  }
}
```

Portable across Windows / macOS / Linux. `--project "."` resolves to the directory Claude Code was launched from.

---

## 4. Smoke test (do this before relying on Serena)

Restart Claude Code, then in conversation:

```
> /mcp
```

`serena` should be green. If red, see Troubleshooting.

Then test on a known function in your codebase:

```
> Using Serena, find all references to the function `<pick a function you know is called from 2+ places>`.
> Now show me the definition.
```

Expected: Serena lists exact file:line for each reference. If results are incomplete or wrong, your LSP is misconfigured — go back to step 2.

---

## 5. Activate in agent routing

Once smoke test passes, add this to your project's `CLAUDE.md`:

```markdown
## Tool routing (this project)

- Exact symbol queries (refs / definition / rename / move) → **Serena**
- Semantic queries / fuzzy intent → **qex**
- Architecture overview → **graphify**
- Fallback (Serena down / language unsupported) → qex + Grep
```

---

## Troubleshooting

### `serena: command not found`

- `uv tool install` puts binaries in `~/.local/bin`. Ensure it's on PATH:

  ```bash
  # macOS / Linux
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

  # Windows (PowerShell, persistent)
  [Environment]::SetEnvironmentVariable("Path", "$env:Path;$env:USERPROFILE\.local\bin", "User")
  ```

### `Serena starts but returns no references`

- LSP didn't resolve imports — your project is missing a manifest. Verify:
  ```bash
  # Python
  ls pyproject.toml

  # TS/JS
  ls tsconfig.json package.json
  ```
- LSP version mismatch — update: `npm update -g pyright` (or equivalent).

### `First query takes 60+ seconds`

- Pyright is warming up (parsing the venv + all deps). Subsequent queries are fast. Pre-warm with a no-op query at session start.

### `Crashes on Windows with "path contains invalid characters"`

- Known issue. Workaround: move project to an ASCII-only path. Example:
  ```powershell
  Move-Item "C:\Users\<user>\Документы\my_app" "D:\projects\my_app"
  ```

### `Crashes / hangs on rust-analyzer`

- rust-analyzer is RAM-hungry (1-2 GB on medium projects). Check `Get-Process rust-analyzer` (Windows) or `ps aux | grep rust-analyzer` (Unix). If swapping, exclude rust from Serena and use Cargo's built-in refs.

### Want to disable temporarily

Comment out the `serena` block in `.mcp.json` and restart Claude Code. Easier than `uv tool uninstall`.

---

## Uninstall

```bash
uv tool uninstall serena-agent
```

Optionally uninstall LSPs:
- `npm uninstall -g pyright typescript-language-server`
- `rustup component remove rust-analyzer`
- `go clean -i golang.org/x/tools/gopls`

Remove the `serena` block from `.mcp.json` and restart Claude Code.

---

## Security notes

- Serena reads source files only via LSP — no execution of project code.
- The LSP itself parses your code. Trust your LSP vendor (Pyright is from Microsoft; rust-analyzer is part of Rust project — both trustworthy).
- Refactoring tools (rename, move) **modify files**. Verify proposed changes before accepting — Serena will edit across many files in one operation.
