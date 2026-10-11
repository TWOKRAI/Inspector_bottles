---
name: feedback_option_denylist_misses_abbreviations_and_argfiles
description: "A prefix deny-list of CLI options is bypassed by git short-option clusters (-nO<cmd>), git long-option abbreviations (--op=, --open-f=) and pytest @argfiles — test every spelling, not the canonical one (deny-list опций обходится склейкой, сокращением и @файлом)"
mechanism: [guards, git, dev-tooling]
module: [scripts/atlas]
role: reviewer
metadata:
  type: feedback
---

Atlas 1.9c `replay.py` filtered `git grep` arguments with `a.startswith(("-O", "--open-files-in-pager", …))`.
git's parse-options also accepts a short cluster (`-nOtouch\ x` = `-n -O"touch x"`) and any unique prefix of a long
option (`--op=`, `--open-f=`): both ran an external command (files created in a temp repo). pytest >= 8.2 reads
`@file` as extra arguments, so `--collect-only @args.txt` smuggled `--junitxml=` past a per-argument filter.
git diff/log options did NOT accept abbreviations (`--outp=` → "unrecognized argument") — the risk is per
subcommand, check each one live.

The blind tester's allow-list test listed only the canonical spellings (`--output=`, `--junitxml=`, `git -c`) and
counted lines ("вне allow-list 8"): deleting any one of seven filters left every test green, and swapping a
right and a wrong exit-code line kept the count. The lead's break-injection plus the reviewer's live probes found it.

**Why:** a deny-list is only as strong as its test; the canonical spelling is the one nobody uses to attack.

**How to apply:** a deny-list check takes the option NAME before `=`, rejects it when any forbidden long option
starts with that name, rejects short clusters that contain a forbidden letter, and rejects `@`-arguments in ANY position (also as the value of `-k`/`-m`) for
tools that expand them. The test lists every spelling with a marker file and asserts by name, never by count.
