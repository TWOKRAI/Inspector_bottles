---
name: feedback-commit-msg-format
description: "commit-msg hook: trailer предпочтительно одной строкой, но с 2026-07-14 хук ТЕРПИТ перенос (git-стиль фолдинг); pre-commit ruff-format → re-stage + re-commit (не amend)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: f448a3e1-419b-4868-aed1-42b320b47f3c
---

Два правила про коммиты в этом проекте (оба стоили лишних попыток 2026-05-28):

**1. Каждый trailer — держать на одной строке (рекомендация; ХУК ТЕПЕРЬ ТЕРПИТ ПЕРЕНОС — фикс 2026-07-14).**
Раньше `scripts/validate_commit/validate_commit.py` (`parse_message`) считал хвостовой абзац trailer-блоком ТОЛЬКО если КАЖДАЯ строка матчит `^[A-Z][A-Za-z\-]*: .+$` → перенос `Why:` на вторую строку ронял весь абзац в body → ложное «Missing required trailers». **Фикс 2026-07-14 (git-стиль):** абзац = trailer-блок, если НАЧИНАЕТСЯ с трейлера; не-матчащие строки внутри фолдятся как продолжение значения. Перенос `Why:`/`Layer:` больше НЕ блокирует коммит (регресс-тест `scripts/validate_commit/tests/test_validate_commit.py`). Причина частого трапа: агенты/heredoc легко вставляют перенос в длинный `Why:`; правило-в-памяти не спасало от чата к чату → починен корень (хук), а не только память.
**How to apply:** по-прежнему предпочитать одну строку на trailer (чище diff), но опечатка-перенос теперь не фатальна. Эмодзи/кириллица в теле и значениях — НЕ проблема (валидатор проверяет только формат `Key: value`).

**2. pre-commit ruff-format модифицирует свежие файлы → коммит падает.**
Хук `ruff format` переформатирует только что отредактированные файлы (часто схлопывает многострочные вызовы/lambda в одну строку) → pre-commit «files were modified by this hook» → коммит НЕ создан.
**How to apply:** после такого падения — повторно `git add` изменённых файлов + НОВЫЙ commit (НЕ amend, т.к. коммита ещё не было). Это же касается hook'а end-of-files/trailing-whitespace для md-файлов (память/планы) и авто-дописывания `docs/sessions/<date>.md` (его тоже добавлять в commit).

См. формат коммитов в CLAUDE.md и [[project-plan-driven-dev]].
