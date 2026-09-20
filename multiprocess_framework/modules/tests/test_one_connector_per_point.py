# -*- coding: utf-8 -*-
"""AST-страж «один разъём на точку» (Task 1.3c, Р-9/Р-10, plans/observability-closure).

Правило (владелец, 2026-09-01, Р-10): `_log_error`/`log_error` (плоскость логов) и
`report_error`/`_track_error`/`track_error` (плоскость ошибок) — запрещены в ОДНОМ
**пути исполнения**. Whitelist отсутствует (Р-9) — правило либо соблюдено, либо
красное.

## Модель — перечисление путей исполнения

`A; if c: B else: D; E` даёт ДВА пути: `A+B+E` и `A+D+E`. Пара «лог+факт» в ОДНОМ
пути = нарушение.

* `if`/`match`/`try`-`except`(`*`) **форкают** список открытых путей: тело `if` и
  `else` (или сквозной проход без `else`) — по копии от каждого пути, вошедшего в
  `if`; каждый `case` — по копии, плюс сквозной путь, если нет `case _`/`case x:`
  (безусловно ловящего рукава); каждый `except`/`except*` — по копии от путей,
  живых на ВХОДЕ в `try` (не после его тела — исключение может прилететь с первой
  же строки). Тернарник (`ast.IfExp`) форкает на уровне ВЫРАЖЕНИЯ тем же приёмом.
* Тело `try`, тело `with`, тело цикла, `else` у `try`, `else` у цикла —
  ПРОХОДНЫЕ: продолжают открытые пути, а не форкают их. `finally` — проходной
  для путей, доживших до конца тела, И прогоняется ОТДЕЛЬНО на путях, закрытых
  РАННИМ выходом изнутри тела/`except`/`else` (см. ниже) — до их фиксации.
* `return`/`raise` **закрывают** путь немедленно и безусловно. `break`/`continue`
  закрывают путь ДО выхода из цикла: `break`-пути возвращаются в оборот СРАЗУ
  ПОСЛЕ цикла (минуя `else` цикла — как в реальной семантике `for`/`while`/`else`);
  `continue`-пути возвращаются в оборот там же, где обычное завершение тела
  (то есть тоже видят `else` цикла) — упрощение: реальных повторных проходов по
  телу цикла не моделируем, это единственное отличие от точного CFG и не теряет
  ни одного факта (см. «Что осталось приближением» ниже).
* Цикл сам форкает как `if` без `else`: на выходе из цикла путь может быть
  «нулевая итерация» (копия входа, тело ни разу не выполнилось), «тело дожило до
  конца» или «вышел через `break`/`continue`» — вход в `finally`/после-цикла код
  видит ВСЕ три группы.
* Вложенные `def`/`class`/`lambda` — своя единица, в текущий путь их вызовы не
  идут — обходчик анализирует их отдельно, как самостоятельные юниты.
* **Слияние путей — по классу эквивалентности `(видел log?, видел track?)`**,
  максимум 4 корзины на любой форк (не потолок «свыше N — схлопнуть в один»:
  такой потолок при превышении откатывал бы правило к отменённой Р-10 модели
  «оба коннектора где-то в функции», подмешивая `(True, False)` с `(False, True)`
  в ложный `(True, True)`). Слияние путей ОДНОГО класса не может ни создать
  нарушение (классы остаются раздельными корзинами), ни потерять его (в корзине
  `(True, True)` хотя бы один путь уже был нарушением) — точно, а не
  приближённо. Отдельного потолка на число путей больше НЕТ: при таком слиянии
  открытых путей после любого форка ≤4 всегда, экспоненциальный взрыв
  структурно невозможен — измерено (`test_max_concurrent_open_paths_on_the_tree`):
  результат ЛЮБОГО слияния ≤4 (гарантия, не наблюдение — в паре булевых
  значений больше 4 комбинаций не бывает); вход в слияние (сколько путей форк
  произвёл ДО объединения — это и есть замена прежнего «потолок сработал 26 раз,
  пик 1024») на дереве не превышает 7.

**Граница правила (не whitelist).** Тело определения самого разъёма —
`ObservableMixin.report_error` (`base_manager/mixins/observable_mixin.py`) — не
является САЙТОМ: это место, где обе дороги РЕАЛИЗОВАНЫ. Граница задана
СТРУКТУРНО (файл, класс, метод) и снимает ТОЛЬКО нарушения, приписанные этому
конкретному юниту — обходчик всё равно спускается внутрь его тела и ставит в
очередь любые вложенные `def`/`class`/`lambda`, которые там встретятся (сейчас
таких нет, но граница не шире обещанного «файл+класс+метод» и на будущее).

**Что обходчик НЕ видит (честно, а не молчаливый провал).** Алиасинг
(`emit = self._log_error; emit(...)`), `functools.partial(self._log_error)`,
вызов через сохранённую ссылку или из чужой функции — AST не связывает имя
переменной с методом объекта статически, а полноценный dataflow-анализ на
это не входит в объём задачи. «Либо соблюдено, либо красное» относится к
ВЫЗОВАМ ПО ИМЕНИ разъёма на сайте — не к любому обходу через косвенный вызов.

## Второй раунд ревью (2026-09-01, HEAD `9794bee0`) — 5 major + 7 minor, все закрыты

Первая путевая редакция (закрывавшая находку J9) сама несла новые дефекты,
найденные ревью с воспроизведением на живом коде:

* **M1** — `_LIVE_NEGATIVE_CASES` хранил голые имена функций (`run_loop`), а
  обходчик производит qualname с классом (`SourceProducer.run_loop`) — сравнение
  `(file, func) not in flagged` было вечно истинным независимо от того, ловит
  обходчик реальный адрес или нет. Ревьюер сломал предмет (`_MAX_OPEN_PATHS=1`)
  и показал: тест зелёный, а `SourceProducer.run_loop` при этом РЕАЛЬНО в
  нарушениях. Перепроверено этим же приёмом (см. отчёт разработчика) — числа
  сошлись. Чинится записью полных qualname'ов **и** встречным утверждением
  «пара вообще достижима среди юнитов, которые обходчик произвёл для файла» —
  иначе следующая опечатка снова даст немоту незамеченной.
* **M2** — `Break`/`Continue`/`Return` возвращали `[]`, `For`/`While` отдавали
  `[]` дальше без исключения: пара, стоящая ПОСЛЕ цикла, чей корпус кончается
  безусловным `break`, теряла ВСЕ открытые пути и не могла быть найдена ни при
  какой расстановке вызовов. Перепроверено минимальной синтетикой (цикл с
  `break` на верхнем уровне тела): пара после цикла → 0, та же пара целиком
  ДО цикла → верно ловится. Чинится тем, что цикл сам — форк (см. модель выше).
* **M3** — `finally` гонялся только по путям, ДОЖИВШИМ до конца тела `try`;
  путь, закрытый `return`/`raise` ВНУТРИ тела/`except`, уходил в `closed` МИМО
  `finally`. Перепроверено: `try: track(); return` + `finally: log()` давал 0
  нарушений (реально голос звучит уже ПОСЛЕ факта — нарушение), тот же код без
  `return` — 1 (контроль). Чинится тегированием раннего выхода (`done`/`break`/
  `continue`) и прогоном `finally` ОТДЕЛЬНО на каждой группе — до того, как она
  попадёт в свой настоящий приёмник (`closed`/буфер `break`/буфер `continue`
  ближайшего цикла или ЕЩЁ ОДНОГО вложенного `finally`, если он есть).
* **M4** — `ast.Match`, `ast.IfExp`, `ast.TryStar` не разбирались отдельно и
  падали в generic-обход, где вызовы ВЗАИМОИСКЛЮЧАЮЩИХ рукавов собирались в ОДИН
  путь — ложный КРАСНЫЙ на легальном коде (проект на 3.12, все три формы
  легальны, whitelist отсутствует ⇒ у автора `match` не было бы выхода вообще).
  Перепроверено: `match`/тернарник/`except*` с парой в разных рукавах — все
  трое ложно краснели. Чинится тем, что все трое форкают, как `if`/`try`.
* **M5** — потолок путей (`_MAX_OPEN_PATHS`, было 512) на превышении схлопывал
  ВСЕ пути группы в ОДИН — внутри такой функции действовала ровно отменённая
  Р-10 модель «оба коннектора где-то в функции». На дереве (метод — AST,
  инструментирован сам `_cap`, не на глаз) потолок реально срабатывал **26 раз
  в 13 функциях**, пик **1024** пути на `ProcessConfig.as_generic_config` — числа
  ревьюера подтверждены независимо. Живого ложного нарушения от этого не
  нашлось (латентный риск, не сегодняшний дефект), но механизм был в дереве.
  Чинится слиянием по классу эквивалентности `(log?, track?)` вместо потолка —
  см. модель выше; потолок как отдельная сущность убран, число максимума путей
  на дереве под новой моделью измерено и названо.
* **M6** (`process_module/DECISIONS.md`, отдельный файл) — дополнение к
  ADR-PM-030 утверждало причинность задом наперёд («пара была компенсацией
  сломанного маршрута»). Перепроверено `git show`/`git log` независимо (числа
  НЕ приняты со слов ревьюера): волна C (`1ce288fc`/`d8d912ad`/`f617d568`,
  2026-07-07) добавила 32 строки `report_error(` и **ноль** `log_error(` —
  то есть инцидентную дорогу ПРИСТАВИЛИ к уже стоящей диагностической, мотив
  дословно в сообщениях коммитов: «breaker кормится только report_error —
  проглоченные ошибки без отчёта невидимы для health-плоскости». Из снятых в
  `1619de79` пар — 12 `_track_error(` и 7 `health.report_error(` (фреймворковая
  дорога `_track_error` до C2 РАБОТАЛА — это же подтверждает прогон C2 в самом
  ADR: `services.track_error → ['errors.log']`). Дополнение переписано как
  хронология с настоящим мотивом, довод про «сломанный маршрут» сужен на
  ПЛАГИННЫЕ сайты (`ctx.health.report_error`, единственная дорога которая
  реально не работала до C2).

Minor (m7-m12) — сделаны все, дешёвые:

* **m7** — код module-level и class-level (не внутри `def`) не анализировался
  (`_scan_body_for_units` брал только функции/классы). Пара в
  `except ImportError:` на верхнем уровне модуля была слепой зоной. Тело модуля
  и тело каждого класса теперь тоже юниты (`"<module>"` / `f"{qualname}<class-body>"`),
  разбираются той же путевой моделью, без двойного учёта вложенных def/class
  (`skip_top_level_defs` — они уже идут отдельными юнитами через
  `_scan_body_for_units`).
* **m8** — см. «Что обходчик НЕ видит» выше: честное предложение про алиасинг/
  `functools.partial`/косвенный вызов вместо молчаливого умолчания.
* **m9** — сообщение об ошибке масштабировалось числом ПУТЕЙ, не дефектов.
  После M5 путей на форк ≤4 всегда, взрыв структурно невозможен; отдельно
  добавлен дедуп нарушений по `(file, func, log_line, track_line)` — один и тот
  же адрес, найденный через разные пути/трейлы, не размножает строки отчёта.
* **m10** — датакласс `Path` переименован в `FlowPath` (не затеняет
  `pathlib.Path`, которым пользуются `_analyze_file`/`scan_tree`).
* **m11** — граница больше не блокирует обход вложенных единиц целиком (см.
  «Граница правила» выше) — фильтрует только нарушения САМОГО пограничного
  юнита, `nested_units` собираются независимо от границы.
* **m12** — `test_guard_is_green_on_the_tree` и `test_live_negative_pairs_are_not_flagged`
  делят один прогон `scan_tree` через `pytest`-фикстуру модульного скоупа
  (было — два независимых обхода 1632 файлов).

## Происхождение (слияние приёмки слепого тестера, первый раунд)

До задачи в дереве лежал независимый RED-тест
`base_manager/tests/test_error_plane_one_connector_ast_guard_acceptance.py`,
написанный тестером ВСЛЕПУЮ (до реализации, из acceptance criteria плана). Он
пинил модель «одна функция» (отменена Р-10) и известное нарушение
`router_manager.py::_report_send_error` (уже мигрировано Task 1.3b). Файл
удалён, содержательные идеи перенесены: «обходчик обязан хоть что-то находить»
→ `test_synthetic_pair_in_one_body_is_a_violation`; «известное нарушение
находится по адресу» → доказано на `ObservableMixin.report_error` (граница).

## Числа (метод — AST, не глазом; полный список см. в git log задачи)

* «в функции» (оба коннектора где-то в поддереве, старая до-J9 мера) → 4.
* Путевая модель без границы, HEAD `9794bee0`/после второго раунда → находит
  нарушение только внутри `ObservableMixin.report_error` (тело `try` —
  проходное, факт и голос делят путь; см. `test_boundary_is_structural_not_a_whitelist_entry`).
* Путевая модель + граница → **0** — дерево зелёное
  (`test_guard_is_green_on_the_tree`); после ВСЕХ правок второго раунда (M2-M5,
  m7) число новых адресов на дереве проверено и названо в отчёте разработчика —
  не подогнано под ожидание.
"""

