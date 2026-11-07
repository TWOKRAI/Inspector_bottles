# Карта архитектуры — документ истины

Статус: **фундамент v1** (2026-11-06). Карта строится из кода генератором, а не пишется руками.
Аналогия — промышленная электрическая схема: узел = аппарат со спецификацией, ребро = провод с
маркировкой (какие имена по нему идут), нарушение правила = красная метка на схеме.

## Состав

| Файл | Что это | Кто пишет |
|---|---|---|
| `model.json` | модель: узлы, рёбра-импорты, интерфейсы, классы, находки, метрики | генератор `scripts/arch_map/build.py` |
| `model.js` | та же модель как `window.ARCH_MODEL = …` (страница открывается с диска, без сервера) | генератор |
| `units.md` | спецификация юнитов таблицами — вход для агентов-ревьюеров | генератор |
| `findings.md` | находки правил, сгруппированы по правилу и паре юнитов | генератор |
| `index.html` | сворачиваемая схема + карточка выбранного узла или провода | вручную (читает только `model.js`) |

Пересборка: `python scripts/arch_map/build.py` из корня репозитория. В `meta.commit` — SHA снимка.
Сторож: `python scripts/arch_map/build.py --check` строит модель в памяти и сверяет с диском все четыре файла
(`model.json`, `model.js`, `units.md`, `findings.md`); `meta.generated` и `meta.commit` в сравнении не участвуют.
Расходится хоть один файл — exit 1 и список расходящихся файлов в stderr.
Обычная сборка завершается кодом 1, если среди находок есть `error` (файлы при этом записаны); `--check` на ошибки не смотрит.

## Уровни схемы

1. **Слой** (`kind: layer`): `multiprocess_framework` → `Services` → `Plugins` → `multiprocess_prototype`;
   `backend_ctl` — внешний инструмент рядом. Разрешённое направление импортов — справа налево по этой цепочке
   (prototype знает всех, framework не знает никого).
2. **Юнит** (`kind: unit`) — единица со спецификацией: модуль `multiprocess_framework/modules/<X>`, сервис
   `Services/<X>`, плагин `Plugins/<группа>/<X>`, подпакет первого уровня `multiprocess_prototype/<X>`,
   `backend_ctl` целиком. Группа плагинов `Plugins/<группа>` — `kind: group`.
3. **Пакет** (`kind: package`) и **файл** (`kind: file`) внутри юнита.

Файлы, лежащие прямо в корне слоя (например `multiprocess_prototype/orchestrator.py`,
`multiprocess_framework/modules/_fallback.py`), собраны в синтетический юнит `<слой>.__root__`.
Юниты framework подвешены прямо к слою: уровень `modules` в дереве пропущен, в id он остаётся.
Синтетические юниты помечены `"synthetic": true`; такой же вид у `<группа плагинов>.__root__` для файлов прямо
в каталоге группы. `backend_ctl` — один настоящий юнит с id `backend_ctl.__root__` (id `backend_ctl` занят слоем);
он не `synthetic`, пакеты внутри (`probes`) подвешены к нему.

Тесты (`tests/`, `test_*.py`, `conftest.py`) в граф не входят; у юнита хранится только их число.

## Схема `model.json` (schema = 1)

