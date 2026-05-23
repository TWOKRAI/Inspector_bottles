# BOOTSTRAP — Full setup guide

The fast path is `claude-kit new` (see [README.md](README.md)). This document covers what runs under the hood, system prerequisites, and manual install when the CLI can't be used.

> **TL;DR.** Install `uv` + `git` once on the machine. Then `claude-kit new <target>` for every new project.

---

## Part 1. System prerequisites (once per machine)

### macOS

```bash
# Required
brew install uv git

# Recommended (for full toolchain)
brew install ollama node make
brew install graphviz                   # for diagram generation (pyreverse/pydeps)

# Optional MCP servers
brew install sentrux/tap/sentrux        # architecture analysis
ollama pull qwen3-embedding:8b          # for qex semantic search (4096-dim)
```

### Linux

```bash
# Required
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install -y git

# Recommended
curl -fsSL https://ollama.com/install.sh | sh
sudo apt install -y nodejs make graphviz
```

### Windows

```powershell
winget install astral-sh.uv
winget install Git.Git
winget install Ollama.Ollama
winget install OpenJS.NodeJS.LTS
winget install GnuWin32.Make
winget install Graphviz
```

After Graphviz install on Windows: ensure `C:\Program Files\Graphviz\bin` is on PATH. Verify with `dot -V`.

---

## Part 2a. Updating an existing project's `.claude/` (`claude-kit upgrade`)

For a project that already has its own `pyproject.toml`, `Makefile`, `src/`,
`tests/` — when you only want a newer `.claude/` (e.g. after the seed grew
new agents, hooks, or MCP modules):

```bash
claude-kit upgrade ~/Project_code/existing_app --dry-run     # preview
claude-kit upgrade ~/Project_code/existing_app --apply       # really update
```

What `claude-kit upgrade` does:

- Creates a `tar.gz` backup of the current `.claude/` (in `$TMPDIR`).
- Stashes per-project artifacts: `memory/`, `modes/_stack.md`,
  `commit-layers.txt`, `settings.local.json`, `.seed-answers.yml`.
- Replaces `.claude/` with the bundled template (only the components
  recorded in `.seed-answers.yml`, or heuristic detection for older seeds).
- Restores stashed artifacts.
- Skips ALL Python bootstrap: no `pyproject.toml` rewrite, no `src/`
  skeleton, no `uv sync`, no `git init`, no first commit. Your project's
  source tree is left exactly as it was.

For projects bootstrapped before v0.2 (no `.seed-answers.yml`): run
`claude-kit upgrade --reseed-answers --apply` once to regenerate the
answers file from a heuristic.

---

## Part 2. Per-project setup (the easy path)

```bash
claude-kit new ~/Project_code/my_app \
  --name "My App" \
  --description "What it does"
cd ~/Project_code/my_app
make gate                               # should be green
```

What `claude-kit new` does, step by step:

1. **Copies bundled template** into `target/.claude/` (filters seed-only artifacts via `manifest.yaml::seed_excludes`)
2. **Instantiates templates** with `{{PACKAGE}}`, `{{PROJECT_NAME}}`, etc.:
   - `pyproject.toml` ← `templates/pyproject.template.toml`
   - `Makefile` ← `templates/Makefile.template`
   - `.pre-commit-config.yaml` ← `templates/pre-commit-config.template.yaml`
   - `CLAUDE.md` ← `templates/claude-md.template.md`
   - `.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`, `README.md`
3. **Creates skeleton**: `src/<package>/__init__.py`, `tests/test_smoke.py`, empty `scripts/`, `docs/`, `plans/`
4. **`uv sync --group dev`** — installs ruff, pyright, pytest, pre-commit into `.venv/`
5. **`pre-commit install`** for commit stage and `--hook-type pre-push` for pyright
6. **`pre-commit run --all-files`** in autofix mode (so first commit lands clean)
7. **`git init -b main`** + first commit

If any step fails, the script prints a warning and continues. Fix the failed step manually and re-run only that part.

---

## Part 3. Per-project setup (the manual path)

If you can't use `claude-kit new` (no Python, or you want to understand each step):

