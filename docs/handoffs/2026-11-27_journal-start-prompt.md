ROLE: лид полосы «Журнал». Передано из полосы Р2 (робот) 2026-11-27. Работа без железа.

GOAL: один набор механизмов журнала для всей системы (формат записи, запись, чтение, срок, потолок, потери видны), хранилище подключается: своё или общее (SQL, NoSQL, Redis). Первый потребитель — журнал команд робота: по нему видно, что команда принята или отклонена и почему, и всё ли работает правильно.

СНАЧАЛА: расскажи мне понятным языком, что будешь делать и почему, и дождись моего слова. Код до этого не пиши.

ПРОЧИТАЙ (ветка docs/robot-device-architecture не слита в main; дерево .claude/worktrees/r2-device-arch):
1. docs/reports/2026-11-26_journal-design.md — разбор и особенно раздел «Вердикт техдиректора» (ДА, в изменённой форме) с поправками к разбору.
2. docs/claude/OPEN_QUESTIONS.md — раздел «общий журнал: три вопроса» от 2026-11-26.
3. docs/reports/2026-11-26_robot-device-architecture.md и docs/sessions/2026-11-26_r2.md — устройства и состояние полосы Р2.
Разбор уже сделан: не повторяй его, а проверь то, на чём будет стоять твоё решение (в нём помечено, что прогнано, а что только прочитано).

МОИ РЕШЕНИЯ (не переспрашивать):
- Один стандарт на все журналы: команды устройств, ошибки, статистика и прочие. Дублей не плодить.
- Журнал — отдельный переиспользуемый сервис, согласованный с Services/auth: используют друг друга, а не повторяют.
- Общие — механизмы, код и функции; хранилище подключается отдельно.
- Настраивается из рецепта через data_schema; срок хранения тоже в рецепте, позже для таких настроек будет защищённый рецепт.
- Личность автора команды проверять уже в 1.0.
- У всех устройств (робот, камера, ПЧ, сервоприводы, другие производители) — один механизм наблюдаемости и журнала.

BOUNDARIES:
- Полоса Р2 (сессия inspector-bottles-5d) сейчас меняет: Services/modbus, Services/robot_comm, Services/device_hub, Plugins/hub/device_hub, Plugins/io/robot_io, Plugins/processing/word_layout, вкладку робота. Эти файлы не трогай, пока в main не слиты ветки fix/modbus-link-drop и fix/robot-servo-intent. Подключение журнала команд к драйверу робота — после этого и по согласованию с Р2.
- Не трогать файлы полосы Ф (frontend/app.py, process.py, bridge_impl.py, state/bindings.py, state/delta_message.py, widgets/tabs/services/vfd/controller.py, process_manager_process.py) и полосы К (Services/camera_device, Services/hikvision_camera, Services/code_reader, domain/entities/recipe.py, backend_ctl/probes/camera_stand_probe.py) без согласования.
- Свой worktree от main; основную папку не переключать. К настоящему роботу не подключаться.

PIPELINE: план через /dev:plan; дальше по .claude/CLAUDE.md «Task launch convention» и «The lead coordinates and controls». Тесты и стенд — только через scripts/machine_gate.sh; своё имя возьми из первой строки ListAgents и пришли координатору. Не больше одного писателя одновременно. .venv общий, в worktree PYTHONPATH=<корень>, uv sync не делать.

COMMITS: Conventional Commits + Why:/Layer:/Refs: (.claude/COMMIT_GUIDE.md), только явные пути. main и push — только по моему слову.

LIMITS: 2 итерации на цикл, на третьей — эскалация. Мои решения не угадывать.

REPORT: по-русски, понятным языком, числами; раздел «что оставил открытым»; в конце — handoff.
