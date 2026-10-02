# Предсказания инъекций 1b.2d-1 (записано ДО прогона, лид, 2026-10-02)
Наборы: A = автор test_field_info_codec_hazards.py; T = тестер test_1b2d_copy_agrees_with_original.py -k container_element_types (10 параметров: 9 list, 1 dict = otel_export.headers)
| # | Инъекция | A | T |
|---|---|---|---|
| I1 | to_dict не пишет item | >=1 | 9 |
| I2 | to_dict не пишет key/value | >=1 | 1 (headers) |
| I3 | from_dict игнорирует item | >=1 | 9 |
| I4 | вложенный literal теряет choices (только nested) | >=1 | 0 (нет вложенных literal в инвентаре) |
| I5 | старый payload: desc["item"] вместо .get | >=1 | 0 (хаб свежий; но голый list в каталоге может уронить копию — тогда >0) |
| I6 | старый payload: desc["key"] вместо .get | >=1 (автор сам не инъецировал) | 0..1 (голый dict ×1 в инвентаре) |
| I7 | снята защита от Literal[None] в _build_nested | 1 | 0 |

## Факт (baseline A 0F/28P, T 0F/10P)
| # | A | T |
|---|---|---|
| I1 | 11F | 9F |
| I2 | 7F | 1F |
| I3 | 10F | 9F |
| I4 | 3F | 0F |
| I5 | 1F | 0F |
| I6 | 4F | **5F** (предсказано 0..1) |
| I7 | 1F | 0F |

Расхождение I6 — неверная модель лида: `desc["key"]` роняет сборку и для вложенного голого `dict` из `list[dict]`
(chain_executor.steps, modbus_sink.payload, overlay_draw ×3 = 5). Свойство «нет ключа → голый контейнер» держится
одним `.get` для двух случаев: старый payload и вложенный голый dict. Скрипт: восстановление в finally, newline="".
I4, I5, I7 держит только набор автора — тестерский набор их не видит (в инвентаре нет вложенных literal и старых payload).
