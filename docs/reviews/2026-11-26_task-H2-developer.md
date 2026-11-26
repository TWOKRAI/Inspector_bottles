# Task H2 — негодное `plate_*` не отменяет загрузку рецепта (developer)

STATUS: DONE_WITH_CONCERNS

Ветка `fix/dcb-h2-plate-fallback`, коммит кода `7b9f32841`. Push и merge не делались.

## Итог

- `multiprocess_prototype/domain/entities/recipe.py`: новая функция `_load_display`, её зовёт `Recipe._coerce_displays`.
- Все ошибки экрана по ключам `plate_*`: ключи убираются из копии словаря, `from_dict` повторяется, на ключ одна строка WARNING.
- Хоть одна ошибка не по `plate_*` или с пустым `loc`: отказ, как раньше.
- `DisplayDefinition` и его тесты не менялись.
- `multiprocess_prototype/domain/tests/test_recipe_plate_fallback.py`: новый файл, 16 тестов.
- Сохранение из GUI умолчание поверх опечатки не пишет (проба ниже).

## Приёмка

| Критерий | Чем проверен | Результат |
|---|---|---|
| `holdd` у одного из двух экранов: рецепт грузится, у него `hold`, у второго как в файле | `test_other_display_keeps_its_plate` | зелёный |
| Одна строка WARNING на поле, с умолчанием, без плохого значения | `test_one_warning_per_bad_field`, `test_unknown_plate_key_is_dropped` | зелёные |
| Ошибка вне `plate_*` (`foo`): рецепт отклонён | `test_non_plate_error_still_rejects_recipe` | зелёный |
| `test_display_plate_fields*.py` зелёные без правок | прогон ниже | зелёные |

## Команды и вывод

Путь импорта (cwd = корень дерева, `PYTHONPATH="$(pwd -W)"`):

```
$ ../../../.venv/Scripts/python.exe -c "import multiprocess_framework as m; print(m.__file__)"
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\k-h2\multiprocess_framework\__init__.py
```

Все тесты шли через `machine_gate.sh <class> inspector-bottles-2a ../../../.venv/Scripts/python.exe -m pytest ... -p no:cacheprovider`.

RED до правки кода, только новый файл:

```
7 failed, 9 passed, 1 warning in 2.80s
```

Упали: `test_bad_plate_mode...`, `test_negative_plate_after_s...`, `test_one_warning_per_bad_field`,
`test_unknown_plate_key_is_dropped`, `test_wrong_type_in_string_plate_field`, `test_other_display_keeps_its_plate`,
`test_input_dict_is_not_mutated`.

Новый файл и `test_display_plate_fields*.py`, класс light:

```
39 passed, 1 warning in 3.83s
```

Финальный прогон по радиусу правки, класс light (новый файл, `test_display_plate_fields*.py`,
`test_hikvision_id3013_quad_recipe.py`, `test_entities_roundtrip.py`, `test_recipe_v3_no_corruption.py`,
`test_recipe_store.py`, `test_recipe_canonical.py`, `test_catalogs.py`, `test_display_catalog_session_blind.py`):

```
497 passed, 7 skipped, 2 warnings in 30.49s
```

NO WINDOW. Команда из брифа (`domain/tests -k plate`) гейтом переведена из light в medium и пропущена:

```
machine_gate: reclassified light -> medium (pytest_module_dir)
STAND WINDOW — skipped (machine_gate: medium, inspector-bottles-2a)
exit=75
```

Весь каталог `multiprocess_prototype/domain/tests` повторно запрошен в конце: снова exit 75. Он не прогонялся.

Статические проверки:

```
ruff check            -> All checks passed!
ruff format --check   -> 2 files already formatted
pyright (2 файла)     -> 0 errors, 0 warnings, 0 informations
sentrux check .       -> 43 rules checked, All rules pass
```

Инъекции поломок (после коммита, файл восстановлен `git checkout`):

| Поломка | Красный тест |
|---|---|
| `all` заменён на `any` | `test_plate_and_non_plate_error_together_rejects_without_warning` |
| убрана охрана пустого `loc` | `test_error_without_plate_loc_rejects_recipe[loc0]` |
| ключи удаляются из исходного словаря | `test_input_dict_is_not_mutated` |

Каждая поломка: `1 failed, 15 passed`.

## Пишет ли сохранение умолчание поверх опечатки

Проба на настоящих `RecipeEngine` + `RecipeManager` + `InspectorRecipeFormatHook` + `RecipeStoreFromManager` +
`DisplayCatalogFromRecipe`, временный файл. Скрипт: scratchpad сессии, `h2_probe/h2_roundtrip.py`.
Qt-виджеты не запускались: проба зовёт методы каталога и функцию сохранения графа напрямую.

Вход: экран `a` с `plate_mode: holdd   # опечатка`, `plate_after_s: -7`, `plate_mod: silence`; экран `b` с
`plate_mode: trigger`. После `store.read`: у `a` `('hold', 2)`, у `b` `trigger`.

