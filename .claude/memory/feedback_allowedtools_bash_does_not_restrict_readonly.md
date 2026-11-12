---
name: allowedtools-bash-does-not-restrict-readonly
description: claude -p --allowedTools Bash(<шаблон>) не запрещает read-only оболочку (ls/find/grep -n/cat); условие «только atlas» так не собрать
metadata:
  node_type: memory
  type: feedback
  last-verified: 2026-11-11
  originSessionId: 869199f2-e18c-4258-a517-1084ab45a695
  modified: 2026-11-11T12:52:53.103Z
---

В пилоте «Атлас против grep» (nav_bench, условие с `bash_allow`) агент Haiku запускал `find`, `ls`, `grep -n` через Bash, хотя в `--allowedTools` был только `Bash(python …/pilot_atlas.py ref *)`. Claude Code сам одобряет безопасные read-only команды; отказали лишь `find -exec` и цепочки. Atlas агент вызвал 1 раз на три сессии, arm бенч пометил `TAINTED` (аудит `bash-pattern`).

**Why:** шаблон в `--allowedTools` ограничивает автоодобрение, а не набор команд; граница «живая проверка грамматики `Bash(...)`» из `tasks/5.1.md` закрыта отрицательно. Условие `atlas` без изоляции мерит «grep + оболочка», а не atlas.

**How to apply:** для чистого условия atlas (4.3, 5.1) — запрет по списку (`Bash(find *)`, `Bash(grep *)`, `Bash(ls *)`, `Bash(cat *)` и т. п. в `disallowed_tools`) либо сессия без Bash; читать `TAINTED` как «оболочка использована», а утечку проверять по трассе (`tool_uses`: пути вне копии). Связано: [[feedback_subscription_tokens_allowed]].
