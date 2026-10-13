# Task 6.5: ассеты стенда одной командой из закоммиченных фикстур, плитка 410x484

- **Статус:** [DONE 2026-10-13] · **Level:** Middle · **Assignee:** developer <!-- lint-language: allow -->

TASK: 6.5 — модуль `build_stand_assets` собирает `data/line_sim` из фикстур, борта фото выравниваются медианой
PLAN: plans/line-sim/plan.md (Task 6.5, строка ~631; статус в plan.md правит лид, не исполнитель)
ROLE: developer
CHAIN: lead(DESIGN) + tester(слепая приёмка `test_acceptance_6_5_stand_assets.py`) -> you -> reviewer
(Файл тестера тоже несёт `__all__` и `Purpose:` — contract-lite `scripts/pre_report_gate.py:165` проверяет все новые `.py`.)
Module contract: new-lite (один файл, публичная точка — `main(argv)` и CLI)

## Посылка (замерено лидом и ревьюером 2026-10-13; не перемерять)

1. Фикстура `Services/line_sim/tests/fixtures/belt_photo_full.png` (598x484 BGR) закоммичена 2026-09-30 10:07
   (`1a2bba9bd`) — ДО выравнивания бортов медианой вдоль X (belt-look «Итог 1.3»). Выровненное фото жило только в
   gitignored `data/`; в основном дереве перезаписано 2026-10-12 (скрипт стенда скопировал фикстуру), копия уцелела
   в соседнем worktree. Лид сохранил её в основное дерево: `data/line_sim_original_2026-09-30/belt_photo_full.png`
   (sha256 `4444f158…ecd8e`, тот же sha в `plans/layer-render/phase-1.md:232`) и `belt_tile.png` (sha256
   `0afb4e7c…45ff7`). Std строк вдоль X в фикстуре: 0..21 — 31.03, 463..483 — 40.11, тело 22..462 — 19.1.
2. `make_seamless_tile(фикстура, force_period=True)` -> период 205, тайл 205x484, шов 8.58, внутр. 17.79.
3. Оригинал == фикстура, у которой каждая строка 0..21 и 463..483 заменена `np.median(row, axis=0).astype(np.uint8)`
   (УСЕЧЕНИЕ; 0 отличающихся пикселей; с `np.round` отличаются 7774 пикселя на 1). Сегодняшний
   `make_seamless_tile(оригинал, force_period=True)` -> период 205, тайл 410x484, RGB побайтно равен сохранённому
   тайлу; альфа `--gap-alpha` — 1080 прозрачных px; шов 12.85, внутр. 17.42, note «резерв: 2 период(а), старт 105».
4. **Решение лида:** верная плитка 410x484 = 2 звена x 205 px (пороги gap-alpha `make_seamless_texture.py:67`
   откалиброваны на ней; вердикт стенда belt-look 1.3 — на ней). Чиним СБОРКУ, комментарий `pipeline.yaml` дополняем.

## DESIGN (решено лидом — набираешь, не выводишь)

Новый файл `Services/line_sim/tools/build_stand_assets.py`, запуск
`python -m Services.line_sim.tools.build_stand_assets [--data-dir data/line_sim] [--force]`,
`main(argv: list[str] | None = None) -> int`; в конце `if __name__ == "__main__": raise SystemExit(main())`.
Фикстуры — публичная константа `FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"`,
читается в момент вызова `main` (не копируется в дефолты при импорте). Своего корня репо НЕ заводить.

- **`--data-dir`:** дефолт строка `data/line_sim`; любое значение проходит через существующий
  `Services.line_sim.core.preset.resolve_repo_path` (относительное — от `preset.REPO_ROOT`, читается в момент
  вызова; абсолютное — как есть). Каталог создаётся `mkdir(parents=True, exist_ok=True)` после предпроверки.
  От cwd не зависит ничто.
