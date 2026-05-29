# F.7 — сравнение подходов (для ревью)

- **Slug:** cross-tab-architecture / F.7-approach
- **Дата:** 2026-05-28
- **Статус:** DECIDED — выбран **НОВЫЙ** подход (ревью Opus, 2026-05-28, одобрено). Реализован.
  Рекомендация ревьюера учтена: docstring-предупреждение «Internal: only for bridge code» на peek/peek_required.
  Результат: полный suite `1 failed (pre-existing theme flaky) / 1997 passed`, warnings 109 → 3 (bridge молчит).
- **Ветка:** `refactor/cross-tab-architecture`
- **Связано:** [`phase-f-legacy-removal.md`](phase-f-legacy-removal.md) Task F.7

## Цель F.7 (из плана)

Перевести `DeprecationWarning` от shim `_DeprecatedExtrasDict` с `ignore` на `error` в pytest —
forcing-функция: любое будущее обращение потребителя к мигрированному ключу `ctx.extras[...]`
валит тест (защита от регрессии после миграции на AppServices DI в Phase E/F.9).

## Технические находки (подтверждены эмпирически)

### Находка 1 — исходный фильтр Phase D это no-op (никогда не работал)

```toml
# было (Phase D, Q5):
"ignore::DeprecationWarning:multiprocess_prototype.frontend._deprecated_extras"
```

Shim эмитит warning со `stacklevel=3` → warning **атрибутируется вызывающему модулю**
(`app_context`, `app_services_factory`, презентер), а НЕ `_deprecated_extras`. Module-scoped
фильтр `:..._deprecated_extras` не матчит ничего. Доказано: полный прогон на base показывает
**109 deprecation-warnings** (включая `app_context.py:62: ctx.extras['auth_state'] deprecated`),
которые фильтр якобы «игнорирует». То есть транзитный шум Phase D-F протекал всё это время.

Проверка matching'а:
- `error:ctx\.extras.*deprecated:DeprecationWarning` (message-based) — **ловит** (через filterwarnings API).
- `module=...app_services_factory` — ловит (атрибуция вызывающему модулю подтверждена).
- `module=..._deprecated_extras` — **НЕ ловит** (никогда).

### Находка 2 — все оставшиеся читатели deprecated extras это легитимные bridge

`grep` production-читателей мигрированных ключей (НЕ тесты):

| Читатель | Природа | Судьба |
|---|---|---|
| `app_services_factory.build_app_services` (7 ключей) | **Builder** — он СТРОИТ app_services из extras | by design до Phase G |
| `app_context.py` аксессоры (`topology_holder()` и т.п.) | Сам deprecated API (бридж) | Phase G удаляет AppContext |
| `tab_factory.py:309,311` (`ctx.topology_bridge()`, `ctx.plugin_manager()`) | Сборка `RuntimeDeps` из ctx (Q-F1=B boundary) | by design до Phase G |
| `administration/section.py:115` (`ctx.action_bus()`) | ActionBus-bridge | **явно Phase G** (Q-F4) |
| `app.py` (15 мест) | только **записи** `extras[k]=v` (`__setitem__` молчит) | не читатель |

**Вывод:** ни одного «случайного чтения из презентера», которое forcing-функция должна ловить.
Все читатели — известные, принятые, Phase-G-bridge. Премиса F.7 («после F.3-F.9 production-чтений
не осталось») **неверна** в том же смысле, что и у F.1 (перенесена в Phase G).

### Находка 3 — `test_theme_by_manifest::test_returns_false_without_qapplication` — pre-existing

Падает в **полном** suite и на base (без правок F.7), зелёный изолированно. Order-dependent
leakage QApplication. **Не связан с F.7**, отдельный баг.

### Фактический fallout при `error::` (message-based) сейчас

`pytest multiprocess_prototype/` → **19 deprecation-падений** (+ 1 theme pre-existing):
- `test_app_services_factory.py` (13) + `test_phase15_smoke.py` (1) — фабрика читает extras.
- `test_app_context.py::TestAppContextExtras` (5) — 3 через аксессоры, 2 через прямой `ctx.extras.get()` в теле теста.

Fails-loud-контракт фабрики (нельзя сломать): `topology_holder`/`plugin_registry`/`service_registry`
→ `KeyError`; `recipe_manager`/`auth_state` → `RuntimeError`.

---

## Подход СТАРЫЙ (первая итерация мысли)

