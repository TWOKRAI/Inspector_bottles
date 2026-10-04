# Task 0.1 — ADR и интерфейсы владения в base_manager

**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Refs:** `plans/2026-10-03_lifecycle-owner-scope/plan.md`, [`DESIGN.md`](DESIGN.md) §2.1, §2.2 (строка «Примитив области»), §4
**Зависит от:** ничего. **Блокирует:** 0.2 (реализация `Scope`/`Handle` строится на этих протоколах), 0.3, 0.4.

## Goal

В `base_manager/interfaces.py` появляется контракт владения: `Stoppable`, `Resource`, `CloseReport`, `Reporter`,
`IHandle`, `IScope`, `ScopeClosedError`. ADR-BM-008 фиксирует решения D1–D3 DESIGN §4, решения CTO 2026-10-04 и
отвергнутые альтернативы; D4–D6 только упоминает (Step 2).
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
- `join_until(self, deadline: float) -> bool` — фаза 2. `deadline` — абсолютное значение `time.monotonic()`.
  `True` = остановлен. На таймауте возвращает `False`, не бросает. **Имя намеренно не `join`** (вердикт CTO
  2026-10-04, Q1): у `threading.Thread`, `multiprocessing.Process`, `QThread` есть `join(timeout)` с ОТНОСИТЕЛЬНЫМ
  таймаутом и без результата — подкласс с добавленным `request_stop` проходил бы `isinstance(…, Stoppable)` и ждал
  абсолютное значение как секунды (зонд: 2.00 с при бюджете 0.1 с, возврат `None`). С `join_until` такой объект не
  Stoppable и не вызываемый → `TypeError` в `own()` до регистрации. Keyword-only `join(*, deadline)` не спасает:
  `isinstance` остаётся `True`.
- `kill()` и `close()` — **не** члены протокола (Protocol не умеет «необязательный метод»). Они описаны в docstring
  протокола как необязательные; `Scope` (0.2) ищет их через `getattr`. Причина `@runtime_checkable`: `Scope.own`
  в 0.2 различает `Stoppable` и вызываемое через `isinstance`.
  - `kill()` — фаза 3, только после `join_until() == False`. **Не блокирует**: отправить сигнал (terminate /
    `cancel_futures`) и вернуться; ожидание смерти — повторный `join_until` к сроку резерва. Причина (зонд CTO):
    `kill()`, блокирующий 0.3 с, при двух застрявших дал 0.80 с = бюджет + 2 × 0.3 — резерв умножается на N;
    неблокирующий — 0.22 с.
  - `close()` — освобождение после успешного `join_until`/`kill`.
- Порядок различения в 0.2 фиксируется здесь в docstring: сначала `isinstance(res, Stoppable)`, иначе `callable(res)`,
  иначе `TypeError`. Объект, который одновременно `Stoppable` и вызываемый, считается `Stoppable`. Причина: так он
  получает фазу 2 к сроку; ветка «вызываемое» её пропустила бы.
- `@runtime_checkable` проверяет только наличие имён (`getattr_static`), не сигнатуру и не смысл. Поэтому отказ от
  `hasattr` прототипа: `hasattr` вызывает `__getattr__`, и прокси/`Mock()` проходили бы как Stoppable (проба H2, H5).

### `Resource`
`Resource = Stoppable | Callable[[], object]` — псевдоним уровня модуля, импортируемый.

### `CloseReport` — `@dataclass(frozen=True)`
Поля и порядок — как в DESIGN §2.1: `path: str`, `elapsed_s: float`, `survivors: tuple[str, ...]`,
`killed: tuple[str, ...]`, `errors: tuple[tuple[str, str], ...]`, `emits_after_close: int = 0`, `complete: bool = True`.
- `errors` — пары `(путь записи, текст ошибки)`.
- `__post_init__` приводит `survivors`, `killed`, `errors` (и каждую пару внутри) к кортежам. Причина: отчёт с
  `survivors=["a"]` иначе не хэшируется (`TypeError: unhashable type: 'list'`, проба H6) и не равен такому же с
  кортежами. Инвариант держит один владелец — сам DTO, а не каждый вызывающий.
  Строка на месте последовательности (`survivors`, `killed`, `errors`) или на месте пары внутри `errors` →
  `TypeError`; пара не из двух элементов → `TypeError`. Причина (ревью р2, проба R2): `tuple("proc/x")` молча
  режет строку на символы — `survivors=h.path` вместо `(h.path,)` дал бы 15 «выживших».