```bash
cd ~/Project_code/my_app

# 1. Copy bundled template manually (or `claude-kit init --mode template` does it)
python -c "from claude_kit.core.template_source import bundled_template_root; \
  import shutil, pathlib; \
  src=next(bundled_template_root().__enter__().iterdir()) and bundled_template_root().__enter__(); \
  shutil.copytree(src, '.claude')"
find .claude -name .DS_Store -delete

# 2. Copy + edit templates manually
cp .claude/templates/pyproject.template.toml ./pyproject.toml
cp .claude/templates/Makefile.template ./Makefile
cp .claude/templates/pre-commit-config.template.yaml ./.pre-commit-config.yaml
cp .claude/templates/gitignore.template ./.gitignore
cp .claude/templates/gitattributes.template ./.gitattributes
cp .claude/templates/editorconfig.template ./.editorconfig
cp .claude/templates/env.example.template ./.env.example
cp .claude/templates/claude-md.template.md ./CLAUDE.md
# Replace {{PACKAGE}}, {{PROJECT_NAME}}, {{DESCRIPTION}}, {{AUTHOR}} by hand

# 3. Create skeleton
mkdir -p src/my_app tests scripts docs plans
touch src/my_app/__init__.py tests/__init__.py

# 4. Install
uv sync --group dev
uv run pre-commit install
uv run pre-commit install --hook-type pre-push

# 5. Git init
git init -b main
git add . && git commit -m "Initial commit"
```

---

## Part 4. MCP servers (optional)

The MCP infrastructure is described in [`mcp/README.md`](mcp/README.md). To wire it up:

```bash
# 1. .mcp.json is generated automatically by `claude-kit new` from mcp_servers: blocks
#    in manifest.yaml. To add a component to an existing project: `claude-kit add <component>`

# 2. context7 (once per machine, user-level)
npx -y ctx7 setup --claude

# 3. Restart Claude Code, then verify
> /mcp        # qex, sentrux, context7 should all be green
```

If you don't need semantic search or DSM analysis, skip this part — the project works without MCP.

---

## Part 5. VS Code (optional)

See [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) for the curated list. Minimum:

```bash
code --install-extension charliermarsh.ruff
code --install-extension ms-python.python
code --install-extension ms-pyright.pyright
code --install-extension anthropic.claude-code
```

---

## Part 6. Sanity checks

After bootstrap, in the new project root:

```bash
make help            # lists targets
make check           # ruff lint + pyright
make test            # pytest with coverage
make gate            # check + test combined
uv run ruff --version
uv run pyright --version
git log --oneline    # one commit "Initial commit: bootstrap ..."
```

### Test-drive — one command to check everything

After the standard checks above, run `/doctor` (slash-command) or directly:

```bash
bash .claude/scripts/doctor.sh
```

