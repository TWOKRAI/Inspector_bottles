# Task 0.1 — ADR и интерфейсы владения в base_manager

**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Refs:** `plans/2026-10-03_lifecycle-owner-scope/plan.md`, [`DESIGN.md`](DESIGN.md) §2.1, §2.2 (строка «Примитив области»), §4
**Зависит от:** ничего. **Блокирует:** 0.2 (реализация `Scope`/`Handle` строится на этих протоколах), 0.3, 0.4.

## Goal

В `base_manager/interfaces.py` появляется контракт владения: `Stoppable`, `Resource`, `CloseReport`, `Reporter`,
`IHandle`, `IScope`, `ScopeClosedError`. ADR-BM-008 фиксирует решения DESIGN §4 и отвергнутые альтернативы.
Реализации в задаче нет — только контракт, DTO и документ.

## Files

| Файл | Что |
|---|---|
| `multiprocess_framework/modules/base_manager/interfaces.py` | новые протоколы, DTO, исключение; `__all__` расширен |
| `multiprocess_framework/modules/base_manager/DECISIONS.md` | новый `ADR-BM-008` |
| `multiprocess_framework/DECISIONS.md` | сводные разделы — только через `python -m scripts.sync`, руками не править |
| `multiprocess_framework/modules/base_manager/README.md` | раздел «Контракт владения» (что есть, где реализация, что в 0.2) |
| `multiprocess_framework/modules/base_manager/STATUS.md` | строка о Task 0.1 |
| `multiprocess_framework/modules/base_manager/docs/INTERFACES_USAGE.md` | короткий пример `IScope`/`IHandle` для потребителя |
| `multiprocess_framework/modules/base_manager/tests/test_lifetime_interfaces.py` | тесты автора (опасности контракта, см. ниже) |

**Изменение против plan.md:** строка `MODULE_TIERS.md` «`event_module` → `base_manager.interfaces`» переезжает в
Task 0.3. Причина: зависимость появится только в 0.3; запись в 0.1 описывала бы связь, которой в коде нет.

## Контракт (точная форма)

Источник — DESIGN §2.1. Ниже то, что там не дописано и решается здесь.

### `Stoppable` — `typing.Protocol`, `@runtime_checkable`
- `request_stop(self) -> None` — фаза 1. Не блокирует, идемпотентен, вызывается из любого потока.
- `join(self, deadline: float) -> bool` — фаза 2. `deadline` — абсолютное значение `time.monotonic()`.
  `True` = остановлен. На таймауте возвращает `False`, не бросает.
- `kill()` и `close()` — **не** члены протокола (Protocol не умеет «необязательный метод»). Они описаны в docstring
  протокола как необязательные; `Scope` (0.2) ищет их через `getattr`. Причина `@runtime_checkable`: `Scope.own`
  в 0.2 различает `Stoppable` и вызываемое через `isinstance`.
- Порядок различения в 0.2 фиксируется здесь в docstring: сначала `isinstance(res, Stoppable)`, иначе `callable(res)`,
  иначе `TypeError`. Объект, который одновременно `Stoppable` и вызываемый, считается `Stoppable`.

### `Resource`
`Resource = Stoppable | Callable[[], object]` — псевдоним уровня модуля, импортируемый.

### `CloseReport` — `@dataclass(frozen=True)`
Поля и порядок — как в DESIGN §2.1: `path: str`, `elapsed_s: float`, `survivors: tuple[str, ...]`,
`killed: tuple[str, ...]`, `errors: tuple[tuple[str, str], ...]`, `emits_after_close: int = 0`, `complete: bool = True`.
- `errors` — пары `(путь записи, текст ошибки)`.
- `ok` (property): `complete and not survivors and not killed and not errors`. **`emits_after_close` в `ok` не входит.**
  Причина: доставка в закрытого владельца подавляется и считается (★5а «никогда молча»); это сигнал для отчёта, не
  провал закрытия. Решение записать в ADR.
- `to_dict() -> dict` — только `dict`/`list`/`str`/`int`/`float`/`bool`: кортежи → списки, `errors` → список
  `{"path": str, "error": str}`, плюс ключ `"ok": bool`. Результат проходит `json.dumps` без `default=`.
- `from_dict(cls, d: dict) -> CloseReport` (classmethod) — обратное преобразование; ключ `"ok"` игнорируется
  (вычисляемое). Правило проекта «Dict at Boundary» требует пару `to_dict`/`from_dict`.
- `CloseReport` пиклится (это DTO). `Scope`/`Handle` не пиклятся — проверяется в 0.2, не здесь.

### `Reporter`
`Reporter = Callable[[CloseReport], None]`.

### `IHandle` — `typing.Protocol`
`path: str`, `kind: str`, `close(self, budget_s: float | None = None) -> CloseReport`. Семантика — docstring из
DESIGN §2.1 (досрочное освобождение одной записи тем же путём, что и область; идемпотентно).