- `ok` (property): `complete and not survivors and not killed and not errors`. **`emits_after_close` в `ok` не входит.**
  Причина: доставка в закрытого владельца подавляется и считается (★5а «никогда молча»); это сигнал для отчёта, не
  провал закрытия. Решение записать в ADR. Docstring поля: счётчик видит доставки только до сборки отчёта; отчёт
  заморожен, поздние доставки в него не попадут — куда они идут, решает Task 0.3.
- `to_dict() -> dict` — только `dict`/`list`/`str`/`int`/`float`/`bool`: кортежи → списки, `errors` → список
  `{"path": str, "error": str}` (потребитель `introspect.lifetime` читает по ключу, не по индексу), плюс ключ
  `"ok": bool`. Набор ключей ровно: `path`, `elapsed_s`, `survivors`, `killed`, `errors`, `emits_after_close`,
  `complete`, `ok`. Результат проходит `json.dumps` без `default=`.
- `from_dict(cls, d: dict) -> CloseReport` (classmethod) — обратное преобразование. Правило проекта «Dict at Boundary»
  требует пару `to_dict`/`from_dict`. Строгий край:
  - ключ `"ok"` игнорируется (вычисляемое): пустой отчёт с `"ok": False` даёт `.ok is True`;
  - нет `emits_after_close` / `complete` → `0` / `True`;
  - нет `path`, `elapsed_s`, `survivors`, `killed` или `errors` → `ValueError` с именем ключа;
  - лишний ключ (кроме `"ok"`) → `ValueError` с именем ключа. Причина: обе стороны — один код одной версии; лишний
    ключ — опечатка или чужой словарь, молча терять его нельзя.
- `CloseReport` пиклится (это DTO). `Scope`/`Handle` не пиклятся — проверяется в 0.2, не здесь.

### `Reporter`
`Reporter = Callable[[CloseReport], None]`.

### Атрибуты протоколов — только read-only property
`IHandle.path`, `IHandle.kind`, `IScope.path`, `IScope.closed`, `IScope.parent` — `@property` без setter.
Причина (проба pyright ревью спека): реализация с read-only `@property path` против протокола с изменяемым атрибутом
`path: str` даёт `"path" is invariant because it is mutable`; обратный случай — property в протоколе, обычный атрибут
в реализации — проходит. Изменяемый `path` дал бы переименование области на лету и сломал бы перепись потоков G4.

### `IHandle` — `typing.Protocol`
`path -> str`, `kind -> str` (property), `close(self, budget_s: float | None = None) -> CloseReport`. Семантика —
docstring из DESIGN §2.1 (досрочное освобождение одной записи тем же путём, что и область; идемпотентно).
`budget_s=None` — `budget_s` области-владельца; резерв kill — её `kill_reserve_s`, правила те же, что у `IScope.close`.

### `IScope` — `typing.Protocol`
Члены и docstring — как в DESIGN §2.1:
- `path -> str`, `closed -> bool`, `parent -> IScope | None` — property.
- `own(self, res: Resource, *, name: str, kind: str = "resource") -> IHandle`
- `child(self, name: str, *, budget_s: float | None = None, kill_reserve_s: float | None = None) -> IScope` —
  `None` = значение родителя, копируется при создании. Пример (Task 1.1): `children = work.child("children",
  budget_s=budget["pm_graceful_s"], kill_reserve_s=budget["pm_total_s"] - budget["pm_graceful_s"])`.
