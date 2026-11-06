# Task map-A1 — отчёт тестера (RED)

STATUS: RED ready — 14 собрано, 14 упали, 0 ошибок сбора; все 14 с `ModuleNotFoundError: No module named 'scripts.atlas.scan'` (подкласс ImportError). Контракт — текст задачи `plans/2026-10-04_atlas/tasks/map-A1.md` (interface.py нет).

Parsed: MODE=red, INTERFACE=none (контракт = текст задачи), TASK=map-A1, PLAN=plans/2026-10-04_atlas/tasks/map-A1.md.

## Команды
- `python -c "import scripts.atlas as m; print(m.__file__)"` -> `...\.claude\worktrees\atlas-map\scripts\atlas\__init__.py` (внутри worktree).
- `pytest scripts/atlas/tests/test_scan.py --collect-only -q` -> `14 tests collected`.
- `pytest scripts/atlas/tests/test_scan.py -q --tb=line -p no:cacheprovider` (через machine_gate light inspector-bottles-32) -> `14 failed, 1 warning in 2.04s`.
- `ruff check -q scripts/atlas/tests/test_scan.py` -> чисто.

## Что прочитано / не прочитано
Прочитано: задача, `conftest.py`, `test_core_store_tree.py:1-80`, `tree.py` (имена и Tree). Не открыты: `scripts/arch_map/`, `docs/reviews/2026-11-06_task-atlas-map-A1-stage0*.md`, `docs/reports/2026-11-06_atlas-map-merge-design.md`, `store.py`, `adapters/code.py`.

## Что истолковано, а не выполнено дословно
- Все сценарии с git и sqlite идут в `run_with_deadline` целиком (соединение sqlite открывается внутри потока: иначе `check_same_thread`). Чистые `scan_text`/`DictSource` без кэша идут в основном потоке, цепочки 600 и 3000 членов тоже: глубокая рекурсия в побочном потоке Windows может упасть по стеку, а не по RecursionError.
- Красный 9: «после обоих вызовов ровно 1 вызов ls-tree» считаю между `files()` и `oids()` на новом `Tree`; последующий `scan` на том же `Tree` в счёт не входит.
- Красный 3: `except` без `Exception`-тела, голый `except:` и т.д. проверены по одному одноимпортному источнику каждый (цикл по четырём заголовкам), одна запись `q` в каждом.
- Красный 5: статус `internal` утверждаю только там, где задача называет `Resolved("internal", ...)`; в остальных — только `targets`/`unresolved`.
- Красный 9: база кэша лежит в `tmp_path` рядом с репозиторием (`repo.path.parent / "atlas.sqlite"`).
- Красный 13: байты `b"\xef\xbb\xbfimport os"` и все `DictSource` с байтами проходят через `scan`, остальное через `scan_text`.

## AMBIGUOUS
Меток `# AMBIGUOUS` в файле нет: двух прочтений литералов не нашёл.

## Что оставлено открытым / ненадёжно
1. Красный сейчас только на отсутствии модуля: проверить, что утверждения верно ловят неправильное поведение, можно только инъекциями лида после GREEN. Тела утверждений ни разу не выполнялись.
2. Литералы oid `96766802…` и пара `DictSource.oids() == Tree.oids()` в красном 1 держатся на `core.autocrlf=true` на машине (`repo.write` на Windows пишет CRLF, блоб LF по задаче). Без этой настройки блоб будет CRLF и красный 1 упадёт не по вине кода. Не проверено, что настройка глобальная, а не локальная в фикстуре.
3. Красный 13: литерал `RecursionError` для 3000 членов зависит от версии Python (3.12.12) и лимита рекурсии; в побочном потоке и при другом лимите может не совпасть.
4. Красный 9: `monkeypatch.setattr(tree_module.subprocess, "run", ...)` подменяет `subprocess.run` глобально (модуль `subprocess` общий), поэтому счёт ведут и вызовы `repo.git`; список очищается перед каждым `scan`. Если реализация вызовет git не через `subprocess.run` (например `Popen`), счёт её не увидит и тест даст ложный зелёный по числам процессов (по нулю вызовов он упадёт, ожидаются 2).
5. Красный 3 ожидает `kind == "lazy"` для `def` внутри `try` и `guarded is False` — прямо по задаче; `ImportRec.names` для `import q` — `()` (R1/красный 2).
6. Тесты автора (блок после красных) не писались: это зона GREEN.

memory hits: search.py blind tests atlas scan -> none relevant (первые 8 строк — про другие механизмы).
MEMORY LESSON: none