from __future__ import annotations

import ast
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path as _FsPath
from typing import Iterator, Optional

import pytest

_REPO_ROOT = _FsPath(__file__).resolve().parents[3]
_SCAN_ROOTS = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype")

_LOG_NAMES = frozenset({"_log_error", "log_error"})
_TRACK_NAMES = frozenset({"_track_error", "track_error", "report_error"})

#: Граница правила (не whitelist, Р-9/Р-10) — тело определения самого разъёма.
_BOUNDARY_FILE = "multiprocess_framework/modules/base_manager/mixins/observable_mixin.py"
_BOUNDARY_QUALNAME = "ObservableMixin.report_error"

#: Живые (не синтетические) негативные пары — легитимные развилки, которые страж
#: обязан НЕ находить. Полные qualname (M1 — голые имена функций сравнивались с
#: qualname класса и НИКОГДА не совпадали, тест был зелёным вхолостую).
_LIVE_NEGATIVE_CASES = (
    # if/else-запасной путь: health.report_error, когда health подключён,
    # иначе _log_error — каждый путь через этот if несёт РОВНО один коннектор.
    ("multiprocess_framework/modules/process_module/generic/source_producer.py", "SourceProducer.run_loop"),
    # разведённые ранним `return` разные классы событий: путь через пустой список
    # точек закрывается на `return` сразу после log_error (факта в нём нет), путь
    # через отказ сохранения закрывается на `return` сразу после report_error.
    ("Plugins/io/drawing_io/plugin.py", "DrawingIoPlugin._do_save"),
)


