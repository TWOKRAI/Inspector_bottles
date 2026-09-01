# -*- coding: utf-8 -*-
"""AST-страж «один разъём на точку» (Task 1.3c, Р-9/Р-10, plans/observability-closure).

Правило (владелец, 2026-09-01, Р-10): `_log_error`/`log_error` (плоскость логов) и
`report_error`/`_track_error`/`track_error` (плоскость ошибок) — запрещены в ОДНОЙ
**ветке исполнения**. Whitelist отсутствует (Р-9) — правило либо соблюдено, либо
красное.

## Модель — перечисление ПУТЕЙ, не изолированных сегментов (правка J9)

**Первая редакция обходчика (тот же день, до инъекции) резала веточную развилку от
ЕЁ ЖЕ РОДИТЕЛЯ и была неверна.** `if`-тело обрабатывалось как отдельный сегмент,
заведённый ПУСТЫМ — вызов до `if` и вызов внутри `if.body` никогда не оказывались в
одном сегменте, даже когда `if` не имеет `else` и оба вызова реально исполняются
подряд на одном и том же прогоне при истинном условии. Матрица инъекций координатора
(заплатка J9, `router_manager.py::_report_send_error`: `if reason:
self._log_error(...)` перед уже стоящим `self.report_error(...)`) поймала это —
страж молчал, хотя при истинном `reason` голос звучит дважды. Тот же прогон
опроверг и мой собственный прогноз про guard-clause (J7a): пара, разведённая `if x:
_log_error(); return`, действительно обязана оставаться зелёной, но старая модель
была зелёной там ПО ТОЙ ЖЕ ошибочной причине (пустой сегмент), а не потому что
`return` — легитимная развилка. Обе кривизны (ложный зелёный на J9, случайно верный
зелёный на guard-clause) чинит одна замена модели.

Правильная модель — **перечисление путей исполнения**, а не одна метка «ветка» на
подсегмент:

* `A; if c: B else: D; E` даёт ДВА пути: `A+B+E` и `A+D+E`. Пара «лог+факт» в ОДНОМ
  пути = нарушение. `if` без `else` — то же самое с `D` пустым (путь проходит `if`
  насквозь, не подбирая ничего).
* `if`/`try`-`except` **форкают** список открытых путей: тело `if` и `else`
  (или сквозной проход при отсутствии `else`) — по копии от каждого пути, вошедшего в
  `if`; каждый `except` — по копии от путей, живых на ВХОДЕ в `try` (не после его
  тела — исключение может прилететь с первой же строки).
* Тело `try`, тело `with`, тело цикла, `else`/`finally` у `try`, `else` у цикла —
  ПРОХОДНЫЕ: продолжают открытые пути, а не форкают их.
* `return`/`raise`/`continue`/`break` **закрывают** путь: он больше не растёт и
  проверяется на нарушение немедленно. Это и делает ранний выход настоящей
  развилкой: `if x: log(); return` + `report()` ниже даёт путь-1 (лог, закрыт на
  `return`, факта в нём нет) и путь-2 (после `if`, только факт) — оба чисты.
  Без `return` тот же код даёт ОДИН путь после `if`, где оба вызова встречаются —
  и это уже нарушение (см. `test_if_without_else_leaks_from_parent_j9_regression` и
  `test_early_return_closes_the_path_guard_clause` ниже — заявленное свойство
  проверено ОБОИМИ прогонами, не только тем, что «зелено»).
* Вложенные `def`/`class`/`lambda` — своя единица, в текущий путь их вызовы не идут
  (без изменений от первой редакции).
* **Потолок открытых путей** (`_MAX_OPEN_PATHS`) — при форке, дающем больше путей,
  чем потолок, все пути группы схлопываются в ОДИН консервативным объединением
  вызовов (сумма log/track, без потери фактов). Без потолка N независимых `if`
  подряд даёт `2**N` путей — экспоненциальный взрыв на глубоко вложенном/длинном
  файле повесил бы страж навсегда. Слияние может дать ЛИШНЕЕ нарушение (пути,
  которые сами по себе не нарушали, но объединены), но никогда не спрячет
  настоящее — объединение calls не теряет ни одного вызова. См.
  `test_path_explosion_is_capped_and_terminates`.

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

1. **Единица правила — «одна функция».** Отменено Р-10 в пользу «одна ветка/путь» —
   сама формулировка правила изменилась, а не его исполнение;
2. **Известное нарушение — `router_module/core/router_manager.py::_report_send_error`.**
   Эта пара уже НЕ существует на боевом коде: Task 1.3b перенесла сайт на единственный
   вызов `self.report_error(...)` (см. `router_manager.py:406-409` — коммент на месте
   прямо объясняет перенос). Тестер писал против HEAD ДО миграции 1.3b, и старый
   контроль умер вместе с мигрированной парой. Та же функция позже сослужила службу
   ещё раз — координатор воспроизвёл на ней находку J9 ВРЕМЕННОЙ заплаткой (внесена
   и сразу откачена, в дереве её нет).

Файл удалён (не оставлен рядом) — две копии одного обходчика были бы хуже одной.
Обе содержательные идеи тестера перенесены сюда: «обходчик обязан хоть что-то
находить на реальном исходнике» → `test_synthetic_pair_in_one_body_is_a_violation`
(контроль по адресу); «известное нарушение находится обходчиком» → сам обходчик
доказан на живом дереве через `ObservableMixin.report_error` (граница выше).

## Числа (сверены с числами владельца до задачи, метод — AST, не глазом)

Обход `multiprocess_framework`, `Services`, `Plugins`, `multiprocess_prototype`, без
`tests/`, `test_*`, `__pycache__`, на HEAD `659930a5`/`83b12f30`:

* «в функции» (оба коннектора где-то в поддереве функции, включая вложенные
  `def`) → **4**: `ObservableMixin.report_error`,
  `SourceProducer.run_loop`, `DrawingIoPlugin._do_save`, `frontend/app.py::run_gui`
  (у `run_gui` — только через вложенный `_ActivatorLog.error`, который сам по себе
  отдельная единица; на уровне путей `run_gui` ЧИСТ — см. ниже);
* «путевая модель» без границы → нарушения находит ТОЛЬКО на путях, реально
  проходящих через `ObservableMixin.report_error` (в нём после правки J9 путевая
  модель находит нарушение на КАЖДОМ из двух путей, форкнутых вложенным `if
  recorded:` до вызова `_log_error` — было 1 при старой сегментной модели, теперь 2,
  оба по тому же самому реальному дефекту рецепта, не по двум разным);
* «путевая модель» + граница → **0** — дерево зелёное (см.
  `test_guard_is_green_on_the_tree`).
"""