| Действие | Файл после действия |
|---|---|
| `persist()` без правки | не изменён |
| правка `name` у `a` | `name: A2`; `holdd`, `-7`, `plate_mod` на месте |
| правка `name` у `b` | `name: B2`; блок `a` не изменён |
| выбор умолчания `plate_mode=hold` у `a` | не изменён, `holdd` остался |
| выбор `plate_mode=silence` у `a` | `plate_mode: silence # опечатка`; `-7` и `plate_mod` остались |
| выбор `plate_after_s=5` у `a` | `plate_after_s: 5`; `holdd` и `plate_mod` остались |
| добавление экрана `c` | блок `a` не изменён |
| удаление экрана `b` | блок `a` не изменён |
| `save_editor_topology_to_recipe` (Save графа) | `displays` не изменены |

Вывод: умолчание в файл не пишется. Значение не по умолчанию заменяет опечатку только в своём поле.
Выбором умолчания опечатку исправить нельзя. Неизвестный ключ `plate_mod` из GUI не убирается.

## Что я истолковал, а не взял буквально

- Строка WARNING повторяет форму GUI (`%s`). У `plate_text` и `plate_source` умолчание пустое, строка кончается на «взят ».
- WARNING пишется после удачного повтора `from_dict`. Если повтор упал, строк нет.
- Если позже упал другой экран или инвариант рецепта, строки по уже очищенным экранам остаются в логе.
- Вместо команды из брифа запускались явные файлы классом light (команда из брифа считается medium).
- Тестовый файл создан до сообщения `DESIGN/FILES` лиду; код продукта правился после него.

## Что оставлено открытым или ненадёжно

- Весь `domain/tests` и полный набор не прогонялись (NO WINDOW).
- GUI не запускался. Вкладка Displays вживую не проверена. Строку GUI из `recipe_displays.py` не проверял.
- Проверка пустого `loc` идёт на подставленной ошибке: у `DisplayDefinition` сейчас нет проверки всей модели.
- WARNING повторяется на каждом чтении рецепта (ожидаемо по брифу). Число строк на одно действие GUI не считал.
- Имя неизвестного ключа из файла пишется в лог без экранирования: ключ с переводом строки разорвёт строку.
- Было до правки: когда рецепт всё же отклонён, текст `ValidationError` содержит значения из файла, и
  `display_catalog_recipe.py:136-140` пишет его в лог.
- На экране пользователь не видит, что поле заменено умолчанием (вне задачи).

## Правки по ревью (APPROVED с замечаниями)

Этот раздел новее разделов выше: тестов в новом файле стало 20 (было 16).

1. `id` и неизвестный ключ в WARNING: если строка не `isprintable()`, пишется `ascii(строка)` (`_one_line`).
   У `id` в такой строке двойные кавычки: `дисплей ''a\n...''`.
2. Добавлены тесты: `my_plate_x` и `platex` отклоняют рецепт; перевод строки в ключе; перевод строки и ESC в `id`.
   `_load` пишет лог с уровня DEBUG, поэтому утечка значения через `info` или `debug` видна.

| Прогон (light) | Предсказание | Факт |
|---|---|---|
| новые тесты на коде без правки | 2 красных | `2 failed, 18 passed` |
| код с правкой | зелёный | `20 passed` |
| мутант `"plate_" in key` | `[my_plate_x]` | `1 failed, 19 passed` |
| мутант `startswith("plate")` | `[platex]` | `1 failed, 19 passed` |
| значение уходит в `logger.info` | 3 красных | `3 failed, 17 passed` |
| ключ без экранирования | 1 | `1 failed, 19 passed` |
| `id` без экранирования | 1 | `1 failed, 19 passed` |
| `all` -> `any` | 1 | `1 failed, 19 passed` |
| нет охраны пустого `loc` | 1 | `1 failed, 19 passed` |
| изменение входного словаря | 1 | `1 failed, 19 passed` |

Мутанты подменяли `_load_display` в памяти (pytest-плагин `h2_mut_plugin.py` в scratchpad). `sha1sum` исходника не изменился.
Радиус правки: `501 passed, 7 skipped`. `ruff check`, `format --check` чисто; pyright `0 errors, 0 warnings`.
Весь `domain/tests`: снова exit 75 (STAND WINDOW), не прогонялся.

## Отклонённые команды и красный хук

1. **Коммит правок по ревью не сделан.** `protect-branch.sh` отклонил `git commit`:
   `refusing 'git commit' on protected branch 'main'`. Дерево стоит на `fix/dcb-h2-plate-fallback`
   (`git branch --show-current`). Команду в другой форме я не повторял. Изменения лежат в дереве незакоммиченными.
   Причина по тексту хука: строка 42 перехватывает команду, только когда какая-то её строка начинается с `git commit`;
   строка 47 берёт ветку из текущего каталога хука, а не из каталога команды. Вывод по этому второму пункту:
   хук видел основную копию (`main`). Это вывод из сообщения хука, отдельно не проверялся.
2. Следствие: коммиты `7b9f32841` и `00fbb223a` шли формой `git add ... && git commit` в одной строке, и этот хук
   их не проверял. Они легли на ветку задачи (`git log` в дереве).
3. `pre_report_gate` красный: `pytest: cannot be imported` и совет `uv sync --extra dev` в дереве. Совет не выполнен:
   правило проекта запрещает `uv sync` в worktree (заменяет CUDA-сборку torch).

memory hits: `search.py recipe display plate validation fallback warning` -> 8 уроков; по описаниям близок
`feedback_a_silent_fallback_hides_a_tool_that_always_fails.md` (откат логировать).

MEMORY LESSON: нет.