def _call_name(func: ast.expr) -> Optional[str]:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _handler_label(index: int, handler: "ast.ExceptHandler") -> str:
    if handler.type is None:
        exc_name = "bare"
    else:
        try:
            exc_name = ast.unparse(handler.type)
        except Exception:  # noqa: BLE001 — метка для сообщения, не критично
            exc_name = "?"
    return f"except[{index}]({exc_name})"


def _is_irrefutable_case(case: "ast.match_case") -> bool:
    """`case _:` или `case x:` (голое имя-захват) без guard — ловит ВСЁ.

    При такой ветке сквозной («ни один case не сработал») путь не нужен —
    ветка гарантированно перехватывает управление.
    """
    return case.guard is None and isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


@dataclass
class CallSite:
    line: int
    name: str


@dataclass
class FlowPath:
    """Один путь исполнения от начала юнита до текущей точки (m10: было `Path`,
    затеняло `pathlib.Path`, которым пользуются `_analyze_file`/`scan_tree`).

    ``trail`` — метки форков, пройденных этим путём (для адреса в сообщении).
    Пустой ``trail`` — путь ни разу не форкался (``root``).
    """

    log: list = field(default_factory=list)
    track: list = field(default_factory=list)
    trail: list = field(default_factory=list)

    def copy(self) -> "FlowPath":
        p = FlowPath()
        p.log = list(self.log)
        p.track = list(self.track)
        p.trail = list(self.trail)
        return p

    def add(self, name: str, line: int) -> None:
        if name in _LOG_NAMES:
            self.log.append(CallSite(line, name))
        if name in _TRACK_NAMES:
            self.track.append(CallSite(line, name))

    def is_violation(self) -> bool:
        return bool(self.log) and bool(self.track)

    def label(self) -> str:
        return ">".join(self.trail) if self.trail else "root"


@dataclass
class Violation:
    file: str
    func: str
    branch: str
    log_site: CallSite
    track_site: CallSite

    def describe(self) -> str:
        return (
            f"{self.file}::{self.func} // {self.branch}: "
            f"{self.log_site.name}@{self.file}:{self.log_site.line} + "
            f"{self.track_site.name}@{self.file}:{self.track_site.line}"
        )