- `barrier(self) -> None`
- `spawn(self, target: Callable[[threading.Event], None], *, name: str) -> IHandle`
- `cancel(self) -> None`
- `close(self, budget_s: float | None = None, *, deadline: float | None = None) -> CloseReport` — docstring
  (вердикт CTO 2026-10-04, Q3):
  - Срок фазы 2: `deadline`, если задан; иначе `now + budget_s`; иначе `now + self.budget_s`. **Оба заданы →
    `ValueError` до любого действия** (два источника одного числа — тот же класс дефекта, что две копии формулы
    бюджета).
  - Дочерняя область, закрываемая родителем, получает срок **`min(срок родителя, now + child.budget_s)`**: ребёнок не
    переживёт родителя и не растянет свой сегмент (прототип без `min`: `work` с бюджетом 0.2 под корнем 1.0 ждал
    1.00 с — застрявший `work` съел бы время `transport`/`planes`).
  - Фаза 3 (kill) выполняет та область, которой принадлежит запись, после СВОЕГО срока фазы 2, в пределах СВОЕГО
    `kill_reserve_s`. **Срок родителя резерв не обрезает** — бюджет родителя обязан его включать (у PM:
    `pm_total = pm_graceful + kill_reserve`, `outer = pm_total + margin`, одна функция `stop_budget`, ADR-PMM-031).
    Обрезка оставила бы опоздавшего ребёнка-процесс живым — сироты, против которых писалась stop-ownership Task 1.4.
  - Ожидание убитых — `join_until(now + kill_reserve_s)` по всем убитым разом.
  - Отчёт: `elapsed_s` ≤ `budget + kill_reserve_s` своей области, если резерв потребовался; ≤ `budget`, если нет.
    Оценка верна для области, в бюджет которой входят резервы её детей (так строится `stop_budget`); область,
    чей ребёнок держит свой резерв сверх её бюджета, может закрываться дольше на этот резерв.
- `live(self) -> list[dict]`

Keyword-only там, где в DESIGN стоит `*`. Имена параметров — ровно такие (вызывающие пишут их по имени).

### Дверь создания корня — решение CTO 2026-10-04 (Q2)
Корень области создаётся ТОЛЬКО фабрикой пакета; в 0.1 — текст ADR, код и тест сигнатуры — Task 0.2:
```python
from multiprocess_framework.modules.base_manager import open_scope, unclosed_roots
def open_scope(path: str, *, budget_s: float, kill_reserve_s: float = 0.0,
               reporter: Reporter | None = None) -> IScope
```
- `budget_s` обязателен: число приходит из `stop_budget` (Dict at Boundary); в `base_manager` числа бюджета не живут.
- `kill_reserve_s = 0.0` по умолчанию: «резерва нет» — не бюджетное число; второй копии `TERMINATE_GRACE_S` /
  `KILL_CONFIRM_S` в `base_manager` не появляется. Корень PM получает резерв из `stop_budget`.
- `Scope`, `Handle` в `__all__` пакета НЕ входят; снаружи аннотация — только `IScope` / `IHandle`. Наследовать
  `Scope` снаружи нельзя — второго владельца через `class X(Scope)` не написать.
- `unclosed_roots() -> list[dict]` реэкспортируется для G3.
- DESIGN §2.3: строка `root = Scope(f"proc/{name}", ...)` читается как
  `root = open_scope(f"proc/{name}", budget_s=..., kill_reserve_s=..., reporter=lifecycle.report)`.
- Отвергнуто (в ADR, внутри решения): фабрика в `interfaces.py` (интерфейс импортировал бы реализацию — инверсия
  направления, ломает «только stdlib»); исключение в allowlist G6 для `process_module` (второе место, где известен
  класс); экспорт класса `Scope` (наследование = второй владелец).
- G2 (Task 0.5) сравнивает **текст** аннотации с `IScope`, а не полагается на отсутствие экспорта:
  `type(open_scope(...))` класс всё равно отдаёт.

### Семантика в docstring (алгоритм — блокировки, сегменты, LIFO — остаётся за 0.2)
- **Reporter.** Задаётся корню; дети наследуют. Вызывается **ровно один раз на каждое закрытие, начатое не изнутри
  закрытия родителя**: `close()` корня — один вызов с итоговым отчётом; досрочный `child.close()` / `Handle.close()` —
  один вызов с отчётом этой записи. Внутри закрытия родителя отчёты детей сливаются в отчёт родителя, отдельных вызовов
  нет. «Выживший — в reporter сразу» (DESIGN §2.2) читается так: отчёт уходит в момент возврата `close`, до
  `os._exit` раннера, а не по gc. Вызов — на потоке закрывающего. Исключение reporter'а ловится, пишется одной строкой
  через stdlib `logging` и из `close` не выходит (принцип ADR-BM-007: учёт не бросает поверх настоящей ошибки).
  `complete=False` для этого не используется — флаг занят реентрантным вызовом.
- **`live()`** — список словарей с ключами ровно `path`, `kind`, `state`; `state` ∈ {`"open"`, `"stopping"`,
  `"survivor"`}. Закрытые записи в `live()` не попадают. Причина литералов: `live()` уходит в `introspect.lifetime`
  (G9) по правилу Dict at Boundary.
