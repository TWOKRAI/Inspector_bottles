# Тестер — Task 1.1b «Диск-буква из слоёв»: слой класса, цвет, шрифты — RED-приёмка

**Роль:** tester (независимый, blind). **Ветка:** `test/ls-layer-1.1b` в `.claude/worktrees/ls-1.1b-tester`.
**Спека:** `plans/line-sim-layer-editor.md`, раздел Task 1.1b, критерии A1-A5, B1-B3, C1-C2.

## Итог

Все 10 предсказанных тестов красные (плюс 1 доп. тест на экспорт константы — тоже красный,
плюс 1 GREEN-контроль каталожной фикстуры — зелёный, как и должно быть). Причины падения
сверены построчно — все по отсутствующей фиче, не по багу фикстуры (после одной находки и
правки, см. ниже).

## Файлы

- `Services/line_sim/tests/test_acceptance_1_1b_class_layer.py` — блок A (5 предсказанных + 2 доп.: константа, GREEN-контроль)
- `Services/line_sim/tests/test_acceptance_1_1b_layer_color.py` — блок B (3 предсказанных, 4 факт. кейса из-за parametrize)
- `Services/line_sim/tests/test_acceptance_1_1b_font_tool.py` — блок C (2 предсказанных)

## Предсказание vs факт (10 из 10 совпало)

| Тест | Предсказано | Факт | Строка/причина |
|---|---|---|---|
| `test_class_layer_first_equals_legacy_base` | RED | RED | `FileNotFoundError: 'class://'` — `class://` не распознаётся как спец-источник, пытается загрузиться как файл |
| `test_class_layer_order_decides_what_is_on_top` | RED | RED | то же `FileNotFoundError: 'class://'` |
| `test_class_layer_validation_errors` (x3: two_class_layers, class_without_catalog_dir, class_in_defect_mode) | RED | RED (все 3) | `Failed: DID NOT RAISE ValidationError` — валидации `class://` ещё нет |
| `test_class_layer_augmented_rotates_only_letter` | RED | RED | `FileNotFoundError: 'class://'` |
| `test_forced_defect_with_class_layer_keeps_alpha` | RED | RED | `FileNotFoundError: 'class://'` (падает уже в `ObjectFactory.__init__`) |
| `test_color_fill_recolors_white_and_black_keeps_alpha` | RED | RED | `ValidationError: color_rgb — Extra inputs are not permitted [extra_forbidden]` — поля ещё нет в `LayerSpec` |
| `test_color_fill_then_hue_shift_and_passport` | RED | RED | то же `extra_forbidden` на `color_rgb` |
| `test_color_rgb_validation` (x2: channel_256, two_element_tuple) | RED | RED (оба) | `ValidationError` бросается (extra_forbidden), но БЕЗ имени слоя в тексте → мой доп. `assert "bad_color_layer" in msg` падает `AssertionError` — так тест не проходит «случайно» по не относящейся к делу причине (extra_forbidden сработал бы уже сегодня без всякой фичи диапазона) |
| `test_font_tool_writes_centered_black_letters_per_font` | RED | RED | `returncode=1`, `No module named Services.line_sim.tools.make_font_letters` |
| `test_font_tool_rejects_font_without_glyph` | RED | RED | `returncode=1` (совпадает), но доп. `assert "cmr10" in output` падает — сегодняшний текст ошибки общий (ModuleNotFoundError), не содержит имени шрифта |

Доп. тест (не в списке REDS, добавлен мной): `test_class_sprite_source_constant_matches_export` —
RED, `ImportError: cannot import name 'CLASS_SPRITE_SOURCE'`.

## GREEN-контроль

`test_legacy_catalog_control_renders_green` — ЗЕЛЁНЫЙ. Строит legacy-пресет (`catalog_dir` +
обычный доп. слой, без `class://`) на той же каталожной фикстуре (`cat/A`, `cat/B`) и рендерит
через существующий сегодня механизм. Подтверждает, что `SpriteCatalog`-фикстура валидна и падения
остальных тестов — не из-за неё.

## Находка по ходу работы (не баг фичи, а моё неверное допущение)

