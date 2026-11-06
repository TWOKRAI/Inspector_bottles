# map-A1 — отчёт разработчика

Ветка `feat/atlas-lookup-map`, база `e6a46261a`. Команды запускались из корня worktree, `PYTHONPATH=<корень>`, `.venv` главного дерева.

Путь импорта: `python -c "import scripts.atlas as m; print(m.__file__)"` ->
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\atlas-map\scripts\atlas\__init__.py` (внутри worktree).

## Приёмка

- (a) `pytest scripts/atlas/tests/test_scan.py scripts/atlas/tests/test_scan_hazards.py`: `24 passed` (14 тестера + 10 автора; после правки лидом двух литералов `typing` в красном 2).
- (b) Тесты автора зелёные: два скана в одну базу, база занята писателем, битое тело, круг JSON, пути (пробел, кириллица, перевод строки), патологические исходники, усечённый `cat-file`, порции `get_scans`, блоб больше предела, плюс якорь на `run_with_deadline`.
- (c) Весь `scripts/atlas/tests`: `5 failed, 373 passed, 2 skipped, 1 warning in 1079.09s (0:17:59)` (через gate `medium`, exit 1). Красные: `test_modules_map.py::test_every_source_file_has_a_module` и `::test_ids_unique_and_parents_valid` (`Services/camera_device/` нет в `modules.yaml`; ни `Services/camera_device`, ни `modules.yaml` не менялись между `1dc6c71b7` и HEAD, тест не читает ни один мой файл: красный до моей правки — по выводу, не по прогону на `1dc6c71b7`); `test_views_pinned.py::test_card_on_origin_main_pin`, `::test_pack_on_origin_main_pin`, `::test_log_on_origin_main_pin` (`вызов завис: нет ответа за 60.0 с` на загруженной машине; прогон на `1dc6c71b7` не делался). Тесты `test_scan*`, `test_core_store_tree`, `test_cache_1_6e*`, `test_ref_code`, `test_reference*`, `test_rules` — зелёные. По просьбе лида красные не чинились.
- (d) `ruff check -q scripts/atlas` — пусто; `ruff format --check` на 5 изменённых файлах — «already formatted».
- (e) Разовые сверки (скрипт — `scratchpad/oneoff.py`, состояние `scripts/arch_map/build.py`: sha256 `8c95fbd5188ba7c4…`, коммит 739394c47):
  - набор — `.py` пяти слоёв без `tests/`, `docs/`, `test_*`, `conftest.py` на HEAD: 1858 файлов; в картe тот же набор (расхождений набора 0 в обе стороны);
  - D2: `unresolved` всего 2; из них из каталога без `__init__.py` — 0;
  - D3 (а): `roots` на HEAD = `Plugins, Services, backend_ctl, multiprocess_framework, multiprocess_prototype`; пересечение с `importlib.metadata.packages_distributions()` — пустое;
  - D3 (б): рёбер сравнено 9727 (импорты из `ParsedFile` карты, индекс по набору карты), расходятся статус или цели: 0;
  - время (`Tree(HEAD)`, 1858 путей, новая база, загруженная машина): холодно 4,79 с (`parsed=1848`: различных oid 1848, `hits=0`, `missing=0`, `error` ни у одного файла), тепло 0,06 с (`parsed=0`, `hits=1848`). Замер лида — окончательный.

## Тестер: красный 2

Входы `"from typing import TYPE_CHECKING\ndef f():\n    if TYPE_CHECKING:\n        import a\n"` и вариант с `def g` под `if TYPE_CHECKING` ожидали одну запись, но сам `from typing import TYPE_CHECKING` — импорт (`("typing","hard",1)`). Ошибка литерала в задаче; лид исправил `test_scan.py` и задачу.

## Что я истолковал, а не выполнил дословно

- `scan_text` ловит `Exception` целиком (не только перечень R4): контракт «не бросает никогда» важнее перечня; имя ошибки — `type(exc).__name__`.
- `Contour`: перенос карты — первая НЕпустая строка побеждает (`Contour: , ,` не блокирует следующую строку); R8 говорит «первая строка побеждает». Красный 8 это не различает.
- `to_json` — ASCII (`ensure_ascii=True`) и без пробелов: одиночный суррогат не ломает запись в sqlite; импорты и классы — списками значений, а не словарями.
- `scan`: `paths` дедуплицируется; блоб, который `read_many` вернул как `None` (файл исчез между `oids()` и чтением), попадает в `missing`, а не в факты.
- `Tree.files()` теперь тоже идёт через `ls-tree -r -z` без `--name-only`; порядок и состав прежние.
- В тесте автора 5 путь с переводом строки кладётся в индекс через `git -c core.protectNTFS=false update-index --cacheinfo`: без флага git на Windows отвечает `Invalid path`.
- Тест автора 2 ставит `PRAGMA busy_timeout = 0` на соединение, иначе каждый вызов ждёт 5 с.

## Что оставлено открытым / ненадёжно

- Полный прогон `scripts/atlas/tests` на загруженной общей машине нестабилен: первый прогон (`-x`) остановился на `test_brief_1_9b.py::test_pin_block_has_marker_and_grammar` («вызов завис: нет ответа за 60.0 с»), другой прогон показал красные в `test_card_pack_1_6c.py`; оба файла по отдельности зелёные (12 passed за 50 с и 12 passed за 44 с). Причина — дедлайн 60 с при нагрузке, а не код; доказательство слабое (нет прогона на `1dc6c71b7` под той же нагрузкой).
- `SyntaxWarning` от `ast.parse` (например, неверная escape-последовательность) не подавляется: уйдёт в stderr при холодном скане.
- Тест автора 1 (две нити) проверяет итог, а не гонку: при сбое планировщика гонка может не проявиться.
- Тест 7 усечения проверяет подменой `run_git`, а не настоящим обрезанным выводом git.
- `ImportIndex` сверен с картой на карте-индексе (набор слоёв); на индексе всего репозитория (с `scripts/` и т. п.) расхождения не измерялись.
- Не проверено: нужна ли запись в `modules.yaml`/README для `scan.py`; рост `scan_cache` без очистки; `sentrux check .` не запускался.
