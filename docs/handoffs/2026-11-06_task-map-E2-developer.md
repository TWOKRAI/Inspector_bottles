# Handoff map-E2, раунд 2 (разработчик) — 2026-11-06

Состояние: раунд 1 сдан (16 тестов зелёные, k0_reference.json и cards.html сгенерированы). Раунд 2 (F1–F13 + P из
docs/reviews/2026-11-06_task-map-E2-review.md) НЕ начат в коде: signboard.py и test_signboard.py не менялись с раунда 1
(главный чекаут D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles, HEAD 1dc6c71b7, без коммитов). Сделано только:
сохранён текст ревью (docs/reviews/2026-11-06_task-map-E2-review.md). Причина остановки — контекст исполнителя выше мягкого бюджета.

Запуск: `export PYTHONUTF8=1`; тесты `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-32 .venv/Scripts/python -m pytest scripts/arch_map/tests/test_signboard.py -q --tb=short -p no:cacheprovider`;
регенерация `.venv/Scripts/python scripts/arch_map/signboard.py bench` и `... cards` (по ~10 и ~35 с). Ловушки: ruff format хука
раздувает файл — после правок `ruff check -q`; в Bash-героках не писать `\n` в строках (инструмент превращает в перевод строки) — использовать `chr(10)`.
Файлы только эти 6; генерат: docs/arch-map/_bench/k0_reference.json, docs/arch-map/cards.html.

## Карта кода (signboard.py, строки на 16:06)
house_spec 653; call_site_hits 584; test_hits 611; test_functions 299; io_of 499; class_members 367; inherited_members 456;
class_signature 432; structural_matches 705; district_spec 727; house_sections 981; district_sections 1026;
model_sections 1036; card_view 1057; render_text 1072; run_bench 1097; build_cards_data 1120; PAGE_TEMPLATE 1198 (JS cardNode);
iter_py_files 182 + SCAN_SKIP (верх файла); build_parser 1414.

## План по находкам (порядок работы)
1. F1: в io_of ветка `.schedule`: нужен `len(args) >= 2` → path_expr = ast.unparse(args[1]) либо keyword `path`; иначе не watch.
   Тесты: фикстура IO_MOD `watch(observer, folder)` -> `observer.schedule(handler, folder, recursive=False)`; ожидаем `folder`; номера строк IO_MOD сдвинуть.
2. F3: io op `replaces` для os.replace/os.rename/shutil.move (аргументы a, b → path_expr "a -> b"), Path.replace/rename (приёмник → аргумент). Тест на `tmp -> path`.
3. F2: call_sites = вызовы из других файлов + из своего файла (метка `same_file`), каждый с охватывающим символом: нужен file_calls с `enclosing` (обход функций с стеком имён, формат `path:275 in persist_session_to_companion`; методы `Класс.метод`). Сортировка: сначала прод, потом probes/tests (пути с `probe`/`tests`/`backend_ctl`), внутри — кратчайший путь. Хранить `call_sites` как список dict {where, in, kind} и строку для текста. Тест: функция вызвана из функции своего же файла.
4. F4: `bases_resolved: [{name, where}]` (resolve_class → ClassFact.file/line); у inherited_members поле `from_where`.
5. F5: `line` у каждого члена (class_members: stmt.lineno; для декорированных — lineno самого def, он уже без декоратора в Python 3.8+) и у домов district_spec.
6. F6: tests как {file, line, name}; text `path:LINE name`; группа по файлу «N тестов»; без капа 5 в эталоне (в странице — кап). test_functions хранит node.lineno.
7. F7: structural_matches: допускать, если у интерфейса ≥ 2 требуемых не-дандер имён ИЛИ совпали арность+имена параметров; исключить `_X`-классы и классы в слоях, не импортирующих интерфейс (layer_of от пути из model или первая компонента пути + проверка importing_files); иначе `structural_total: None` + текст «слишком общий протокол (1 член)». IConfig→Config должен остаться (проверить на реальном репо).
8. F8: у Protocol/ABC без __init__ — `signature: None`, текст «конструктора нет (интерфейс)»; у классов с неразрешёнными внешними базами и без __init__ — None.
9. F9: line2 интерфейса: «… / наследников N».
10. F11: `--skip-dir` (action=append, default из EXTRA_SKIP_DIRS), прокинуть в get_index/iter_py_files (ключ кэша учитывает набор).
11. F12: meta.dirty в run_bench: `git status --porcelain` по проиндексированным путям (список файлов из idx.files, либо просто каталоги верхнего уровня) → bool/список.
12. F13: reference JSON компактно (`separators=(",", ":")`, без indent); в отчёте — размер и оценка токенов chars/3.5.
13. P: единая структура карточки. Секции ровно в порядке: «Назначение» / «Подключение» / «Связи» / «Где работает» / «Проверка» / «Состояние»; пустые — «—». Распределение: house — Назначение (line1+doc), Подключение (signature, members, inherited), Связи (uses me/I use, bases, subclasses, structural, call_sites), Где работает (io), Проверка (tests), Состояние (kind, doc_missing); layer/unit/package — Назначение (purpose), Подключение (import_rule, __all__, interfaces), Связи (fan in/out, counts), Где работает (commands, threads, recipes; процессы — «—» пока нет данных), Проверка (findings, направление), Состояние (tier); district — Назначение (doc_line), Подключение (дома: имя/вид/строка), Связи (files_in/out, вызовы), Где работает/Проверка/Состояние по данным или «—». JSON: те же ключи верхнего уровня (`sections` как объект с шестью ключами) рядом с плоскими полями. card_view/render_text/PAGE_TEMPLATE (JS cardNode читает c.sections как массив пар — сохранить формат массив пар, всегда 6 штук в порядке). Обновить SIGNBOARD.md (контракт секций).
14. F10: тесты: ABC наследует 2 абстрактных члена от базы в другом файле (inherited_members len 2); `.schedule(handler, folder)`; same-file call + охватывающий символ; `replaces`; run_bench на мини-репо (meta.targets == N).
15. Регенерировать k0_reference.json и cards.html; скриншот (Edge headless, `#card=` для закрепления; пути в scratchpad).
16. Инъекции (предсказания записать в отчёт ДО запуска): F1 вернуть args[0]; inherited_members = []; убрать охватывающий символ. Дописать «Раунд 2» в docs/reviews/2026-11-06_task-map-E2-developer.md; финальный отчёт ≤ 25 строк.
