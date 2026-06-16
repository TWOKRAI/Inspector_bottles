# План: плагин раскладки слова `word_layout`

**Ветка:** `feat/word-layout` (создаётся при старте реализации; сейчас WIP на `feat/pult-control-panel`)
**Slug:** `word-layout`
**Статус:** Phase 1-2 DONE (ядро + плагин, 49 тестов зелёных, ruff чист). Phase 3 ЧАСТИЧНО:
`word_layout` вписан в `hikvision_letter_robot.yaml` (`infer.predictions → layout.word_layout`),
структура рецепта провалидирована headless. Осталось: robot_io-проводка (железо/калибровка),
live-smoke на стенде, Phase 4 (README/STATUS + memory).

**Корректность детекта (важно):** в `hikvision_letter_robot` `center_crop` режет кадр по
триггеру линии → `ml_inference` даёт ~1 предсказание на диск (без пауз между разными буквами).
Поэтому «новый диск» = смена буквы ИЛИ пауза; дедуп по БУКВЕ (не углу — дрожит ±1-2°);
`settle_frames=1` в рецепте (для тракта «1 кадр на диск» >1 не возьмёт диск).

## Цель

Новый processing-плагин `word_layout` — **планировщик раскладки слова** для робота-сортировщика.
По целевому слову, координатам первого/последнего диска и потоку распознаваний
(`ml_inference` → буква + угол) выдаёт для каждого диска **задание роботу
`{x_mm, y_mm, angle_deg}`**: куда положить и на сколько довернуть.

«По сути всё уже есть» — недостающее звено между распознаванием и укладкой.

## Решения владельца (2026-06-16)

1. **Поток дисков — конвейер-сортировщик.** Диски едут по ленте, `ml_inference` читает
   каждый по очереди, робот хватает с ленты (по энкодеру) и кладёт в слот слова с
   доворотом. → Переиспользуем CVT-путь `robot_io` → `robot_enqueue_job` → `send_job(x,y)`.
2. **Угол — только плагин, железо потом.** v1: плагин СЧИТАЕТ угол доворота и кладёт в
   задание `{x,y,angle_deg}`. Реальный доворот в Lua-прошивке (`cvt_universal_full.lua`,
   `send_job` + протокол + драйвер) — **follow-up**. Укладка по (x,y) работает уже сейчас.
3. **Подбор буквы — потоковый жадный.** Каждый распознанный диск → первый незаполненный
   слот слова с этой буквой; ненужные буквы/дубли пропускаются; слово готово, когда все
   слоты заполнены.

## Решения по умолчанию (правятся при ревью)

- **Источник слова:** register-поле `target_word` (владелец задаёт в пульте/инспекторе) +
  опциональный входной порт `word` (на будущее — мост из телефона). Прямой мост
  `phone.state.word → порт` — отдельный мелкий follow-up (см. «Открытые вопросы»).
- **Координаты (по уточнению владельца):** основной режим `use_pitch=True` — от ПЕРВОГО
  диска по направлению `line_angle_deg` (90 = вдоль +Y: X постоянный, Y растёт) с шагом
  `pitch_mm` (0 = авто = диаметр 110 мм). Слово любой длины ложится с ОДНИМ шагом. Альт.
  режим `use_pitch=False` — равномерно между first и last. Все поля — register (в пульт).
- **Выход роботу — полная поза `{x_mm, y_mm, z_mm, r_deg}`** (+char/slot/raw_angle). z —
  `place_z_mm`, r — доворот (у КАЖДОГО диска свой; финальная ориентация общая `angle_zero_deg`).
- **Радиус 55 мм** — авто-шаг = диаметр 110 мм + проверка зазора (`spacing_warn`).
- **Два слова:** `target_word` с пробелом → пробел = `word_gap_slots` пустых ячеек (дефолт 1)
  на ТОЙ ЖЕ линии. Две отдельные строки (свой первый/последний) — follow-up.
- **Угол:** `correction = wrap180(angle_zero_deg − angle_sign·detected_angle)`; при
  `angle_valid=False` (полная симметрия буквы) `correction=0`. `angle_zero_deg`/`angle_sign` —
  калибровка нуля модель↔робот (открытый вопрос памяти letter+angle).
- **Детект нового диска (debounce):** эмитим, когда уверенное предсказание стабильно
  `settle_frames` кадров И «взведены»; после эмита разоружаемся, взводимся снова, когда
  предсказания пропали/слабые (диск ушёл). Опц. порт `trigger` — взять диск принудительно
  (кнопка пульта / датчик), минуя авто-debounce.

## Структура

```
Plugins/processing/word_layout/
  __init__.py
  geometry.py     # чистые функции: slot_positions, correction_angle, wrap180, parse_word
  assembler.py    # WordAssembler — потоковый жадный матчер (stateful)
  plugin.py       # WordLayoutPlugin(ProcessModulePlugin), category=processing
  config.py       # WordLayoutPluginConfig (register_bindings)
  registers.py    # WordLayoutRegisters (живые поля + readonly прогресс)
  README.md  STATUS.md
  tests/
    test_geometry.py
    test_assembler.py
    test_plugin.py
```

## Фазы