This single command verifies all layers of the Claude-Kit installation:
- MCP servers (qex / Ollama / sentrux / context7 + optional from `.mcp.json`)
- Settings.json validity + critical hooks registered
- Agents lint (frontmatter, model, tools whitelist)
- Routing consistency (agents' `mcp:server:tool` ↔ `mcp/ROUTING.md`)
- Indexes freshness (qex age, sentrux scan)
- Hooks executable bit
- Plans integrity (no orphan multi-phase folders)

Use after bootstrap (initial check) and periodically (drift check after weeks of work).

Output shows `[OK]` / `[WARN]` / `[FAIL]` per layer + final verdict. Exit code: `0` healthy, `1` failures, `2` failures + warnings.

All green → ready to develop.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uv: command not found` | `brew install uv` (mac) / `curl -LsSf https://astral.sh/uv/install.sh \| sh` (Linux) |
| `pre-commit install` fails | `uv add --group dev pre-commit` then re-run |
| `make: command not found` (Windows) | Install `GnuWin32.Make` or call commands directly: `uv run ruff check .` |
| Pyright complains about `.claude/` | Should not — it's in `[tool.pyright].exclude`. If it does, check `pyproject.toml` |
| First commit fails after autofix | `cd <project> && git add . && git commit -m "Initial commit"` manually |
| `claude-kit: command not found` | `uv tool install claude-kit` или `pip install claude-kit` |
| Bootstrap stops at `uv sync` with network error | Network/DNS issue. Re-run `claude-kit new` with `--no-install`, then `uv sync` manually when online |

---

## Optional features (opt-in)

These are available in the seed but not active by default. Activate when you need them.

### A. Read-only path protection

Hook `protect-readonly.sh` is **wired into `settings.json` and active**, but does nothing until you create `.claude/readonly-paths`. To enable:

```bash
cp .claude/templates/readonly-paths.template .claude/readonly-paths
$EDITOR .claude/readonly-paths    # uncomment patterns that apply
```

Example use cases: protect `data/raw/`, `data/corpus.db`, applied DB migrations, vendored code.

After saving, any Claude `Edit`/`Write` whose path matches a pattern is blocked with exit 2.

### B. Daily session log (active by default)

Stop-hook `session-end-daily-log.sh` writes `git status` + diff stat into `docs/sessions/YYYY-MM-DD.md` when a session ends. Pairs with the `/wrap-up` command (semantic summary). **Active by default** since the permissions-hardening release — the mechanical git-state capture is cheap (one `git status` + one `git diff --shortstat`) and ensures every session leaves a paper trail even if `/wrap-up` is skipped.

To **disable**, remove the `Stop` block from `.claude/settings.json` (or point `SESSIONS_DIR` env var to a throwaway path).

Customization via env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SESSIONS_DIR` | `docs/sessions` | Where daily logs live |
| `PATH_FILTER` | (none) | Restrict to path prefix, e.g. `src/` |

### C. Project anti-patterns log (`EXAMPLES.md`)

When you find yourself correcting the agent on the same kind of mistake twice, capture it in a project `EXAMPLES.md`:

```bash
cp .claude/templates/examples.template.md EXAMPLES.md
$EDITOR EXAMPLES.md   # add concrete ❌/✅ examples
```

Reference it from your root `CLAUDE.md` so future Claude sessions read it: `Project-specific anti-patterns → [EXAMPLES.md](EXAMPLES.md)`.

### D. Project skills

The seed ships four hand-picked skills (project-local, from [mattpocock/skills](https://github.com/mattpocock/skills), MIT):

| Skill | Trigger | What it does |
|-------|---------|--------------|
| `/caveman` | "caveman mode", "be brief" | Ultra-compressed responses, ~75% fewer tokens |
| `/grill-me` | "grill me", design review | Relentless interview through every branch of a plan |
| `/zoom-out` | manual only | Step up an abstraction layer; map modules + callers |
| `/prototype` | "prototype this", "try a few designs" | Throwaway terminal/UI prototype to validate a design |

Full descriptions: `.claude/skills/README.md`. They live under `.claude/skills/` (project-local) and travel with the seed.

**graphify** is separate — it's a CLI-installed knowledge-graph tool, registered user-global. See [`mcp/graphify/SETUP_GUIDE.md`](mcp/graphify/SETUP_GUIDE.md).

If you find a workflow that you trigger by hand ≥3 times, consider turning it into a new skill. See `.claude/skills/README.md` for structure.

### E. Plan-driven workflow + commit validator (active by default)

`claude-kit new` installs the full plan ↔ branch ↔ commit chain:

| Artifact | Path | Purpose |
|---|---|---|
| Plan template | `.claude/templates/PLAN.template.md` | starting point for `/plan` |
| Plans dir | `plans/` (+ `plans/README.md`) | one file per task; multi-phase via subfolder |
| Commit guide | `.claude/COMMIT_GUIDE.md` | full format spec |
| Layer config | `.claude/commit-layers.txt` | whitelist for `Layer:` trailer — **edit to match your architecture** |
| Validator | `scripts/validate_commit/validate_commit.py` | parses commit messages |
| Hook | `.git/hooks/commit-msg` (installed by `claude-kit new`) | rejects commits without `Why:` / `Layer:` |
| Session journal | `docs/sessions/YYYY-MM-DD.md` (+ `README.md`) | written by `/wrap-up` |

**Workflow:**
```
/plan <task>            # Manager → plans/<slug>.md + branch <type>/<slug>
/implement Task X.Y     # Developer → code + commit with Refs: plans/<slug>.md
/ship                   # verify Refs trailers + close plan when all [DONE]
/wrap-up                # session log → docs/sessions/<today>.md
/plan-status            # progress bar for current branch's plan
```

**First customization:** open `.claude/commit-layers.txt` and replace the generic defaults (`app/lib/tests/...`) with your project's actual architecture layers (e.g. `api/domain/adapters` for hexagonal, or `framework/services/plugins` for layered).

**To disable** (rare): `rm .git/hooks/commit-msg`. The plan/branch commands still work, just without enforcement on commit format.

### G. Protected branches (active by default, configurable)

Hook `protect-branch.sh` is **wired in and active**. It blocks `git commit` on branches matching a protected pattern, catching the failure mode where `/pipeline` or `/implement` forgets `git checkout -b feat/<slug>` and commits straight to `main`.

**Default protected set** (when no config file present):
`main`, `master`, `develop`, `dev`, `release/.*`, `prod`, `production`.

**To customize** (add `staging`, `qa/.*`, allow hotfix branches, etc.):
```bash
cp .claude/templates/protected-branches.template .claude/protected-branches
$EDITOR .claude/protected-branches   # one branch name or regex per line; ^/$ added automatically
```

**To disable for one repo** (rare — usually you want this protection): create an empty `.claude/protected-branches` file. The hook reads it, sees no patterns, exits 0.

**To override per-machine** (e.g. on a sandbox where committing to `main` is intentional): place the empty file in `~/.claude/` or set the project's `settings.local.json` to remove the hook entry.

### H. Incremental typecheck on Edit/Write (opt-in)

Hook `typecheck-changed.sh` runs `pyright --outputjson` on the single Python file you just edited, prints up to 5 errors to stderr (non-blocking, info-only). Useful on large projects where you don't want to wait for `make gate` to discover type errors.

**Default: OFF.** Cold-start pyright takes 3-10s; on a 70k LoC project that's painful on every Edit. Once warm, incremental runs settle to ~500ms-2s.

**To enable per-shell:**
```bash
export CLAUDE_TYPECHECK_ON_EDIT=1
```

**To enable per-project** (recommended for big codebases): add the env block to `.claude/settings.local.json`:
```json
{ "env": { "CLAUDE_TYPECHECK_ON_EDIT": "1" } }
```

The hook **never** blocks — Edit succeeds, errors are advisory. Pyright is resolved from `.venv/Scripts/pyright.exe` / `.venv/bin/pyright` first, then PATH; if missing, the hook silently no-ops.

### I. Settings invariant linter (active in CI, manual otherwise)

Script `scripts/lint_settings.py` + slash-command `/lint-settings` validate that `.claude/settings.json` still holds the hardening invariants from the seed:

- Required `deny` patterns (`--no-verify`, `git push --force`, `git reset --hard`, `sudo`, `chmod 777`, `mkfs`, `dd if=`, ...) — exit 1 if missing.
- Required `Write`/`Edit` secrets protection (`**/.env`, `**/*.pem`, `**/*.key`, `**/id_rsa`, `**/id_ed25519`) — exit 1 if missing.
- Forbidden patterns NOT in `allow` (`uv add *`, `pip install *`, `npx *`, `cp *`, `chmod *`, `git merge *`, ...) — exit 1 if present.
- Required hooks wired in (`validate-safe-command`, `protect-readonly`, `protect-branch`, `autoformat-python`, `check-imports`, `restore-context`, `session-health-check`, `session-end-daily-log`) — warning if missing.

**Manual:** `python scripts/lint_settings.py` or `/lint-settings` from inside Claude Code.

**CI:** wire into `.github/workflows/ci.yml`:
```yaml
- name: Validate Claude settings invariants
  run: python scripts/lint_settings.py --strict
```

Closes the "concentration risk" of `settings.json` — anyone who locally weakens the permissions will trip the CI gate.

### F. Long-term memory (active by default)

`claude-kit new` creates `.claude/memory/MEMORY.md` automatically. Path is overridden in `.claude/CLAUDE.md` → "Memory (OVERRIDE)" so the agent writes here (project-local, git-tracked) instead of the native `~/.claude/projects/<project>/memory/` (machine-local, not portable).

Commands:

| Command | Purpose |
|---------|---------|
| `/memory:status` | List entries by type (user/feedback/project/reference) |
| `/memory:search <query>` | Search over `.claude/memory/` + `docs/sessions/` (grep + optional qex) |
| `/memory:init` | One-shot init for a project that didn't go through `claude-kit new` |

The agent writes entries automatically per the "auto memory" rules (in the system prompt). You don't need to manage MEMORY.md manually — just review it occasionally.

Why not an external plugin (`claude-mem`, `mem0`, `basic-memory`, `letta`): they bring a parallel JS/daemon stack (Node/Bun/Chroma/HTTP worker) or an opaque SQLite+vector store. The chosen approach is **local-first, minimum dependencies, Markdown under git** — anything more is opt-in per project.

Memory is **per-project**: `claude-kit sync-back` excludes `memory/` so individual entries stay with the project.

---

## Related docs

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Quickstart + seed structure |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each seed version |
| [STACK.md](STACK.md) | Every tool with rationale |
| [VSCODE_EXTENSIONS.md](VSCODE_EXTENSIONS.md) | VS Code extension list |
| [CLAUDE-SETUP.md](CLAUDE-SETUP.md) | Quick orientation in `.claude/` |
| [templates/README.md](templates/README.md) | How `claude-kit new` consumes templates |
| [mcp/README.md](mcp/README.md) | MCP servers config |
| [modes/_stack.md](modes/_stack.md) | Per-project customization |
