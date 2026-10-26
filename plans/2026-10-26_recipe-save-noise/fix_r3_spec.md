# Фикс после ревью р2 (1.1a, 1.1b, 1.1h) — спека лида, 2026-10-26

Пробы ревьюера лежат в `…\b0a34eda-…\scratchpad\rv\`: p30, p31, p32, p33. Запускать их только через light-гейт.

## 1. F1 — кортеж в страховке (`recipe/yaml_io.py`)

Сейчас `_plain` переводит в plain только dict и list. Для tuple `_kind` возвращает `other`, а `_equal(list, tuple)` даёт False. В итоге `update_yaml_preserving(p, {"k": (1, 2)})` падает с ValueError, хотя старая версия писала `k: [1, 2]`.

Правка:
- `_plain` переводит tuple в list;
- `_kind` относит tuple к списку.

Тесты:
- в `test_thin_contracts.py`: `update_yaml_preserving(p, {"k": (1, 2)})` → в файле `k:` со списком, PyYAML читает `[1, 2]`;
- в `test_yaml_patch.py`: `patch_yaml_preserving(новый, {}, {"k": (1.0, 2.0)})` пишет список.

## 2. AssertionError ruamel → ValueError (`recipe/yaml_io.py::_dump_atomic`)

В `_dump_atomic` ловить AssertionError только вокруг `yaml.dump`. Перебрасывать `ValueError("<путь>: дамп ruamel не удался — запись отменена, файл цел")` с `from exc`. Ловить шире не нужно.

Тест: подменить дампер так, чтобы он бросал AssertionError (monkeypatch на объекте yaml или на функции дампа). Проверить ValueError и что байты файла прежние.

## 3. F2 — flow-стиль навсегда (`recipe/_ruamel_doc.py::_evacuate_emptied` + `yaml_io._Delta.run`)

Сейчас `_evacuate_emptied` ставит `container.fa.set_flow_style()`. Если карту целиком заменяют другими ключами, все старые ключи удаляются, контейнер становится flow, затем приходят новые ключи, и стиль остаётся flow. Это даёт шум на 9 из 22 рецептов (p31).

Правка:
- в момент опустошения запомнить исходный стиль контейнера, а flow не ставить;
- в конце `_Delta.run`, до дампа, финализировать: контейнерам, которые остались пустыми, поставить flow (`[]`/`{}`); заполненным вернуть исходный стиль.

Тест в `test_thin_contracts.py`: `update_blueprint_metadata_preserving(рецепт с блочным gui_positions, {"gui_positions": {"main": [1, 2]}, "locked_nodes": ["a"]})`. Ожидание: `gui_positions` остаётся блочной картой с ключом `main:` на своей строке. Байты — литералом. Синтетика той же формы, что в `phone_inspect.yaml` / `line_filter_inspect.yaml`.

Регресс-проверка: тесты опустевшего контейнера (`items: []`, `locked_nodes: []`) по-прежнему зелёные, файл пишется во flow.

## 4. F3 — тест читателя без времени (`recipe/tests/test_file_lock.py::test_atomic_write_retries_while_reader_holds_file`)

Сейчас обе границы держатся на `threading.Timer` (0,06 и 0,5 с). Под нагрузкой тест красный в 21–25 случаях из 25 (p32).

Правка, без времени:
- обернуть `service.os.replace` счётчиком, настоящая PermissionError от открытого читателя сохраняется;
- `time.sleep` в service подменить пустышкой.

Два варианта:
- позитив: читатель закрывается на 2-й отказавшей попытке → запись прошла, попыток ровно 3;
- негатив: читатель не закрывается → PermissionError ровно после `_REPLACE_ATTEMPTS` (=5) попыток.

Литералы 3 и 5 — в тесте, не из кода. Если в тесте остаётся поток, то это daemon-поток с join-дедлайном.

## 5. 1.1h POSIX (`recipe/file_lock.py`)

(а) `_try_lock` должен ловить только «лок занят»:
- POSIX: `BlockingIOError`;
- Windows: `OSError` с errno 13 (EACCES) или 36 (EDEADLOCK).

Прочие OSError пробрасываются как настоящая причина, а не превращаются в `RecipeLockTimeout`.

(б) `_unlock` в `finally` не должен затирать исходную ошибку. Ошибку `_unlock` при уже летящем исключении логировать или подавлять с `__context__`. Без исходного исключения — пробрасывать.

Тесты:
- `_try_lock` на закрытом fd (EBADF) → OSError, не `RecipeLockTimeout` (литерал errno не нужен, достаточно типа и «не timeout»);
- исключение внутри `with recipe_file_lock(...)` всплывает исходным, даже если `_unlock` бросает (подменить `_unlock`).

## Не делать

- float без точки (`1e-05`) и строки `On`/`yes`/`12:30` (громкий отказ страховки) — отдельная задача, вопрос в OPEN_QUESTIONS (1.3);
- `fork` с общим дескриптором — запись в ADR (1.3).

## 6. Новый дефект HEAD — AssertionError в `representer.merge_comments` (найден hypothesis, коммит `f5b0b19ac`)

`test_property_patch_with_comments_reaches_after` красный на HEAD. Пример сохранён в локальной `.hypothesis`.

Вход:
```
# c0\nk:  # e1\n  # c2\n  -  # e3\n    # c4\n    k:  # e5\n      # c6\n      k: null  # e7\n      # c8\n      ka: null  # e9\n
```
after: `{"k": [{"k": {}, "knew": 1}], "knew": 1}`.

Что сделать:
- Найти корень и починить в `_ruamel_doc.py`. Вероятно, два токена в одном слоте или разделение заголовка элемента (ср. `_share_item_header`).
- Пример закрепить детерминированно: `@example(...)` у property-теста или отдельный литеральный тест. Он не должен зависеть от локальной базы hypothesis.
- Если починить корень нельзя, допустим отказ `ValueError` при целом файле (через п. 2) — только с ESCALATION к лиду и объяснением. Ослаблять property-тест нельзя.

## 7. Новый дефект HEAD — дубль комментариев при опустошении элемента списка

Вход (из T6 `item_emptied`):
```
p:\n  - n: gui\n    meta: {}\n  # lead\n  - a: 1\n    # inner\n    b: 2\n  - n: z\n
```
При `p[1] = {}` в файле дважды встречаются `# lead` и `# inner`. Файл валиден, `load == after`.

Ожидание: каждый комментарий ровно один раз. Включить счёт комментариев в T6[item_emptied] (сейчас он там не проверяется).

## 8. Мелочь: имя T7

`test_scalar_replaced_by_container_drops_scalar_eol_comment_no_glue`: склейка на ruamel 0.19 не воспроизводится, тест страхует снятие EOL-комментария. Переименовать: `..._drops_scalar_eol_comment`.
