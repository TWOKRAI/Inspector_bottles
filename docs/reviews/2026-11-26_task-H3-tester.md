# H3, tester: проверка переноса строки на плашке

STATUS: DONE_WITH_CONCERNS

## Итог

`test_plate_wraps_and_every_exit_unwraps` теперь снимает минимум метки перед замером высоты.
Под инъекцией «текст обрезан» новый тест красный, старый зелёный. Код плашки не изменён.

Изменение: `multiprocess_prototype/frontend/tests/test_plate_modes_blind.py`, после `assert label.wordWrap() is True`
добавлен вызов `label.setMinimumSize(0, 0)` и строка комментария. Сама проверка высоты не менялась.

## Окружение

- Ветка `test/dcb-h3-plate-wrap`, база `1b61ca8c6`. Она впереди локального `main` (`eaaf82a60`, это merge-base).
  `git diff --stat main HEAD` по `display_slot.py` и по тесту пуст.
- Импорт: `...\.claude\worktrees\k-h3\multiprocess_framework\__init__.py`, `...\k-h3\multiprocess_prototype\__init__.py`.
- Qt offscreen, команды через `machine_gate.sh light inspector-bottles-2a`, `PYTHONPATH=$(pwd -W)`.

## Базовый прогон

`../../../.venv/Scripts/python.exe -m pytest multiprocess_prototype/frontend/tests/test_plate_modes_blind.py -q --tb=short -p no:cacheprovider`

```
42 passed, 1 warning in 26.77s
```

Старый файл (`git show HEAD:<файл>`, временная копия `test_zz_h3_old_tmp.py` рядом, после прогона удалена): `42 passed`.

`ruff check`: `All checks passed!`. `ruff format --check`: `1 file already formatted`.

## Прогноз (объявлен до инъекций)

| Инъекция | Новый файл | Старый файл |
|---|---|---|
| A: `setText(text[:10])`, `wordWrap` = `True` | 6 красных: `wraps` x3, `test_silence_threshold_per_display`, `test_next_frame_removes_silence_plate`, `test_mode_change_to_hold_on_rebuild` | 3 красных (последние три), `wraps` зелёные |
| B: `setWordWrap(False)`, текст длинный | `wraps` x3 | `wraps` x3 |

## Факт

| Инъекция | Новый файл | Старый файл |
|---|---|---|
| A | `6 failed, 36 passed` | `3 failed, 39 passed` |
| B | `3 failed, 39 passed` | `3 failed, 39 passed` |

Наборы красных тестов совпали с прогнозом поимённо.

A, новый тест, все три параметра:

```
test_plate_modes_blind.py:491: assert 12 >= (2 * 12)
```

A, три посторонних красных (одинаковы в обоих файлах): строки 260, 312, 331. Они читают текст метки,
а обрезка срезает «нет кадров» (`assert 'нет кадров' in 'Один · № —'`).

B, оба файла:

```
test_plate_modes_blind.py:487: assert False is True      # label.wordWrap()
```

## Ответ про вторую поломку (`wordWrap(False)`)

Тест красный, но на проверке флага (строка 487). До проверки высоты выполнение не доходит.
Поэтому высота измерена отдельной пробой вне дерева (`h3_probe.py` в scratchpad, `2*fm = 24`):

| Состояние кода | `wordWrap` | длина текста | h4w(320) с минимумом | h4w(320) без минимума |
|---|---|---|---|---|
| исходное | True | 120 | 240 | 68 |
| A | True | 10 | 240 | 12 |
| B | False | 120 | 240 | 12 |

Без минимума проверка высоты сама различает B (12 < 24). С минимумом все три состояния дают 240.

## Откат

После каждой инъекции `git checkout -- display_slot.py`. Итоговый `git diff --stat` этого файла пуст,
`git status --short` показывал только тестовый файл.

## Что истолковано, а не выполнено буквально

- Старый тест запущен как временная копия всего файла в том же каталоге, чтобы действовали те же conftest.
- Инъекции наложены через `sed` одним скриптом с `trap` на откат. В скрипте осталась лишняя строка
  `sed -i ... /dev/null`; она дала сообщение `couldn't edit /dev/null` и ничего не изменила.

## Что осталось открытым или ненадёжным

- Порог «не меньше двух строк» ловит только текст, который уложился в одну строку. Обрезка, после которой
  остаётся две строки и больше, пройдёт. Это вывод из условия, прогоном не проверен. Полный текст метки
  (`label.text() == _LONG_TEXT`) этот тест не сравнивает; DESIGN этого не просил.
- Замер идёт после снятия минимума, то есть проверяет способность метки переносить текст, а не то, что
  видно в слоте на экране.
- Числа 68 и 12 получены offscreen: Qt сообщает, что не нашёл каталог шрифтов. На настоящей платформе
  метрики будут другими; там тест не запускался.
- Запускался только этот файл.

memory hits: `python <main>/scripts/memory/search.py qt label word wrap height minimum test injection` ->
вывод обрезан до первых 8 строк; по `description` прямо про перенос строки или высоту QLabel среди них нет.

MEMORY LESSON: none
