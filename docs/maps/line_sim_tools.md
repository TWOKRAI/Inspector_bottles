# Карта зоны: `Services/line_sim/tools/make_seamless_texture.py`

Первый автор — Task 1.4 (layer-render); дальше правят в своём handoff. Номера строк — на коммит Task 1.4.

## Функции

- `find_period`, `make_seamless_tile(image, *, force_period)` — период/зеркало, бесшовный тайл (`:100`, `:205`).
- `gap_alpha_mask(tile_rgb, *, hue, sat_min, rails_px, min_area=0)` — альфа-маска просветов, `(H, W)` uint8 {0, 255} (`:244`).
- `main(argv)` — CLI (`:288`): масштаб -> шов -> маска по готовому тайлу -> PNG (RGBA с `--gap-alpha`).

## Флаги просвета и проверки (все — только вместе с `--gap-alpha`)

| Флаг | Дефолт | Проверка (ошибка `parser.error` с именем флага) |
|---|---|---|
| `--gap-hue LO,HI` | `_GAP_HUE=(25,85)` `:73` | пара целых 0..179, `LO<=HI` (`:384-386`) |
| `--gap-sat-min N` | `_GAP_SAT_MIN=40` `:74` | целое 0..255 (`:388-392`) |
| `--rails-px TOP,BOTTOM` | `_RAILS_PX=(22,22)` `:80` | пара целых >= 0; `TOP+BOTTOM < h` (`:446`) |
| `--gap-min-area N` | `_GAP_MIN_AREA=8` `:77` | целое >= 0 (`:393-398`); `0` — фильтр выключен |

Общая проверка «флаг без `--gap-alpha`» — `:373-381` (кортеж флагов, `:378` — `--gap-min-area`).

## Инварианты (Task 1.4) и где держатся

| Инвариант | Файл:строка | Тесты |
|---|---|---|
| Фильтр = один `connectedComponentsWithStats(..., connectivity=8)`; площадь строго `< min_area` -> 255 | `:268-271` | `test_acceptance_layer_render_1_4_*` A2, A3; hazards `exactly_min_area` |
| Порядок: сначала строки бортов, потом фильтр | `:266-268` | A4b; hazards `rails_rows_do_not_count_toward_area` |
| Дефолт функции `min_area=0` (выход побайтно прежний); дефолт CLI = 8 | `:250`, `:394` | A1 (sha), 1.2 `test_hazards_gap_alpha.py`, A5 |
| `min_area <= 0` и `1` — не фильтр | `:268` | hazards `min_area_one_is_a_no_op`, `negative_*` |
| Края тайла по x не склеиваются | (нет кода — решение) | A3 `x_edges_are_not_glued` |
| Фильтр трогает только альфу (RGB тайла тот же) | `:449-455` | A5 RGB, hazards `combine_into_the_written_alpha` |
| Вход функции не мутируется | `:262-271` (`gap` — новый массив, вход не трогается) | hazards `input_not_mutated`, 1.2 `does_not_mutate_input` |

## Тесты

`Services/line_sim/tests/`: `test_acceptance_layer_render_1_2_gap_alpha.py`, `test_hazards_gap_alpha.py` (1.2),
`test_acceptance_layer_render_1_4_gap_min_area.py` (слепые), `test_hazards_1_4_gap_min_area.py` (автор).

## Открыто

Склейка краёв тайла по x (на реальном тайле меняет 4 px); закрытие непрозрачных точек внутри просвета; A6/A7 — на данных вне git (лид).
