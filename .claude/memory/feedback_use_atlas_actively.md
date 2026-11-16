---
name: feedback-use-atlas-actively
description: "Владелец 2026-11-13: использовать Атлас (scripts/atlas) активно — паспорта в брифах, atlas check как гейт, lint-result для отчётов"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e147e7a0-a862-486f-a6b6-acca4c94b237
  modified: 2026-11-12T21:42:00.741Z
---

Владелец (чат полосы Ф, 2026-11-13): «используй атлас активно».

**Why:** Атлас даёт паспорт файла/символа из кода без чтения модуля целиком; экономит токены агентов и держит брифы на фактах.

**How to apply:** `python -m scripts.atlas map <путь.py>` / `ref <модуль> [--symbol ...]` в бриф исполнителю вместо пересказа кода; `atlas check` (гейт против merge-base) после каждой задачи; `atlas lint-result <отчёт>` для итога задачи. Паспорты мелкие (members + used_by, методы класса не раскрывает; `used_by` бывает пуст) — якорные функции всё равно читать `grep -n` + Read. `atlas brief <slug>#<id>` на плане run-state отвечает «task not found» (формат реестра не выяснен). Запуск из корня основного дерева основным `.venv`.