### `IScope` — `typing.Protocol`
Члены и docstring — как в DESIGN §2.1:
- `path: str`; `closed` и `parent` — **read-only property** (`parent -> IScope | None`).
- `own(self, res: Resource, *, name: str, kind: str = "resource") -> IHandle`
- `child(self, name: str, *, budget_s: float | None = None) -> IScope`
- `barrier(self) -> None`
- `spawn(self, target: Callable[[threading.Event], None], *, name: str) -> IHandle`
- `cancel(self) -> None`
- `close(self, budget_s: float | None = None, *, deadline: float | None = None) -> CloseReport`
- `live(self) -> list[dict]`

Keyword-only там, где в DESIGN стоит `*`. Имена параметров — ровно такие (вызывающие пишут их по имени).

### `ScopeClosedError(RuntimeError)`
Бросается `own`/`spawn`/`child` закрытой (или закрывающейся) области. Docstring: ресурс, переданный в `own`, к моменту
броска уже освобождён.

### Ограничения файла
- `interfaces.py` импортирует только stdlib (`abc`, `typing`, `dataclasses`, `threading`). Сегодня так и есть; не
  нарушать. Основание — G6 и D1: `lifetime.py` и его контракт — только stdlib.
- Существующие `IBaseManager`/`IBaseAdapter`/`IObservableMixin` не меняются (это ABC; новые — Protocol, см. ADR).

## Steps
1. Дописать контракт в `interfaces.py` по разделу выше; расширить `__all__` семью именами.
2. ADR-BM-008 в `base_manager/DECISIONS.md`: контекст (DESIGN §1, таблица фактов — коротко, со ссылкой), решение
   (D1–D6 + сток ★5 + `ok` без `emits_after_close`), почему Protocol, а не ABC (структурная совместимость: адаптеры
   потоков, процессов, пулов не наследуют базу фреймворка), **отвергнутое с причиной**: отдельный `lifetime_module`;
   `WeakMethod`/слабые ссылки (D3); три корня процесса вместо одного с барьерами; передача `close` потоку-владельцу;
   список обёрток совместимости (shim-список) вместо атомарной миграции (D6). Раздел «Открыто» — ссылка на DESIGN §6.
3. `python -m scripts.sync` → сводные разделы `multiprocess_framework/DECISIONS.md`.
4. README / STATUS / INTERFACES_USAGE.
5. Тесты автора `test_lifetime_interfaces.py` (опасности, которые видит только автор): `to_dict` при пустых и
   непустых `errors`; `from_dict(to_dict(r)) == r` на отчёте со всеми полями; `ok` не зависит от `emits_after_close`;
   `interfaces.py` импортирует только stdlib (AST, литеральный список разрешённых модулей).
6. `python scripts/validate.py` и тесты `base_manager` зелёные.

## Acceptance criteria
- [ ] Из `multiprocess_framework.modules.base_manager.interfaces` импортируются `Stoppable`, `Resource`,
      `CloseReport`, `Reporter`, `IHandle`, `IScope`, `ScopeClosedError`; все семь — в `__all__`; старые три остались.
- [ ] `inspect.signature` каждого метода `IScope`/`IHandle`/`Stoppable` совпадает с разделом «Контракт»: имена
      параметров, значения по умолчанию, keyword-only.
- [ ] `isinstance(obj, Stoppable)`: `True` для объекта с `request_stop` и `join`; `False`, если нет `join`;
      `False` для голой функции.
- [ ] `CloseReport` заморожен: присваивание поля → `dataclasses.FrozenInstanceError`.
- [ ] `CloseReport.ok` литералами: `True` для пустого отчёта; `False` при одном survivor, при одном killed, при одной
      ошибке, при `complete=False`; `True` при `emits_after_close=5` и прочем пустом.
- [ ] `to_dict()` проходит `json.dumps` без `default=`; содержит `"ok"`; `errors` — список словарей
      `{"path", "error"}`; `from_dict(to_dict(r)) == r`; `pickle.loads(pickle.dumps(r)) == r`.
- [ ] `ScopeClosedError` — подкласс `RuntimeError`.
- [ ] `interfaces.py` импортирует только stdlib.
- [ ] ADR-BM-008 содержит пять отвергнутых альтернатив из Step 2, каждую с причиной; `multiprocess_framework/DECISIONS.md`
      пересобран `scripts.sync`.
- [ ] `python scripts/validate.py` зелёный; тесты `base_manager` зелёные (число passed — в отчёте).

## Out of scope
- Реализация `Scope`/`Handle`, `unclosed_roots()`, `BaseManager.scope` — Task 0.2.
- `Subscribers`, строка `MODULE_TIERS` про `event_module` — Task 0.3.
- Qt-адаптеры — Task 0.4. Стражи G2–G10 — Task 0.5.
- Миграция любых потребителей; правка существующих ABC.

## Открыто — для ревьюера спека
1. **Как процесс создаёт корень.** DESIGN §2.3 пишет `Scope(...)` в `ProcessLifecycle`, а G6 запрещает импорт
   `base_manager.core.lifetime` вне `base_manager`. Значит, конструктор должен приходить через пакет
   (`base_manager/__init__.py` реэкспорт) или фабрику в интерфейсах. Здесь не решается — решение нужно до спека 0.2,
   иначе G6 (0.5) и Task 1.2 разойдутся.
2. `ok` без `emits_after_close` — решение этой задачи (см. «Контракт»); если ревьюер видит, что G1/★5а требует иного,
   менять здесь, до тестера.