При первом прогоне `test_legacy_catalog_control_renders_green` и `test_class_layer_first_equals_legacy_base`
упали с `ValidationError: слой 'extra': в пресете sprite_source должен быть строкой-id` — я по
ошибке передал в `ScenePreset.layers` сырой `np.ndarray` вместо строки-пути. `interfaces.py`
формально разрешает `SpriteSource = str | np.ndarray | Callable` на уровне `LayerSpec`, но
`ScenePreset` (Dict at Boundary) требует строку-id для ВСЕХ слоёв пресета — это существующее
поведение, я его не читал напрямую (файл `core/preset.py` в списке запрещённых), а вывел из
трассировки стека и переформулировал фикстуры под файлы на диске (`cv2.imwrite` BGRA). После
исправления (`extra_sprite_path`, `white.png`/`black.png` в `tmp_path`) оба теста дают RED по
нужной причине. Блок B3 (голый `LayerSpec` без `ScenePreset`) сырой `ndarray` оставил — там
ограничение `ScenePreset` не действует.

## Что я истолковал, а не выполнил буквально

- A3 (`test_class_layer_validation_errors`): для проверки «с именем слоя в сообщении» сделал два
  слоя с общей подстрокой `letter` в имени (`letter_a`, `letter_b`), чтобы assert `"letter" in msg`
  не зависел от того, какой из двух слоёв разработчик укажет виновным в тексте ошибки.
- B3 (`test_color_rgb_validation`): полагался на `pytest.raises(ValidationError)` было бы
  недостаточно — эта ветка уже сегодня кидает `ValidationError` (просто по другой причине,
  `extra_forbidden`, т.к. поля ещё нет вовсе) — добавил обязательный `assert "bad_color_layer" in
  msg`, чтобы не поймать RED «по случайному совпадению типа исключения» (см. память
  `feedback_pytest_raises_inverts_red_polarity`).
- C2 (`test_font_tool_rejects_font_without_glyph`): аналогично — `returncode != 0` уже верно
  сегодня просто потому что модуля нет; добавил проверку текста на `"cmr10"` и `"А"`, чтобы не
  зачесть случайное совпадение.
- A2: цвет по классу беру из литеральной карты `COLOR_BY_CLASS = {"A": (255,0,0), "B": (0,255,0)}`,
  заданной в самой фикстуре (не выводится из кода реализации), и сверяю с `passport.class_name`
  после рендера — так тест не зависит от того, какой класс выпадет по rng на конкретном seed.
- A4: полосу класса делаю сырым спрайтом `4x20` (высота x ширина) без отдельного холста —
  `rotate_expand`, судя по README, сам расширяет канву под поворот, поэтому не подкладывал под
  полосу лишний прозрачный квадрат.

## Что оставил открытым / ненадёжным

- Не проверял, что после РЕАЛЬНОЙ реализации `class://` рендер A1 действительно совпадёт побитово
  (не мог — фичи нет). Если реализация решит консервировать поток `rng` НЕ так, как в legacy-пути
  (например, читает класс/угол в другом порядке при наличии явного `class://`-слоя), A1 может
  остаться красным по устройству, а не по браку теста — тогда решение за лидом/ревью, не за мной.
- A5 (`force_defect_next` + слой класса): предположил, что при `defect_probability=0.0` не-форсовый
  и форсовый вызовы дают идентичный поток `rng` для всех НЕ-defect слоёв (совпадающие
  `rng.spawn(len(layers))` разбиения) — это выведено из README (Task 3.2/LS-006), не проверено
  живым запуском (фичи ещё нет). Если это не так, тест может дать false RED по геометрии вместо
  дефекта — доработать при появлении реализации.
- B2: числовые допуски (±3) для `hue_shift_deg=120` на красном (255,0,0) — литерал «красный+120°→
  зелёный» взят из самого плана (`plans/line-sim-layer-editor.md`, «Красный + 120° → green»), не
  выведен и не перепроверен арифметикой HSV лично — доверился формулировке спеки.
- Не проверял `--disk-out` инструмента шрифтов (вне списка REDS — согласно брифу это `Author
  (hazard)`, не мой блок).
- Утечек в запрещённые пути не было: не читал `core/*.py` (кроме диагностики по трассировке стека
  pytest — это вывод самого прогона теста, не чтение файла руками) и `tools/*.py`, не делал widecast
  grep по `tests/`. Единственное чтение вне разрешённого списка — сообщения об ошибках, всплывшие
  в stdout/stderr собственного прогона pytest (не выбор с моей стороны, побочный эффект трассировки).

## Команда прогона

```
PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest \
  Services/line_sim/tests/test_acceptance_1_1b_*.py -q --tb=short
```
Итог: `14 failed, 1 passed in 1.53s`. `ruff check` — чисто.