class _PathWalker:
    """Обходчик ОДНОГО юнита (функции/метода/лямбды/тела модуля/тела класса) —
    перечисляет пути исполнения.

    Вложенные `def`/`class`/`lambda` в текущий путь не идут — они складываются в
    ``nested_units`` и разбираются отдельно, как самостоятельные юниты.

    ``skip_top_level_defs`` — для псевдо-юнитов «тело модуля»/«тело класса»
    (m7): `def`/`class`-стейтменты там уже поставлены в очередь ОТДЕЛЬНО
    (`_scan_body_for_units`), повторный учёт дал бы дубль с неверным именем
    (`.<locals>.` вместо точечного).
    """

    def __init__(self, file_rel: str, qualname: str, *, skip_top_level_defs: bool = False) -> None:
        self.file = file_rel
        self.qualname = qualname
        self._skip_top_level_defs = skip_top_level_defs
        self.violations: list[Violation] = []
        self.nested_units: list[tuple[str, ast.AST]] = []
        # Буферы раннего выхода (M2/M3): `break`/`continue` не глохнут в `closed`
        # навсегда — они дожидаются своего цикла в отдельном буфере; активный
        # `finally` (если есть) перехватывает ЛЮБОЙ ранний выход (return/raise/
        # break/continue) раньше, чем тот попадёт в свой настоящий приёмник.
        self._break_stack: list[list["FlowPath"]] = []
        self._continue_stack: list[list["FlowPath"]] = []
        self._finally_stack: list[list[tuple[str, "FlowPath"]]] = []

    # ------------------------------------------------------------------ #
    # Публичный вход — разобрать тело юнита целиком.
    # ------------------------------------------------------------------ #
    def run(self, body: list) -> None:
        closed: list[FlowPath] = []
        open_paths = self._walk_stmts(body, [FlowPath()], closed)
        # Юнит кончился — то, что ещё открыто, закрывается неявным концом функции.
        closed.extend(open_paths)
        for p in closed:
            self._check(p)

    def _check(self, p: "FlowPath") -> None:
        if p.is_violation():
            self.violations.append(Violation(self.file, self.qualname, p.label(), p.log[0], p.track[0]))

    # ------------------------------------------------------------------ #
    # Ранний выход — единая точка маршрутизации (M3): перехватывается ближайшим
    # активным `finally`, иначе идёт в НАСТОЯЩИЙ приёмник.
    # ------------------------------------------------------------------ #
    def _emit_exit(self, kind: str, paths: list, closed: list) -> None:
        if not paths:
            return
        if self._finally_stack:
            self._finally_stack[-1].extend((kind, p) for p in paths)
            return
        if kind == "done":
            closed.extend(paths)
        elif kind == "break" and self._break_stack:
            self._break_stack[-1].extend(paths)
        elif kind == "continue" and self._continue_stack:
            self._continue_stack[-1].extend(paths)
        # break/continue вне цикла — SyntaxError на этапе ast.parse, сюда не
        # доходит; проверка `and self._break_stack` — чисто защитная.

    def _run_finally_per_kind(self, tagged: list, finalbody: list, closed: list) -> tuple:
        """Прогнать `finally` ОТДЕЛЬНО на каждой группе раннего выхода (M3).

        Раздельно — не «одним списком» — потому что после `finally` каждый путь
        обязан вернуться на СВОЙ исходный выход (`return` остаётся `return`,
        `break` остаётся `break`), а общий список стёр бы эту метку. `finally`
        может сам форкать (например, из-за `if` внутри него) — прогоны друг на
        друга не влияют, они независимы по построению.
        """
        by_kind: dict = {"done": [], "break": [], "continue": []}
        for kind, p in tagged:
            by_kind[kind].append(p)
        result: dict = {}
        for kind, group in by_kind.items():
            if not group:
                result[kind] = []
                continue
            result[kind] = self._walk_stmts(finalbody, group, closed) if finalbody else group
        return result["done"], result["break"], result["continue"]

    # ------------------------------------------------------------------ #
    # Перечисление путей.
    # ------------------------------------------------------------------ #
    def _walk_stmts(self, stmts: list, paths: list, closed: list) -> list:
        for stmt in stmts:
            paths = self._walk_stmt(stmt, paths, closed)
        return paths

    def _walk_stmt(self, stmt: ast.stmt, paths: list, closed: list) -> list:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # m7: в псевдо-юнитах «тело модуля/класса» def/class уже идут своим
            # юнитом через _scan_body_for_units — здесь просто проходим мимо.
            if not self._skip_top_level_defs:
                self.nested_units.append((f"{self.qualname}.<locals>.{stmt.name}", stmt))
            return paths

        if isinstance(stmt, ast.If):
            paths = self._collect_expr(stmt.test, paths)  # test — безусловно, во ВСЕ пути
            body_paths = [p.copy() for p in paths]
            for p in body_paths:
                p.trail.append(f"if@{stmt.lineno}.body")
            body_paths = self._walk_stmts(stmt.body, body_paths, closed)
            if stmt.orelse:
                else_paths = [p.copy() for p in paths]
                for p in else_paths:
                    p.trail.append(f"if@{stmt.lineno}.else")
                else_paths = self._walk_stmts(stmt.orelse, else_paths, closed)
            else:
                # Нет else — путь проходит `if` НАСКВОЗЬ: копия родителя,
                # продолжающая ЕГО накопление, а не пустой изолированный старт.
                else_paths = [p.copy() for p in paths]
            return self._normalize(body_paths + else_paths)

        if isinstance(stmt, ast.Match):  # 3.10+ (M4)
            paths = self._collect_expr(stmt.subject, paths)
            case_groups: list = []
            has_catch_all = False
            for idx, case in enumerate(stmt.cases):
                c_paths = [p.copy() for p in paths]
                for p in c_paths:
                    p.trail.append(f"match@{stmt.lineno}.case[{idx}]")
                if case.guard is not None:
                    c_paths = self._collect_expr(case.guard, c_paths)
                c_paths = self._walk_stmts(case.body, c_paths, closed)
                case_groups.extend(c_paths)
                if _is_irrefutable_case(case):
                    has_catch_all = True
            if not has_catch_all:
                # Ни один рукав не гарантирован — путь «ничего не совпало».
                case_groups.extend([p.copy() for p in paths])
            return self._normalize(case_groups)

        if isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):  # except* — 3.11+ (M4)
            entry_paths = [p.copy() for p in paths]  # пути, живые НА ВХОДЕ в try
            has_finally = bool(stmt.finalbody)
            if has_finally:
                self._finally_stack.append([])

            body_paths = self._walk_stmts(stmt.body, [p.copy() for p in paths], closed)
            handler_paths: list = []
            for idx, handler in enumerate(stmt.handlers):
                # Каждый except форкается от ВХОДА в try, не от конца тела —
                # исключение может прилететь с первой же строки тела.
                h_paths = [p.copy() for p in entry_paths]
                label = f"try@{stmt.lineno}.{_handler_label(idx, handler)}"
                for p in h_paths:
                    p.trail.append(label)
                h_paths = self._walk_stmts(handler.body, h_paths, closed)
                handler_paths.extend(h_paths)
            if stmt.orelse:
                body_paths = self._walk_stmts(stmt.orelse, body_paths, closed)
            merged = self._normalize(body_paths + handler_paths)

            if has_finally:
                tagged = self._finally_stack.pop()
                done_s, break_s, continue_s = self._run_finally_per_kind(tagged, stmt.finalbody, closed)
                # Пути раннего выхода: после finally — на СВОЙ настоящий приёмник
                # (может статься, ещё через ОДИН вложенный finally, если он есть).
                self._emit_exit("done", done_s, closed)
                self._emit_exit("break", break_s, closed)
                self._emit_exit("continue", continue_s, closed)
                # Обычное завершение (без раннего выхода) — тоже через finally.
                merged = self._walk_stmts(stmt.finalbody, merged, closed)
            return merged

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                paths = self._collect_expr(item.context_expr, paths)
            return self._walk_stmts(stmt.body, paths, closed)  # проходной

        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            test_or_iter = stmt.iter if isinstance(stmt, (ast.For, ast.AsyncFor)) else stmt.test
            paths = self._collect_expr(test_or_iter, paths)
            zero_iter_paths = [p.copy() for p in paths]  # цикл не выполнился ни разу
            self._break_stack.append([])
            self._continue_stack.append([])
            body_survivors = self._walk_stmts(stmt.body, [p.copy() for p in paths], closed)
            continue_exits = self._continue_stack.pop()
            break_exits = self._break_stack.pop()
            # `continue` возвращается туда же, где обычное завершение тела —
            # оба варианта одинаково видят `else` цикла (упрощение: реальных
            # повторных проходов не моделируем — см. докстринг файла).
            normal_exit = self._normalize(zero_iter_paths + body_survivors + continue_exits)
            if stmt.orelse:
                normal_exit = self._walk_stmts(stmt.orelse, normal_exit, closed)
            # `break` НЕ видит `else` цикла (реальная семантика Python) —
            # подмешивается ПОСЛЕ него.
            return self._normalize(normal_exit + break_exits)

        if isinstance(stmt, ast.Return):
            paths = self._collect_expr(stmt.value, paths) if stmt.value is not None else paths
            self._emit_exit("done", paths, closed)
            return []

        if isinstance(stmt, ast.Raise):
            paths = self._collect_expr(stmt.exc, paths) if stmt.exc is not None else paths
            self._emit_exit("done", paths, closed)
            return []

        if isinstance(stmt, ast.Break):
            self._emit_exit("break", paths, closed)
            return []

        if isinstance(stmt, ast.Continue):
            self._emit_exit("continue", paths, closed)
            return []

        # Простой стейтмент (Expr, Assign, AugAssign, AnnAssign, Global, Import, ...).
        return self._collect_expr(stmt, paths)

    def _collect_expr(self, node, paths: list) -> list:
        """Собрать вызовы из выражения/стейтмента ВО ВСЕ пути списка, форкая на
        тернарнике (`ast.IfExp`) — та же семантика, что у `if`, но на уровне
        выражения (M4): `x if c else y` не может слить `x`- и `y`-рукав в один
        путь, иначе `report() if c else _log_error()` ложно краснеет.
        """
        if node is None:
            return paths
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            marker = getattr(node, "name", None) or f"lambda@{node.lineno}"
            self.nested_units.append((f"{self.qualname}.<locals>.{marker}", node))
            return paths
        if isinstance(node, ast.IfExp):
            paths = self._collect_expr(node.test, paths)  # test — безусловно
            body_paths = self._collect_expr(node.body, [p.copy() for p in paths])
            else_paths = self._collect_expr(node.orelse, [p.copy() for p in paths])
            return self._normalize(body_paths + else_paths)
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                for p in paths:
                    p.add(name, node.lineno)
        for child in ast.iter_child_nodes(node):
            paths = self._collect_expr(child, paths)
        return paths

    def _normalize(self, paths: list) -> list:
        """Слить пути в классы эквивалентности `(видел log?, видел track?)` —
        максимум 4 корзины (M5). Точно, не приближённо: слияние путей ОДНОГО
        класса не может создать нарушение (классы раздельны) и не может его
        потерять (в корзине `(True, True)` уже был хотя бы один нарушивший
        путь). Заменяет прежний потолок `_MAX_OPEN_PATHS`, который на
        превышении схлопывал ЛЮБОЙ избыток путей в ОДИН, смешивая классы и
        отдавая правило отменённой модели «оба коннектора где-то в функции».
        Применяется на КАЖДОМ форке (не только сверх какого-то предела) — тогда
        взрыв путей структурно невозможен: после любого слияния путей ≤4,
        следующий форк даёт ≤8 перед следующим слиянием и снова ≤4.
        """
        buckets: dict = {}
        order: list = []
        for p in paths:
            key = (bool(p.log), bool(p.track))
            if key not in buckets:
                buckets[key] = p
                order.append(key)
            else:
                rep = buckets[key]
                rep.log.extend(p.log)
                rep.track.extend(p.track)
        return [buckets[k] for k in order]


