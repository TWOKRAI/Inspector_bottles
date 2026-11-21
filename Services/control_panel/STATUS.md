# STATUS — Services.control_panel

**Фаза:** Phase 1-3 DONE + qt-mcp smoke verified. Phase 6 («Пульт оператора 1.0»): задачи 6.1–6.4 DONE, влиты в main
(6.1 `fa03cd8a7`, 6.1b/6.1c — тесты слова `8c5f1dd4d`/`dc56f14df`, 6.2 `69c40c3a6`, 6.3 `e836b2db5`, 6.4 `519db0930`).
6.5 живая приёмка — в процессе; результат — в отчёте `docs/reports/2026-11-21_pult_6.5.md` (пишет лид).
6.6 — документы (README, STATUS).

## Готово
- **Phase 1 (services):** `controls.py` — ControlSpec (button/toggle/slider/number/text) +
  коэрция/валидация. `plugin/` — ControlPanelPlugin (source), пул out_1..out_8, команды
  set/emit/add/remove/update. Публикация в state. 21 тест.
- **Phase 2 (prototype GUI):** вкладка Services → «Пульт» (виджет/presenter/секция):
  динамический рендер контролов из state, форма «Добавить контрол», подтверждение удаления.
  Операция — live-команда; add/remove — live + персист в рецепт (SetPluginConfig). 8 тестов.
- **Phase 3:** демо-рецепт `recipes/pult_demo.yaml` (4 контрола).
- **qt-mcp smoke verified:** Services-таб грузится, 4 контрола рендерятся, нажатие «Старт»
  эмитит `out_1 = True` (подтверждено логом ноды pult). Поймал и починил баг: секция
  не реализовывала `action_buttons()` → весь Services-таб падал «Ошибка загрузки».

## Дальше
- Phase 4 — запись памяти (dual-write): **не сделана**.
- Phase 6 / 6.5 — живая приёмка β8 на симе (окно `stand`): не проведена.

## Известные ограничения v1
- Пул портов фиксирован (out_1..out_8) — динамические именованные порты позже.
- Значения контролов (value) в state публикуются на структурных изменениях
  (add/remove/update), не на каждый set — GUI источник истины во время операции.
- add/remove персистятся в editor-топологию (рецепт dirty); на диск — при Save рецепта.
