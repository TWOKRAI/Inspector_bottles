# STATUS — Services.control_panel

**Фаза:** Phase 1 (backend-плагин) — DONE.

## Готово (Phase 1)
- `controls.py` — ControlSpec (button/toggle/slider/number/text) + коэрция/валидация.
- `plugin/` — ControlPanelPlugin (source), пул портов out_1..out_8, команды set/emit/add/remove/update.
- Публикация контролов в state (`processes.<proc>.state.control_panel`).
- 21 тест (controls + plugin), ruff чист, плагин обнаруживается discovery.

## Дальше
- Phase 2 — вкладка Services «Пульт»: динамический рендер контролов + «добавить контрол».
  **Персист контролов в рецепт** (поле `controls` ноды) при save — рецептный сервис.
- Phase 3 — демо-рецепт `pult_demo.yaml` + проводка портов.
- Phase 4 — qt-mcp smoke + память.

## Известные ограничения v1
- Пул портов фиксирован (out_1..out_8) — динамические именованные порты позже.
- Значения контролов (value) в state публикуются на структурных изменениях
  (add/remove/update), не на каждый set — GUI источник истины во время операции.