- **Дочерние CLI — через атрибут модуля:** `make_seamless_texture.main(...)`, `make_font_letters.main(...)`
  (`from Services.line_sim.tools import make_seamless_texture, make_font_letters`), не `from … import main` — иначе
  monkeypatch приёмки п. 15 не сработает. Аргументы — `str(path)`.
- **Предпроверка до первой записи:** существуют обе фикстуры (`belt_photo_full.png`, `real_disk_snapshot.png`) и оба
  шрифта (`<matplotlib.get_data_path()>/fonts/ttf/DejaVuSans.ttf`, `DejaVuSansMono.ttf`). Нет хоть одного -> stderr
  `ошибка шага preflight: <путь> не найден`, код 1, каталога `--data-dir` нет или он пуст.
- **а) `belt_photo_full.png`:** фикстура читается `imread_unicode(..., cv2.IMREAD_COLOR)`; строки 0..21 и 463..483
  заменяются `np.median(row, axis=0).astype(np.uint8)` (усечение, без `np.round`), повторённой на 598 столбцов.
  Константы `_RAIL_TOP_ROWS = range(0, 22)`, `_RAIL_BOTTOM_ROWS = range(463, 484)` с комментарием «belt-look: тело —
  кропы y 22..462, борта — строки реального кадра; медиана вдоль X с усечением — Итог 1.3, оригинал
  data/line_sim_original_2026-09-30». Тело не трогается. Выход 598x484x3, `imwrite_unicode`. Перед записью фото
  `belt_tile.png` удаляется (`unlink(missing_ok=True)`): связь «новое фото -> новый тайл» переживает упавший прогон.
- **б) `belt_tile.png`:** только `make_seamless_texture.main([<photo>, "--out", <tile>, "--force-period",
  "--gap-alpha"])`. Провал шага = `SystemExit`, любое `Exception` или код != 0. Своей логики тайла нет. Ждём 410x484x4.
- **в) `letters_ink/` + `letters_ink_disk.png`:** перед вызовами каталог `<data>/letters_ink` удаляется целиком
  (`shutil.rmtree` ровно этого подкаталога, если есть; внутри обработки ошибок шага — `OSError` даёт
  `ошибка шага letters: …`, код 1): `make_font_letters` не чистит `--out`, а лишний файл в
  `letters_ink/<буква>/` станет образцом класса (LS-014, `Services/line_sim/DECISIONS.md:384`). Затем два вызова
  `make_font_letters.main([...])`, по шрифту на вызов, аргументы ровно как в `scripts/run_sim_all.ps1:84-89`:
  `--letters АКРХ --font <ttf> --stroke-px 3 --size-px 300 --letter-frac 0.4763 --ink-rgb 65,70,82 --grain-sigma 9
  --edge-blur-px 1 --seed 1 --disk-from-photo <FIXTURES_DIR>/real_disk_snapshot.png --out <data>/letters_ink
  --disk-out <data>/letters_ink_disk.png`. `main` возвращает `None`; провал = `SystemExit` (любой код/строка) или
  `Exception`. Ждём каталоги `А`, `К`, `Р`, `Х` x файлы `DejaVuSans_s3.png`, `DejaVuSansMono_s3.png`; диск 300x300x4.
- **г) Идемпотентность по группам** `photo` (а), `tile` (б), `letters` (в: 8 файлов + диск). Группа готова, только
  если ВСЕ её файлы существуют И каждый читается обратно `imread_unicode` (вернул не `None`, не бросил); иначе
  пересобирается вся группа. Если в этом прогоне `photo` собрана (`built`), `tile` пересобирается обязательно.
  `--force` пересобирает все три. Готовая группа не перезаписывается (байты и mtime целы).