def _is_boundary(rel: str, qualname: str) -> bool:
    return rel == _BOUNDARY_FILE and qualname == _BOUNDARY_QUALNAME


def _scan_body_for_units(body: list, prefix: str, queue: list) -> None:
    """Верхнеуровневые (не вложенные внутрь функции) def/class — в очередь юнитов."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            queue.append((f"{prefix}{stmt.name}", stmt))
        elif isinstance(stmt, ast.ClassDef):
            queue.append((f"{prefix}{stmt.name}", stmt))


def _dedupe_violations(violations: list) -> list:
    """m9: один и тот же адрес (файл+функция+строки обоих вызовов), найденный
    через разные пути/трейлы, не размножает строки отчёта."""
    seen: dict = {}
    for v in violations:
        key = (v.file, v.func, v.log_site.line, v.track_site.line)
        seen.setdefault(key, v)
    return list(seen.values())


def _analyze_module(tree: ast.Module, rel: str, *, apply_boundary: bool = True) -> list:
    """Разобрать один УЖЕ распарсенный модуль → список нарушений."""
    violations, _analyzed = _analyze_module_full(tree, rel, apply_boundary=apply_boundary)
    return violations


def _analyze_module_full(tree: ast.Module, rel: str, *, apply_boundary: bool = True) -> tuple:
    """Как `_analyze_module`, но дополнительно возвращает МНОЖЕСТВО (file, qualname)
    юнитов, которые обходчик реально произвёл — нужно для проверки
    достижимости `_LIVE_NEGATIVE_CASES` (M1): без этого опечатка в имени/файле
    даёт тест, зелёный вхолостую, а не по здоровью кода.
    """
    violations: list[Violation] = []
    analyzed: set = set()
    queue: list[tuple[str, ast.AST]] = []
    _scan_body_for_units(tree.body, "", queue)

    def _walk_unit(qualname: str, body_or_expr, *, is_lambda: bool = False, skip_top_level_defs: bool = False) -> None:
        analyzed.add((rel, qualname))
        walker = _PathWalker(rel, qualname, skip_top_level_defs=skip_top_level_defs)
        if is_lambda:
            paths = walker._collect_expr(body_or_expr, [FlowPath()])
            for p in paths:
                walker._check(p)
        else:
            walker.run(body_or_expr)
        if not (apply_boundary and _is_boundary(rel, qualname)):
            violations.extend(walker.violations)
        queue.extend(walker.nested_units)

    # m7: код module-level ВНЕ def/class (например `try/except ImportError` на
    # верхнем уровне файла) — тоже юнит, а не слепая зона.
    _walk_unit("<module>", tree.body, skip_top_level_defs=True)

    while queue:
        qualname, node = queue.pop()
        if isinstance(node, ast.ClassDef):
            _scan_body_for_units(node.body, f"{qualname}.", queue)
            # m7: код прямо в теле класса (не внутри методов) — тоже юнит.
            _walk_unit(f"{qualname}<class-body>", node.body, skip_top_level_defs=True)
            continue
        if isinstance(node, ast.Lambda):
            _walk_unit(qualname, node.body, is_lambda=True)
        else:
            _walk_unit(qualname, node.body)

    return _dedupe_violations(violations), analyzed


def _analyze_file(path: _FsPath, repo_root: _FsPath, *, apply_boundary: bool = True) -> tuple:
    rel = path.relative_to(repo_root).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return [], set(), False
    violations, analyzed = _analyze_module_full(tree, rel, apply_boundary=apply_boundary)
    return violations, analyzed, True


def _iter_source_files(repo_root: _FsPath) -> Iterator[_FsPath]:
    for root_name in _SCAN_ROOTS:
        root = repo_root / root_name
        for path in sorted(root.rglob("*.py")):
            posix = path.as_posix()
            if "/tests/" in posix or path.name.startswith("test_") or "__pycache__" in posix:
                continue
            yield path


def scan_tree(repo_root: _FsPath, *, apply_boundary: bool = True) -> tuple:
    """Обойти все 4 слоя → (нарушения, файлы-без-разбора, юниты-достигнутые)."""
    violations: list[Violation] = []
    unparsed: list[str] = []
    analyzed: set = set()
    for path in _iter_source_files(repo_root):
        file_violations, file_analyzed, ok = _analyze_file(path, repo_root, apply_boundary=apply_boundary)
        violations.extend(file_violations)
        analyzed |= file_analyzed
        if not ok:
            unparsed.append(path.relative_to(repo_root).as_posix())
    return _dedupe_violations(violations), unparsed, analyzed


# ========================================================================== #
# ТЕСТЫ
# ========================================================================== #


@pytest.fixture(scope="module")
def tree_scan() -> tuple:
    """m12: ОДИН обход дерева на весь модуль тестов, а не по разу на тест."""
    return scan_tree(_REPO_ROOT)


class TestOneConnectorPerPointGuard:
    def test_guard_is_green_on_the_tree(self, tree_scan: tuple) -> None:
        """Страж зелёный на дереве после Task 1.3b и второго раунда ревью."""
        violations, unparsed, _analyzed = tree_scan
        # «Не разобрал» ≠ «данных нет» (правило проекта) — молчащий парсер даёт
        # зелёный по пустоте, а не по здоровью кода. Явно посчитано и названо.
        assert not unparsed, (
            f"AST не разобрал {len(unparsed)} файлов — тишина не считается "
            f"наблюдением, страж обязан назвать их: {unparsed}"
        )
        assert violations == [], "нарушения правила «один разъём на точку»:\n" + "\n".join(
            v.describe() for v in violations
        )

    def test_synthetic_pair_in_one_body_is_a_violation(self) -> None:
        """Контроль по адресу: обходчик обязан хоть что-то находить."""
        source = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx):
                    self._log_error("отказ")
                    self._track_error(exc, ctx)
            """
        ).strip("\n")
        tree = ast.parse(source, filename="<synthetic-control>")
        violations = _analyze_module(tree, "synthetic_control.py")

        assert len(violations) == 1, violations
        v = violations[0]
        assert v.file == "synthetic_control.py"
        assert v.func == "Foo.bar"
        assert v.branch == "root"
        assert v.log_site.line == 3
        assert v.track_site.line == 4

    def test_if_without_else_leaks_from_parent_j9_regression(self) -> None:
        """Регресс-сторож J9: `if` без `else` обязан наследовать вызовы РОДИТЕЛЯ."""
        source = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, reason):
                    self.report_error(exc, context=ctx)
                    if reason:
                        self._log_error(f"[{reason}] detail")
            """
        ).strip("\n")
        tree = ast.parse(source, filename="<synthetic-j9-if-leak>")
        violations = _analyze_module(tree, "synthetic_j9_if_leak.py")

        assert len(violations) == 1, violations
        v = violations[0]
        assert v.func == "Foo.bar"
        assert v.track_site.line == 3
        assert v.log_site.line == 5

    def test_early_return_closes_the_path_guard_clause(self) -> None:
        """Guard-clause: ранний `return` — легитимная развилка, немота — нет."""
        with_return = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, x):
                    if x:
                        self._log_error("x")
                        return
                    self._track_error(exc, ctx)
            """
        ).strip("\n")
        violations_with_return = _analyze_module(
            ast.parse(with_return, filename="<synthetic-guard-clause-return>"),
            "synthetic_guard_clause_return.py",
        )
        assert violations_with_return == [], violations_with_return

        without_return = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, x):
                    if x:
                        self._log_error("x")
                    self._track_error(exc, ctx)
            """
        ).strip("\n")
        violations_without_return = _analyze_module(
            ast.parse(without_return, filename="<synthetic-guard-clause-no-return>"),
            "synthetic_guard_clause_no_return.py",
        )
        assert len(violations_without_return) == 1, violations_without_return
        v = violations_without_return[0]
        assert v.log_site.line == 4
        assert v.track_site.line == 5

    def test_pair_reachable_across_the_qualname(self) -> None:
        """M1-регресс: `_LIVE_NEGATIVE_CASES` обязаны быть ДОСТИЖИМЫ обходчиком.

        Ревью сломало предмет (`_MAX_OPEN_PATHS=1` в старой модели) и показало:
        старый тест с ГОЛЫМИ именами (`run_loop`) был зелёным вхолостую — кортеж
        `(file, "run_loop")` никогда не совпадал с реальным `(file,
        "SourceProducer.run_loop")`, который обходчик производит. Эта проверка
        ловит именно такую опечатку: пара обязана быть СРЕДИ юнитов, которые
        реально прошли анализ для этого файла — если нет, дальше сравнивать
        нечего.
        """
        for file, func in _LIVE_NEGATIVE_CASES:
            path = _REPO_ROOT / file
            assert path.is_file(), f"{file} не найден"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            _violations, analyzed = _analyze_module_full(tree, file)
            assert (file, func) in analyzed, (
                f"{file}::{func} НЕ найден среди юнитов, которые обходчик "
                f"произвёл для этого файла (имя устарело/опечатка) — сравнение "
                f"с флагом нарушений было бы зелёным вхолостую (M1)"
            )

    def test_live_negative_pairs_are_not_flagged(self, tree_scan: tuple) -> None:
        """Легитимные развилки с живого дерева НЕ краснеют — по имени и файлу."""
        violations, _unparsed, _analyzed = tree_scan
        flagged = {(v.file, v.func) for v in violations}
        for file, func in _LIVE_NEGATIVE_CASES:
            assert (file, func) not in flagged, (
                f"{file}::{func} ошибочно попал(а) в нарушения — легитимная "
                f"развилка (if/else или ранний return) сломана обходчиком"
            )

    def test_synthetic_negative_pair_two_different_except_handlers(self) -> None:
        """Третий негативный случай правила: два разных `except` одного `try`.

        Честно: не с живого дерева — полным AST-сканом подтверждено, что эта
        форма (лог в одном except, факт в другом except ТОГО ЖЕ try) сейчас в
        дереве не встречается ни разу.
        """
        source = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx):
                    try:
                        risky()
                    except ValueError:
                        self._log_error("значение не то")
                    except RuntimeError:
                        self._track_error(exc, ctx)
            """
        ).strip("\n")
        tree = ast.parse(source, filename="<synthetic-except-split>")
        violations = _analyze_module(tree, "synthetic_except_split.py")

        assert violations == [], violations

    def test_boundary_is_structural_not_a_whitelist_entry(self) -> None:
        """Граница реально что-то снимает — а не совпала с опечаткой."""
        path = _REPO_ROOT / _BOUNDARY_FILE
        assert path.is_file(), f"файл границы не найден: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        without_boundary = _analyze_module(tree, _BOUNDARY_FILE, apply_boundary=False)
        assert any(v.func == _BOUNDARY_QUALNAME for v in without_boundary), (
            f"без границы {_BOUNDARY_QUALNAME} обязан быть в нарушениях — "
            "иначе непонятно, снимает ли граница вообще что-нибудь"
        )

        with_boundary = _analyze_module(tree, _BOUNDARY_FILE, apply_boundary=True)
        assert not any(v.func == _BOUNDARY_QUALNAME for v in with_boundary), (
            f"с границей {_BOUNDARY_QUALNAME} обязан выпасть из нарушений"
        )

    def test_boundary_does_not_block_nested_units(self) -> None:
        """M11-регресс: граница не шире обещанного «файл+класс+метод».

        Синтетика на месте настоящей границы: пограничный метод получает
        СОБСТВЕННОЕ нарушение (обязано выпасть) И вложенную функцию со СВОИМ,
        независимым нарушением (обязана остаться — она не пограничный метод,
        просто живёт внутри него).
        """
        source = textwrap.dedent(
            """
            class ObservableMixin:
                def report_error(self, exc, context=None):
                    self._log_error("прямое нарушение самого разъёма")
                    self._track_error(exc, context)

                    def _nested_helper(e, ctx):
                        self._log_error("вложенное — своё")
                        self._track_error(e, ctx)

                    return _nested_helper
            """
        ).strip("\n")
        tree = ast.parse(source, filename="<synthetic-boundary-nested>")
        violations, analyzed = _analyze_module_full(tree, _BOUNDARY_FILE, apply_boundary=True)

        assert (_BOUNDARY_FILE, "ObservableMixin.report_error.<locals>._nested_helper") in analyzed, (
            "вложенная функция внутри границы обязана быть ДОСТИГНУТА обходчиком"
        )
        assert not any(v.func == _BOUNDARY_QUALNAME for v in violations), (
            "нарушение самого пограничного метода обязано быть снято границей"
        )
        assert any(v.func == "ObservableMixin.report_error.<locals>._nested_helper" for v in violations), (
            "нарушение ВЛОЖЕННОЙ функции не должно исчезать вместе с границей — это разные юниты"
        )

    def test_loop_reopens_paths_after_break_m2_regression(self) -> None:
        """M2-регресс: `break`/`continue`/`return` внутри цикла не гасят весь
        остаток функции — путь возвращается в оборот ПОСЛЕ цикла.

        Живое воспроизведение (ревью, HEAD `9794bee0`): `Plugins/io/robot_draw/
        plugin.py::RobotDrawPlugin.process` — пара, разведённая по разные
        стороны цикла, чьё тело безусловно кончается `break`, давала 0
        (ложный зелёный); та же пара целиком ДО цикла — ловилась. Синтетика
        воспроизводит именно этот механизм, не форму «цикл вообще».
        """
        straddling = textwrap.dedent(
            """
            class Foo:
                def process(self, items, exc, ctx):
                    self._track_error(exc, ctx)
                    for item in items:
                        self._do_something(item)
                        break
                    self._log_error("после цикла")
            """
        ).strip("\n")
        violations = _analyze_module(ast.parse(straddling, filename="<synthetic-m2-straddle>"), "s.py")
        assert len(violations) == 1, violations
        v = violations[0]
        assert v.track_site.line == 3
        assert v.log_site.line == 7

        both_before = textwrap.dedent(
            """
            class Foo:
                def process(self, items, exc, ctx):
                    self._track_error(exc, ctx)
                    self._log_error("до цикла")
                    for item in items:
                        self._do_something(item)
                        break
            """
        ).strip("\n")
        violations_before = _analyze_module(ast.parse(both_before, filename="<synthetic-m2-control>"), "c.py")
        assert len(violations_before) == 1, violations_before

    def test_break_skips_loop_else_continue_does_not(self) -> None:
        """`break` минует `else` цикла (реальная семантика Python), `continue`
        видит его как обычное завершение тела — проверка по РАЗНЫМ адресам."""
        via_break = textwrap.dedent(
            """
            class Foo:
                def bar(self, items, exc, ctx):
                    for item in items:
                        self._track_error(exc, ctx)
                        break
                    else:
                        self._log_error("else — не выполнится при break, но статически виден")
            """
        ).strip("\n")
        v_break = _analyze_module(ast.parse(via_break, filename="<synthetic-break-else>"), "be.py")
        assert v_break == [], v_break  # track уходит через break, else его не видит

        via_continue = textwrap.dedent(
            """
            class Foo:
                def bar(self, items, exc, ctx):
                    for item in items:
                        self._track_error(exc, ctx)
                        continue
                    else:
                        self._log_error("else — continue его тоже достигает")
            """
        ).strip("\n")
        v_continue = _analyze_module(ast.parse(via_continue, filename="<synthetic-continue-else>"), "ce.py")
        assert len(v_continue) == 1, v_continue

    def test_finally_covers_early_return_m3_regression(self) -> None:
        """M3-регресс: `finally` обязан отработать и на выходе через `return`
        внутри тела `try`, не только на путях, доживших до конца тела."""
        with_return = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx):
                    try:
                        self._track_error(exc, ctx)
                        return
                    finally:
                        self._log_error("cleanup")
            """
        ).strip("\n")
        v_with = _analyze_module(ast.parse(with_return, filename="<synthetic-m3-return>"), "wr.py")
        assert len(v_with) == 1, v_with

        without_return = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx):
                    try:
                        self._track_error(exc, ctx)
                    finally:
                        self._log_error("cleanup")
            """
        ).strip("\n")
        v_without = _analyze_module(ast.parse(without_return, filename="<synthetic-m3-control>"), "nr.py")
        assert len(v_without) == 1, v_without

    def test_match_ifexp_exceptstar_do_not_false_flag_m4_regression(self) -> None:
        """M4-регресс: `match`/тернарник/`except*` — взаимоисключающие рукава,
        не одно тело. Ни один не обязан краснеть."""
        match_src = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, kind):
                    match kind:
                        case "a":
                            self._log_error("a")
                        case "b":
                            self._track_error(exc, ctx)
            """
        ).strip("\n")
        assert _analyze_module(ast.parse(match_src, filename="<synthetic-match>"), "m.py") == []

        ternary_src = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, cond):
                    x = self._log_error("x") if cond else self._track_error(exc, ctx)
            """
        ).strip("\n")
        assert _analyze_module(ast.parse(ternary_src, filename="<synthetic-ternary>"), "t.py") == []

        except_star_src = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx):
                    try:
                        risky()
                    except* ValueError:
                        self._log_error("v")
                    except* RuntimeError:
                        self._track_error(exc, ctx)
            """
        ).strip("\n")
        assert _analyze_module(ast.parse(except_star_src, filename="<synthetic-except-star>"), "es.py") == []

    def test_match_without_catch_all_gets_a_fallthrough_path(self) -> None:
        """`match` БЕЗ `case _`/`case x:` даёт сквозной путь «ничего не совпало»
        — пара, разведённая по РАЗНЫМ явным рукавам, при этом остаётся чистой
        (control к предыдущему тесту, доказывает, что сквозной путь не мешает
        легальному коду), а пара, стоящая ДО `match` и в РУКАВЕ, обязана
        краснеть — сквозной путь наследует вызовы родителя (как `if` без else,
        J9)."""
        source = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, kind):
                    self._track_error(exc, ctx)
                    match kind:
                        case "a":
                            self._log_error("a")
            """
        ).strip("\n")
        violations = _analyze_module(ast.parse(source, filename="<synthetic-match-fallthrough>"), "mf.py")
        assert len(violations) == 1, violations
        v = violations[0]
        assert v.track_site.line == 3
        assert v.log_site.line == 6

    def test_equivalence_class_merge_does_not_false_flag_m5_regression(self) -> None:
        """M5-регресс: старый потолок при превышении схлопывал ВСЕ пути в ОДИН,
        смешивая `(log, ø)` с `(ø, track)` в ложный `(log, track)`. Слияние по
        классу эквивалентности не имеет права сделать то же самое — даже когда
        путей у ОДНОГО форка много (>4).

        Форма важна: НЕЗАВИСИМЫЕ последовательные `if` (первая редакция этого
        теста) — не годятся для этой проверки, потому что у них есть РЕАЛЬНЫЕ
        комбинированные пути (x1=False идёт в track, x2=True идёт в log — это ОДИН
        настоящий путь исполнения с обоими коннекторами, и находка обходчика на
        нём была бы верной, а не ложной; проверено — обходчик там ПРАВ, ошибался
        тест). Нужен ОДИН форк с МНОГИМИ взаимоисключающими рукавами, где ни один
        рукав сам по себе не смешивает коннекторы: `match` с 8 case, половина
        чисто log, половина чисто track — 9 путей на одном форке (>4), ни один
        реальный путь не проходит через два рукава сразу.
        """
        lines = ["class Foo:", "    def bar(self, exc, ctx, kind):", "        match kind:"]
        for i in range(4):
            lines.append(f'            case "log{i}":')
            lines.append(f'                self._log_error("only log {i}")')
        for i in range(4):
            lines.append(f'            case "track{i}":')
            lines.append("                self._track_error(exc, ctx)")
        lines.append("            case _:")
        lines.append("                pass")
        source = "\n".join(lines) + "\n"
        violations = _analyze_module(ast.parse(source, filename="<synthetic-m5-classes>"), "cls.py")
        assert violations == [], violations

    def test_max_concurrent_open_paths_on_the_tree(self, tree_scan: tuple) -> None:
        """Число максимума одновременно открытых путей на дереве под моделью
        слияния по классу эквивалентности (M5) — измерено, не заявлено.

        Слияние ограничивает РЕЗУЛЬТАТ любого форка четырьмя корзинами
        `(log?, track?)` — это структурная гарантия (в `dict` больше 4 разных
        булевых пар не бывает), и здесь она перепроверяется прогоном, а не
        принимается на слово. Отдельно меряем МАКСИМАЛЬНЫЙ ВХОД в `_normalize`
        (сколько путей форк реально произвёл ДО слияния) — это то число, которое
        раньше называлось «потолок сработал 26 раз, пик 1024» (M5, старая
        модель); новое число показывает, насколько слияние на каждом форке (а
        не только сверх предела) меняет картину.
        """
        max_out = 0
        max_in = 0
        orig = _PathWalker._normalize

        def patched(self, paths):
            nonlocal max_out, max_in
            max_in = max(max_in, len(paths))
            out = orig(self, paths)
            max_out = max(max_out, len(out))
            return out

        _PathWalker._normalize = patched
        try:
            scan_tree(_REPO_ROOT)
        finally:
            _PathWalker._normalize = orig

        assert max_out <= 4, f"результат слияния обязан быть ≤4 (структурная гарантия), увидено {max_out}"
        # Число входа — не критерий провала (оно и не обязано быть маленьким),
        # но обязано быть НАЗВАНО в отчёте разработчика, а не оставлено немым.
        assert max_in >= max_out, f"вход слияния меньше выхода — противоречие: in={max_in} out={max_out}"

    def test_path_explosion_terminates_without_a_ceiling(self) -> None:
        """Без отдельного потолка (M5 снял `_MAX_OPEN_PATHS`) длинная цепочка
        `if` не должна повесить обходчик — слияние по классу держит счёт путей
        плоским на каждом форке."""
        depth = 30  # 2**30 без слияния — заведомо нежизнеспособно
        lines = ["class Foo:", "    def bar(self, c):"]
        for _ in range(depth):
            lines.append("        if c:")
            lines.append("            pass")
        source = "\n".join(lines) + "\n"
        tree = ast.parse(source, filename="<synthetic-path-explosion>")

        started = time.perf_counter()
        violations = _analyze_module(tree, "synthetic_path_explosion.py")
        elapsed = time.perf_counter() - started

        assert violations == [], violations
        assert elapsed < 5.0, f"обходчик завис/затянул анализ на цепочке if: {elapsed:.2f} с"

    def test_module_and_class_level_code_is_analyzed_m7_regression(self) -> None:
        """M7-регресс: пара на module-level (не внутри `def`) и на class-level
        (не внутри метода) — раньше слепая зона, `_scan_body_for_units` искала
        только функции/классы."""
        module_level = textwrap.dedent(
            """
            try:
                import optional_thing
            except ImportError as exc:
                _log_error_stub("нет optional_thing")
                _track_error_stub(exc, None)
            """
        ).strip("\n")
        # Пара по ФОРМЕ, но имена не разъёмные — правило про конкретные разъёмы,
        # а не про «два вызова в except». Контр-проверка к блоку ниже: если бы
        # страж ловил по форме, эта синтетика уже была бы красной.
        violations_stub = _analyze_module(ast.parse(module_level, filename="<synthetic-module-level>"), "ml.py")
        assert violations_stub == [], violations_stub
        # Те же строки с РЕАЛЬНЫМИ именами разъёмов — проверяем достижимость юнита.
        module_level_real = textwrap.dedent(
            """
            try:
                import optional_thing
            except ImportError as exc:
                self._log_error("нет optional_thing")
                self._track_error(exc, None)
            """
        ).strip("\n")
        violations_real = _analyze_module(ast.parse(module_level_real, filename="<synthetic-module-level-2>"), "ml2.py")
        assert len(violations_real) == 1, violations_real
        assert violations_real[0].func == "<module>"

        class_level = textwrap.dedent(
            """
            class Foo:
                try:
                    _X = compute()
                except Exception as exc:
                    self._log_error("class-body отказ")
                    self._track_error(exc, None)

                def bar(self):
                    pass
            """
        ).strip("\n")
        violations_class = _analyze_module(ast.parse(class_level, filename="<synthetic-class-level>"), "cl.py")
        assert len(violations_class) == 1, violations_class
        assert violations_class[0].func == "Foo<class-body>"

    def test_duplicate_violations_are_deduped_by_address_m9(self) -> None:
        """m9: один и тот же адрес (файл+функция+обе строки), достигнутый через
        РАЗНЫЕ пути, не должен размножать записи в отчёте."""
        source = textwrap.dedent(
            """
            class Foo:
                def bar(self, exc, ctx, a, b):
                    if a:
                        pass
                    if b:
                        pass
                    self._log_error("x")
                    self._track_error(exc, ctx)
            """
        ).strip("\n")
        # Два независимых if БЕЗ else дают 4 пути к моменту вызовов — все несут
        # ОДИН И ТОТ ЖЕ адрес (log@7, track@8), но через разные trail.
        violations = _analyze_module(ast.parse(source, filename="<synthetic-m9-dedup>"), "dd.py")
        assert len(violations) == 1, violations
