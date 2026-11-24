# Правки пробы qt-mcp по ревью (итерация 1 из 2)

Ветка `chore/qt-mcp-probe-hook` (коммиты 3e1b76dcf, 70bb76f1b), сессия qtmcp-bd. Правки лежат в дереве, не закоммичены.
Сообщение коммита: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/dev_qtmcp/commit_msg.txt`.

memory hits: `scripts/memory/search.py qt-mcp probe port` -> `feedback_qt_mcp_flag_value_is_compared_verbatim.md`, `reference_qt_mcp_launch.md`, `feedback_probe_liveness_is_not_render.md`.

## Что изменено

**Один путь (замечание 2).** Ручки прежние: `QT_MCP_PROBE`, `QT_MCP_PORT` (их читают сам `qt_mcp`, хук `.pth` и сервер).
- `multiprocess_prototype/frontend/qt_mcp_probe.py` переписан: `ENV_PROBE`/`ENV_PORT` :32-33, `_port` :39, `_resolve_install` :53, `install_if_enabled` :60. Параметр `log` заменён на `warn` (по умолчанию `get_std_logger(__name__).warning`, то есть без вызывающего код не молчит). `installer` не перепривязывается (`install = _resolve_install() if installer is None else installer`).
- `multiprocess_prototype/frontend/app.py:245-249`: один вызов `install_if_enabled(warn=lambda msg: process._log_warning(msg, module="startup"))`. Старый блок `if os.environ.get("QT_MCP_PROBE") == "1"` (бывш. 270-294) удалён; его история (Т-4, HR-6) перенесена в docstring модуля. `module="startup"` сохранён.
- Строка-признак жизни `qt-mcp probe installed on localhost:<порт>` сохранена как начало успешного лога (на неё ссылаются `backend_ctl/AGENTS.md:54` и память).

**Замечание 1.** `qt_mcp_probe.py:105-107`: `probe = install(port=port)`; `None` -> одно предупреждение «проба не поставлена: порт N занят либо нет QApplication», `False`.

**Замечание 3.** `qt_mcp_probe.py:85-89`: битый порт -> предупреждение «QT_MCP_PORT='…': ожидается целое 1..65535, проба не поставлена», `False`, откат на 9142 отсутствует. `:93-103`: `ImportError` имеет свой текст; любое другое исключение импорта или `install` -> предупреждение с типом и текстом исключения, `False`. Пустой `QT_MCP_PORT` (пробелы) = умолчание 9142 (допущение, см. ниже).

**Замечание 7.** `qt_mcp_probe.py:79-83`: `""` и `"0"` — молча выключено; `"1"` — включено; всё остальное (`1:9142`, `true`, `yes`, ` 1`) — одно предупреждение «ожидается 1», `False`. Сравнение дословное, как у `.pth`.

**Замечания 5, 8.** Успех и отказ оба на WARNING, но тексты разные: успех — «qt-mcp probe installed on localhost:P — ОТКРЫТАЯ ДВЕРЬ: без аутентификации, читает поля паролей, слушает только 127.0.0.1»; отказ всегда начинается «qt-mcp: … проба не поставлена». Оправдание уровня — в docstring `install_if_enabled`.

**Замечание 9.** `X | None`, `collections.abc.Callable/Mapping`; E501 в docstring устранён (строка 9 прежней редакции переписана).

**Замечание 4.**
- `.claude/plugins/mcp-qt/.claude-plugin/plugin.json`: `args` = `--from git+https://github.com/0xCarbon/qt-mcp@24303a69d498417dfcec0223bfaa95964f788c17 --with "mcp<2" qt-mcp` (JSON валиден, проверен загрузкой). Версию плагина (0.4.0) не менял.
- `.claude/plugins/mcp-qt/README.md` (раздел «Launcher options» переписан): пин живёт в версионируемом `plugin.json`, `.mcp.json` в `.gitignore` и перегенерируется; таблица ручек; про нестандартный порт нужен `QT_MCP_PORT` и в `env` сервера. Файл на английском, как был, поэтому строка безопасности (замечание 5) дана по-английски по смыслу; дословная русская формулировка — в docstring модуля и `.rules/gui.md`.
- Локальный `/Users/twokrai/Project_code/Inspector_bottles/.mcp.json` не трогал.

