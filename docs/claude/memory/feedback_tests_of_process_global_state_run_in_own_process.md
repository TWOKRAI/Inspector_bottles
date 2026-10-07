---
name: tests-of-process-global-state-run-in-own-process
description: "Тесты, меняющие глобальное состояние процесса (gc.freeze/unfreeze), идут в своём интерпретаторе; «вернуть как было» хелпером приблизительно и флакует на другой платформе / tests that flip process-global state run in a child process, never restore it by helper"
module: [process_module]
mechanism: [test-infra, fixtures]
role: teamlead
metadata:
  type: feedback
---

T1: тесты механизма заморозки звали настоящие `gc.freeze`/`gc.unfreeze` в общем прогоне pytest и размораживали сессионную кучу (~670 тыс. объектов): следующая граница платила 170–282 мс. Хелпер «вернуть заморозку» (unfreeze → collect(1) → freeze) прошёл ревью, а на CI Linux споткнулся: `gc.get_freeze_count()` не монотонен (замороженный объект, умерший по refcount, уменьшает счётчик: −6 на CI, −51 в опыте на 50 объектах), а полный `gc.collect()` после `unfreeze` на CPython 3.12 возвращает 377 объектов без `freeze`.

**Why:** глобальное состояние процесса нельзя вернуть точно: повторный `freeze` замораживает уже другой набор объектов. Допуск `abs(delta) < 100` лишь прячет это. Причина — тест трогает состояние родителя.

**How to apply:** тесты, которые меняют глобальное состояние процесса, исполнять в дочернем интерпретаторе: `collect_ignore` в `conftest.py` + одна тест-обёртка (`subprocess`, `timeout`, `pytest.fail` на зависание, итоговая строка `startswith("26 passed")`, `dict(os.environ, …)` и без `PYTEST_ADDOPTS`); страж по AST (R4) не пускает такие вызовы в тест-файлы вне `collect_ignore`; «родитель не затронут» доказывать объектом-часовым, не счётчиком. Измерять внутри сессии: старт `pytest.main` сам ставит политику и размораживает кучу.
