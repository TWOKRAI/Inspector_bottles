---
date: 2026-10-02
topic: layer-render волна 5 (Task 2.4a) — спека написана, дальше ревью спеки
machine: Windows
branch: feat/layer-render
---

## Состояние

- Волна 4 влита: 2.3 `ca0e6203a`, 6.4 `e18d22d44`, закрытие `7f414a2dc`; радиус 1597 passed, 3 skipped. Временные
  worktree и ветки волны 4 удалены. `main` не двигался (сосед — сессия 19, transport-single-policy: SHA сообщить до движения `main`).
- Решения владельца 2026-10-02 (в журнале `plan.md`): волна 5 — только 2.4; 2.4 режется на **2.4a** (пресет + каталог,
  чистые переносы) и **2.4b** (фабрика → `RenderedObject` + превью); `SpriteCatalog` переезжает **целиком** с `CatalogConfig`,
  метой, `SymmetryType`, процедурными фонами; три теста в `layer_render/tests` с импортом `line_sim` — утверждённое исключение.
- Спека 2.4a — `plans/layer-render/phase-2-core.md`, раздел «Task 2.4a» (`67bca9cf0`). Разведка: agentId `a60b3d02cfe190df2`
  (Explore, отчёт в транскрипте; ключевые факты вошли в спеку и TRAPS).
- Страница для владельца обновлена: claude.ai/artifact/2K3PQc8BqtrCAghdgg2ppp (версия 2 — система редактора целиком, планы).
- Память: `feedback_one_control_proves_sufficiency_not_exclusivity` (dual-write, `90ac5c2c8`).

## Next step

1. **Стадия 0:** reviewer Opus, синхронно, `MODE: plan` на текст Task 2.4a (DESIGN / FILES / Acceptance). Правки — в спеку.
2. Слепой tester (Sonnet) в worktree на коммите после правок спеки, до кода; файл `test_acceptance_2_4a_preset_catalog.py`;
   литералы A3/A4 снимаются на коде до переезда.
3. developer (Sonnet) в своём worktree; коммитит лид. Затем инъекции лида (оба набора), ревью Opus, слияние.
4. 2.4b — спека после слияния 2.4a (разведка уже есть: `make()` в line_sim обязан вернуть `LayeredObject`; приватные
   `_preset`, `_catalog`, `_build_defect_blob`, `_DEFECT_*` трогают тесты; `LayeredObject` нужен второй конструктор из `RenderedObject`).

## Open

- Follow-up: `compose_layers` на стеке без слоёв на канве падает сырым `ValueError: max() iterable argument is empty`.
- 6.4: CLI-границы шире регистра `center_crop` (0.1..5.0) — записано в докстринге, не исправлено.
- `docs/claude/OPEN_QUESTIONS.md` 168 КБ при бюджете 32 КБ — отдельной задачей.
