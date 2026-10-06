---
name: feedback_subagents_share_the_leads_scratchpad
description: "Субагент пишет в тот же scratchpad сессии, что и лид: ревьюер 6.1 сохранил свой inject.py поверх харнесса инъекций лида — у каждого агента своя подпапка / subagents share the lead's session scratchpad, same-name files are silently overwritten — give each agent its own subfolder"
mechanism: [agents, break-injection]
module: [scripts]
metadata:
  node_type: memory
  type: feedback
---

2026-10-06, plans-progress Task 6.1. Лид прогнал матрицу из 14 инъекций харнессом
`scratchpad/inject.py` (≈12 КБ, спеки 41/34/56/71/61). Ревьюер в том же прогоне ревью делал свои
инъекции и записал `scratchpad/inject.py` (3,4 КБ) — файл лида исчез, `grep '"61": "pp-61"'` → 0.
Журнал матрицы уцелел только потому, что лежал под другим именем.

**Why:** путь scratchpad в системном промпте субагента — тот же каталог сессии, что у лида.
Короткие имена (`inject.py`, `probe.py`, `msg.txt`) у разных ролей совпадают, Write перезаписывает
молча, предупреждения нет.

**How to apply:** в брифе каждого субагента, который пишет файлы, назвать подпапку:
`scratchpad/<роль><задача>/` (`dev61/`, `rev61/`). Свои харнессы лид держит в `lead<задача>/`.
Харнесс, нужный дальше задачи, — не в scratchpad, а в памяти или в репозитории.
Связано: [[feedback_inject_only_after_the_work_is_committed]].