### Phase 1 — Чистое ядро (geometry + assembler) + тесты
**Layer:** plugins

- `geometry.py`:
  - `wrap180(deg) -> float` — привести угол к (−180, 180].
  - `parse_word(text, gap_slots) -> list[Cell]` — буквы + пробелы→gap-ячейки; нормализация
    регистра (upper). Возвращает ячейки с флагом «буква/пробел» и индексом слота.
  - `slot_positions(first_xy, last_xy, cells) -> list[(x,y)]` — линейная интерполяция по
    всем ячейкам (буквы + gap), позиции только для букв (в порядке). n=1 → first.
  - `correction_angle(detected_deg, angle_valid, zero_deg, sign) -> float`.
  - `spacing_ok(positions, diameter) -> bool` — зазор ≥ диаметра.
- `assembler.py`:
  - `WordAssembler(slots: list[Slot])` где `Slot={char,x,y,filled}`.
  - `offer(label, angle_deg, angle_valid) -> Job|None` — первый незаполненный слот с
    `char==label.upper()`; заполнить, вернуть `{slot, x_mm, y_mm, char, angle_deg, raw_angle}`;
    иначе None. `remaining()`, `done`, `reset()`.
- **Тесты:** wrap180 границы; parse одно/два слова + gap; интерполяция (включая n=1, концы);
  correction (valid/невалидный/sign/zero); матчер (порядок, дубли, ненужные, готовность).
- **Acceptance:** `pytest Plugins/processing/word_layout/tests/test_geometry.py test_assembler.py` зелёный; ruff чист.

### Phase 2 — Плагин `word_layout`
**Layer:** plugins

- `registers.py` (`SchemaBase`): `target_word`, `first_x/first_y/last_x/last_y` (мм),
  `disk_radius_mm=55`, `word_gap_slots=1`, `angle_zero_deg=0`, `angle_sign=1`,
  `min_confidence=0.5`, `settle_frames=3`, `use_trigger=False`, `predictions_source="predictions"`,
  `job_key="robot_job"`. Readonly: `word_norm`, `slots_total`, `slots_filled`, `next_letter`,
  `last_label`, `last_angle_deg`, `last_correction_deg`, `jobs_emitted`, `done`, `spacing_warn`.
- `config.py`: `WordLayoutPluginConfig(PluginConfig)` + `register_bindings`.
- `plugin.py`: входы `predictions`(list[dict]), `word`(опц.), `trigger`(опц.); выход
  `robot_job`(dict, опц.) + frame pass-through. `process()`:
  1. слово: из порта `word` или `target_word`; геометрия из регистров → при изменении
     пересобрать `WordAssembler` (positions);
  2. debounce/trigger → при «новом» уверенном диске `offer()`;
  3. успех → положить `item[job_key]={x_mm,y_mm,angle_deg,label,slot,word}`, счётчики,
     publish прогресса в state (для дисплея/дашборда).
- **Тесты:** pass-through; смена слова пересобирает; жадный эмит один раз на диск;
  debounce не дублирует; trigger форсит; готовность.
- **Acceptance:** `pytest Plugins/processing/word_layout/` зелёный; ruff чист.

### Phase 3 — Проводка + рецепт
**Layer:** mixed (plugins + prototype)

- `robot_io`: пробросить `angle_deg` в `robot_enqueue_job` (если есть в job) — forward-compat,
  драйвер пока игнорирует (железо потом). 1–2 строки, без риска.
- Рецепт распознавания: камера/лента → (crop) → `ml_inference` (модель буква+угол) →
  `word_layout` → `robot_io`. Поля `word_layout` (first/last/word/калибровка) — в пульт-дашборд.
- Проверить headless: порты, wire, blueprint check 0 ошибок.
- **Acceptance:** рецепт грузится; jobs уходят в hub (лог `robot_enqueue_job`).

### Phase 4 — Docs + memory + smoke
- `README.md`/`STATUS.md` плагина; запись памяти (dual-write `docs/claude/memory/` +
  локально) + MEMORY.md индекс.
- Smoke: headless-прогон рецепта (предсказания → jobs с координатами слотов), при наличии —
  qt-mcp дашборд (поля плагина правятся вживую).

## Открытые вопросы / follow-up

- **Мост слова из телефона:** `phone.state.word` → порт `word_layout`. Варианты: телефон
  эмитит слово как signal при приёме; или подписка плагина на state. Решить в Phase 3.
- **Доворот в железе:** `send_job(x,y,rz)` + Lua + протокол + драйвер (решение 2 — отдельно).
- **Калибровка нуля модель↔робот:** подобрать `angle_zero_deg`/`angle_sign` на реальном
  железе (открытый пункт памяти letter+angle).
- **Две строки** (свои первый/последний на слово) — если понадобится多.

## Грабли (учесть)
- Нормализация регистра буквы и слова (кириллица upper) — лейблы модели vs `target_word`.
- Эмит ровно один раз на диск (debounce/разоружение) — иначе слот «залипает» каждый кадр.
- `angle_valid=False` — НЕ пропускать диск, а ставить `correction=0` (симметрия, доворот не нужен).
- Новый корень state (`word_layout.**`) — дашборд/дисплей должен быть подписан (glob bind).