**Имена ручек.** `.claude/plugins/mcp-qt/SETUP_GUIDE.md` и `templates/mcp-config.json.snippet`: `QT_MCP_PROBE_HOST/PORT` -> `QT_MCP_HOST/PORT` (так читает `qt_mcp/server/mcp_server.py:20-21`). Попутно в SETUP_GUIDE исправлены две ложные для закреплённой версии фразы: «`QT_MCP_DISABLE=1` отключает пробу» (grep по пакету: переменная нигде не читается) и «`import qt_mcp.probe` запускает пробу на :9142» (без `QT_MCP_PROBE=1` импорт ничего не делает, см. `qt_mcp/probe/__init__.py:222-243`). Добавлено: порт задавать и в app, и в `env` сервера.

**`.rules/gui.md`** (строки 52-55): битые ссылки на `../.claude/mcp/qt-mcp/` заменены на `../.claude/plugins/mcp-qt/`; описание ручек и отказов; строка безопасности. Строки с `QT_MCP_PROBE=1` в других местах уже были верны.

**Память.** `docs/claude/memory/feedback_qt_mcp_flag_value_is_compared_verbatim.md` и `reference_qt_mcp_launch.md`: дописан итог 2026-11-22; в `reference_...` исправлена устаревшая отсылка `app.py:59-71`.

**Зеркало плагина.** Копий `.claude/plugins/mcp-qt` в других каталогах нет (`git ls-files | grep -i mcp-qt` — только сам источник), копировать некуда. `.claude/plugins/.seed-manifest.json` хранит sha256 посеянных файлов mcp-qt; не менял (это снимок посева, а не зеркало; прежний коммит 70bb76f1b тоже его не трогал). Если `claude-kit upgrade` сравнивает хэши, он увидит локальную правку.

## Тесты и прогоны

`machine_gate.sh light qtmcp-bd` + `.venv/bin/python -m pytest`, `PYTHONPATH=<дерево>`; `multiprocess_prototype.__file__` и `qt_mcp_probe.__file__` лежат в дереве `--qtmcp`.
- `test_qt_mcp_probe.py`: **25 passed** (было 8 тестов старой редакции). 11 функций; параметризации: выключено ×3, порт ×4, пустой порт, битый порт ×5, опечатка флага ×6, и др.
- Замечание 1: `test_install_returning_none_is_not_reported_as_installed` (подмена возвращает `None` -> `False`, ровно одно предупреждение).
- Замечание 3: `test_bad_port_warns_once_and_does_not_install_nor_fall_back` (False, подмена не вызвана, одно предупреждение с именем ручки и «1..65535»); `test_installer_exception_is_a_warning_not_a_crash`.
- Замечание 7: `test_flag_typo_warns_once_and_returns_false`.
- Замечание 6: `test_real_probe_answers_ping_on_custom_port` (настоящий `qt_mcp.probe`, offscreen `QApplication` в подпроцессе, `subprocess.run(timeout=90)`, свободный порт через `bind(0)`, ping -> `pong` по 127.0.0.1) и `test_real_probe_on_busy_port_returns_false_with_one_warning` (порт занят чужим слушающим сокетом -> `False` + одно предупреждение). `pytest.importorskip("qt_mcp.probe")`. Прогон в этой среде: оба прошли, не пропущены.
- `ruff check` и `ruff format --check` по `qt_mcp_probe.py`, `test_qt_mcp_probe.py`, `app.py`: All checks passed, 3 files already formatted. `compileall` и `import multiprocess_prototype.frontend.app` — без ошибок.

### Break-injection

Предсказания записаны до прогона: `.../scratchpad/dev_qtmcp/predictions.txt`; патчи и раннер — `run_mutants.py` в том же каталоге (мутанты в копиях `mut_M*`, исходники не ломались).

