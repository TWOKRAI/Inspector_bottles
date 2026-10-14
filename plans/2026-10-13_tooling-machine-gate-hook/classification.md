# Таблица классификации — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

> Вынесено из плана 2026-10-13 (бюджет размера документа 32 КБ). Контракт для тестов; литералы, не из кода.
> Ответ владельца 2026-10-13: добавлен класс `medium` (~2–5 мин) — правило в плане, раздел «Ответы владельца»; таблицу под него правит Task 1.1.


`classify` режет строку на сегменты по `&&`, `||`, `;`, `|`, переводу строки. Сегмент, в котором есть
`machine_gate.sh`, пропускается: его классифицирует сам гейт. Для каждого остального сегмента печатается
одна строка `<kind>\t<reason>\t<сегмент>`, где `kind` ∈ {`heavy`, `light`}. Сегменты класса «нет»
не печатаются. Пустой вывод значит «тестовых команд нет». Код выхода всегда 0.

Команда распознаётся **только в позиции команды**: в начале сегмента, после необязательных `VAR=val`,
`timeout N`, `uv run [--опции]`, `<python> [-опции] -m`. Слово в аргументах (`grep pytest`) не в счёт.

| # | Сегмент | kind | reason |
|---|---|---|---|
| C1 | `python scripts/run_framework_tests.py` | heavy | `run_framework_tests` |
| C2 | `uv run --no-sync python scripts/run_framework_tests.py -k recipe` | heavy | `run_framework_tests` |
| C3 | `powershell -File scripts/run_sim_all.ps1` | heavy | `run_sim_all` |
| C4 | `python scripts/validate_commit/check_injections.py --plan x` | heavy | `injection_matrix` |
| C5 | `python scripts/mutation_gate.py` | heavy | `injection_matrix` |
| C6 | `python backend_ctl/probes/break_inject_g3_seams.py` | heavy | `injection_matrix` |
| C7 | `uv run --no-project python .claude/plugins/mcp-qex/reindex_retry.py` | heavy | `qex_index` |
| C8 | `python scripts/qex_retry.py` | heavy | `qex_index` |
| C9 | `pytest -q` | heavy | `pytest_no_file_args` |
| C10 | `python -m pytest multiprocess_framework/modules` | heavy | `pytest_no_file_args` |
| C11 | `pytest -n 4 a/tests/test_x.py` | heavy | `pytest_xdist` |
| C12 | `.venv/Scripts/python.exe -m pytest -q --tb=short Services/robot_comm/tests/test_kinematics_v2.py` | light | `pytest_files` |
| C13 | `PYTHONPATH=/d/wt pytest a/tests/test_x.py::test_one -q` | light | `pytest_files` |
| C14 | `cd /d/wt && pytest -q` | heavy (2-й сегмент) | `pytest_no_file_args` |
| N1–N8 | `grep -n pytest pyproject.toml`; `git log --grep=pytest --oneline`; `cat pytest.ini`; `rg run_framework_tests scripts`; `git show HEAD:scripts/run_sim_all.ps1`; `echo pytest`; `pip show pytest`; `ls` | — (пустой вывод) | — |

Правило pytest: `light` только если есть хотя бы один аргумент вида `*.py` или `*.py::*` **и** нет аргумента-пути
без `.py` (токен с `/` или `\`, не начинающийся с `-`) **и** нет `-n`/`-n=`/`-nN`/`--numprocesses`. Иначе `heavy`.
Скрипты C1–C8 узнаются по имени файла (basename) в позиции аргумента python/powershell.

Гейт в режимах `heavy|light` вызывает `classify "$*"`. Заявка `light`, а классификатор сказал `heavy` →
дальше гейт работает как `heavy` и пишет в stderr `machine_gate: reclassified light -> heavy (<reason>)`.
Заявка `heavy` никогда не понижается.
