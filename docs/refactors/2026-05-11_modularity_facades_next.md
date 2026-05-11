# Modularity restoration — next steps после фасадов

**Дата:** 2026-05-11
**Branch:** `chore/mlx-embeddings-migration` (текущая) — два коммита уже на ней.
**Триггер:** ADR-120 обещал восстановление modularity (0.448 → 0.242 после Phase 5). За эту сессию вернули 0.249 → **0.263** через фасадный подход; bottleneck сместился с modularity на acyclicity. Дальше — Phase-уровневые carve-out'ы.

## Что уже сделано (на этой ветке)

### Коммит `8252c88` — фасад `process_module.plugins`
- В `multiprocess_framework/modules/process_module/plugins/__init__.py` реэкспортированы `SchemaBase`, `FieldMeta`, `register_schema` (из `data_schema_module`) и `PluginConfig` (из `generic.generic_process_config`).
- 49 файлов в `Plugins/` переписаны на единый импорт через `process_module.plugins`.
- Эффект: cross_module_edges 1544 → 1457 (−87), modularity 0.249 → 0.258, quality_signal 6195 → 6210.

### Коммит `3eca0d5` — `frontend.schema_adapter` + дофасадить plugins
- Новый файл `multiprocess_framework/modules/frontend_module/schema_adapter.py` — реэкспорт `SchemaBase`, `FieldMeta`, `register_schema`, `FieldRouting`, `RegisterDispatchMeta`.
- 22 файла `frontend_module/` мигрированы на adapter.
- В `process_module.plugins.__init__` добавлен реэкспорт `ExecutionMode`, `ThreadConfig` (worker), `RegistersManager`.
- 3 остаточных файла `Plugins/` (io/database, sources/heartbeat, color_mask тест) — на фасад.
- Эффект: edges 1457 → 1433 (−24), modularity 0.258 → 0.263, quality_signal 6210 → 6218.

### Накопительные метрики

| Метрика | Было | Стало | Δ |
|---|---|---|---|
| quality_signal | 6195 | **6218** | +23 |
| modularity (raw) | 0.249 | **0.263** | +0.014 |
| cross_module_edges | 1544 | **1433** | −111 |
| propagation_cost | 27 | **25** | −2 |
| bottleneck | modularity | **acyclicity** | сместился |
| check_rules | 9/9 pass | 9/9 pass | без регрессий |

Тесты на каждом коммите: framework 2531 passed, plugins 170, prototype 945 — без регрессий.

---

## Что мы НЕ делаем (и почему)

1. **Adapter в `multiprocess_prototype/_fw.py`** — дубль publishing API `frontend_module.actions`/`.managers`. Нарушает явную convention из docstring `frontend_module/__init__.py` («доменные расширения через submodule API»). Marginal +0.003 modularity не стоит размывания границ.
2. **Расширение `frontend_module/__init__.py`** — автор сознательно ограничил public API одним Manager-классом, остальное — через submodule API. Не лезем.
3. **Микро-фасады «ради метрики»** — фасадный поход исчерпан. Дальше плато: каждый новый фасад даёт ≤−5 edges, ≤+0.002 modularity. Это noise.

## Проверка гипотез через DSM (2026-05-11, после план-ревью)

Прогнали `mcp__sentrux__scan` + `mcp__sentrux__dsm` + точечный grep по двум кандидатам перед `git mv`. Результат:

| Кандидат | Внутренних импортов в `frontend_module.*` | Внешних потребителей вне `frontend_module` | Carve-out delta (прогноз) |
|---|---|---|---|
| `components/_examples/` | ≥10 (schema_adapter, components.base/compound/numeric/group/checkbox) | 1 (тест внутри frontend) | **отрицательная** — создадим ~15 новых cross-module edges, которых сейчас нет |
| `actions/` | 0 (нет обратных импортов в frontend) | ≥14 (prototype/frontend/actions/*, Services/sql/action_log/*) | **положительная** — edges не растут, frontend_module становится тоньше |

**Метрики на момент проверки:** quality_signal=6224 (+6 от планового 6218), modularity raw=0.267, cross_module_edges=1433, bottleneck=acyclicity (raw=1, score=5000), clusters=`[]` — sentrux не выделяет именованных кластеров на этом графе.

**Вывод:** Вариант 1 отменён. Вариант 2 повышается в приоритет.

## Где остался реальный leverage

### ~~Вариант 1: Carve-out `frontend_module/components/_examples/`~~ — ОТКЛОНЁН

**Причина отказа (зафиксирована проверкой DSM 2026-05-11):** `_examples/*` импортируют ~15 раз обратно в `frontend_module.components.base/compound/numeric/group/checkbox` и `frontend_module.schema_adapter`. Пока поддерево сидит внутри frontend_module — это intra-module edges (для sentrux не считаются как cross). После `git mv` они превратятся в cross-module edges от нового `frontend_examples_module` к старому `frontend_module`, и modularity уйдёт **вниз**, не вверх.

Прогноз в плане «+0.005…+0.008» был построен на гипотезе изоляции, которая опровергнута. Урок занесён в раздел «Критерии carve-out» ниже.

### Вариант 2: Carve-out `frontend_module/actions/` — ТЕПЕРЬ ПЕРВЫЙ

**Что:** Action / ActionBus / ActionBuilder / ActionHandler / handlers/* — это action-bus (undo/redo pattern), отдельная концепция от UI-виджетов.

**Куда:** `multiprocess_framework/modules/actions_module/` ИЛИ `Services/actions/` (зависит от взгляда: framework-runtime vs прикладной сервис).

**Шаги:**
1. Разведка: `grep -rln "from multiprocess_framework.modules.frontend_module.actions"` — сколько мест и где.
2. ADR с указанием куда переезжает и почему.
3. `git mv frontend_module/actions → actions_module/` (или Services/actions/).
4. Sed-замена импортов во всех ~14 prototype-файлах и в frontend (если frontend сам что-то импортирует из своих actions).
5. Обновить `frontend_module/__init__.py` (убрать упоминание actions из docstring), создать соответствующий manifest для нового модуля.
6. Обновить `.sentrux/rules.toml`: добавить boundary для нового модуля (`actions → prototype` запретить, как у frontend).
7. `validate.py` + полный тестовый прогон + sentrux session_end.

**Прогноз:** +0.01…+0.02 modularity. Создаём чистый кластер actions, frontend_module становится тоньше.

**Риск:** средний. Нужно проверить, что actions не циркулирует обратно в frontend (могут быть handler'ы, которые знают про конкретные frontend-виджеты).

**Время:** 4-6 часов.

### Вариант 3: sentrux Pro ($15/мес, отложено)

**Когда брать:** если упрёмся в acyclicity (level_breaks=7) и нужна адресная диагностика «какие именно 7 edges перепрыгивают уровни». Free версия даёт только raw=1, score=5000 без указания файлов. Pro покажет конкретный список.

**До этого:** не брать, варианты 1 и 2 двигают modularity без необходимости в Pro-диагностике.

---

## Критерии фасада-адаптера (правило, а не «давайте везде»)

Чтобы фасады создавались не по принципу «в каждом модуле», а по data-driven критерию — фиксируем порог. Фасад-адаптер (тип `process_module.plugins`, `frontend_module.schema_adapter`) уместен, только если ВСЕ четыре условия выполнены:

1. **N ≥ 10 файлов внутри одного top-level модуля** тянут одну поперечную зависимость (или одну группу зависимостей). Меньше — не нужно, экономия ≤ 5 edges = шум на фоне 1400+ total.
2. **Зависимость поперечная** — за пределы своего top-level модуля. Фасад внутри своего модуля sentrux'у безразличен: intra-module edges не считаются как cross.
3. **Реэкспорт чистый** (pass-through): тип/функция/декоратор без UI-надстроек, без бизнес-логики, без условной диспатчеризации. Иначе фасад превратится в смешение слоёв — это явно зафиксировано в [schema_adapter.py:15-18](multiprocess_framework/modules/frontend_module/schema_adapter.py#L15-L18).
4. **Стабильная сигнатура** — реэкспортируем то, что меняется редко. Если зависимость в активной разработке, фасад превращается в barrier для refactoring (двойной апдейт `__all__` + docstring + потребители).

**Контр-показания (когда фасад НЕ делаем даже при N≥10):**
- Уже есть public API через `__init__.py` модуля-источника — потребители должны импортировать оттуда, а не через адаптер.
- Bottleneck сместился с modularity на другое (см. ниже).

## Критерии carve-out (правило, а не «давайте вынесем»)

Carve-out поддерева в отдельный top-level модуль уместен, только если ВСЕ четыре условия:

1. **Слабая обратная связь:** поддерево импортирует ≤ N=2 раз внутрь своего родителя. **Это самый важный критерий и единственная причина, по которой Вариант 1 отменён.** До carve-out нужно посчитать grep'ом обратные импорты — если их 10+, carve-out даст отрицательную дельту (intra → cross).
2. **Когерентная концепция:** поддерево — отдельная абстракция (actions/undo-redo, plugin runtime, schema engine), а не «случайно сложенные файлы».
3. **N ≥ 5 внешних потребителей** за пределами родителя — иначе carve-out не оправдывает ADR + новый README/STATUS + boundary в `.sentrux/rules.toml`.
4. **N ≥ 8 файлов / 500 LOC** — иначе это «карликовый модуль», увеличивающий шум в DSM без выигрыша.

**Acceptance перед `git mv` (обязательная разведка):**
```bash
# 1. Обратные импорты внутрь родителя (должно быть ≤ 2)
grep -rn "from multiprocess_framework.modules.<parent>" <subtree>/ --include="*.py" | grep -v "<parent>.<subtree>"

# 2. Внешние потребители (должно быть ≥ 5)
grep -rln "<parent>.<subtree>\|<parent>/<subtree>" --include="*.py" . | grep -v __pycache__ | grep -v <subtree>/

# 3. Размер (≥ 8 файлов / 500 LOC)
find <subtree>/ -name "*.py" | wc -l
find <subtree>/ -name "*.py" -exec wc -l {} + | tail -1
```

Если хотя бы один из критериев не выполнен — carve-out отменить или дожидаться, пока поддерево дорастёт/изолируется.

## Когда вообще НЕ заниматься modularity

Bottleneck в sentrux переключается. Если `mcp__sentrux__health` показывает `bottleneck != "modularity"`, фасады и carve-out'ы дают marginal-выигрыш на текущей метрике-боли:

- **bottleneck=acyclicity** (текущее состояние, raw=1, score=5000) — лечится разрывом конкретных циклов между уровнями (level_breaks=7). Free-версия sentrux не показывает какие именно edges перепрыгивают; Pro показывает. До этого фасад/carve-out не помогает.
- **bottleneck=depth** (raw≥6) — слишком глубокий dependency chain, лечится spike-edges (фасад как раз помогает).
- **bottleneck=equality** — лечится либо разбиением гигантских модулей (`data_schema_module` 16K LOC), либо merge'ом карликовых.

Перед началом нового шага рефакторинга — `mcp__sentrux__health` → читаем `bottleneck` → выбираем инструмент под него, а не «опять фасады».

## Рекомендованный порядок (обновлено 2026-05-11)

1. ~~Вариант 1 (_examples carve-out)~~ — **отменён** проверкой DSM, см. выше.
2. **Вариант 2 (actions carve-out) — первый и единственный по modularity.** Размер 12 файлов / 1100 LOC, 0 обратных импортов в frontend, ≥14 внешних потребителей. Соответствует всем четырём критериям carve-out.
3. **Замерить sentrux** после carve-out actions. Если modularity дала +0.005…+0.01 — фиксируем достижение и переключаемся на acyclicity (sentrux Pro для адресной диагностики 7 level_breaks).
4. **Промежуточный merge** в main сразу после Варианта 2 — не накапливать одной megafeature.

## Команды для старта в новом чате

```bash
# Контекст текущего состояния
git log --oneline -3
mcp__sentrux__scan path=/Users/twokrai/Project_code/Inspector_bottles
mcp__sentrux__health   # убедиться, что bottleneck всё ещё modularity-friendly
mcp__sentrux__check_rules

# Разведка перед carve-out actions (Вариант 2, теперь первый)
# Внутренние обратные импорты (должно быть 0)
grep -rn "from multiprocess_framework.modules.frontend_module" \
  multiprocess_framework/modules/frontend_module/actions/ --include="*.py" \
  | grep -v "frontend_module.actions"
# Внешние потребители (ожидание ≥14)
grep -rln "frontend_module.actions" --include="*.py" . \
  | grep -v __pycache__ | grep -v multiprocess_prototype_backup \
  | grep -v "frontend_module/actions/"

# После carve-out — обязательная проверка
python scripts/validate.py
python scripts/run_framework_tests.py
mcp__sentrux__session_end
```

## Файлы-якоря для контекста нового чата

- [multiprocess_framework/DECISIONS.md](../../multiprocess_framework/DECISIONS.md) — ADR-120 контекст про modularity, нужно дописать ADR-124.
- [multiprocess_framework/modules/process_module/plugins/__init__.py](../../multiprocess_framework/modules/process_module/plugins/__init__.py) — текущий фасад plugins, шаблон для следующих.
- [multiprocess_framework/modules/frontend_module/schema_adapter.py](../../multiprocess_framework/modules/frontend_module/schema_adapter.py) — текущий фасад frontend, шаблон.
- [.sentrux/rules.toml](../../.sentrux/rules.toml) — добавлять boundary при создании нового модуля.
- [docs/refactors/2026-05_arch_cleanup.md](2026-05_arch_cleanup.md) и [2026-05-10_post_phase5.md](2026-05-10_post_phase5.md) — предыдущие планы для согласования стиля.