- **д) Вывод:** в stdout ровно 3 строки с префиксом `built ` / `skipped `, порядок photo, tile, letters; тексты:
  `built belt_photo_full.png 598x484x3`, `built belt_tile.png 410x484x4`, `built letters_ink 8 files, disk 300x300x4`
  (у `skipped` — тот же хвост; размеры — из файлов, прочитанных обратно). stdout дочерних CLI не перенаправляется.
  Провал -> stderr `ошибка шага <photo|tile|letters>: <причина>`, код 1, следующие группы не строятся.
- **е) Кириллица:** обратное чтение ТОЛЬКО `imread_unicode` из `Services.dataset_gen.core.catalog` (как соседние
  инструменты). Голый `cv2.imread` на Windows не читает кириллический путь.

`scripts/run_sim_all.ps1`: в блоке «# 0. Ассеты сима» (строки 71-92) остаются комментарий и `Set-Location $Root`;
строки 74-92 (`$SimData` … закрывающая `}` блока букв) заменяются на
`& $Py -m Services.line_sim.tools.build_stand_assets` и `if ($LASTEXITCODE) { throw "ассеты сима не собрались" }`.
`$SimData`/`$Fonts` дальше не используются (проверено grep). Больше в скрипте ничего не меняется.

`apps/line_sim/pipeline.yaml` строки 123-128 — только комментарий: плитка 410x484 = 2 звена x 205 px; борта фото
выровнены медианой строки вдоль X (без этого инструмент берёт 1 звено, 205x484); единственная команда сборки —
`python -m Services.line_sim.tools.build_stand_assets`. Значения YAML не трогать.

## FILES (полный список; нужен другой файл — стоп, спроси лида)

1. `Services/line_sim/tools/build_stand_assets.py` — новый модуль
2. `Services/line_sim/tests/test_build_stand_assets.py` — тесты автора
3. `scripts/run_sim_all.ps1` — блок ассетов -> один вызов
4. `apps/line_sim/pipeline.yaml` — только комментарий 123-128

(`Services/line_sim/tests/test_acceptance_6_5_stand_assets.py` пишет слепой tester; автор его не правит, только гоняет.)

## REDS (до кода модуля, файл 2)

- `Services/line_sim/tests/test_build_stand_assets.py::test_photo_rails_flat_body_equal`
- `…::test_tile_is_410x484x4`
- `…::test_letters_8_files_and_disk_300`
- `…::test_second_run_skips_and_keeps_bytes_and_mtime`
- `…::test_force_rebuilds_all`
- `…::test_partial_letters_group_rebuilt_and_junk_removed`
- `…::test_photo_rebuilt_forces_tile_and_unreadable_tile_rebuilt`
- `…::test_missing_fixture_exit_nonzero_nothing_written`
- `…::test_child_failure_exit1_error_line`
- `…::test_relative_data_dir_resolves_from_preset_repo_root`

## ACCEPTANCE (слепой tester без реализации; все пути — tmp, реальный `data/line_sim` не трогать)

1. Код 0; `belt_photo_full.png` 598x484x3 uint8.
2. Строки 0..21 и 463..483 собранного фото: std вдоль X == 0 по каждому каналу; пиксель ==
   `np.median(fixture[r], axis=0).astype(np.uint8)` (усечение; tester считает сам из фикстуры).
3. Строки 22..462 собранного фото байт-в-байт равны фикстуре.
4. `belt_tile.png` 410x484x4; stdout дочернего CLI содержит `period_px=205` и `size=410x484`.
5. `letters_ink`: ровно 4 подкаталога `А К Р Х`, в каждом ровно `DejaVuSans_s3.png`, `DejaVuSansMono_s3.png`
   (8 файлов); `letters_ink_disk.png` 300x300x4. Чтение — `imread_unicode`.
6. Первый прогон: среди строк stdout с префиксом `built `/`skipped ` ровно 3, по порядку
   `built belt_photo_full.png 598x484x3`, `built belt_tile.png 410x484x4`, `built letters_ink 8 files, disk 300x300x4`.
   Второй без `--force`: те же 3 с `skipped ` вместо `built `; у всех 11 файлов mtime_ns и байты не изменились.