Глобальный message-based `error` + закрыть легитимные bridge через:
- `warnings.catch_warnings()`-suppress внутри фабрики;
- module-scoped `ignore`-exemptions в pyproject для `app_services_factory` / `app_context` / `tab_factory`;
- `@pytest.mark.filterwarnings("ignore:...")` на тест-классах;
- вывод: ценность сейчас ≈ 0 (ловить нечего) → **перенести error-flip в Phase G** (как F.1),
  а сейчас лишь починить no-op `ignore` на рабочий message-based `ignore`.

**Плюсы:** минимум кода; честно отражает, что премиса неверна (параллель с F.1).
**Минусы:**
- либо «ничего не достигли сейчас» (defer), что противоречит «добиваться функциональности»;
- либо разброс suppress/exemptions по 3-4 местам + фрагильные module-пути в фильтре (ломаются при rename);
- module-exemptions опираются на тонкую семантику атрибуции warning'а вызывающему модулю;
- `administration action_bus` остаётся незакрытой дырой.

---

## Подход НОВЫЙ (предлагаемый к реализации)

Один механизм: **bridge-слой читает extras молча, прямой `ctx.extras[...]` из потребителя → error.**

1. **shim `_DeprecatedExtrasDict`** — добавить два silent-читателя (зеркало `get`/`[]`):
   ```python
   def peek(self, key, default=None):          # silent .get() для bridge
       return dict.get(self, key, default)
   def peek_required(self, key):               # silent [] для bridge (KeyError если нет)
       return dict.__getitem__(self, key)
   ```
2. **`build_app_services`** — `ctx.extras["X"]` → `ctx.extras.peek_required("X")` (5, KeyError сохранён),
   `ctx.extras.get("X")` → `ctx.extras.peek("X")` (2, None сохранён → RuntimeError-проверки целы).
3. **аксессоры `app_context.py`** — `self.extras.get(` → `self.extras.peek(` (replace_all, ~15, None-семантика сохранена).
4. **pyproject** — message-based `error` (уже применён):
   ```toml
   'error:ctx\.extras.*deprecated:DeprecationWarning'
   ```
5. **`test_app_context.py`** — 2 прямых `ctx.extras.get("registers_manager"/"plugin_registry")` в теле теста
   → через публичные аксессоры `ctx.registers_manager()` / `ctx.plugin_registry()` (тест того же, но через public API).

**Что ловит forcing-функция после этого:** любой НОВЫЙ `ctx.extras["topology_holder"]` /
`ctx.extras.get("topology_holder")` из презентера/таба/секции → warning → error в тесте.
Bridge (фабрика + аксессоры + tab_factory через аксессоры + administration через аксессор) — молчит.

**Плюсы:**
- один явный механизм (`peek`/`peek_required` = «санкционированное bridge-чтение»), самодокументируемый;
- forcing-функция реально работает СЕЙЧАС (ловит прямой extras-доступ), не отложена;
- нет фрагильных module-путей в конфиге; устойчив к rename;
- чистит 109 протекавших warnings (bridge молчит);
- правки мелкие и механические, без re-indent/структурных рисков.

**Минусы / на что смотреть ревьюеру:**
- forcing-функция ловит только **прямой `ctx.extras[...]`**, но НЕ вызов аксессора `ctx.topology_holder()`
  (он молчит). Приемлемо? (аксессоры почти мёртвы пост-F.9, удаляются в Phase G; «use services.X» — цель,
  но прямой extras — главный анти-паттерн по brief §2.2 / Dict-at-Boundary).
- два метода на shim вместо одного — не over-engineering ли? (альтернатива: один `peek` с sentinel-default,
  но менее читаемо).
- `peek` слегка ослабляет «единственный путь — services.X», легализуя bridge-чтение через метод.

---

## Вопрос ревьюеру

1. Какой подход брать — **НОВЫЙ (peek)** или **СТАРЫЙ (defer→Phase G + починить ignore)**?
2. Если НОВЫЙ: `peek`/`peek_required` (2 метода) vs один `peek` с sentinel — что чище?
3. Достаточна ли forcing-функция, ловящая только прямой `ctx.extras[...]` (аксессоры молчат)?
   Или нужно ловить и `ctx.X()`-аксессоры тоже (тогда они валят tab_factory/administration → надо exempt)?
4. Не нарушает ли `peek` принцип «editor vs runtime» / Dict-at-Boundary? Нет ли скрытой дыры?
5. Корректна ли квалификация F.7 как «достижима сейчас», или премиса всё же требует переноса в Phase G (как F.1)?
