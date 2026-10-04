---
name: feedback_worktree_for_parallel_samefile
description: Параллельные агенты правят ОДИН файл с незакоммиченными изменениями — работать в изолированном git worktree от committed HEAD
metadata:
  type: feedback
---

Когда параллельные агенты держат **незакоммиченные** правки в файле, который тебе тоже нужно менять (пример 2026-07: телеметрия-агенты правили `backend_ctl/driver.py` Task 1.4 в main-дереве, а мне надо было делать Phase 0 backend-ctl-hardening тоже по `driver.py`), НЕЛЬЗЯ делать `git checkout -b` в том же рабочем дереве — это утащит их незакоммиченную работу на твою ветку и сломает им контекст.

**Как правильно:** `git worktree add -b <branch> ../<dir> HEAD` — изолированная копия от committed HEAD (без их uncommitted-правок). Правки/тесты в worktree с main-venv python (`../main/.venv/Scripts/python.exe`) импортируют пакет ИЗ worktree (cwd на sys.path) — полная изоляция. При мерже в main 3-way разведёт непересекающиеся хунки одного файла (я трогал endpoint/транспорт/подписки, они — telemetry-методы 696–803).

**Почему:** один checkout = одно рабочее дерево; worktree даёт второе, разделяя `.git` (refs/объекты общие, коммиты независимы).

**Как применять:** обычные субагенты (Agent tool) работают в ОСНОВНОМ дереве — их для правок в таком сценарии не спавнить (столкнутся). Делать правки самому в worktree, коммитить по одной задаче. Расширяет [[feedback_parallel_agents_commit_race]] (макс 2 без worktree): при коллизии по ФАЙЛУ worktree обязателен, не опционален.