```jsonc
{
  "meta": {"schema": 1, "generated": "2026-11-06T12:00:00", "commit": "1dc6c71b7",
           "layers": ["multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "backend_ctl"],
           "counts": {"nodes": 0, "units": 0, "files": 0, "edges": 0, "findings": 0,
                      "parse_errors": 0, "unresolved_absolute": 0}},

  // id узла = точечный путь Python от корня репозитория; parent = id родителя или null у слоя
  "nodes": [
    {"id": "multiprocess_framework", "kind": "layer", "parent": null, "name": "multiprocess_framework", "order": 0},
    {"id": "multiprocess_framework.modules.router_module", "kind": "unit", "parent": "multiprocess_framework",
     "name": "router_module", "path": "multiprocess_framework/modules/router_module",
     "spec": {
       "loc": 0, "files": 0, "tests": 0,
       "docs": {"readme": true, "status": true, "decisions": true, "interfaces": true},
       "all": ["RouterManager"],                       // __all__ из __init__.py юнита
       "interfaces": [{"name": "IRouterManager", "style": "ABC", "file": "…/interfaces.py", "line": 10,
                       "methods": ["send", "receive"]}],
       "classes_top": [{"name": "RouterManager", "bases": ["ChannelRoutingManager"], "file": "…", "line": 1}],
       "fan_in": 0, "fan_out": 0, "instability": 0.0,  // по юнитам, hard+lazy, без tc
       "tier": "core",                                  // = card.tier
       "card": {"purpose": "…", "tier": "core", "contour": ["ipc"],
                "adr_count": 3, "commands": ["start"], "threads": [{"name": "x", "where": "путь:строка"}],
                "sources": {"purpose": "modules.yaml"}},   // см. «Карточка юнита»
       "recipes": ["multiprocess_prototype/recipes/a.yaml"],  // живые рецепты, где юнит назван в plugin_class:
       "recipes_inactive": ["…/tests/b.yaml"]            // то же в путях с tests | fixtures | archive
     }},
    {"id": "….router_module.core", "kind": "package", "parent": "….router_module", "name": "core", "path": "…"},
    {"id": "….router_module.core._sender", "kind": "file", "parent": "….router_module.core", "name": "_sender",
     "path": "…/core/_sender.py", "loc": 0,
     "classes": [{"name": "X", "bases": ["Y"], "line": 1, "methods": ["public_only"]}],
     "functions": ["public_top_level"]}
  ],

  // ребро = один оператор import между двумя файлами графа (внешние библиотеки не входят)
  "edges": [
    // оба конца — файлы. `__init__.py` пакета — файл с id `<пакет>.__init__` (сам пакет — узел-каталог).
    // `from pkg import sub`, где sub — подмодуль, ведёт в файл sub; иначе — в `pkg.__init__`.
    {"src": "<id файла>", "dst": "<id файла>", "kind": "hard|lazy|tc",
     "names": ["RouterManager"], "line": 12,
     "guarded": true}   // ключ есть только у импорта под try/except ImportError|ModuleNotFoundError|Exception
  ],

  "findings": [
    {"rule": "layer-reverse", "severity": "error|warn|info",
     "src_unit": "<id>", "dst_unit": "<id>", "src": "<id файла>", "dst": "<id>", "where": "path.py:12",
     "detail": "текст одной строкой"}
    // у unit-cycle: src_unit = первый настоящий юнит компоненты, dst_unit/src/dst/where = null,
    // плюс "members": [вершины компоненты]; у находок без файла (unit-hygiene и т. п.) src/dst/where = null
  ]
}
```

`kind` ребра: `hard` — импорт на верхнем уровне файла; `lazy` — внутри функции, метода или условия;
`tc` — под `if TYPE_CHECKING:` (в том числе внутри функции). Тело класса исполняется при импорте — `hard`; метод и
`async def` — `lazy`. Классификация — как в `scripts/arch_graph/ast_graph.py`, с двумя отличиями: `def` внутри `if`
остаётся `lazy`, `TYPE_CHECKING` внутри функции — `tc`. `guarded` — признак необязательной зависимости.

## Правила находок (v1)