- **`kind`.** Зарезервированы `"scope"` (запись `child`) и `"thread"` (запись `spawn`); по умолчанию `"resource"`;
  остальное — свободная строка.
- **Пометка потока, закрывающего свою область** (DESIGN §2.1, совет 8) — в `survivors` литерал `"<path> (self)"`.
- **`name`** — непустая строка без `/` и без суффикса ` (self)` (иначе неотличима от пометки выше), иначе
  `ValueError`. Повтор имени среди **незакрытых** записей области → `ValueError`; после `Handle.close()` или
  закрытия ребёнка имя свободно. Причина: путь — идентичность записи в отчёте и в переписи потоков G4; два
  одинаковых живых пути неразличимы. `Subscribers` (0.3) и `attach_qt` (0.4) генерируют уникальные имена сами.

### `ScopeClosedError(RuntimeError)`
Бросается `own`/`spawn`/`child` закрытой (или закрывающейся) области. Docstring: ресурс, переданный в `own`, к моменту
броска уже освобождён.

### Тексты ошибок
- `ScopeClosedError` называет путь области, `name` записи и состояние (`closing` / `closed`).
- `TypeError` из `own` (не Stoppable и не вызываемое) называет `type(res).__name__`, не `repr(res)`: `repr` чужого
  объекта может быть дорогим, бросать или тащить данные.
- `ValueError` из `from_dict` называет имя ключа, но не печатает словарь.

### Ограничения файла
- `interfaces.py` импортирует только stdlib. Разрешённый литеральный список: `__future__`, `abc`, `collections.abc`,
  `dataclasses`, `threading`, `typing`. Сегодня так и есть; не нарушать. Основание — G6 и D1: `lifetime.py` и его
  контракт — только stdlib.
- Существующие `IBaseManager`/`IBaseAdapter`/`IObservableMixin` не меняются (это ABC; новые — Protocol, см. ADR).

## Steps
1. Дописать контракт в `interfaces.py` по разделу выше; расширить `__all__` семью именами.
2. ADR-BM-008 в `base_manager/DECISIONS.md`:
   - **Контекст:** DESIGN §1, таблица фактов — коротко, со ссылкой. Одна строка о границе: межпроцессный протокол
     останова — ADR-PMM-031 / ADR-SRM-016, BM-008 его не повторяет.
   - **Решает сам:** D1 (дом), D2 (один `Stoppable` + вызываемое), D3 (без слабых ссылок), `ok` без
     `emits_after_close`, Protocol вместо ABC (адаптеры потоков, процессов, пулов не наследуют базу фреймворка),
     дверь создания корня `open_scope` (Q2), `join_until` вместо `join` (Q1), сроки и резерв kill (Q3: `min`,
     резерв сверху, `kill()` не блокирует, «оба заданы» → `ValueError`) — вердикт CTO 2026-10-04 со ссылками на зонды.
     **Только упоминает:** D4 — ADR модуля process в Task 1.2; D5 — frontend в 0.4/0.5; D6 — политика плана.
   - **Отвергнутое — восемь пунктов, каждый отдельным пунктом списка с жирным именем и причиной:** **отдельный
     `lifetime_module`**; **`WeakMethod` / слабые ссылки** (D3); **три корня процесса** вместо одного с барьерами;
     **передача `close` потоку-владельцу**; **список обёрток совместимости** вместо атомарной миграции (D6);
     **несколько протоколов по видам ресурса** (D2); **проверка `hasattr`, как в прототипе** (`__getattr__` прокси и
     `Mock()` проходят как Stoppable); **`join` + запрет в docstring** (правило в прозе против ловушки в типах, Q1).
   - Раздел «Открыто» — ссылка на DESIGN §6.
3. `python -m scripts.sync` → сводные разделы `multiprocess_framework/DECISIONS.md`.
4. README (раздел «Контракт владения» + маркер `Stability:`; устаревшие §6/§9 про «ADR-114…117» — не трогать, отдельная
   задача) / STATUS / INTERFACES_USAGE. Пример в `INTERFACES_USAGE.md` только принимает готовый `owner: IScope` и не
   создаёт корень.
5. Тесты автора `test_lifetime_interfaces.py` (опасности, которые видит только автор): `to_dict` при пустых и
   непустых `errors`; `from_dict(to_dict(r)) == r` на отчёте со всеми полями; `ok` не зависит от `emits_after_close`;
   `interfaces.py` импортирует только stdlib (AST, литеральный список из «Ограничений файла»).
