# -*- coding: utf-8 -*-
"""AST-страж «один разъём на точку» (Task 1.3c, Р-9/Р-10, plans/observability-closure).

Правило (владелец, 2026-09-01, Р-10): `_log_error`/`log_error` (плоскость логов) и
`report_error`/`_track_error`/`track_error` (плоскость ошибок) — запрещены в ОДНОЙ
**ветке исполнения**. Whitelist отсутствует (Р-9) — правило либо соблюдено, либо
красное.

Единица правила — ВЕТКА, не функция. Развилку дают ТОЛЬКО:
    * `if.body` vs `if.orelse`;
    * каждый `except`-обработчик одного `try` (свой, и все они отдельны от тела `try`).
Развилку НЕ дают: тело `try`, тело `with`, тело цикла, `else`/`finally` у `try`,
`else` у цикла — поток идёт СКВОЗЬ них, это продолжение той же ветки. Ранний
`return`/`raise`/`continue`/`break` делит ветку на сегменты «до» и «после».
Вложенные `def`/`class`/`lambda` — своя единица, в текущую ветку их вызовы не
считаются (обходчик анализирует их отдельно, само по себе).

**Почему тело `try` обязано быть проходным, а не веткой — это была ошибка автора
Р-10 в первой редакции прототипа.** Если считать тело `try:` отдельной веткой, то
сайт вида `_track_error(...)` перед `try: ... _log_error(...)` проскакивает мимо
правила, и страж даёт ложный зелёный. Проверено этим же обходчиком на
`ObservableMixin.report_error`: с этой ошибкой дерево даёт 0 нарушений, без неё — 1
(см. `test_boundary_is_structural_not_a_whitelist_entry` ниже — без границы этот же
адрес обязан попасть в список).

**Граница правила (не whitelist).** Тело определения самого разъёма —
`ObservableMixin.report_error` (`base_manager/mixins/observable_mixin.py`) — не
является САЙТОМ: это место, где обе дороги РЕАЛИЗОВАНЫ (см. докстринг метода —
факт синхронно, голос под защитой `try`). Правило говорит про сайты вызова, не про
реализацию механизма. Граница задана СТРУКТУРНО — (файл, имя класса, имя метода) —
а не «пропустить файл целиком»: `test_boundary_is_structural_not_a_whitelist_entry`
доказывает, что без этой тройки метод остаётся нарушением, а не то, что граница
случайно совпала с пустым файлом.

## Происхождение (слияние приёмки слепого тестера)

До этой задачи в дереве лежал независимый RED-тест
`base_manager/tests/test_error_plane_one_connector_ast_guard_acceptance.py`,
написанный тестером ВСЛЕПУЮ (до реализации, из acceptance criteria плана). Он пинил
ДВЕ вещи:

1. **Единица правила — «одна функция».** Отменено Р-10 в пользу «одна ветка» — сама
   формулировка правила изменилась, а не его исполнение;
2. **Известное нарушение — `router_module/core/router_manager.py::_report_send_error`.**
   Эта пара уже НЕ существует: Task 1.3b перенесла сайт на единственный вызов
   `self.report_error(...)` (см. `router_manager.py:406-409` — коммент на месте прямо
   объясняет перенос). Тестер писал против HEAD ДО миграции 1.3b, и старый контроль
   умер вместе с мигрированной парой — не потому что сломался, а потому что предмет,
   который он проверял, физически перестал существовать.

Файл удалён (не оставлен рядом) — две копии одного обходчика были бы хуже одной:
зелёный доказывал бы согласие двух копий одной модели, а не здоровье кода (правило
проекта «одна ветка исполнения» применительно к самим тестам). Обе содержательные
идеи тестера перенесены сюда: «обходчик обязан хоть что-то находить на реальном
исходнике» → `test_synthetic_pair_in_one_body_is_a_violation` (контроль по адресу);
«известное нарушение находится обходчиком» → сам обходчик доказан на живом дереве
через `ObservableMixin.report_error` (см. границу выше — до C2/1.3b дорога плагина в
плоскость ошибок была ПОЧИНЕНА, и парность в самом разъёме — не костыль, а место, где
обе дороги ЖИВУТ по построению).

## Числа (сверены с числами владельца до задачи, метод — AST, не глазом)

Обход `multiprocess_framework`, `Services`, `Plugins`, `multiprocess_prototype`, без
`tests/`, `test_*`, `__pycache__`, на HEAD `659930a5`:

* «в функции» (оба коннектора где-то в поддереве функции, включая вложенные
  `def`) → **4**: `ObservableMixin.report_error`,
  `SourceProducer.run_loop`, `DrawingIoPlugin._do_save`, `frontend/app.py::run_gui`
  (у `run_gui` — только через вложенный `_ActivatorLog.error`, который сам по себе
  отдельная единица; на уровне веток `run_gui` ЧИСТ — см. ниже);
* «в ветке» (Р-10) → **1**: только `ObservableMixin.report_error` (тело `try` —
  проходное, факт и голос делят один сегмент);
* «в ветке» + граница → **0**.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCAN_ROOTS = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype")

_LOG_NAMES = frozenset({"_log_error", "log_error"})
_TRACK_NAMES = frozenset({"_track_error", "track_error", "report_error"})

#: Граница правила (не whitelist, Р-9/Р-10) — тело определения самого разъёма.
_BOUNDARY_FILE = "multiprocess_framework/modules/base_manager/mixins/observable_mixin.py"
_BOUNDARY_QUALNAME = "ObservableMixin.report_error"

#: Живые (не синтетические) негативные пары — легитимные развилки, которые страж
#: обязан НЕ находить. Взяты с дерева после Task 1.3b.
_LIVE_NEGATIVE_CASES = (
    # if/else-запасной путь: health.report_error, когда health подключён,
    # иначе _log_error — две ветки одного if, каждая с ОДНИМ коннектором.
    ("multiprocess_framework/modules/process_module/generic/source_producer.py", "run_loop"),
    # разведённые ранним `return` разные классы событий: пустой список точек
    # (класс B, log_error + return) отдельно от отказа сохранения (except + return).
    ("Plugins/io/drawing_io/plugin.py", "_do_save"),
)


def _call_name(func: ast.expr) -> Optional[str]:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _handler_label(index: int, handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        exc_name = "bare"
    else:
        try:
            exc_name = ast.unparse(handler.type)
        except Exception:  # noqa: BLE001 — метка для сообщения, не критично
            exc_name = "?"
    return f"except[{index}]({exc_name})"


@dataclass
class CallSite:
    line: int
    name: str


@dataclass
class Segment:
    """Накопитель вызовов ОДНОГО сегмента одной ветки — до следующего разделителя."""

    log: list = field(default_factory=list)
    track: list = field(default_factory=list)

    def add(self, name: str, line: int) -> None:
        if name in _LOG_NAMES:
            self.log.append(CallSite(line, name))
        if name in _TRACK_NAMES:
            self.track.append(CallSite(line, name))

    def is_violation(self) -> bool:
        return bool(self.log) and bool(self.track)


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


class _BranchWalker:
    """Обходчик ОДНОГО юнита (функции/метода/лямбды) — своё дерево веток.

    Вложенные `def`/`class`/`lambda` в текущую ветку не идут — они складываются в
    ``nested_units`` и разбираются отдельно, как самостоятельные юниты (см. модульную
    докстринг-семантику Р-10 выше).
    """

    def __init__(self, file_rel: str, qualname: str) -> None:
        self.file = file_rel
        self.qualname = qualname
        self.violations: list[Violation] = []
        self.nested_units: list[tuple[str, ast.AST]] = []

    # ------------------------------------------------------------------ #
    # Публичный вход — разобрать список стейтментов как ОДНУ ветку.
    # ------------------------------------------------------------------ #
    def walk_branch(self, stmts: list, label: str) -> None:
        seg = Segment()
        self._walk_stmts(stmts, seg, label)
        self._close(seg, label)

    def _close(self, seg: Segment, label: str) -> None:
        if seg.is_violation():
            self.violations.append(Violation(self.file, self.qualname, label, seg.log[0], seg.track[0]))
        seg.log = []
        seg.track = []

    def _walk_stmts(self, stmts: list, seg: Segment, label: str) -> None:
        for stmt in stmts:
            self._walk_stmt(stmt, seg, label)

    def _walk_stmt(self, stmt: ast.stmt, seg: Segment, label: str) -> None:
        # Вложенные def/class — своя единица (Р-10): в текущую ветку не идут.
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.nested_units.append((f"{self.qualname}.<locals>.{stmt.name}", stmt))
            return

        if isinstance(stmt, ast.If):
            # test исполняется безусловно на пути к обеим веткам — часть текущего сегмента.
            self._collect_expr(stmt.test, seg)
            self.walk_branch(stmt.body, f"{label}>if@{stmt.lineno}.body")
            if stmt.orelse:
                self.walk_branch(stmt.orelse, f"{label}>if@{stmt.lineno}.else")
            return

        if isinstance(stmt, ast.Try):
            # Тело try — ПРОХОДНОЕ (не ветка): продолжает ТЕКУЩИЙ сегмент.
            self._walk_stmts(stmt.body, seg, label)
            # Каждый except — своя ветка, отдельная от тела try и от соседних except.
            for idx, handler in enumerate(stmt.handlers):
                self.walk_branch(handler.body, f"{label}>try@{stmt.lineno}.{_handler_label(idx, handler)}")
            # else/finally у try — тоже проходные, продолжают текущий сегмент.
            if stmt.orelse:
                self._walk_stmts(stmt.orelse, seg, label)
            if stmt.finalbody:
                self._walk_stmts(stmt.finalbody, seg, label)
            return

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                self._collect_expr(item.context_expr, seg)
            self._walk_stmts(stmt.body, seg, label)  # тело with — проходное
            return

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._collect_expr(stmt.iter, seg)
            self._walk_stmts(stmt.body, seg, label)  # тело цикла — проходное
            if stmt.orelse:
                self._walk_stmts(stmt.orelse, seg, label)  # else цикла — тоже проходной
            return

        if isinstance(stmt, ast.While):
            self._collect_expr(stmt.test, seg)
            self._walk_stmts(stmt.body, seg, label)
            if stmt.orelse:
                self._walk_stmts(stmt.orelse, seg, label)
            return

        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            value = getattr(stmt, "value", None)
            if value is None:
                value = getattr(stmt, "exc", None)
            if value is not None:
                self._collect_expr(value, seg)
            # Ранний выход делит ветку на сегменты «до» и «после» (Р-10).
            self._close(seg, label)
            return

        # Простой стейтмент (Expr, Assign, AugAssign, AnnAssign, Global, Import, ...).
        self._collect_expr(stmt, seg)

    def _collect_expr(self, node, seg: Segment) -> None:
        if node is None:
            return
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            marker = getattr(node, "name", None) or f"lambda@{node.lineno}"
            self.nested_units.append((f"{self.qualname}.<locals>.{marker}", node))
            return
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                seg.add(name, node.lineno)
        for child in ast.iter_child_nodes(node):
            self._collect_expr(child, seg)


def _is_boundary(rel: str, qualname: str) -> bool:
    return rel == _BOUNDARY_FILE and qualname == _BOUNDARY_QUALNAME


def _scan_body_for_units(body: list, prefix: str, queue: list) -> None:
    """Верхнеуровневые (не вложенные внутрь функции) def/class модуля — в очередь юнитов."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            queue.append((f"{prefix}{stmt.name}", stmt))
        elif isinstance(stmt, ast.ClassDef):
            _scan_body_for_units(stmt.body, f"{prefix}{stmt.name}.", queue)


