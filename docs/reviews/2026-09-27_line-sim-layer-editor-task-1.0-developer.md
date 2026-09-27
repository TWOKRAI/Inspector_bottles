# Task 1.0 — developer (GREEN), редактор слоёв line_sim: переносимые пути ScenePreset

Роль: `developer`. Worktree `.claude/worktrees/ls-layer`. План: `plans/line-sim-layer-editor.md`,
Task 1.0. Спека — DESIGN брифа (не выводилась заново).

## Что сделано

- `Services/line_sim/core/preset.py`: добавлено реальное поле `base_dir: str | None = None`;
  `from_yaml` больше не переписывает строки путей — вместо `_resolve_relative_paths` (удалён)
  ставит `base_dir = str(Path(path).parent.resolve())`, перекрывая любой `base_dir`, случайно
  оставшийся в самом YAML; новый публичный метод `resolve_path(value) -> str` — ленивая
  резолюция (schema-id/абсолютный путь без изменений; относительный — от `base_dir`, либо
  без изменений, если `base_dir` не задан); `to_yaml` не пишет `base_dir` и пересчитывает
  относительные `catalog_dir`/`layers[*].sprite_source` от каталога ЦЕЛЕВОГО файла через
  `os.path.relpath` (с `# ponytail:`-откатом на абсолютный путь при `ValueError` — разные
  диски Windows).
- `Services/line_sim/core/factory.py`: `ObjectFactory.__init__` теперь зовёт
  `preset.resolve_path(...)` перед `load_catalog`/`load_image_rgba` — единственное место,
  где строка пути реально превращается в путь для чтения файла.
- `Services/line_sim/README.md` (абзац «Пресет») и `STATUS.md` — обновлены под новое
  поведение.
- `Services/line_sim/tests/test_hazards_1_0_paths.py` — новый, 7 тестов автора (внутренние
  риски механизма: двойной ребейз A→B→C, отсутствие `base_dir` в записанном YAML, игнор
  устаревшего `base_dir` из самого файла, побайтовая неприкосновенность абсолютных путей и
  `fixture://`-id, рабочая (не только pydantic-равная) фабрика после `from_dict(to_dict())`
  + `chdir`, поведение пресета без файла-источника не изменилось, откат `_rebase_value` на
  `os.path.relpath` `ValueError`).

## Тесты

```
PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest \
  Services/line_sim/tests Plugins/sim/scene_source -q --tb=short
```

`270 passed, 1 skipped, 2 failed` (273 собрано). Зелёные: все 3 бывших RED из
`test_acceptance_1_0_paths.py` + 4 её же прежних GREEN + все 7 моих hazard-тестов + весь
остальной радиус `Services/line_sim/tests` и `Plugins/sim/scene_source` — КРОМЕ двух тестов
ниже. `ruff check Services/line_sim` — `All checks passed!`.

### Два падения — не в FILES, конфликт со старым контрактом, который DESIGN буквально отменяет

1. `Services/line_sim/tests/test_acceptance_3_1.py::test_preset_yaml_round_trip` — строит
   пресет через `from_dict` (`base_dir=None`), затем `to_yaml`→`from_yaml` и ждёт полного
   pydantic-равенства с исходным. `from_yaml` теперь ВСЕГДА ставит `base_dir` в каталог
   файла (DESIGN п.2, буквально) — у исходного пресета `base_dir=None`, у прочитанного —
   реальный путь. Поля не совпадают → `==` падает. Причина исключительно в `base_dir`
   (сравнил вручную: `catalog_dir`/`layers`/остальные поля идентичны).
2. `Services/line_sim/tests/test_hazards_3_2.py::test_relative_catalog_dir_resolved_from_yaml_dir_not_cwd`
   — буквально ждёт `Path(preset.catalog_dir) == (presets_dir / "catalog").resolve()` сразу
   после `from_yaml`. DESIGN явно требует обратного: `from_yaml` строки не резолвит,
   резолюция — только в `resolve_path()`/`ObjectFactory`. Тест писан под контракт Task 3.2,
   который Task 1.0 целенаправленно заменяет.

Сам план (`plans/line-sim-layer-editor.md`, Task 1.0, AC) содержит пункт «прежние тесты
`Services/line_sim/tests/` и `Plugins/sim/scene_source/` зелёные» — этот пункт и буквальный
DESIGN брифа (п.2: «stop rewriting strings») взаимно противоречат друг другу именно на этих
двух тестах: они утверждают ИМЕННО то поведение, которое п.2 приказывает убрать. Я не могу
одновременно выполнить оба требования, не отступив от буквального DESIGN — а «не
перевыводить DESIGN самостоятельно» стоит в брифе явным запретом. Оба файла — вне `FILES`
(`test_acceptance_3_1.py`, `test_hazards_3_2.py` там не перечислены), правкой их я бы нарушил
«FILES — nothing else».

Семантическое свойство, которое тест 2 защищал (резолюция не зависит от `cwd`), не потеряно —
оно отдельно покрыто `test_load_independent_of_cwd` (приёмочный, критерий 5) и не сломано.
Свойство теста 1 (`from_yaml(to_yaml(p)) == p`) продолжает выполняться для пресетов, реально
загруженных `from_yaml` и сохранённых в тот же каталог (см. `test_to_yaml_same_dir_has_no_absolute_path`
и мой hazard-тест на цепочку A→B→C) — ломается только для пресета, собранного `from_dict`
(без файла-источника вовсе), что и есть источник конфликта.

## Что я истолковал, а не выполнил буквально

- Докстринг `ScenePreset` (Post: `from_yaml(to_yaml(p)) == p`) оставил как унаследованный
  текст из версии до Task 1.0 — по факту он теперь верен только при условии «`p.base_dir`
  уже указывает на целевой каталог» (т.е. p сам был загружен `from_yaml` и сохраняется в тот
  же каталог), а не универсально. Явно не переписывал условие докстринга под это уточнение —
  решил, что это тонкость для лида/ревьюера, а не для меня самостоятельно менять контракт.

## Что оставил открытым / ненадёжным

- **2 падающих теста вне `FILES`** (см. выше) — не трогал по правилу «файл вне FILES → стоп
  и спросить лида»; решение о том, обновлять ли `test_acceptance_3_1.py`/`test_hazards_3_2.py`
  под новый контракт (они буквально проверяют старое поведение, которое DESIGN отменяет) —
  за лидом/teamlead.
- Не проверял поведение `to_yaml` при относительном (не resolved) `path`-аргументе
  функции — тесты передают только абсолютные `tmp_path`-пути; `Path(path).parent.resolve()`
  должен справиться, но отдельного теста на этот случай нет.
- Хазард-тест на откат `os.path.relpath` при `ValueError` (кросс-дисковый Windows) —
  собственный break-injection через `monkeypatch.setattr(os.path, "relpath", ...)`, не
  настоящий кросс-дисковый сценарий (недостижим на macOS/CI) — доказывает код пути, не
  реальное окружение.
- Break-injection (стадия 3) не выполнял — по протоколу это стадия лида, не делегируется.

Boundary: task closed. /compact (focus: files + tests + plan path).