6. `python scripts/validate.py` и тесты `base_manager` зелёные.

**Handoff:** tester (RED по acceptance, отдельный worktree на коммите спека до реализации) → teamlead (GREEN, лимит
2 итерации, коммит с трейлерами, без push) → ведущий (инъекции против обоих наборов) → reviewer (синхронно).
**Gate:** `python scripts/validate.py`; тесты `base_manager` (число passed в отчёте); ruff на изменённых `.py`.

## Acceptance criteria
- [ ] Из `multiprocess_framework.modules.base_manager.interfaces` импортируются `Stoppable`, `Resource`,
      `CloseReport`, `Reporter`, `IHandle`, `IScope`, `ScopeClosedError`; все семь — в `__all__`; `IBaseManager`,
      `IBaseAdapter`, `IObservableMixin` остались в `__all__`.
- [ ] `inspect.signature` каждого метода `IScope`/`IHandle`/`Stoppable` совпадает с разделом «Контракт»: имена
      параметров, значения по умолчанию, keyword-only.
- [ ] `IScope.path`, `IScope.closed`, `IScope.parent`, `IHandle.path`, `IHandle.kind` — объекты `property` в
      `__dict__` своего протокола, у каждого `fset is None`.
- [ ] `inspect.signature(IScope.child)` — параметры ровно `(self, name, *, budget_s=None, kill_reserve_s=None)`;
      `inspect.signature(IScope.close)` — `(self, budget_s=None, *, deadline=None)`;
      `inspect.signature(Stoppable.join_until)` — `(self, deadline)`; у `Stoppable` нет атрибута `join`.
- [ ] `isinstance(obj, Stoppable)`: `True` для объекта с `request_stop` и `join_until`; `False`, если нет
      `join_until`; `False` для объекта с `request_stop` и `join` (без `join_until`); `False` для подкласса
      `threading.Thread` с добавленным `request_stop`; `False` для голой функции; `False` для
      `threading.Thread(target=f)` и `multiprocessing.Process(target=f)` (не запущенных).
- [ ] `CloseReport` заморожен: присваивание поля → `dataclasses.FrozenInstanceError`.
- [ ] `CloseReport(..., survivors=["a"], killed=[], errors=[["p", "e"]])` → поля — кортежи; `hash()` не бросает;
      отчёт равен такому же, собранному из кортежей.
- [ ] `CloseReport(..., survivors="a", ...)` → `TypeError`; `errors=["pe"]` → `TypeError`;
      `errors=[("p", "e", "x")]` → `TypeError`.
- [ ] `CloseReport.ok` литералами: `True` для пустого отчёта; `False` при одном survivor, при одном killed, при одной
      ошибке, при `complete=False`; `True` при `emits_after_close=5` и прочем пустом.
- [ ] `to_dict()`: `set(r.to_dict()) == {"path", "elapsed_s", "survivors", "killed", "errors", "emits_after_close",
      "complete", "ok"}`; проходит `json.dumps` без `default=`; `errors` — список словарей с ключами ровно
      `{"path", "error"}`.
- [ ] `from_dict`: `from_dict(to_dict(r)) == r` на отчёте со всеми полями непустыми; без `emits_after_close` и
      `complete` → `0` и `True`; пустой отчёт с `"ok": False` → `.ok is True`; без `"survivors"` → `ValueError`, в
      тексте есть `survivors`; лишний ключ `"extra"` → `ValueError`, в тексте есть `extra`; `hash(from_dict(d))` не
      бросает.
- [ ] `pickle.loads(pickle.dumps(r)) == r`.
- [ ] `ScopeClosedError` — подкласс `RuntimeError`.
- [ ] `interfaces.py` импортирует только модули из списка «Ограничения файла» (проверка по AST).
- [ ] ADR-BM-008 содержит восемь отвергнутых альтернатив из Step 2, каждую отдельным пунктом с жирным именем и причиной;
      `multiprocess_framework/DECISIONS.md` пересобран `scripts.sync` (проверяет ревьюер, не тестер).
- [ ] `python scripts/validate.py` зелёный; тесты `base_manager` зелёные (число passed — в отчёте).

## Out of scope
- Реализация `Scope`/`Handle`, `unclosed_roots()`, `BaseManager.scope`, фабрика `open_scope` и её экспорт из
  `base_manager/__init__.py` — Task 0.2.
