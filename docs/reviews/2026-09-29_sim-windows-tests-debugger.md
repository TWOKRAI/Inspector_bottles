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

# Раунд 2: Services/robot_comm (12 падений при неустановленной QT_QPA_PLATFORM)

Команда: `env -u QT_QPA_PLATFORM PYTHONPATH=$PWD python -m pytest -q Services/robot_comm`.
До: 12 failed / 822 passed. После: 0 failed / 835 passed / 5 skipped / 2 xpassed. Skip/xfail не добавлено.
Совместный прогон `Plugins/sim Services/line_sim Services/robot_comm`: 1395 passed, 2 failed — оба плавающие (см. ниже).

| # | Тест(ы) | Причина | Сторона | Фикс | SHA |
|---|---|---|---|---|---|
| A | 11 Qt-тестов видов (test_sim_view*, test_z_view*, test_t2w_lead_guards rz/zscale) | на нативной платформе Qt под Windows пиксели QPixmap не те; проходили только с внешним `QT_QPA_PLATFORM=offscreen` | (b) | `Services/robot_comm/tests/conftest.py`: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`, явная переменная главнее | 880f36e4 |
| C | test_zscale_mark_label_flips_below_at_top | не продукт: на offscreen под Windows нет шрифтов (`QFontDatabase: Cannot find font directory ... Qt no longer ships fonts`), текст рисуется рамками-заглушками. Вход: ZScale 120x300, P_HOME_Z=0 -> линия y=8, drawText baseline=14 (как задумано). Наблюдено без шрифта: полноцветные пиксели в строках 2-9 (тест ищет 11-23). Со шрифтом: строки 6-13 (пересечение с 11-23 есть) | (b) окружение | conftest: на win32 `QT_QPA_FONTDIR` -> временный каталог с одним DejaVuSans.ttf из matplotlib (зависимость проекта); явная переменная главнее | 7cd8fb50 |
| B | test_lua_block_markers_and_sha (`'6f7b966e' == 'a14430ba'`) | тест хешировал СЫРЫЕ байты autocrlf-checkout (CRLF, a14430ba); продукт `codegen.yaml_sha8` уже нормализует CRLF->LF: git-blob (LF) и Windows-checkout дают одинаково 6f7b966e | (b) | тест хеширует LF-форму; новый `test_yaml_sha8_independent_of_checkout_line_endings` (LF и CRLF -> один отпечаток) | 85997fe9 |

## По (B): что сравнивает прошивка
- Единственная величина от БАЙТ файла — sha8 в заголовке сгенерированного Lua-блока (`-- ===== BEGIN GENERATED (delta_v2.yaml <sha8>) =====`), маркер актуальности; он уже LF-нормализован в продукте. Замер: git-blob 6f7b966e / product на CRLF-checkout 6f7b966e / сырые байты CRLF a14430ba.
- `DICT_FINGERPRINT` (23080) — CRC16 по разобранному словарю параметров (`codegen._dict_fingerprint(doc["params"])`), от концов строк не зависит. `TLM_FW_BUILD` — номер сборки прошивки, не хеш файла.
- Поэтому вариант «.gitattributes eol=lf» или правка кодогена не нужны: протокол и закоммиченные артефакты (`core/protocol_v2.py`, `core/params_v2.py`) не менялись, `codegen.check` чист. Контракт робота не тронут; эскалации не требуется.
- Break-injection: убрал `.replace(b"\r\n", b"\n")` в `yaml_sha8` -> красные: новый тест, `test_lua_block_markers_and_sha`, `test_cli_check_exit_code` (3 из 3, как ожидал; кроме ожидаемых двух cli_check тоже смотрит закоммиченные артефакты). Продукт восстановлен, `git status` чист.

## Что интерпретировал, а не выполнил буквально
- Задание (C) описано как «падает даже с offscreen» — воспроизведено ровно так; причина в шрифтах offscreen, а не в метриках продукта. Лечение вынесено в окружение тестов, а не в тест (утверждение не менял).
- conftest ставит offscreen для всего pytest-процесса, если собраны тесты robot_comm (переменная общая на процесс). В совместном прогоне это тоже прошло.

## Что оставил открытым / ненадёжно
- ИСПРАВЛЕНИЕ раунда 1: флик `test_delay_ms_delays_and_does_not_serialize` — НЕ от моих правок. Замер 25 прогонов подряд: HEAD 6/25 падений, база 89d4f156 4/25. Прежнее «0 из 6 на базе» было везением. Причина, вероятно: тест меряет `time.monotonic` (шаг 15.625 мс, elapsed 0.297 = 19 тиков), а `asyncio.sleep` на том же грубом таймере может проснуться на тик раньше -> «>= 0.3» недобирает. Не чинил (вне охвата, плавающий), продуктовый ли это дефект (задержка короче заданной до ~15 мс на Windows) — не доказано.
- pult_web-флики в совместном прогоне (`test_truth_routes_forbidden_host_403`) — известное семейство, не трогал.
- (C): DejaVuSans подмешан только на win32; на Linux/macOS offscreen шрифты берёт у системы (fontconfig), там не проверял.
- Подмена `QT_QPA_FONTDIR` создаёт временный каталог при импорте conftest и удаляет его `atexit`; при жёстком убийстве процесса каталог `qt_fonts_*` в %TEMP% останется.