| Мутант | Ожидал красных | Получил | Красные тесты |
|---|---|---|---|
| M1: результат `install` отброшен (`if probe is None` -> `if False`) | 2 | 2 | `test_install_returning_none…`, `test_real_probe_on_busy_port…` |
| M2: `ValueError` из `_port` не перехвачен | 5 | 5 | `test_bad_port…` ×5 |
| M3: битый порт откатывается на 9142 | 5 | 5 | `test_bad_port…` ×5 |
| M4: опечатка флага молчит | 6 | 6 | `test_flag_typo…` ×6 |
| M5: опечатка флага включает пробу | 6 | 6 | `test_flag_typo…` ×6 |
| M6: `DEFAULT_PORT = 9143` | 2 | **3** | `test_enabled_installs_on_default_port…`, `test_empty_port_means_default`, `test_install_returning_none…` |
| M7: исключение `install` не перехвачено | 1 | 1 | `test_installer_exception…` |

Промах в M6: я не учёл, что тест с `None` тоже проверяет `calls == [9142]` и текст «порт 9142 занят». Расхождение в сторону большей чувствительности, не слабее.

## Допущения

1. Пустой/пробельный `QT_MCP_PORT` = умолчание 9142 (как в прежней редакции); непустой битый — ошибка. Пробелы вокруг числа допускаются (`int` их снимает, как и в `qt_mcp`).
2. Флаг сравнивается без `strip`: `" 1"` — опечатка. Так же ведёт себя `.pth` (`== '1'`).
3. Один `warn` для успеха и отказа (оба WARNING по решению лида); различие — текстом. Лог `_log_info` старого блока заменён на WARNING сознательно (п.5/8).
4. Успех-лог оставил с английским маркером `qt-mcp probe installed on localhost:` ради потребителей маркера (`backend_ctl/AGENTS.md:54`, память).
5. Версию `plugin.json` не поднимал (не просили).

## Что оставил открытым / ненадёжным

- **Проводка `app.py:run_gui` не доказана ни одним тестом**: `run_gui` поднимает весь GUI-процесс, юнит-тест её не покрывает; корректность самого вызова (лямбда `warn` -> `process._log_warning(..., module="startup")`) проверена только чтением и импортом модуля. Живую проверку (окно + ping, строка в логе `gui`) делает лид.
- Тест с настоящей пробой доказывает `install_if_enabled` + `qt_mcp.probe` на offscreen-платформе в подпроцессе, а не боевой GUI. Дополнительно: при импорте `qt_mcp.probe` его `_auto_hook` (при `QT_MCP_PROBE=1` и уже созданном `QApplication`) сам ставит пробу, а `install` идемпотентен; поэтому в тесте нельзя отделить «поставил наш вызов» от «поставил хук при импорте». Для вопроса «открылся ли порт и отвечает ли он» это неважно, для атрибуции — да.
- Свободный порт через `bind(0)` + `close()` имеет окно гонки (другой процесс может занять порт до старта дочернего); на практике не наблюдал, но флака не исключаю.
- `QT_API` в SETUP_GUIDE (раздел Troubleshooting про PyQt5/PySide6) тоже нигде не читается в пакете `qt_mcp` (grep пуст); не правил, не проверял поведение детекции биндинга — отчёт, а не правка.
- `.seed-manifest.json` хранит прежние хэши файлов mcp-qt; кто и как их сверяет при `claude-kit upgrade`, не проверял.
- Утверждение в README «веб-страница, достучавшаяся до порта, не исключена» — предположение, не проверено (сервер игнорирует не-JSON строки, но кросс-протокольную отправку не пробовал).
- Старый ручной хук был проверен лидом живьём; новый путь живьём мной не проверялся (проверено только offscreen-подпроцессом).
- Исправленная привязка: `.pth` и `_auto_hook` читают `QT_MCP_PORT` через `int()` без защиты; при битом порте они молча ничего не ставят (`.pth` глушит исключение), а наш код предупреждает. Если запуск идёт без нашего хука (другой путь), опечатка снова молчит — это поведение внешнего пакета.
