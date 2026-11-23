# Task R1b: ассеты стенда сима — весь алфавит, 33 буквы

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer (Sonnet) <!-- lint-language: allow -->
- **Files:** `Services/line_sim/tools/build_stand_assets.py`, `Services/line_sim/tests/test_build_stand_assets.py`,
  `Services/line_sim/tests/test_acceptance_6_5_stand_assets.py`, `apps/line_sim/pipeline.yaml`
- **Acceptance:** `build_stand_assets` собирает `letters_ink` из 33 букв (`Ё А Б … Я`, 66 спрайтов + диск), повторный
  запуск без `--force` — `skipped`; старый каталог из 8 спрайтов пересобирается; тесты — на `tmp_path`
- **Handoff:** developer(REDS в брифе: красный прогон до правки `src`, break-injection) -> reviewer(express)
- **Gate:** stage 0 — sonnet reviewer вместе с R1; тесты радиуса через `machine_gate.sh` + `ruff check -q`
- **Module contract:** impl-only (CLI и `main(argv)` прежние; меняется набор букв и литерал строки статуса)
- **Dependencies:** нет (main `10d50e315`); потребитель — стенд R1 (A12), release-1.0 §2.1

TASK: R1b — `build_stand_assets` строит каталог букв всего алфавита (решение владельца 25: «ассеты сима — весь алфавит»)   PLAN: plans/line-sim/plan.md
ROLE: developer
CHAIN: решение 25, ORDER #3 -> you -> стенд R1 (стадия 4: П Е Р М И А Б в каталоге), release-1.0 §2.1 (предусловие «каталог — весь алфавит»)