- `Subscribers`, строка `MODULE_TIERS` про `event_module` — Task 0.3.
- Qt-адаптеры — Task 0.4. Стражи G2–G10 — Task 0.5.
- Миграция любых потребителей; правка существующих ABC.

## Решения CTO 2026-10-04 (эскалация ревьюера спека, итерация 1)
Q1 = `join_until`; Q2 = `open_scope` в пакете, `Scope` не экспортируется; Q3 = сигнатура ревьюера + `min` для срока
ребёнка + неблокирующий `kill()` + «оба заданы» → `ValueError`. Все три меняют DESIGN §2.1/§2.3 — DESIGN поправлен
тем же коммитом (ред. 3.1). Зонды CTO: `scratchpad/cto01/q1_join.py`, `q3_reserve.py` (сессия 08888c98, вне репозитория).

## Для следующих спеков (найдено ревью спека 0.1 и CTO)
- **0.2:** `tests/test_base_manager.py:183` пиклит менеджер — `BaseManager.scope` ленивое или вне `__getstate__`.
- **0.2:** `Mock()` — не Stoppable, но вызываемый: фейки тестера — настоящие классы или `Mock(spec=...)`.
- **0.2:** класс вместо экземпляра в `own`: `isinstance(Fake, Stoppable) is True` (проба H3) — решить, отклонять ли.
- **0.2:** сигнатура `open_scope` пинится тестом только в 0.2 — тестер 0.2 получает её литералом из раздела «Дверь».
- **0.2:** `kill_reserve_s = 0.0`: `kill()` зовётся, `join_until(now)` сразу → убитый попадёт в `survivors`; не
  прогнано. Если 0.2 решит «при 0.0 kill не звать» — записать почему.
- **0.2:** правило `min` и «фаза 3 у владельца записи с его резервом» в прототипе отсутствуют — доказать инъекциями:
  срок родителя без `min` → красный тест сегмента с меньшим бюджетом; блокирующий `kill()` в фейке → красный тест
  «`elapsed_s` ≤ budget + reserve при двух застрявших».
- **0.2:** `IHandle.close(None)` → бюджет владельца — принято без прогона.
- **1.1:** `ChildProcessStop.kill()` обязан не блокировать (Q3), а DESIGN П1 описывает его как terminate →
  `TERMINATE_GRACE_S` → kill — форму неблокирующей эскалации решает спек 1.1.
- **1.1:** резерв области детей — шестое число `stop_budget` или `pm_total − pm_graceful`; литеральный тест
  `stop_budget(5.0)`: `pm_graceful 5.0`, `pm_total 7.0`, `outer 8.5`, `outer > pm_total > pm_graceful`.
- **0.5:** G2 сравнивает текст аннотации с `IScope`.
- **0.2:** ключи словарей `unclosed_roots() -> list[dict]` (потребитель G3) — задать литералами.
- **0.2 / 1.2 — следствия чтения reporter'а (ревью р2):** (1) выжившие сегмента `work` при закрытии корня доходят
  до reporter только после закрытия `planes` → всегда в `emergency_log`, не в живой логгер; ветка DESIGN «живой
  логгер» работает только для досрочных закрытий. (2) каждый досрочный `Handle.close()` (каждая отписка) зовёт
  reporter — 0.2 решает: reporter молчит при `ok and emits_after_close == 0`, или досрочные закрытия зовут его
  только для не-`ok`. Причина: строка на диске стоит 745 Б (замер closure).
- **1.2:** фрагмент DESIGN §2.3 создаёт `child("work")` без `budget_s` → по правилу `None` `work` получает бюджет
  корня, а с `min` и резервом сверху `transport`/`planes` получат истёкший срок (сток дренирует 0 с). Task 1.2
  обязана дать `work` явный `budget_s=work_s`, и его резерв — уместить в бюджет корня.
- **1.1:** эскалацию terminate → kill в `ChildProcessStop` отсчитывать от момента `kill()`, не от `join_until`:
  `join_until` по детям последовательны, иначе grace ребёнка k сдвигается ожиданием детей 1…k−1 (вывод ревьюера
  р2 рассуждением, не прогоном). Совместимая с контрактом форма одна — повторный `join_until` адаптера после
  `kill()`; поток-таймер вне области ловит G4, блокирующий `kill()` запрещён Q3. Арифметика: 1.0 + 1.0 =
  `pm_total − pm_graceful` = 2.0.