def _analyze_module(tree: ast.Module, rel: str, *, apply_boundary: bool = True) -> list:
    """Разобрать один УЖЕ распарсенный модуль → список нарушений."""
    violations: list[Violation] = []
    queue: list[tuple[str, ast.AST]] = []
    _scan_body_for_units(tree.body, "", queue)

    while queue:
        qualname, node = queue.pop()
        if isinstance(node, ast.ClassDef):
            # Вложенный класс — не юнит сам по себе, разобрать его методы.
            _scan_body_for_units(node.body, f"{qualname}.", queue)
            continue
        if apply_boundary and _is_boundary(rel, qualname):
            continue
        walker = _BranchWalker(rel, qualname)
        if isinstance(node, ast.Lambda):
            seg = Segment()
            walker._collect_expr(node.body, seg)
            walker._close(seg, "root")
        else:
            walker.walk_branch(node.body, "root")
        violations.extend(walker.violations)
        queue.extend(walker.nested_units)

    return violations


def _analyze_file(path: Path, repo_root: Path, *, apply_boundary: bool = True) -> tuple:
    rel = path.relative_to(repo_root).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return [], False
    return _analyze_module(tree, rel, apply_boundary=apply_boundary), True


def _iter_source_files(repo_root: Path) -> Iterator[Path]:
    for root_name in _SCAN_ROOTS:
        root = repo_root / root_name
        for path in sorted(root.rglob("*.py")):
            posix = path.as_posix()
            if "/tests/" in posix or path.name.startswith("test_") or "__pycache__" in posix:
                continue
            yield path


