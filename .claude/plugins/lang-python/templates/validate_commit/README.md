# scripts/validate_commit/ — commit message validator

Checks Conventional Commits subject + required trailers (`Why:`, `Layer:`) per the project commit guide.

Full format guide: [`.claude/COMMIT_GUIDE.md`](../../.claude/COMMIT_GUIDE.md).

## Install the hook

```bash
bash scripts/validate_commit/install_hook.sh
```

Installs `commit-msg` hook in `.git/hooks/`. Runs on every `git commit` (skipped by `--no-verify`).

`claude-kit-project new` calls this automatically right after `git init`, so a project bootstrapped from the seed already has the hook in place.

## Run manually

```bash
# From file
python3 scripts/validate_commit/validate_commit.py path/to/commit-msg.txt

# From stdin
git log -1 --format=%B | python3 scripts/validate_commit/validate_commit.py -
```

Exit code: `0` — OK, `1` — errors, `2` — bad CLI usage.

## What is checked

| Rule | Severity |
|---|---|
| Subject in `<type>(<scope>): <subject>` format | error |
| `type` ∈ {feat, fix, refactor, docs, test, chore, perf, build, ci, style, revert} | error |
| Blank line between subject and body | error |
| Trailer `Why:` present | error |
| Trailer `Layer:` present | error |
| `Layer:` values whitelisted (see config below) | error |
| `Risk:` starts with low/medium/high | warning |
| `Reversible:` ∈ {yes, no, migration-needed} | warning |
| Unknown trailer key | warning |
| `Why:` too brief (< 5 chars) | warning |

## Skipped

- `Merge ...` / `Revert ...` commits
- `fixup!` / `squash!` / `amend!` (interactive rebase)

## Configuring allowed Layer values

Per-project layers live in `.claude/commit-layers.txt` (one layer per line, `#` for comments). The validator reads this file at runtime; if missing, falls back to generic defaults: `app, lib, tests, docs, scripts, infra, build, ci, mixed`.

Example `.claude/commit-layers.txt`:
```
# Match your architecture's actual layers
api
domain
adapters
tests
docs
infra
mixed
```

The validator finds this file by walking up from CWD to the first ancestor with `.git`.

## CI integration (optional)

```bash
# Validate every commit on a PR branch against main
for sha in $(git log --format=%H main..HEAD); do
    git log -1 --format=%B "$sha" | \
        python3 scripts/validate_commit/validate_commit.py - || exit 1
done
```

## Bypass

```bash
git commit --no-verify  # only for merge/rebase
```
