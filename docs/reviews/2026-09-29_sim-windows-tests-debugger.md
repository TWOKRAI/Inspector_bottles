# sim-win: 10 стабильных падений Plugins/sim + Services/line_sim на Windows (debugger, 2026-09-29)

Ветка `fix/sim-windows-tests`. Команда: `PYTHONPATH=$PWD .venv/Scripts/python.exe -m pytest -q --tb=short Plugins/sim Services/line_sim`.
До: 13 failed / 549 passed / 3 skipped. После (два прогона): 1 failed / 561 passed / 3 skipped и 2 failed / 560 passed / 3 skipped.
Все 10 стабильных зелёные в обоих прогонах. Оставшиеся падения — плавающие (см. ниже). Skip/xfail не добавлено.

| # | Тест(ы) | Причина | Сторона | Фикс | SHA |
|---|---|---|---|---|---|
| 1 | test_precondition_plain_bind_on_time_wait…; test_start_listener_raises_when_port_taken_by_foreign | pymodbus 3.13 жёстко `reuse_address=True`; на Windows SO_REUSEADDR = bind ПОВЕРХ живого слушателя, `start_listener()` не падал. TIME_WAIT на Windows bind не блокирует вовсе (замер) | (a) продукт + (b) предусловие | `Services/robot_comm/server/sim_robot.py`: подкласс `ModbusTcpServer` (только win32) с сокетом `SO_EXCLUSIVEADDRUSE` -> `create_server(sock=)`; без гонки. Предусловие теста на win32 фиксирует факт платформы (bind проходит) | 3bcb4405 |
| 2 | test_a3_collapse_runs; test_wire_collapses_consecutive_repeats | склейка работала (n=303 верно); строгое `t >` ломал `time.monotonic` = GetTickCount64, шаг ~15.6 мс | (c) продукт | `Services/robot_comm/server/sim_journal.py`: часы по умолчанию `time.perf_counter` | df585c58 |
| 3 | test_commit_keeps_file_mode | Windows: chmod меняет лишь read-only, `st_mode` пишемого файла всегда 0o666; commit права сохраняет корректно | (b) | сравнение прав до/после вместо литерала 0o644 (на POSIX предусловие 0o644 сохранено) | 1a3a2c35 |
| 4 | test_h8_…; test_texture_channel_order_in_frame | `os.path.relpath` C:(temp)/D:(репо) в самом тесте; продукт `relpath` в этом пути не зовёт | (b) | фикстура `repo_texture_dir` (mkdtemp в `data/`, gitignored) | a536943e |
| 5 | test_font_tool_writes_centered…; test_font_tool_rejects_letter_wider… | `cv2.imread` не открывает кириллический путь; окружение потомка без SYSTEMROOT роняет интерпретатор (WinError 10106) | (b) | `imread_unicode`; SYSTEMROOT + PYTHONIOENCODING=utf-8 + encoding=utf-8 | 7eab6ac3 |
| 6 | test_save_as_on_windows_writes_forward_slashes | на Windows `os.path` is `ntpath`: подмена `relpath` лямбдой, зовущей `ntpath.relpath` по имени -> RecursionError; `to_yaml` слэши нормализует верно | (b) | ссылка на настоящий `ntpath.relpath` берётся до подмены | ea197959 |

Про relpath между дисками в продукте: `Services/line_sim/core/preset.py::_rebase_value` уже ловит `ValueError` и откатывается на абсолютный путь (тест `test_rebase_falls_back_to_absolute_when_relpath_raises` зелёный) — продуктового дефекта в кросс-дисковом сценарии нет.

## Проверка, что тесты ловят регрессию
- #1: до фикса `test_start_listener_raises_when_port_taken_by_foreign` красный (DID NOT RAISE); удаление подкласса возвращает красное — это исходное состояние. Break-injection полноценно не гонял (за лидом).
- #2: до фикса красные оба; вернув `time.monotonic` — красные.

## Что интерпретировал, а не выполнил буквально
- FILES п.4 «robot_host journal/listener»: реальные модули лежат в `Services/robot_comm/server` (вне охвата); лид одобрил правку сообщением.
- Предусловие #1 на win32 и сравнение прав #3 — платформенная ветка утверждения (не skip, не ослабление): на POSIX прежние строгие проверки сохранены.

## Что оставил открытым / ненадёжно
- Плавающие в прогонах: pult_web (`test_negative_content_length_is_400…`, `test_foreign_host_header_rejected_403…`) — семейство из OPEN_QUESTIONS, не трогал; НОВЫЙ флик `robot_host/test_acceptance_5_4_faults.py::test_delay_ms_delays_and_does_not_serialize` (elapsed 0.297 < 0.3, 1 из 6 прогонов с моими правками, 0 из 6 на базе 89d4f156 — выборка мала, связь с моими правками не доказана и не опровергнута). Подозрение: тест меряет `time.monotonic` (шаг 15.6 мс), а `asyncio.sleep` в цикле тоже на нём — задержка «>= 0.3» на Windows может недобирать до ~15 мс; это возможный продуктовый дефект, не проверял.
- #3 на Windows по существу не может упасть (права всегда 0o666) — осталась проверка «commit не ломает файл»; реальное защищаемое свойство живёт на POSIX.
- #1: `SO_EXCLUSIVEADDRUSE` проверен на Python 3.12 / Windows 10 / pymodbus 3.13; подкласс опирается на `init_setup_connect_listen`, `loop`, `handle_new_connection` pymodbus — при апгрейде pymodbus сломаться может, сломается громко (падение теста).
- Вне охвата в `Services/robot_comm`: 12 падений без моих правок (test_z_view_internal и др.) — не разбирал.
- Плагинный `_probe_port_free` не менял; остаётся TOCTOU-проба ДО pymodbus (как раньше), слушающий сокет теперь сам эксклюзивен.
