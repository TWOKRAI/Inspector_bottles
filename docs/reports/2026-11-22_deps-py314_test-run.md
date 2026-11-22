# Полный прогон тестов на Python 3.14 (стек A) — 2026-11-22, MacBook

**Суть.** Ветка `chore/deps-py314` (Python 3.14.7, PySide6 6.12, numpy 2.5, opencv 5.1, pydantic 2.14, pymodbus 3.16) прогнана полным набором на macOS. **База на 3.12 (стек B) НЕ снималась** (решение владельца: сравнивать позже, на Windows). Поэтому красные не классифицированы: кто красный из-за 3.14, а кто красный и на 3.12 — неизвестно.

**Итог.** 34 790 прошло, 728 красных (341 failed + 10 errors framework, 238 services, 6 plugins, 1 prototype, 132 misc). Слиянию `chore/deps-py314` это мешает, пока красные не сравнены с базой.

## Таблица A (Python 3.14.7)
| блок | всего | passed | failed | error | skipped | время |
|---|---|---|---|---|---|---|
| framework (`multiprocess_framework/modules`) | 14 610 | 14 203 | 341 | 10 | 54 (+2 xfailed) | 1406,7 с |
| Services | 8 047 | 7 768 (+2 xpassed) | 238 | 0 | 39 | 819,0 с |
| Plugins | 2 765 | 2 751 | 6 | 0 | 8 | 780,8 с |
| prototype (`multiprocess_prototype`) | 4 995 | 4 962 | 1 | 0 | 32 | 210,0 с |
| misc (apps, scripts, Utils, examples, robot) | 5 255 | 5 106 | 132 | 0 | 17 | 1095,9 с |
| backend_ctl | не запускался | | | | | |

## Команды (повторить на другой машине и на 3.12)
Переменные: `PYTHONUTF8=1`, `PYTHONPATH=<корень дерева ветки>`. Общий хвост: `-q --tb=short -p no:cacheprovider --timeout=300 -rfEs --junitxml=<каталог>/<блок>.xml`. Каждая команда через гейт: `bash "<основное дерево>/scripts/machine_gate.sh" heavy <сессия> <команда>`.
- framework: cwd `multiprocess_framework/modules`, `python -m pytest` (без путей, `pytest.ini`);
- services: cwd корень, `python -m pytest Services`;
- plugins: `python -m pytest Plugins`;
- prototype: `python -m pytest multiprocess_prototype`;
- misc: `python -m pytest apps scripts Utils examples robot`;
- backend_ctl (не выполнялся): `python -m pytest backend_ctl -m "not harness_smoke"`.

Список красных (имена, по блокам, `# <блок>`): `2026-11-22_deps-py314_test-run_failed.txt` рядом. Имена из junit (`classname::name`), точный nodeid может отличаться точками в имени модуля.

## Красные: топ причин по первой строке ошибки (junit)
- **framework (351):** `OSError: [Errno 28] No space left on device` — 232 failed + 8 errors при setup (при 242 ГБ свободных на `/`; гипотеза — лимит POSIX shm/семафоров macOS, тот же класс, что C-93; не проверено); `assert False is True` — 41; `KeyError: 'data'` — 13; `assert None is not None` — 10. Больше всего в `process_manager_module` (118) и `process_module` (109).
- **services (238):** сравнения float с расхождением последнего знака (`27.027821779556117` против `27.02782177955612`) — 24; различия числа внутри JSON-строки `{"damaged": ...}` — 24. Причины не разбирались.
- **plugins (6):** все разные (идентификаторы потоков в показании, словарь `device_id`, `18273 == 18255`, два хэша, `class_layer`).
- **prototype (1):** `register-поля Plugins+Services разошлись со снимком catalog_register_fields.txt: появились ['robot_io.forward_ok', 'robot_io.last_dropped_job']` — похоже на устаревший снимок относительно кода, а не на 3.14 (проверить на 3.12).
- **misc (132):** `AssertionError: код=0` — 46; `код=2` — 40; `код=124` (таймаут) — 7; `date: illegal…` (вывод BSD `date` на macOS вместо пустого) — 6; `axis: dead (thread crashed 0/2…)` — 3.

## Что оставил открытым / ненадёжным
- База 3.12 не снята: красные не сравнены (нужен тот же прогон `.venv` на 3.12; версии пакетов различаются: pytest 9.2.0 / pytest-asyncio 1.5.0 / PySide6 6.12.0 на 3.14 против 9.0.3 / 1.3.0 / 6.10.3 на 3.12, поэтому разница будет и от пакетов).
- `backend_ctl` на 3.14 не запускался; живой стенд не поднимался.
- `pytest-qt` не установлен ни на одном стеке (`ModuleNotFoundError: pytest_qt`): тесты с `qtbot` могут падать или не собираться.
- Ложные красные на macOS вероятны (shm/семафоры, BSD `date`); окончательно — по сравнению с Windows и базой 3.12.
- Время framework и misc получено под фоновой нагрузкой других процессов.
- Три теста `layer_render` красные на 3.14 и зелёные на 3.12 (из ранней пробы, подозрение на opencv 5.1) — в этом прогоне отдельно не подтверждались.
- Число тестов не сходится: ранний `--collect-only` дал 21 714, а блоки выше суммарно дают около 35 тысяч (вероятно, ранний сбор шёл по другому набору путей). Расхождение не разбиралось.
- Windows и Orin NX (torch под JetPack) проверены только метаданными.