def scan_tree(repo_root: Path, *, apply_boundary: bool = True) -> tuple:
    """Обойти все 4 слоя → (нарушения, файлы, которые не разобрались)."""
    violations: list[Violation] = []
    unparsed: list[str] = []
    for path in _iter_source_files(repo_root):
        file_violations, ok = _analyze_file(path, repo_root, apply_boundary=apply_boundary)
        violations.extend(file_violations)
        if not ok:
            unparsed.append(path.relative_to(repo_root).as_posix())
    return violations, unparsed


# ========================================================================== #
# ТЕСТЫ
# ========================================================================== #


class TestOneConnectorPerPointGuard:
    def test_guard_is_green_on_the_tree(self) -> None:
        """Страж зелёный на дереве после Task 1.3b — достижимо только по Р-10.

        Прежняя формулировка «в одной функции» была бы красна по построению на
        4 функциях (см. докстринг файла) — зелёным дерево становится ТОЛЬКО когда
        единица правила — ветка, а не функция.
        """
        violations, unparsed = scan_tree(_REPO_ROOT)
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
        """Контроль по адресу: обходчик обязан хоть что-то находить.

        Без этого теста зелёный прогон выше был бы немотой, а не здоровьем (правило
        проекта «ноль наблюдений выглядит как результат наблюдения»). Синтетика — не
        подмена живой проверки, а доказательство, что сам обходчик рабочий, ДО того
        как мы доверяем его нулю на реальном дереве.
        """
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

    def test_live_negative_pairs_are_not_flagged(self) -> None:
        """Легитимные развилки с живого дерева НЕ краснеют — по имени и файлу.

        Не общий «список пуст»: если бы страж вообще ничего не находил (сломан),
        этот тест был бы зелёным вхолостую. Проверяется конкретное отсутствие
        КОНКРЕТНОЙ функции — это разные утверждения.
        """
        violations, _ = scan_tree(_REPO_ROOT)
        flagged = {(v.file, v.func) for v in violations}
        for file, func in _LIVE_NEGATIVE_CASES:
            assert (file, func) not in flagged, (
                f"{file}::{func} ошибочно попал(а) в нарушения — легитимная "
                f"развилка (if/else или ранний return) сломана обходчиком"
            )

    def test_synthetic_negative_pair_two_different_except_handlers(self) -> None:
        """Третий негативный случай правила: два разных `except` одного `try`.

        **Честно: НЕ с живого дерева, в отличие от двух случаев выше.** Полным AST-
        сканом всех четырёх слоёв (framework/Services/Plugins/prototype, без
        tests/) подтверждено: функций, где оба коннектора вообще встречаются
        вместе, ровно 4 (см. числа в докстринге файла — совпадают с числами
        владельца). Ни в одной из них, и нигде больше в этом дереве на
        HEAD `659930a5`, `_log_error` не стоит в одном `except`, а
        `report_error`/`_track_error` — в ДРУГОМ `except` ТОГО ЖЕ `try`: сама эта
        форма сейчас в коде не встречается ни разу. Инструкция задачи просила все
        три случая «с живого дерева», но для этого конкретного паттерна живого
        случая нет — искал скриптом (AST по всем `ast.Try` с 2+ обработчиками),
        не глазом. Если он появится позже — это готовая точка, куда его перенести.
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
        """Граница реально что-то снимает — а не совпала с опечаткой.

        Без границы `ObservableMixin.report_error` обязан попасть в нарушения
        (доказывает, что страж вообще видит эту пару); с границей — обязан выпасть.
        Оба утверждения в одном тесте: граница неотличима от опечатки, если
        проверить только одну сторону.
        """
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
