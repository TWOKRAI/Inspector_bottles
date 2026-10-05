# Memory audit — brief for classifier agents (read fully)

## Why
Project memory has grown to 433 files (2.4 MB). Only the index `MEMORY.md` (~21.5k chars, ~6.5k tokens) loads into
EVERY session; the files load only when an agent opens them. Goal: keep what is genuinely useful, shrink the index to
≤ 8 KB (~2k tokens), make each lesson findable by module/mechanism, stop duplicates and stale "progress" notes from
competing with real lessons. NOTHING is deleted now — you only classify and propose. The owner and the lead decide.

## Inputs
- Working copy (read from here only): `scratchpad/memory-audit/merged/` — union of the two copies, newer version wins.
  Full path: C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/8f41fef8-166e-4d75-9771-d92dc8289bbb/scratchpad/memory-audit/merged/
- Current index: `merged/MEMORY.md` (what loads every session) and `merged/CRAFT.md` (craft index, loaded on trigger).
- `pass1.json` (same folder as this brief): per-file status same / differ / only_git / only_local, type, size.
- Repo for fact checks: D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles (main). Never grep -r from repo root; use git grep.

## Hard rules
- READ-ONLY everywhere. Do NOT edit, move or delete anything in either memory folder or the repo. Do not commit.
- Write only your own report file (path in your prompt). If Write is refused, return the report as text.
- Context economy: per file read the frontmatter + first ~20 lines (`head -25`). Read the whole file only when deciding a
  merge or when the head is ambiguous. You have ~135–160 files; budget your reading.

## Kinds (assign exactly one per file)
| Kind | Signal | Proposed action |
|---|---|---|
| RULE | imperative about how to work; must fire BEFORE anyone remembers it; process, not a measured fact | move into a mechanism: `project-rules` skill / a hook / a command / CLAUDE.md line; memory keeps a one-line pointer. Name the target. |
| LESSON | a trap or technique with evidence (input → observed output, a number, a commit) and a trigger | KEEP. Propose `module:` and/or `mechanism:` tags (e.g. module: router_module; mechanism: break-injection). |
| STATE | progress of a plan/track, "next task", dated status | REPLACE with pointer to the plan (plans/<slug>) or ARCHIVE if the plan is closed. Check the plan exists: `git ls-files plans | grep <slug>`. |
| REFERENCE | environment, setup, paths, versions, machine facts | KEEP; mark `local-only` if machine-specific (GPU, Windows paths). |
| DUP | same trap/rule as another file | MERGE into the named survivor (the one with better evidence); say what unique bit to carry over. |
| REDUNDANT | restates what code, git, a plan or CLAUDE.md already says | ARCHIVE; cite where the fact lives. |
| STALE | refers to removed code/plans or a superseded decision | ARCHIVE; cite the evidence (git grep returns 0, plan archived, later decision). |

## Output (Russian, STE-80; identifiers as-is)
1. Table, one row per file: `file | kind | action | target (survivor / mechanism / plan) | tags (module/mechanism) | hook ≤ 12 words | reason ≤ 15 words`.
2. Merge groups: survivor ← list of files, and the unique content each brings.
3. RULE files → proposed mechanism and the exact one-line rule text.
4. Index candidates: at most 12 entries from your share that MUST stay in the new `MEMORY.md` (rules that must fire every
   session, or lessons so costly they justify ~40 tokens each in every session). One line each: `[Title](file) — hook`.
5. Counts per kind and the estimated bytes saved from the index.
6. "What is unreliable in my classification" — non-empty (files read only by head, uncertain merges, etc.).
Return to the caller: report path + counts + index candidates + top 5 merge groups.