7. `--force`: 3 строки `built …`, mtime_ns всех 11 файлов вырос.
8. Удалить `letters_ink/Х/DejaVuSansMono_s3.png` -> прогон без `--force`: `skipped belt_photo_full.png 598x484x3`,
   `skipped belt_tile.png 410x484x4`,
   `built letters_ink 8 files, disk 300x300x4`, снова 8 файлов.
9. `monkeypatch.setattr(build_stand_assets, "FIXTURES_DIR", <пустой tmp>)` -> код != 0, stderr содержит
   `preflight`, каталога `--data-dir` нет или он пуст.
10. `monkeypatch.chdir(tmp/elsewhere)` с абсолютным `--data-dir` -> п. 1-5 выполняются.
11. `monkeypatch.setattr(preset, "REPO_ROOT", tmp/root)`, `chdir(tmp/cwd)`, `--data-dir out` -> файлы в
    `tmp/root/out`, `tmp/cwd/out` не существует.
12. `--data-dir <tmp>/ассеты стенда` (кириллица и пробел) -> п. 1-6 выполняются.
13. Удалить только фото -> прогон без `--force`: `built belt_photo_full.png 598x484x3`,
    `built belt_tile.png 410x484x4`, `skipped letters_ink 8 files, disk 300x300x4`.
14. Обрезать `belt_tile.png` до 0 байт -> прогон без `--force`: код 0, `built belt_tile.png 410x484x4`.
15. `monkeypatch.setattr(make_seamless_texture, "main", lambda argv=None: 2)` на пустом `--data-dir` -> код 1,
    stderr содержит `ошибка шага tile`, `letters_ink` не создан. `make_font_letters.main` -> `raise SystemExit("x")`
    -> код 1, stderr содержит `ошибка шага letters`.
16. Положить `letters_ink/А/junk.png`, удалить `letters_ink_disk.png` -> прогон без `--force`: в `letters_ink`
    ровно 8 файлов, `junk.png` нет, диск 300x300x4.

Справочно (не порог): note тайла «резерв: 2 период(а), старт 105», шов ≈12.85, внутр. ≈17.42.

**Живая приёмка (лид):** (1) пиксели собранного фото и RGB собранного тайла равны файлам
`data/line_sim_original_2026-09-30/` — сравнение декодированных массивов, не sha PNG (кодировщик может отличаться);
(2) пустой `data/line_sim` (старое — в `data/line_sim_old_<дата>`, не удалять) -> `scripts/run_sim_all.ps1` поднимает
стенд на собранных ассетах; плитка в кадре ROI — 2 звена, шов бортов не виден.

## TESTS (через гейт; main `.venv`, `PYTHONPATH` — корень worktree; никакого `uv sync`)

```
cd D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/line-sim-6.5
PYTHONPATH="$PWD" PYTHONUTF8=1 bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-55 \
  D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python -m pytest -q --tb=short \
  Services/line_sim/tests/test_build_stand_assets.py Services/line_sim/tests/test_acceptance_6_5_stand_assets.py \
  Services/line_sim/tests/test_acceptance_look_1_1_period.py Services/line_sim/tests/test_acceptance_1_1b_font_tool.py
D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python -m ruff check -q Services/line_sim/tools/build_stand_assets.py Services/line_sim/tests/test_build_stand_assets.py
```
Доказать путь импорта из того же cwd: `python -c "import Services.line_sim.tools.build_stand_assets as m; print(m.__file__)"`
-> путь внутри worktree. Код 75 = гейт пропустил, не красный прогон (в отчёт «NO WINDOW»).

## OUT OF SCOPE

