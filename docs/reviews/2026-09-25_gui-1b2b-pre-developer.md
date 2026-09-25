# Task 1b.2b-pre — `RegistersManager.from_catalog` строит editable-копии — отчёт разработчика

**Дата:** 2026-09-25
**Ветка:** `feat/gui-1b2b-precondition`, воркtree `.claude/worktrees/gui-1b2b-pre`
**План:** `plans/2026-09-22_gui-service/phase-1b-recipe-service.md`

## Что сделано

В `RegistersManager.from_catalog()` (`multiprocess_framework/modules/registers_module/core/manager.py`)
для каждой записи каталога с непустыми `register.fields` теперь строится СИНТЕТИЧЕСКАЯ
копия регистра:

```python
create_model(
    name, __base__=SchemaBase,
    **{fi.field_name: (Annotated[fi.field_type, fi.meta] if fi.meta else fi.field_type, fi.default)
       for fi in fields}
)()
```

над уже декодированными `FieldInfo` (тот же `to_dict()`/`from_dict()`-кодек, что и
`get_fields()`, Task 1b.2a). Копия — полноценный `SchemaBase` (`validate_assignment=True`),
поэтому `set_value`/`validate`/`set_field_value`/dispatch работают на ней так же, как на
живом регистре плагина.

Изоляция per-plugin: сборка одной записи оборачивается в `try/except`; при падении —
`manager._log_warning(...)`, `continue` — `_fields_cache` этого плагина не трогается
(GUI видит форму, но без записи), остальные плагины не задеты. `from_catalog` никогда не
бросает наружу из-за одной поломанной записи.

Docstring `from_catalog` обновлён (снята фраза «регистры не инстанцируются вовсе»).

## Файлы

- `multiprocess_framework/modules/registers_module/core/manager.py` — `from_catalog` +
  новая module-level функция `_build_register_copy(name, fields)`
- `multiprocess_framework/modules/registers_module/tests/test_from_catalog_copy_hazards.py`
  — новый, 4 hazard-теста автора
- `multiprocess_framework/modules/registers_module/DECISIONS.md` — ADR-RM-007
- `multiprocess_framework/DECISIONS.md` — регенерирован `python -m scripts.sync`
- `multiprocess_framework/modules/registers_module/STATUS.md` — строка в истории изменений

## Тесты — что запускал и что получил

Тестерский RED-файл (10 тестов, коммит `4fa5aa88`) — все стали GREEN:

```
$ pytest multiprocess_prototype/adapters/tests/test_catalog_registers_editing_acceptance.py -q
10 passed in 2.03s
```

Радиус (тестерский файл + сосед 1b.2a + весь модуль registers_module, включая новый
hazard-файл):

```
$ pytest multiprocess_prototype/adapters/tests/test_catalog_registers_editing_acceptance.py \
         multiprocess_prototype/adapters/tests/test_remote_plugin_catalog_acceptance.py \
         multiprocess_framework/modules/registers_module -q
100 passed in 2.99s
```

(до правки, без hazard-файла — 86 passed; после — 100 passed: +10 тестерских +4 hazard).

`ruff check multiprocess_framework/modules/registers_module/` — `All checks passed!`

`python scripts/validate.py` (из корня воркtree) — `Ошибок нет! Предупреждений нет!`,
включая `[OK] ADR-документация синхронизирована` (после `python -m scripts.sync`).

## Hazard-тесты автора (докстринг-первый, что может сломать ИМЕННО этот механизм)

1. **Сосед-калека** — поле `model_dump` (защищённый pydantic-namespace `model_*`)
   бросает `ValueError` на `create_model` — измерено эмпирически ДО написания теста
   (`python -c` с `create_model(..., model_dump=(int, 0))` → `ValueError: Field
   'model_dump' conflicts with member ...`). Проверено: `from_catalog` не падает,
   здоровый сосед остаётся редактируем, `get_fields()` калеки не пострадал.
2. **Два менеджера из одного payload не делят инстансы** — `create_model` строит
   новый класс на каждый вызов `from_catalog`; проверено прямым `is not` + независимой
   мутацией.
3. **Копия реально отклоняет невалидное значение** — `set_value(below_min)` → `False`,
   значение в регистре не меняется (не молчаливый passthrough).
4. **`FieldMeta.routing` переживает пересборку через `create_model`** — `Annotated`-
   метаданные легко потерять при рефакторинге; spy на `send_callback` проверяет РОВНО
   один вызов с ожидаемым каналом (`control_proc_a`), а не просто факт «что-то
   вызвалось».

Все 4 — новый файл, `pytest ... -q`: `4 passed in 0.04s` (входит в 100 выше).

## Что интерпретировал, а не просто выполнил по брифу

- DESIGN дал точную формулу построения модели — использовал её дословно как
  `_build_register_copy`, вынес в module-level функцию (не метод), чтобы try/except
  в `from_catalog` не разрастался инлайн и был симметричен по стилю с остальными
  helper'ами файла (`resolve_dispatch_targets` тоже module-level в соседнем файле).
- Для hazard (a) сам подобрал конкретное поле, которое РЕАЛЬНО валит `create_model`
  (`model_dump`) — эмпирически проверил, что `"model_config"` и поле с ведущим `_`
  из примеров в брифе НЕ падают (pydantic их либо переопределяет, либо трактует как
  private-атрибут и просто не создаёт поле, без исключения) — значит они не годились
  бы как «поломанная запись» для этого теста; задокументировал находку в докстринге
  файла, чтобы это не выглядело подгонкой теста под implementation.
- `ADR-RM-007` добавил секцию «финальный судья — бэкенд» явно (лид указал этот пункт
  в брифе как принятое ограничение) — не расширял и не сокращал.

## Что осталось открытым / ненадёжным в моей работе

- Не проверял поведение `from_catalog` под реальным GUI-процессом (backend-ctl/qt-mcp
  не подключены в этой сессии) — только pytest на уровне модуля и прикладного
  адаптера; интеграция с живой формой (`FieldSetHandler`/`TopologyBridge`) покрыта
  тестерским AC6, но это тоже pytest, не живой стенд.
  qt-mcp в этой сессии не подключился (`CONNECTION_CLOSED`) — не проверял руками.
- Не пытался специально найти ВСЕ имена полей, которые `create_model` отвергает —
  нашёл один достаточный пример (`model_*` namespace) для hazard-теста; полный список
  запрещённых pydantic-имён не исследовал (не требовалось по DESIGN).
- Cross-field `model_validator` на реальных плагинах в этом репозитории не
  инвентаризировал — ADR-RM-007 фиксирует ограничение как принятое лидом, но не
  проверял, есть ли среди 43 плагинов с регистром такие валидаторы (если есть —
  копия будет менее строгой, чем оригинал, именно в этом месте; это ожидаемое,
  задокументированное расхождение, не регрессия).
- Break-injection против обоих тестовых наборов (тестерского и моего hazard-файла)
  — задача лида по протоколу, я её не делал.
