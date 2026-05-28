---
name: feedback-commit-msg-format
description: "commit-msg hook: каждый trailer (Why/Layer/Refs/...) должен быть ОДНОЙ строкой (перенос ломает парсер); pre-commit ruff-format → re-stage + re-commit (не amend)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: f448a3e1-419b-4868-aed1-42b320b47f3c
---

Два правила про коммиты в этом проекте (оба стоили лишних попыток 2026-05-28):

**1. Каждый trailer — строго одна строка.**
`scripts/validate_commit/validate_commit.py` (`parse_message`) считает хвостовой абзац trailer-блоком ТОЛЬКО если КАЖДАЯ его строка матчит `^[A-Z][A-Za-z\-]*: .+$`. Если `Why:` (или любой trailer) перенесён на вторую строку — продолжение не матчит → весь абзац не распознаётся как trailers → ошибка «Missing required trailers Why/Layer», хотя они формально есть.
**How to apply:** держать `Why:`, `Layer:`, `Refs:`, `Risk:`, `Reversible:`, `Tested:` каждый на ОДНОЙ строке (можно длинной). Многострочные значения запрещены. Эмодзи/кириллица в теле и в значениях trailer'ов — НЕ проблема (валидатор не проверяет содержимое, только формат `Key: value`); ранняя гипотеза «эмодзи ломает hook» оказалась ложной.

**2. pre-commit ruff-format модифицирует свежие файлы → коммит падает.**
Хук `ruff format` переформатирует только что отредактированные файлы (часто схлопывает многострочные вызовы/lambda в одну строку) → pre-commit «files were modified by this hook» → коммит НЕ создан.
**How to apply:** после такого падения — повторно `git add` изменённых файлов + НОВЫЙ commit (НЕ amend, т.к. коммита ещё не было). Это же касается hook'а end-of-files/trailing-whitespace для md-файлов (память/планы) и авто-дописывания `docs/sessions/<date>.md` (его тоже добавлять в commit).

См. формат коммитов в CLAUDE.md и [[project-plan-driven-dev]].
