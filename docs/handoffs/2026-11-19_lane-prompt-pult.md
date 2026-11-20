# Стартовый промпт — Полоса Пульт — фаза 6 «Пульт оператора 1.0»: ревью плана (без кода) (координатор inspector-bottles-9e, 2026-11-19)

Сводка веток, порядок слияния и общие правила — `2026-11-19_lane-prompts-index.md`. Вставлять блок ниже в новый чат целиком.

```
ВКЛАДКА: Пульт · фаза 6 «Пульт оператора 1.0» (ORDER #15–#17, β8): ревью плана, код — после слова владельца
ROLE: lead of lane Пульт (продолжение Р2), plans/pult-control-panel.md Phase 6 — на ветке `docs/pult-operator-phase6` (`9ca6e0ead`, в main НЕ влита; читать `git show docs/pult-operator-phase6:plans/pult-control-panel.md`).
READ FIRST: Phase 6, «Связи», «Открытые вопросы», «Что осталось ненадёжно»; docs/reports/2026-11-15_R2_lane.md (smoke 6.0 backend-путь: 59 тестов зелёные, `pult_demo` check() = []); plans/release-1.0/design.md §3 β8; `Plugins/processing/word_layout`, `Plugins/io/robot_io`; docs/handoffs/2026-11-15_day2-robot.md.
ЭТАП 0 (код не писать, слот писателя не занимает):
  а) Стадия 0 reviewer sonnet (run_in_background: false) на тексте Phase 6: DESIGN, FILES, REDS, зависимости; сверка с run-state 2.2/2.3 (кнопки ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать — главное окно, полоса Ф; пульт их не дублирует, пока владелец не скажет иначе — В4) и ORDER #21/R4 (рецепт β правит К).
  б) GUI-путь smoke 6.0 не проверен: qt-mcp `CONNECTION_CLOSED` — проверить подключение у себя; иначе backend_ctl + тесты вкладки.
  в) Список В1–В6 владельцу с рекомендацией каждого; план докоммитить в `main` отдельным `docs(plans):` по слову владельца (создание/закрытие плана — отдельный коммит).
ПОСЛЕ слова владельца: 6.0 → 6.1 вертикальный срез «Слово» → 6.2–6.6, когда освободится слот писателя.
BOUNDARIES: вкладка «Пульт», `Plugins/hub/device_hub` — свои; главное окно и кнопки run-state (Ф), `Services/camera_device` (К), рецепт β (К, R4) — не писать.
PIPELINE/LOAD/COMMITS/LIMITS/REPORT: как в блоке Р2 (только документы; `machine_gate.sh`; `docs(...)`; отчёт `docs/reports/<дата>_pult_<задача>.md`, по-русски, непустое «что осталось открытым / ненадёжно»).
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: В1–В6 плана; В4 (дублировать ли кнопки run-state в пульте).
```

