# Фаза 5 — один генератор букв

Родитель: [plan.md](plan.md). Итог фазы: буквы для сима и для датасета рисует одно ядро. Дообучение (`letters-retrain`
Фаза 1) этой фазы **не ждёт**: каталог 33 букв × системные шрифты строится уже существующим
`python -m Services.line_sim.tools.make_font_letters --letters <33 буквы> --font ... --stroke-px ...`.

Порядок исполнения — как в [phase-1.md](phase-1.md).

Почему ядро — в `Services/dataset_gen/tools/`, а не в `line_sim`: `dataset_gen` стоит ниже `line_sim` и не может
импортировать его (цикл, граница из 1.3); `line_sim` импортирует `dataset_gen` уже сегодня.

---

### Task 5.1 — ядро рисования букв переезжает в `dataset_gen/tools`, `line_sim`-путь — прокладка

- **Статус:** [PENDING] · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** impl-only (CLI и выход не меняются; переезд модуля)
- **CHAIN:** `tester`(RED: sha256 выхода до задачи) → `developer`(GREEN) → `reviewer`

**Goal:** код `make_font_letters` (493 стр.) живёт в `Services/dataset_gen/tools/make_font_letters.py`;
`python -m Services.line_sim.tools.make_font_letters` и импорты из старого пути работают как раньше.

**Files:**
1. `Services/dataset_gen/tools/make_font_letters.py` (новый — тело переезжает дословно)
2. `Services/line_sim/tools/make_font_letters.py` — прокладка: реэкспорт публичных имён + `main` + `if __name__ == "__main__"`
3. `Services/line_sim/tools/make_letter_catalog.py` — `DEFAULT_DIAMETER_PX` реэкспортом из нового места (контракт 5.3b
   §4.1: «импортирован, не продублирован» — источник один)
4. `Services/dataset_gen/README.md`, `Services/line_sim/README.md` — где теперь инструмент
- тесты: `Services/dataset_gen/tests/test_make_font_letters_moved.py`

**Acceptance:**
- [ ] `test_acceptance_look_1_2_ink_disk.py`, `test_hazards_look_1_2.py`, `test_acceptance_1_1b_font_tool.py`,
      `test_acceptance_font_stroke.py`, `test_hazards_font_stroke.py`, `test_hazards_1_1b_tool_preset.py` — зелёные без правки.
- [ ] Обе команды (`-m Services.line_sim.tools.make_font_letters` и `-m Services.dataset_gen.tools.make_font_letters`) с
      одинаковыми аргументами (DejaVuSans из matplotlib, `--letters АК --stroke-px 0 --stroke-px 3 --disk-out`) пишут
      побайтно одинаковые каталоги.
- [ ] `Services/dataset_gen/` не импортирует `Services.line_sim` (греп + `sentrux check .`).

**Out of scope:** новые опции, `make_ru_letter_sprites` (5.2), `make_letter_catalog.py` (кроме константы).

---

### Task 5.2 — `make_ru_letter_sprites` — пресет поверх того же ядра

- **Статус:** [PENDING] (зависит от 5.1 и решения О-3) · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** impl-only
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** `make_ru_letter_sprites` перестаёт рисовать сам: CLI (`--out --size --font --letters`), структура
(`<буква>/base.png` + `meta.yaml`) и `RU_UPPERCASE` (импортирует `test_config_preset.py:58`) остаются, рисует ядро 5.1.

**Files:**
1. `Services/dataset_gen/tools/make_ru_letter_sprites.py` — вызов ядра; собственный код рисования удалён
2. `Services/dataset_gen/tools/make_font_letters.py` — режим «буква на белом диске» (только если О-3 = байт в байт)
3. `Services/dataset_gen/README.md`
- тесты: `Services/dataset_gen/tests/test_ru_letter_sprites_core.py`

**Acceptance (по О-3):**
- [ ] О-3 «байт в байт» (рекомендация): sha256 всех 33 `base.png` + `meta.yaml` при `--font <DejaVuSans-Bold из matplotlib> --size 256`
      — литералы сняты тестером до задачи — совпадают после.
- [ ] О-3 «новые пиксели»: высота/D каждой буквы ∈ [0.47, 0.50] тем же методом замера, что в `letters-retrain`
      (`scratchpad/lettersize/lm.py` лида); пресеты `ru_letters_disk.yaml` и `manual_letters_disk.yaml` грузятся.
- [ ] `Services/dataset_gen/tests/` — зелёные; в `make_ru_letter_sprites.py` нет ни `ImageDraw`, ни `ImageFont` (греп).

**Out of scope:** перегенерация данных на диске и переобучение — это решение `letters-retrain`.
