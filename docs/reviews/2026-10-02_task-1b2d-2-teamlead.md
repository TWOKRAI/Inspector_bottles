# Task 1b.2d-2 — отчёт teamlead (правила данными в FieldMeta + атомарная запись)

Ветка `feat/gs-1b2d`, база `fecd01a8b`. Коммиты: `c4dc0bc01` (реализация), следующий за ним — hazard-тесты автора, DECISIONS, итог регулярки в спеке, этот отчёт.

## Результат прогонов

- Радиус из брифа: **1131 passed, 1 failed** — единственный красный `test_fieldinfo_path_default_goes_as_str` (известный, красный и на main, путь Windows).
- Тесты process_module/потребителей записи: `process_module/tests/test_1b2d_set_config_all_or_nothing.py`, `test_plugin_config_extra.py`, `test_registers_integration.py`; `frontend_module/tests/test_form_context_write.py`, `integration/test_form_context_integration.py`, `test_{combo,spinbox,slider,numeric,compound}_form_ctx.py`; `Plugins/processing/{color_mask,resize}/tests/test_registers_integration.py`; `frontend/bridge/tests/test_command_catalog.py`; `Plugins/tests/test_health_report_sites.py`; `Plugins/sources/camera_service/tests/test_commands.py` — **124 passed**. Прямых тестов generic `cmd_set_config`, кроме тестерского файла, в дереве нет (греп).
- Hazard-тесты автора `data_schema_module/tests/test_field_meta_rules_hazards.py`: **17 passed**.

## Где держится каждое свойство (для инъекций лида)

| Свойство | Место |
|---|---|
| strip | `data_schema_module/core/field_meta.py:114` |
| pattern | `field_meta.py:116` |
| choices_map (upper, промах = отказ, каноничное) | `field_meta.py:119` |
| value_pattern (ключ, без значения) | `field_meta.py:128` |
| нестроковый вход → ValueError | `field_meta.py:113`, `:126` |
| поле без правил не обёрнуто | `field_meta.py:276` |
| неизвестный ключ: конструктор / from_dict | `field_meta.py:256` / `:408` |
| rules в to_dict | `field_meta.py:392` |
| le_field | `data_schema_module/core/schema_base.py:76` |
| откат `__dict__` (перечитывается после исключения) | `data_schema_module/core/schema_mixin.py:314` |
| откат fields_set | `schema_mixin.py:319` |
| текст отказа без значения | `schema_mixin.py:320`, `_refusal_text` `:333` |
| update_field через apply_values | `schema_mixin.py:283` |
| set_field_value через apply_values | `registers_module/core/manager.py:206` |
| уведомление сохранённым значением | `manager.py:211` |
| cmd_set_config всё-или-ничего | `process_module/plugins/base.py:1647` |
| otel endpoint правила | `Services/otel_export/config.py:55` (`ENDPOINT_RULES`), `:128`; `Plugins/io/otel_export/registers.py:70` |
| otel level / headers / batch≤queue | `config.py:67` (`_LEVEL_CHOICES`), `:169`, `:211` |
| line_filter dedup ≤ hysteresis | `Plugins/filter/line_filter/registers.py:89` |

Номера строк сняты на коммите `c4dc0bc01`; перед инъекцией сверяйте грепом по тексту.

## Самоинъекции (прогноз записан до прогона; радиус без forms, 1041 тест)

| Инъекция | Умерло | Совпало с прогнозом |
|---|---|---|
| I1 strip выключен | 2: whitespace_normalized, pinned_literals | да |
| I2 pattern выключен | 25: корпус ×8, blank ×3, AC2 endpoint ×4, leak endpoint, pinned, сервисные error-state ×5, hazard ×2 | да (шире: сервисные тесты otel) |
| I3 value_pattern выключен | 18: AC2 headers ×2, leak headers ×2, сервисные headers ×12, hazard non_string m | да (шире) |
| I4 choices_map: промах принимается | 4: AC2 unknown, pinned, сервисные level ×2 | да |
| I5 le_field выключен | 9: AC2 line_filter ×2, AC2 otel ×2, pinned, сервисные ×3, hazard le_none | да |
| I6 откат `__dict__` выключен | 12: atomic ×2, set_config ×2, AC2 межполевые ×4, pinned, hazard ×3 | да |
| I7 откат fields_set выключен | 3: atomic `lo_above_hi`, hazard rollback, hazard reentrant | **частично**: прогнозировал оба atomic; `hi_below_lo` выжил — `hi` уже в fields_set, утечка там невидима. Покрыто hazard-тестом |
| I8 cmd_set_config построчно | 2: set_config cross_field, type_rejection | да |
| I9 `str(exc)` вместо `errors(include_input=False)` | 3: leak endpoint, leak headers, hazard refusal_text | да |
| I10 уведомление введённым значением | 1: hazard notify | да — **сторожит только тест автора** |
| I11 обёртка у поля без правил | 1: hazard schema | да — **сторожит только тест автора** |

## Регулярка endpoint

Итог: без поправок, `https?://[^\s/?#]+/[^\s?#]*[^\s/?#][^\s?#]*` (записано в спеку). Корпус `test_endpoint_signal_path_hazard.py`: 8/8 неполных отвергнуты, текст содержит `/v1/logs` и `404`; 3/3 полных приняты дословно. Дрейфа на корпусе нет; дрейф вне корпуса — как в спеке (верхний регистр схемы, `?`/`#`, пробел внутри, `http://[::1/…`), отдельным прогоном не замерял.

## Что интерпретировал, а не исполнил

- `Plugins/io/otel_export/registers.py` — расширение FILES, **одобрено лидом** (переобъявленный `endpoint` терял правила родителя).
- Hazard-тест на реальный `OtelExportRegisters` из файла фреймворка удалён (хук слоёв: framework не импортирует Services/Plugins); реальный класс сторожат AC2-случаи endpoint (I2 это подтвердил).
- Номер ADR: в брифе не назван; первый свободный — **ADR-DS-010** (ADR-DS-009 последний). ADR-RM-007 дополнен датированным пунктом, а не новой записью.
- `cmd_set_config`: `applied` теперь несёт сохранённые значения; на отказе пишется `log_warning`.
- `schema_mixin.py` переформатирован хуком ruff-format при коммите (файл был не отформатирован и на HEAD).

## Что оставил открытым / ненадёжно

- I10 и I11 сторожат только тесты автора — независимого покрытия у «уведомление сохранённым значением» и «поле без правил не платит» нет.
- Реентерабельность: ключ, записанный вложенным `apply_values` вне внешнего набора, не откатывается, а fields_set при этом откатывается (значение есть, отметки нет) — потолок, пинится литералом.
- Докстринг `Plugins/io/otel_export/registers.py` ещё ссылается на удалённый `_endpoint_not_blank` (вне одобренной правки — follow-up).
- Сообщения `min`/`max` в `_check_field_constraints` по-прежнему печатают число — правило «без значения» на них не распространял.
- Ключ `headers` в тексте отказа — пользовательский ввод (по спеке: «называет КЛЮЧ»).
- Полный набор тестов не гонял (по брифу — у лида); `scripts.sync` не запускал.
