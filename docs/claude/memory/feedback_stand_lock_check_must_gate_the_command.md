---
name: stand-lock-check-must-gate-the-command
description: "Проверка замка должна гейтить команду: агент печатал stand.lock и всё равно гнал pytest в чужой замер; форма `A && cmd || echo` прячет красный как «пропущено» — только scripts/machine_gate.sh, exit 75 = пропуск (guard, stand lock, machine.lock)"
mechanism: [agents, live-stand]
metadata:
  type: feedback
---

**2026-10-13:** the form below is itself wrong — `A && cmd || echo skipped` prints «skipped» with exit 0
when `cmd` ran and went red (reviewer reproduced: holder + `false` → «NO WINDOW — skipped», exit 0). Use
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" heavy|light <session> <cmd...>`: the command's own exit code, 75 = skipped;
with no `machine.lock` it gates on `stand.lock` measure.

2026-09-30: the reviewer was told "before every pytest run check stand.lock". It did — `cat stand.lock; pytest …` in one
command — and pytest ran anyway: the neighbour's `measure` lock had appeared seconds earlier, ~5.7 s of Qt tests landed
in the neighbour's A/B window, and the neighbour had to be told to re-measure.

**Why:** a check whose result nothing reads is not a gate. Agents batch the check and the action into one shell call.

**How to apply:** in every brief that runs tests while a neighbour may measure, give the literal guarded form:
`[ ! -e /d/PROJECT_INNOTECH/Inspector_vision/stand.lock ] && <pytest …> || echo "STAND LOCKED — skipped"`.
Same for my own runs. If a neighbour announced a measure "in N minutes", finish or pause test work before N.
Protocol: [[shared-stand-and-tests-protocol]].