| Правило | Серьёзность | Когда срабатывает |
|---|---|---|
| `layer-reverse` | error | импорт против цепочки слоёв (framework → Services/Plugins/prototype и т. д.); `tc` — warn; framework/Services/Plugins → `backend_ctl` тоже; prototype → `backend_ctl` и всё из `backend_ctl` находок не даёт, как и другие правила на рёбрах с `backend_ctl` |
| `unit-cycle` | error, если внутри компоненты есть любой цикл по `hard`-рёбрам; warn, если цикл держится только на `lazy` | сильно связная компонента из 2+ вершин по `hard`+`lazy` (`tc` не берётся); вершина — юнит или отдельный файл из синтетического `__root__` (иначе фасад `__init__.py` слоя склеивает полсотни юнитов); одна находка на компоненту, состав — в `members` и `detail`; `backend_ctl` в графе циклов не участвует |
| `deep-import` | warn | импорт из другого юнита мимо его витрины. Витрина: `__init__` юнита, его `interfaces`, а также `__init__` любого пакета юнита с литеральным `__all__`, если все импортируемые имена в нём есть (`import pkg` и `from pkg import *` — через витрину). Находка — для любого другого файла, для `__init__` без литерального `__all__` и для имени вне `__all__` (оно названо в `detail`) |
| `private-import` | warn | импортируется имя или файл с `_` в начале из другого юнита |
| `unit-hygiene` | info | у юнита нет `interfaces.py`, `README.md`, `STATUS.md` или тестов |
| `unresolved-relative` | error; info внутри `try … except ImportError` | относительный импорт не разрешается в файл графа |
| `unit-undeclared` | info | у юнита не объявлено поле карточки (`purpose`, `tier`, `contour`); в `detail` — какие |
| `registry-drift` | warn | юнит графа не находится в `modules.yaml`, либо путь из `modules.yaml` не существует на диске |
| `parse-error` | error | файл не разобран `ast.parse` (синтаксис, кодировка); узел остаётся в графе без рёбер; число — `meta.counts.parse_errors` |
| `unresolved-absolute` | warn; info, если цель — тестовый файл (исключён из графа) | абсолютный импорт с корневым пакетом не разрешается в файл графа; число — `meta.counts.unresolved_absolute` |
| `recipe-unknown-plugin` | warn | строка `plugin_class: <dotted>` в живом `*.yaml`/`*.yml` не соответствует ни одному юниту (в неживых рецептах не проверяется) |

Каталоги `docs/` (примеры кода), `tests/`, `test/`, `test_*.py` и `conftest.py` в граф не входят; число `test_*.py` — в `spec.tests`.

Плагины подключаются не импортом, а конфигом. Поэтому генератор читает текстом (регулярка, без разбора YAML) строки
`plugin_class: <dotted>` во всех `*.yaml` и `*.yml` репозитория (кроме точечных каталогов, `__pycache__`, `node_modules`,
`graphify-out`, `logs*` и `data/atlas`), сопоставляет значение с юнитом по самому длинному префиксу и кладёт пути
рецептов в `spec.recipes`; рецепты в путях с частью `tests`, `fixtures` или `archive` — в `spec.recipes_inactive`.
`fan_in` считает только импорты: `fan_in = 0` у плагина не значит «не используется» — смотрите `spec.recipes`
(колонка «в рецептах» в `units.md` считает только живые).

## Карточка юнита — собирается, не пишется

Отдельного файла карточек нет. Генератор собирает `spec.card` из самого юнита; у каждого поля в
`card.sources` записан файл, из которого оно взято. Поле без источника — `null`, а юнит получает
находку `unit-undeclared`.

| Поле | Класс | Откуда |
|---|---|---|
| `purpose` | объявляется в коде юнита | первая непустая строка докстринга `__init__.py` юнита; иначе `purpose` записи корневого `modules.yaml` (резолвер `scripts/atlas/modules.py`) |
| `tier` | объявляется в коде юнита | строка `Tier: core\|optional\|frozen` в том же докстринге; иначе `tier` из `modules.yaml` |
| `contour` | объявляется в коде юнита | строка `Contour: ipc, state` (список через запятую) в том же докстринге; запасного источника нет |
| `adr_count` | из документов юнита | число заголовков ADR в `DECISIONS.md` юнита |
| `commands` | из кода | литеральные ключи словарей `commands = {...}` в классах и литеральные имена в `register_command(...)` |
| `threads` | из кода | имена из `threading.Thread(name=...)` с `путь:строка` |

Заголовочные строки докстринга `__init__.py` юнита (регулярка `^(Tier|Contour):[ \t]*(.+)$`):

```python
"""Одно предложение: зачем юнит существует.

Tier: core
Contour: ipc, state
"""
```

Допустимые `Tier`: core, optional, frozen; `Contour`: lifecycle, ipc, processing, state, observability, foundation, ui, device, data.
Файл `module.yaml` генератор не читает. Процессы, в которых исполняется юнит, не объявляются; потоки выводятся из кода (`threads`).

## Чего в v1 нет

- листа «рантайм»: процессы, очереди, каналы Router, команды — сейчас это снимок
  [`docs/maps/framework-core.md`](../maps/framework-core.md) и [`docs/diagrams/foundation-audit/`](../diagrams/foundation-audit/index.html);
- сторожа в CI «модель = код» (вопрос 15 брифа CTO, строка С5);
- вызовов и наследования между юнитами как отдельных рёбер (базы классов лежат в узлах).