Фикстуры; логика `make_seamless_texture` / `make_font_letters` / `preset`; прочие рецепты и пресеты
(`presets/README.md` — его команда букв с DejaVuSans-Bold здесь не синхронизируется); `Plugins/sim/robot_host`,
`Services/robot_comm` (полоса R); статус в `plan.md`; реальные `data/line_sim` и `data/line_sim_original_2026-09-30`.

## TRAPS — опасности для автора

- Частичная сборка: тайл есть, букв нет (или 1 шрифт из 2 после падения второго вызова) — проверка «каталог
  `letters_ink` существует» (как в скрипте сегодня) пропустит неполную группу. Готовность = все файлы + чтение.
- Медиана — усечение `astype(np.uint8)`; `np.round` даёт 7774 пикселя мимо оригинала (п. 2 приёмки красный).
- LS-014: без очистки `letters_ink` перед пересборкой старые/чужие PNG остаются образцами класса.
- Маркеры lite для ревью кода: в докстринге модуля `Public API:` и `Stability: lite`, у `main` — `Pre:`/`Post:`
  (как `Services/robot_comm/core/client_v2.py`).
- `--data-dir` — только через `preset.resolve_repo_path`; своё `parents[3]` сломает п. 11 приёмки.
- `from … import main` вместо вызова через модуль — monkeypatch п. 15 не действует.
- Оба новых `.py` (модуль и тест) несут `__all__` и абзац `Purpose:` в докстринге модуля — contract-lite
  `scripts/pre_report_gate.py:165`; образец — `Services/robot_comm/tests/test_sim_e2e_v2.py`.
- Тесты пишут только в `tmp_path`; ни один тест не трогает реальный `data/`.
- Память: `feedback_a_decision_orphans_what_encoded_the_previous_one` — старый 205x484 тайл в живом `data/line_sim`
  переживёт прогон без `--force` (группа «готова»); миграция — пустой каталог или один `--force` (живая приёмка).

## Цели break-injection (лид пишет предсказания позже; по одной на свойство)

1. Выравнивание бортов (а) — отключено / только верхний борт / диапазон строк сдвинут на 1 / `np.round` вместо усечения.
2. Тело 22..462 не тронуто.
3. Тайл через `--force-period --gap-alpha` (снять любой флаг).
4. Аргументы букв (stroke/seed/шрифт) — ровно как в скрипте.
5. Пропуск готовой группы без `--force` (байты/mtime).
6. `--force` пересобирает все группы.
7. Готовность группы = все файлы (частичная группа пересобирается).
8. Готовность группы = файл читается (0-байтный тайл пересобирается).
9. Собранное фото тянет пересборку тайла — и между прогонами (удаление тайла до записи фото).
10. Очистка `letters_ink` перед пересборкой (junk удалён).
11. Предпроверка до первой записи (пустой `--data-dir` при отсутствии фикстуры).
12. Код 1 при провале дочернего CLI (`SystemExit` / исключение / код != 0) и останов следующих групп.
13. Разрешение `--data-dir` через `preset.REPO_ROOT`, не от cwd.

## Ответы лида (2026-10-13)

1. Относительный `--data-dir` — от корня репо через `preset.resolve_repo_path` (пути `pipeline.yaml` тоже от корня).
2. Проверки формы готового тайла нет. Строка `skipped belt_tile.png <размер>` печатает размер из файла — старый
   205x484 виден в консоли стенда. Миграция — пустой каталог или один `--force` (живая приёмка лида).
3. Порог — пиксельное равенство формуле усечения (п. 2 приёмки) и размер 410x484 с `period_px=205`; шов и note —
   справочно. Живая проверка лида — пиксели фото и RGB тайла равны `data/line_sim_original_2026-09-30/`.
4. (ревью кода, итерация 1) LS-014: группа `letters` готова, только если набор `*.png` под `letters_ink` в точности
   равен ожидаемым 8 путям и все читаются; лишний файл — пересборка с очисткой. Серый PNG в слоте — размер `…x1`, не падение.

HANDOFF IN: none
