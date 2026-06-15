# STATUS — Services.control_panel

**Фаза:** Phase 1-3 DONE + qt-mcp smoke verified. Остался Phase 4 (память).

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
- Phase 4 — запись памяти (dual-write).

## Известные ограничения v1
- Пул портов фиксирован (out_1..out_8) — динамические именованные порты позже.
- Значения контролов (value) в state публикуются на структурных изменениях
  (add/remove/update), не на каждый set — GUI источник истины во время операции.
- add/remove персистятся в editor-топологию (рецепт dirty); на диск — при Save рецепта.

## Известные ограничения v1
- Пул портов фиксирован (out_1..out_8) — динамические именованные порты позже.
- Значения контролов (value) в state публикуются на структурных изменениях
  (add/remove/update), не на каждый set — GUI источник истины во время операции.
