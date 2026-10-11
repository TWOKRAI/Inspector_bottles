---
name: a-plugin-in-addopts-runs-before-conftest-and-needs-pythonpath
description: "Плагин pytest из репозитория в addopts (-p pkg.plugin) импортируется ДО conftest.py: при cwd=multiprocess_framework/modules корня репозитория нет в sys.path (нет editable-установки), прогонщик ломается «No module named»; лечится ключом pythonpath в том же ini; на импорте плагина — только stdlib (conftest позже ставит spawn) / a repo pytest plugin in addopts imports before conftest and needs pythonpath"
module: [process_module]
mechanism: [test-infra, hooks]
role: reviewer
metadata:
  type: feedback
---

Бриф 0.5b требовал `-p scripts.lifecycle_guards.pytest_plugin` в `addopts` модульного `pytest.ini`. Приёмка из корня зелёная (`python -m pytest` кладёт cwd в `sys.path`), а прогонщик `scripts/run_framework_tests.py` (cwd = `modules`, CI без PYTHONPATH) падал: `ImportError: Error importing plugin "scripts.atlas": No module named 'scripts.atlas'`; `import scripts` там давал namespace-пакет pywin32. Ведущий не видел падения: в его worktree стоял `PYTHONPATH=<корень>`.

**Why:** у проекта нет build-system, в `.venv` нет editable-установки; плагин `-p` импортируется раньше `conftest.py`, а корень в путь вставляет именно conftest.

**How to apply:**
- Рядом с `addopts = -p …` в том же ini ставить `pythonpath = ../..` (относительно ini); проверка: `env -u PYTHONPATH python scripts/run_framework_tests.py <каталог> -q` и литерал раздела плагина в выводе — код 0 сам по себе не показывает, что плагин загружен.
- Приёмку «плагин подключён» писать литералом из его вывода, а не кодом возврата.
- На импорте плагина — только stdlib: `pytest_configure` из `modules/conftest.py` позже ставит `spawn`; `multiprocessing`, `PySide6`, `base_manager` — лениво внутри хуков.
- Подпроцессные тесты плагина: `cwd` во временной папке, `-c <tmp>/pytest.ini`, `PYTHONPATH=<корень>`, иначе подцепятся `addopts` и conftest репозитория.

Related: [[feedback-tests-of-process-global-state-run-in-own-process]]
