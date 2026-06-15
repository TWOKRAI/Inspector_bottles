# Services.control_panel — сервис «Пульт»

GUI-пульт: пользователь создаёт контролы (кнопка, тумблер, слайдер, поле числа/текста),
а нода `control_panel` в pipeline **эмитит значение контрола на выходной порт** при
операции. Порт вяжется к потребителю в редакторе Pipeline.

## Рецептность

Контролы хранятся **в рецепте** — это поле `controls` в конфиге ноды `control_panel`
(внутри `blueprint`). У каждого рецепта свой набор кнопок/слайдеров. При старте плагин
читает `controls` из конфига; GUI-правки сохраняются обратно в рецепт (через save).

## Состав

| Файл | Назначение |
|------|-----------|
| `controls.py` | `ControlSpec`: тип/порт/значение + валидация/коэрция (core, без Qt) |
| `interfaces.py` | Публичные типы (`ControlSpec`, `ControlType`) |
| `plugin/plugin.py` | `ControlPanelPlugin` (source): `produce()` дренит эмиты в items |
| `plugin/config.py` | `ControlPanelConfig`: `panel_id`, `controls: list[dict]`, `port_count` |
| `plugin/registers.py` | `ControlPanelRegisters` (tunable) |

## Порты

Фиксированный пул `out_1..out_8` (dtype `any`). Каждый контрол ссылается на свой `out_N`.
Динамические именованные порты (по label контрола) — follow-up.

## Команды плагина

`get_controls`, `set_control{id,value}` (обновить+эмитнуть), `emit_control{id}`
(кнопка-триггер), `add_control{spec}`, `remove_control{id}`, `update_control{id,patch}`.

## Поток

`produce()` (source-цикл) сливает накопленные эмиты → items `{out_N: value,
"data_type":"signal", "panel_id":...}` → chain_targets. Команды из GUI пишут в очередь
эмитов под lock (как сигналы `phone_camera`).