DESIGN (decided by the lead — you type it, you do not derive it):
  Сейчас: `Services/line_sim/tools/build_stand_assets.py:62` `_LETTERS = "АКРХ"`, группа `letters` = 8 спрайтов + диск
  (`_letter_files`, `:98-99`), статус `built letters_ink 8 files, disk 300x300x4`; сборка удаляет `letters_ink` перед
  записью (`:169-171`, защита LS-014 — лишний файл стал бы образцом класса). Отсюда «затирает каталог 33 букв» из ORDER #3:
  каталог, собранный руками на 33 буквы, при запуске инструмента не совпадает с ожидаемыми 8 путями и стирается.
  1. `_LETTERS = "ЁАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"` — 33 буквы, порядок `sorted()` (тот же, что у папок `SpriteCatalog`
     и у `data/models/mobilenet_v3_large_20260616_050828_classes.txt` в основном дереве; файл вне git — тест на него не
     опирается, литерал строкой в тесте). Шрифты те же (`DejaVuSans`, `DejaVuSansMono` из matplotlib — кириллица есть).
  **Трактовка «больше не затирает каталог» (ORDER #3), решение лида:** инструмент собирает все 33 буквы, а каталог из
  ровно 66 ожидаемых спрайтов не пересобирается (`skipped`). Удаление `letters_ink` перед пересборкой (защита LS-014)
  остаётся: каталог в любом другом составе инструмент по-прежнему стирает и строит заново. Отклонение от буквы ORDER
  лид заносит в отчёт владельцу; вопроса владельцу в этой задаче нет.
  2. Логику групп, идемпотентность, удаление каталога перед сборкой и `_letters_dir_is_exact` НЕ менять: старый каталог
     на 8 спрайтов теперь «не точный» → пересборка (это и есть миграция стенда). Каталог из ровно 66 ожидаемых
     спрайтов → `skipped`, не трогается (байты и mtime целы).
  3. Строка статуса — `built letters_ink 66 files, disk 300x300x4`; всего файлов сборки 69 (66 + диск + фото + тайл).
  4. Литералы старых тестов 6.5 меняются ТОЛЬКО в числах: `8 files` → `66 files`, `11` → `69`, `"АКРХ"` в
     эталонной сборке теста (`test_build_stand_assets.py:329`) → тот же литерал из 33 букв. Это решение лида в этой
     задаче (тесты закрытой Task 6.5, не слепого tester R1); логику тестов не трогать.
  5. `apps/line_sim/pipeline.yaml` — только комментарий о каталоге (`--letters АКРХ` в примере `make_letter_catalog`
     → указание на `build_stand_assets`, весь алфавит). Ключи не меняются.
  Стенд: `data/line_sim` вне git (`.gitignore:135`, C-55, C-62); в worktree его нет, в основном дереве нет `letters_ink`
  (есть `letter_catalog`, `letter_catalog_akrx`, `letter_catalog_rep` — их инструмент не трогает). Лид в стадии 4 R1
  запускает `python -m Services.line_sim.tools.build_stand_assets` в дереве стенда (относительный `--data-dir` —
  от корня того дерева, `preset.resolve_repo_path`), затем проверяет `ls data/line_sim/letters_ink` — 33 папки.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. `Services/line_sim/tools/build_stand_assets.py` — `_LETTERS`, докстринги (`8 путями` → `66`, «11 файлов» → «69»)
  2. `Services/line_sim/tests/test_build_stand_assets.py` — числа литералов (DESIGN 4) + три новых теста (REDS)
  3. `Services/line_sim/tests/test_acceptance_6_5_stand_assets.py` — числа литералов (DESIGN 4)
  4. `apps/line_sim/pipeline.yaml` — комментарий (DESIGN 5)

REDS (predicted red tests, before the `src` edit):
  - `Services/line_sim/tests/test_build_stand_assets.py::test_letters_full_alphabet` (новый: 33 папки `Ё…Я`, по 2 спрайта, имена `DejaVuSans_s3.png`, `DejaVuSansMono_s3.png`)
  - `Services/line_sim/tests/test_build_stand_assets.py::test_old_8_sprite_catalog_rebuilt` (новый: в `tmp_path` каталог из 8 спрайтов `АКРХ` → `built`, после — 66)
  - `Services/line_sim/tests/test_build_stand_assets.py::test_other_letters_ink_layout_rebuilt` (новый: 66 ожидаемых спрайтов + лишний `letters_ink/А/extra.png` → `built`, лишнего файла нет; фиксирует rmtree, LS-014)
  Итого новых тестов — 3 (выше), плюс старые тесты обоих файлов с правленными литералами.
  - все тесты обоих файлов, где строка статуса `letters_ink 66 files` или счёт `69` (после правки литералов, до правки `src`)

ACCEPTANCE: на `tmp_path`: `main(["--data-dir", <tmp>])` → код 0, третья строка stdout `built letters_ink 66 files, disk 300x300x4`;
  в `letters_ink` 33 папки, их имена = `list("ЁАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")`, в каждой по 2 PNG RGBA; второй запуск →
  `skipped letters_ink 66 files, …`, mtime файлов не изменился; каталог на 8 спрайтов → `built`; `load_catalog(<tmp>/letters_ink)`
  → `num_classes == 33`, `class_names` = тот же список; `all(unicodedata.is_normalized("NFC", n) for n in class_names)`
  (папки Ё и Й — в NFC; на APFS имя хранится как записано). Время полного теста сборки — в отчёте (66 спрайтов против 8).

TESTS: `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> pytest -q --tb=short Services/line_sim/tests/test_build_stand_assets.py Services/line_sim/tests/test_acceptance_6_5_stand_assets.py`;
  `ruff check -q` по FILES. Если прогон > 2 мин — класс `medium`, сказать в отчёте.

OUT OF SCOPE: `make_font_letters.py`, `make_letter_catalog.py`, другие каталоги `data/line_sim/*`, пресеты, код R1.
TRAPS: каталог в тестах — только `tmp_path` (не `data/`); `FIXTURES_DIR` подменяют тесты — не кэшировать; лишний файл в
  `letters_ink/<буква>/` = образец класса (LS-014) — удаление каталога перед сборкой оставить.
HANDOFF IN: none