from __future__ import annotations

import ast
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCAN_ROOTS = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype")

_LOG_NAMES = frozenset({"_log_error", "log_error"})
_TRACK_NAMES = frozenset({"_track_error", "track_error", "report_error"})

#: Потолок одновременно открытых путей на один юнит. Без него N независимых `if`
#: подряд удваивают список путей на каждом — `2**N` при N~30 вешает страж навсегда
#: на реальном файле. При превышении — консервативное слияние (см. `_cap_paths`).
_MAX_OPEN_PATHS = 512

#: Граница правила (не whitelist, Р-9/Р-10) — тело определения самого разъёма.
_BOUNDARY_FILE = "multiprocess_framework/modules/base_manager/mixins/observable_mixin.py"
_BOUNDARY_QUALNAME = "ObservableMixin.report_error"

#: Живые (не синтетические) негативные пары — легитимные развилки, которые страж
#: обязан НЕ находить. Взяты с дерева после Task 1.3b, перепроверены под путевой
#: моделью (не только под первой, сегментной).
_LIVE_NEGATIVE_CASES = (
    # if/else-запасной путь: health.report_error, когда health подключён,
    # иначе _log_error — каждый путь через этот if несёт РОВНО один коннектор.
    ("multiprocess_framework/modules/process_module/generic/source_producer.py", "run_loop"),
    # разведённые ранним `return` разные классы событий: путь через пустой список
    # точек закрывается на `return` сразу после log_error (факта в нём нет), путь
    # через отказ сохранения закрывается на `return` сразу после report_error.
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
class Path:
    """Один путь исполнения от начала юнита до текущей точки.

    ``trail`` — метки форков, пройденных этим путём (для адреса в сообщении).
    Пустой ``trail`` — путь ни разу не форкался (``root``).
    """

    log: list = field(default_factory=list)
    track: list = field(default_factory=list)
    trail: list = field(default_factory=list)

    def copy(self) -> "Path":
        p = Path()
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
    """Обходчик ОДНОГО юнита (функции/метода/лямбды) — перечисляет пути исполнения.

    Вложенные `def`/`class`/`lambda` в текущий путь не идут — они складываются в
    ``nested_units`` и разбираются отдельно, как самостоятельные юниты.
    """

    def __init__(self, file_rel: str, qualname: str) -> None:
        self.file = file_rel
        self.qualname = qualname
        self.violations: list[Violation] = []
        self.nested_units: list[tuple[str, ast.AST]] = []

    # ------------------------------------------------------------------ #
    # Публичный вход — разобрать тело юнита целиком.
    # ------------------------------------------------------------------ #
    def run(self, body: list) -> None:
        closed: list[Path] = []
        open_paths = self._walk_stmts(body, [Path()], closed)
        # Юнит кончился — то, что ещё открыто, закрывается неявным концом функции.
        closed.extend(open_paths)
        for p in closed:
            self._check(p)

    def _check(self, p: "Path") -> None:
        if p.is_violation():
            self.violations.append(Violation(self.file, self.qualname, p.label(), p.log[0], p.track[0]))

    # ------------------------------------------------------------------ #
    # Перечисление путей.
    # ------------------------------------------------------------------ #
    def _walk_stmts(self, stmts: list, paths: list, closed: list) -> list:
        for stmt in stmts:
            paths = self._walk_stmt(stmt, paths, closed)
        return paths

    def _walk_stmt(self, stmt: ast.stmt, paths: list, closed: list) -> list:
        # Вложенные def/class — своя единица (без изменений): в текущий путь не идут.
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.nested_units.append((f"{self.qualname}.<locals>.{stmt.name}", stmt))
            return paths

        if isinstance(stmt, ast.If):
            # test исполняется на пути к ОБЕИМ веткам — не форкает, идёт во все пути.
            for p in paths:
                self._collect_expr(stmt.test, p)
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
                # Нет else — путь проходит `if` НАСКВОЗЬ (J9): копия родителя без
                # добавленного тела `if`, а не пустой изолированный сегмент.
                else_paths = [p.copy() for p in paths]
            return self._cap(body_paths + else_paths)

        if isinstance(stmt, ast.Try):
            entry_paths = [p.copy() for p in paths]  # пути, живые НА ВХОДЕ в try
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
            merged = self._cap(body_paths + handler_paths)
            if stmt.finalbody:
                # finally — проходной для ВСЕХ путей (успех и каждый except).
                merged = self._walk_stmts(stmt.finalbody, merged, closed)
            return merged

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                for p in paths:
                    self._collect_expr(item.context_expr, p)
            return self._walk_stmts(stmt.body, paths, closed)  # проходной

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            for p in paths:
                self._collect_expr(stmt.iter, p)
            paths = self._walk_stmts(stmt.body, paths, closed)  # проходной
            if stmt.orelse:
                paths = self._walk_stmts(stmt.orelse, paths, closed)
            return paths

        if isinstance(stmt, ast.While):
            for p in paths:
                self._collect_expr(stmt.test, p)
            paths = self._walk_stmts(stmt.body, paths, closed)
            if stmt.orelse:
                paths = self._walk_stmts(stmt.orelse, paths, closed)
            return paths

        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            value = getattr(stmt, "value", None)
            if value is None:
                value = getattr(stmt, "exc", None)
            if value is not None:
                for p in paths:
                    self._collect_expr(value, p)
            # Ранний выход ЗАКРЫВАЕТ путь — он не растёт дальше (J9-фикс).
            closed.extend(paths)
            return []

        # Простой стейтмент (Expr, Assign, AugAssign, AnnAssign, Global, Import, ...).
        for p in paths:
            self._collect_expr(stmt, p)
        return paths

    def _collect_expr(self, node, p: "Path") -> None:
        if node is None:
            return
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            marker = getattr(node, "name", None) or f"lambda@{node.lineno}"
            self.nested_units.append((f"{self.qualname}.<locals>.{marker}", node))
            return
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                p.add(name, node.lineno)
        for child in ast.iter_child_nodes(node):
            self._collect_expr(child, p)

    def _cap(self, paths: list) -> list:
        """Потолок открытых путей — консервативное слияние при превышении.

        Схлопывает ВСЕ пути группы в один union'ом log/track (без потери вызовов —
        может дать лишнее нарушение, никогда не спрячет настоящее). Иначе `2**N`
        независимых `if` подряд не даёт стражу завершиться на реальном файле.
        """
        if len(paths) <= _MAX_OPEN_PATHS:
            return paths
        merged = Path()
        merged.trail = ["capped(>{}paths)".format(_MAX_OPEN_PATHS)]
        for p in paths:
            merged.log.extend(p.log)
            merged.track.extend(p.track)
        return [merged]


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
        walker = _PathWalker(rel, qualname)
        if isinstance(node, ast.Lambda):
            p = Path()
            walker._collect_expr(node.body, p)
            walker._check(p)
        else:
            walker.run(node.body)
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
        единица правила — путь, а не функция и не изолированный сегмент.
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
        проекта «ноль наблюдений выглядит как результат наблюдения»).
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

    def test_if_without_else_leaks_from_parent_j9_regression(self) -> None:
        """Регресс-сторож J9: `if` без `else` обязан наследовать вызовы РОДИТЕЛЯ.

        Найдено инъекцией координатора на живом коде (`router_manager.py::
        _report_send_error`, заплатка `if reason: self._log_error(...)` перед уже
        стоящим `self.report_error(...)`): первая редакция обходчика заводила ПУСТОЙ
        сегмент для тела `if` — вызов до `if` и вызов внутри никогда не встречались
        в одном сегменте, и страж молчал, хотя при истинном условии звучат ОБА.
        Путевая модель обязана видеть путь «через `if`» как ПРОДОЛЖЕНИЕ пути до
        `if`, а не изолированную ветку с нуля.
        """
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
        """Guard-clause: ранний `return` — легитимная развилка, немота — нет.

        Пара обязана быть в ОДНОМ тесте (координатор): иначе зелёный на варианте
        с `return` неотличим от того, что обходчик просто ничего не находит — его
        держит именно закрытие пути на `return`, что доказывает КРАСНЫЙ вариант без
        `return` рядом, на том же теле.
        """
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
        владельца). Ни в одной из них, и нигде больше в этом дереве, `_log_error`
        не стоит в одном `except`, а `report_error`/`_track_error` — в ДРУГОМ
        `except` ТОГО ЖЕ `try`: сама эта форма сейчас в коде не встречается ни
        разу. Инструкция задачи просила все три случая «с живого дерева», но для
        этого конкретного паттерна живого случая нет — искал скриптом (AST по всем
        `ast.Try` с 2+ обработчиками), не глазом.
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

    def test_path_explosion_is_capped_and_terminates(self) -> None:
        """Потолок путей не даёт стражу зависнуть на длинной цепочке `if`.

        14 НЕЗАВИСИМЫХ (не вложенных) `if` подряд без потолка дают `2**14` = 16384
        путей — далеко за `_MAX_OPEN_PATHS` (512). Синтетика в памяти, файл на диск
        не кладём. Проверяется и завершение (не висит), и отсутствие ложного
        падения обходчика на самом факте превышения потолка.
        """
        depth = 14
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
