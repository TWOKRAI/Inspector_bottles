---
name: feedback-commit-ascii-only
description: "commit-msg hook отклоняет эмодзи/не-ASCII в теле commit-сообщения — писать commit-messages только текстом (кириллица OK, эмодзи нет)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: f448a3e1-419b-4868-aed1-42b320b47f3c
---

Commit-сообщения в этом проекте НЕ должны содержать эмодзи (🔴, ✅ и т.п.) в теле.

**Why:** commit-msg hook (`.git/hooks/commit-msg` → `scripts/validate_commit/validate_commit.py`) при наличии эмодзи в теле отклоняет коммит с генерик-подсказкой про отсутствие `Why:`/`Layer:` (хотя trailers на месте) — вводит в заблуждение. Стоило 2 неудачных попытки коммита G.1.1 (2026-05-28); замена `🔴`→текст сразу прошла. Кириллица в теле — OK (предыдущие коммиты с русским текстом проходят); проблема именно в эмодзи/спец-символах.

**How to apply:** в `git commit -m`/heredoc писать только обычный текст. Если в плане/коде есть маркер 🔴 — в commit-сообщении заменять на слово («silent-failure risk», «критично»). Обязательные trailers `Why:` и `Layer:` — как обычно (см. [[project-plan-driven-dev]] и CLAUDE.md commit-формат). Также помнить: pre-commit `ruff format` часто переформатирует свежие файлы → коммит падает «files were modified by this hook» → пере-`git add` изменённых + повторный коммит (НЕ amend).
