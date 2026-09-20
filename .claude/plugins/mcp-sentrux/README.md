# sentrux — architectural health gate

**sentrux** ([github.com/sentrux/sentrux](https://github.com/sentrux/sentrux)) — a structural analyzer for a codebase. A single Rust binary, no runtime dependencies. Computes the import graph, coupling metrics, cycles — and rolls it all into one **quality_signal** (0–10000), convenient to use as a gate before a commit or merge.

In this project sentrux is wired in as an **MCP server** (Claude Code can call it) + 8 project slash commands `/mcp-sentrux:sentrux-*`.

---

## What it gives you

| Pain | How sentrux helps |
|------|----------------------|
| "Everything's tangled, but it's unclear exactly where" | Computes 5 metrics (modularity, acyclicity, depth, equality, redundancy), shows the **bottleneck** — the main cause of the drop |
| "Where are the cycles between modules?" | `dsm` builds a Dependency Structure Matrix and highlights cycles |
| "Did the refactor make things worse?" | `session_start` records a baseline → make changes → `session_end` shows the quality delta |
| "Which modules have no tests?" | `test_gaps` finds uncovered nodes in the graph — prioritizing the ones with many dependencies |
| "`domain/*` must not import `adapters/*` — how do I make CI catch that?" | `.sentrux/rules.toml` + `sentrux check` (exit 0/1, CI-friendly) |
| "Which way is our quality trending — up or down?" | `evolution` shows trends over time |

**sentrux is orthogonal to qex:**

- **qex** answers "*where* is X used" (semantic search).
- **sentrux** answers "*how healthy* is the architecture".

They **do not duplicate** each other. Don't use sentrux for code search, don't use qex to assess coupling.

---

## Starter rule archetypes

`claude-kit new` **automatically** deploys `.sentrux/rules.toml` from the
`rules.src-package.toml` archetype with your package name already filled in — nothing
to fill in by hand, and the project is "green" from the first commit. `max_cycles` and
`no_god_files` are active right away; the `[[boundaries]]` block (architecture boundary)
arrives **commented out** with the package name pre-filled — uncomment it once layer
folders appear (see "Green from day 1" below). Two more archetypes ship in the kit for
a different architecture.

| Archetype | When to pick it | Dependency chain (top to bottom) |
|---------|----------------|-------------------------------------|
| **`rules.src-package.toml`** | Default for the seed skeleton (**deploys itself**): a single `src/<pkg>/` split into subpackages | `cli → services → core → utils` |
| **`rules.layered.toml`** | Classic n-tier: each layer depends only on the one below, infrastructure at the base | `presentation → application → domain → infrastructure` |
| **`rules.hexagonal.toml`** | Ports & adapters / clean / onion: the domain at the center, dependencies point inward | `app → adapters → ports → domain` |

(`→` = "allowed to import". Upward/outward imports are forbidden.)

To switch to a different archetype (pick one line — `src-package` is already deployed
by default):

```bash
cp .claude/plugins/mcp-sentrux/templates/rules.layered.toml   .sentrux/rules.toml
cp .claude/plugins/mcp-sentrux/templates/rules.hexagonal.toml .sentrux/rules.toml
```

> **⚠️ If you copy manually — a mandatory edit, otherwise the rules silently don't work.**
> (The `claude-kit new` auto-deploy fills in the package name itself; manual steps are
> only needed if you copy an archetype by hand.) sentrux matches paths in `[[boundaries]]`
> as **literal directory prefixes** — `*` stands in only for a file name and does **not**
> expand directory segments. So `src/*/core` matches nothing, and a boundary that
> matches nothing **passes silently** (a false sense of protection). After copying:
> 1. replace `your_package` with your package name under `src/` (e.g. `src/acme/core`);
> 2. **remove the `# ` from the `[[boundaries]]` block** — like in the auto-deploy, it
>    arrives commented out (while there are no layer folders yet — an `active` boundary passes silently);
> 3. check that the rules "bite" — add a deliberate upward import, confirm
>    `sentrux check` fails on it, then remove it.
>
> For several packages under `src/`, duplicate the `[[boundaries]]` block per
> package (the paths are literal). A fully commented-out "bare" scaffold with all
> rule types is in [`rules.template.toml`](rules.template.toml).

### Green from day 1

Archetypes are **active, but don't get in the way** at the start:

- `max_cycles = 0` and `no_god_files = true` are active — both are green on clean code
  and catch real problems right away.
- The minimum-metric thresholds (`min_modularity`, `min_redundancy`, etc.) are
  **commented out**: a new/small project legitimately falls short of them even without
  real violations. Uncomment and raise them once the codebase matures.
- The `[[boundaries]]` block (dependency direction between layers) also arrives
  **commented out** — deliberately. A fresh project has no layer folders yet, and an
  *active* boundary that matches nothing **passes silently** and creates a false sense
  that the architecture is protected. The package name in it is already filled in: once
  `src/<pkg>/core` etc. appear, just remove the `# ` from the block (and check that it
  "bites" — add a deliberate bad import, confirm `sentrux check` fails).

This way there's neither a false "red" on day 1 nor a false "green": everything active
really works, and everything not yet applicable is visibly commented out.

> **⚠️ sentrux 0.5.7 blind spots (a boundary passes silently).** When you uncomment
> `[[boundaries]]`, keep in mind two places where they **don't** trigger:
> - **Relative imports don't resolve:** `from ..cli import x` bypasses the boundary
>   silently. In gated layers use **absolute** imports (`from <pkg>.cli import x`)
>   — or add a lint rule forbidding relative imports.
> - **A flat module** `src/<pkg>/<layer>.py` is **not** matched by the dir path
>   `src/<pkg>/<layer>` — keep layers as subpackages (`src/<pkg>/<layer>/`), or add
>   the `.py` suffix to the boundary path for a flat layer.

---

## Installation

> The fast "install → wire up → verify" path — [`SETUP_GUIDE.md`](SETUP_GUIDE.md).
> Below are the platform-specific details.

### macOS

```bash
brew install sentrux/tap/sentrux
```

Grammars download automatically on first run.

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh | sh
```

### Windows

**Option 1 — curl (recommended, if you have the Rust toolchain):**

```powershell
# Download the binary into ~/.cargo/bin/ (already on PATH if Rust is installed)
curl -L -o "%USERPROFILE%\.cargo\bin\sentrux.exe" ^
  https://github.com/sentrux/sentrux/releases/latest/download/sentrux-windows-x86_64.exe

# Verify
sentrux --version
```

Grammars (51 language parsers) download automatically on first run (~30 MB).

**Option 2 — manual install:**

1. Download `sentrux-windows-x86_64.exe` from the [latest release](https://github.com/sentrux/sentrux/releases/latest)
2. Rename it to `sentrux.exe`
3. Place it in any directory on PATH (e.g. `%USERPROFILE%\.cargo\bin\` or `%USERPROFILE%\bin\`)

**Option 3 — via claude-kit:**

```bash
claude-kit new        # creates the project and generates .mcp.json from the enabled plugins' plugin.json
# or, for an existing project:
claude-kit add sentrux
```

`claude-kit` will automatically enable sentrux in `.mcp.json` when you pick the
corresponding component.

### Verifying the install

```bash
sentrux --version          # should print "sentrux X.Y.Z"
sentrux check              # should print "Quality: NNNN" and the rule list
```

### MCP connection

The MCP binding is declared in `.mcp.json` (the binary starts via `sentrux mcp`). After
installing, restart Claude Code and check: `/mcp` → sentrux should be green.

---

## Metrics and quality_signal

`quality_signal` is the **geometric mean** of five sub-metrics, each normalized to
0–10000.

| Metric | What it measures | A low score means |
|---------|-----------|----------------|
| **modularity** | How internally cohesive and loosely coupled modules are | Blurred boundaries, leaking details |
| **acyclicity** | Absence of cycles in the import graph | Cycles exist → score bottoms out |
| **depth** | Depth of architectural layers | Everything on one flat level / too deeply nested |
| **equality** | Even distribution of complexity across modules | A god-module / dozens of tiny ones |
| **redundancy** | Duplicates / repeated code | A lot of copy-paste |

The `quality_signal` scale:

| Range | Interpretation |
|----------|---------------|
| 0–3000 | The architecture is tangled, a refactor is unavoidable |
| 3000–6000 | Medium. Bottlenecks are visible, targeted improvements will help |
| 6000–8000 | Good. Maintainable, routine hygiene |
| 8000–10000 | Excellent. Keep the current level |

**The main rule:** don't look at the absolute number — look at the **delta**
before/after changes and at the **bottleneck**.

---

## Slash commands (`.claude/commands/sentrux-*`)

### Snapshots and analysis

| Command | What it does | When to call it |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-health` | scan + health, an overall snapshot: quality_signal + bottleneck + 5 metrics | At the start of a session, to understand "where we're starting from" |
| `/mcp-sentrux:sentrux-dsm` | Dependency Structure Matrix: relations between modules, cycles | When the bottleneck is `acyclicity`, or you need to understand "who pulls in whom" |
| `/mcp-sentrux:sentrux-gaps` | List of modules with no tests (prioritized by coupling) | Before `/dev:ship`, before a PR |
| `/mcp-sentrux:sentrux-evolution` | Metric trends over time | A retrospective after a large refactor |

### Refactoring workflow

| Command | What it does | When to call it |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-baseline` | Records quality_signal as a reference point (`session_start`) | **Before** starting a large refactor |
| `/mcp-sentrux:sentrux-diff` | Compares the current state against the baseline (`session_end`), shows the delta | **After** changes, before a commit |

### Rules and CI

| Command | What it does | When to call it |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-rules` | Checks `.sentrux/rules.toml` via MCP, an interactive breakdown of violations | After changing layer boundaries / new imports |
| `/mcp-sentrux:sentrux-check` | CLI `sentrux check` (exit 0/1, for pre-commit and CI) | In scripts, in pre-commit, in CI |

---

## Typical scenarios

### 1. Before a refactor

```
/mcp-sentrux:sentrux-baseline       # record the starting point
... make your changes ...
/mcp-sentrux:sentrux-diff           # see signal_before → signal_after
```

If `signal_after < signal_before` — you broke something. Run `/mcp-sentrux:sentrux-dsm`
to find where new couplings or cycles appeared.

### 2. Finding cycles

```
/mcp-sentrux:sentrux-health         # bottleneck = acyclicity, score 2500/10000
/mcp-sentrux:sentrux-dsm            # see which modules formed a cycle
```

Candidates for breaking the cycle:

- move shared code into a lower layer;
- invert the dependency through an interface / event;
- split a "fat" module into two.

### 3. Before `/dev:ship` (PR)

```
/mcp-sentrux:sentrux-gaps           # what tests don't cover — close the critical gaps
/mcp-sentrux:sentrux-check          # architecture rules are not violated
/mcp-sentrux:sentrux-diff           # quality has not dropped against the baseline
```

### 4. Configuring invariants

Usually `.sentrux/rules.toml` is already deployed by `claude-kit new` (the
`src-package` archetype). If you edit it by hand — a minimal example (DIP /
hexagonal style):

```toml
[constraints]
max_cycles   = 0
no_god_files = true

# Paths in [[boundaries]] are LITERAL directory prefixes: `*` stands for a file name
# and does NOT expand a directory segment, so "src/*/domain" matches nothing.
# Use the full path src/<pkg>/<layer> (no trailing slash). Keys: from/to/reason
# (there is NO `forbidden` key — sentrux silently ignores unknown keys).
[[boundaries]]
from   = "src/your_package/domain"
to     = "src/your_package/adapters"
reason = "domain does not depend on adapters (DIP)"
```

> This is a generic example. Fit the paths to your project's real layers/package, or
> take a ready-made archetype from `templates/` (see "Starter rule archetypes" above).

Next:

```
/mcp-sentrux:sentrux-rules          # check via MCP — interactive
/mcp-sentrux:sentrux-check          # the same check via CLI — for CI
```

---

## MCP tools (nine)

The slash commands above are wrappers over these MCP tools. You can call them directly
too (if you need a non-standard combination):

| Tool | Purpose |
|------|-----------|
| `mcp__sentrux__scan` | Full metric recompute (required before the others in a new session) |
| `mcp__sentrux__rescan` | Quick update after changes |
| `mcp__sentrux__health` | quality_signal + bottleneck + 5 metrics |
| `mcp__sentrux__dsm` | Dependency Structure Matrix |
| `mcp__sentrux__test_gaps` | Modules with no tests |
| `mcp__sentrux__check_rules` | Validate `.sentrux/rules.toml` |
| `mcp__sentrux__session_start` | Save the baseline |
| `mcp__sentrux__session_end` | Compare against the baseline (pass/fail + delta) |
| `mcp__sentrux__evolution` | Historical dynamics |

---

## CLI (without MCP)

Useful for CI / pre-commit / scripts. Works the same way on macOS, Linux, Windows:

```bash
sentrux                        # GUI with a live treemap (if a display is available)
sentrux check                  # validate rules.toml, exit 0/1
sentrux gate --save            # save the baseline
sentrux gate                   # compare against the baseline (CI mode)
sentrux mcp                    # start the MCP server (this is what .mcp.json does)
sentrux plugin list            # language plugins
```

> **Note:** in v0.5.7+ the project path is determined automatically (the current
> directory). The `.` argument is not needed.

---

## Troubleshooting

**`/mcp` shows sentrux as failed**

```bash
# macOS / Linux
which sentrux                  # the binary must be on PATH
sentrux mcp --help             # should say "Start the MCP server"

# Windows (Git Bash)
where sentrux                  # or: which sentrux
sentrux mcp --help
```

If the binary is there but MCP still fails — restart Claude Code:
- VS Code: `Ctrl+Shift+P` (Windows) / `Cmd+Shift+P` (macOS) → `Developer: Reload Window`
- CLI: restart the terminal

**`scan` takes too long**

Large project → check `.gitignore` and `.ignore`. sentrux respects them (like
ripgrep). Exclude archives, binaries, and generated files from indexing.

**`session_end` says "no baseline"**

First `/mcp-sentrux:sentrux-baseline`, then changes, then `/mcp-sentrux:sentrux-diff`.
The baseline is stored in the MCP server's memory — it won't survive a Claude Code
restart.

**Metrics don't change after edits**

`mcp__sentrux__rescan`, or just `/mcp-sentrux:sentrux-health` (it calls scan again).

---

## Sources

- Repository: <https://github.com/sentrux/sentrux>
- Install/releases: <https://github.com/sentrux/sentrux/releases>
- Pro version (advanced root-cause diagnostics): <https://github.com/sentrux/sentrux> → Upgrade

The full list of the project's slash commands is in the root [`CLAUDE.md`](../../../CLAUDE.md), in the project commands section.
## Launcher options

**Default** (used automatically by `claude-kit add sentrux`): declared inline in `.claude-plugin/plugin.json` → `mcpServers.sentrux`.

```
command: sentrux
args: ["mcp"]
```

Requires the `sentrux` binary in PATH (see "Setup" above).

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
