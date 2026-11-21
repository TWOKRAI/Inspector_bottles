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

`get_controls`, `set_control{id,value}` (обновить+эмитнуть), `emit_control{id}` (кнопка-триггер), `add_control{spec}`, `remove_control{id}`, `update_control{id,patch}`.
На `monitor` `set_control`/`emit_control` отвечают `{"status":"error","message":"контрол только для чтения (monitor)"}`, эмита нет.

## Поток

`produce()` (source-цикл) сливает накопленные эмиты → items `{out_N: value,
"data_type":"signal", "panel_id":...}` → chain_targets. Команды из GUI пишут в очередь
эмитов под lock (как сигналы `phone_camera`).

## Источники и типы

- `source`: `local` (эмит на свой порт, дефолт); `param` (правка поля `target_field` ноды `target_process`); `action` (команда `target_command`, фикс. аргументы `command_args`, значение — в `value_arg`); `monitor` (показ `state_path`).
- `type: monitor` — только чтение, даже без `source: monitor`. `state_path` — полный путь StateStore; `value_key` — ключ dict-значения (`conn`), пусто — значение как есть.

## Пульт оператора 1.0 (рецепты)

| id | Что делает | Куда идёт |
|---|---|---|
| `word` | новое слово (Enter) | param → процесс `layout`, `target_word` |
| `belt_run` | пуск ленты (`vfd_run`) | action → `devices`, `vfd_belt` |
| `belt_stop` | стоп ленты (`vfd_stop`) | action → `devices`, `vfd_belt` |
| `home` | «Домой» (`robot_park`) | action → `devices`, `robot_main` |
| `servo_on` | «Серво ВКЛ» (`robot_servo`, `on: true`) | action → `devices`, `robot_main` |
| `mon_conn` | связь с роботом | monitor ← `devices.state.robot_main.conn` |
| `mon_park` | парковка | monitor ← `devices.state.robot_main.park.state` |
| `mon_last` | последняя буква | monitor ← `processes.layout.state.word_layout.last_label` |
| `mon_assembled` | собрано | monitor ← `processes.layout.state.word_layout.assembled` |
| `mon_done` | слово собрано | monitor ← `processes.layout.state.word_layout.done` |

Рецепт `letter_robot_sim.yaml`, процесс `pult` (последний, `run_gated: false`). В β (`hikvision_letter_robot.yaml`) 8 контролов: «Домой» и «Серво ВКЛ» — только после R4 (перевод β на `delta_v2`).

## Известные ограничения 1.0

- Нет блокировок контролов по состоянию системы: «Домой» при «работает» роняет очередь заданий; блокировка по `system.run.state` — после 1.0.
- «Слово»: только Enter, без подтверждения; пустое слово откатывает регистр; поле не читает регистр обратно (правду показывает монитор «Собрано»). Оператор может удалить его (✕) — «режим оператора» после 1.0.
- Мониторы: значения по-английски (`done` → True/False, `conn` → connected, `park.state` → parking/done/failed); до первой публикации `last_label`/`assembled` — пустая строка. Подсказка ряда «👁 .» бессмысленна — после 1.0.
- Ловушка YAML: `value_arg: "on"` только в кавычках. Голое `on` = True, `parse_controls` молча роняет контрол.
