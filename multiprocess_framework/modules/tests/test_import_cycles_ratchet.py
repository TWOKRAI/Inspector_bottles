"""Храповик на циклы импорта framework: число, размер и охват файловых SCC не растут.

Зачем свой граф, а не sentrux или ``scripts/arch_graph``:

* sentrux не видит относительные импорты (а framework почти весь на них) —
  его «зелёный» по циклам внутри ``multiprocess_framework/modules`` ничего не
  доказывает;
* ``scripts/arch_graph/ast_graph.py`` — скрипт с ``argv`` на уровне модуля и
  считает пакеты, а не файлы; импортировать его из теста нельзя.

Поэтому тест САМОДОСТАТОЧНЫЙ: только stdlib (``ast``, ``pathlib``).

Модель графа (литералы ``*_BASELINE`` измерены ровно в ней):

* узлы — production-файлы под ``multiprocess_framework/modules``: исключены
  пути с каталогом ``tests``, файлы ``test_*.py`` и ``conftest.py``, всё под
  ``_frozen``;
* рёбра — ``import`` / ``from ... import`` на ЛЮБОЙ вложенности: верхний
  уровень и ленивые (тело функции, метода, ``try``, условия), КРОМЕ тела
  ``if TYPE_CHECKING:`` (его ``else`` — считается: он исполняется);
* разрешаются и относительные, и абсолютные импорты; форма
  ``from pkg import submodule`` даёт ребро в файл подмодуля, ``from pkg
  import name`` — в ``pkg/__init__.py``; импорт пакета = его ``__init__.py``;
  неявные ``__init__.py`` родителей НЕ добавляются;
* импорты вне ``multiprocess_framework/modules`` и в исключённые файлы
  отбрасываются; динамические (``importlib.import_module``) не видны.

SCC — алгоритм Тарьяна, итеративный (глубина графа не упирается в рекурсию).

Два храповика на одном графе:

1. **Строгий** — все рёбра, включая дверь ``_fallback``. Держит «ничего не
   выросло, ни одного нового ребра в цикле».
2. **По санкционированным швам** — тот же граф без рёбер из
   :data:`SANCTIONED_SEAMS`. Дверь к логгеру для нижних слоёв переносит
   ребро, а не режет его (строгий счёт видит её ленивое ребро), поэтому без
   исключения все остальные циклы framework тонут в одной большой компоненте.
   Здесь они меряются отдельно, и новый ход к логгеру В ОБХОД двери ловится.

Рост любого числа — красный; сообщение перечисляет с файлами компоненты, которых
нет в базе (по первому по алфавиту файлу) или которые выросли.
Уменьшение — тоже красный, но с другим текстом: «цикл уменьшился, подтяни
литерал» — это нормальная победа, а не поломка; без этого храповик молча
перестаёт держать достигнутое (``python <этот файл>`` печатает оба замера).

**Слепое пятно модели.** Неявные ``__init__.py`` родительских пакетов (``import
a.b.c`` исполняет ``a/__init__`` и ``a/b/__init__``) и ``importlib`` /
``__import__`` строкой не моделируются. В модели с предками компоненты другие и
крупнее (ревью Opus 2026-11-12: 87 / 52 / 33 файла), так что числа здесь —
нижняя оценка связности, а не карта рантайма.

**Честная оговорка о шве data_schema -> logger_module (2026-11-12).** «43 -> 41»
в строгом счёте — артефакт модели (дверь переносит ребро, а не режет его), а не
изменение рантайма: на импорте пакета голос ``metrics`` по-прежнему резолвит
логгер. Измеренный выигрыш шва — храповик по швам: 38 -> 19.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest


class _Baseline(NamedTuple):
    scc_count: int
    largest: int
    files_in_scc: int
    #: Каждая SCC базового замера как (первый по алфавиту файл, размер) — только
    #: для сообщения (какая компонента новая или выросла), не для утверждения.
    #: По одним размерам новую компоненту не отличить от старой того же размера
    #: (поймано инъекцией c3: сообщение назвало чужую пару).
    components: tuple[tuple[str, int], ...]


#: Рёбра, которые храповик 2 не считает. Неизменяемый список: рост — архитектурное
#: решение (запись в data_schema_module/DECISIONS.md, ADR-DS-009), а не правка
#: теста (см. test_sanctioned_seams_has_exactly_one_entry).
SANCTIONED_SEAMS: tuple[tuple[str, str, str], ...] = (
    (
        "_fallback.py",
        "logger_module/adapters/std_facade.py",
        "единственная документированная дверь к логгеру для нижних слоёв; ленивая, первое обращение",
    ),
)

# Замер 2026-11-12. На HEAD до правок: строгий 6 SCC / наибольшая 43 / 64 файла,
# по швам 6 / 38 / 59. После перевода data_schema_module/core/field_meta.py и
# core/metrics.py на _fallback.FallbackLogger — литералы ниже.
_SMALL_CYCLES: tuple[tuple[str, int], ...] = (
    ("process_module/configs/observability_config.py", 11),
    ("data_schema_module/factory/dna_factory.py", 4),
    ("app_module/manifest.py", 2),
    ("process_module/generic/frame_trace.py", 2),
    ("recipe/service.py", 2),
)
STRICT_BASELINE = _Baseline(scc_count=6, largest=41, files_in_scc=62, components=(("_fallback.py", 41), *_SMALL_CYCLES))
SANCTIONED_BASELINE = _Baseline(
    scc_count=6, largest=19, files_in_scc=40, components=(("base_manager/__init__.py", 19), *_SMALL_CYCLES)
)

_MODULES_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _MODULES_DIR.parents[1]


def _is_production(path: Path) -> bool:
    rel_parts = path.relative_to(_MODULES_DIR).parts
    if "tests" in rel_parts[:-1] or "_frozen" in rel_parts:
        return False
    return not (path.name.startswith("test_") or path.name == "conftest.py")


def _dotted(path: Path) -> str:
    parts = list(path.relative_to(_REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


class _ImportCollector(ast.NodeVisitor):
    """Все Import/ImportFrom файла на любой вложенности, кроме тела ``if TYPE_CHECKING``."""

    def __init__(self) -> None:
        self.found: list[ast.Import | ast.ImportFrom] = []

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.found.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.found.append(node)


def build_graph() -> dict[str, set[str]]:
    """Файловый граф production-кода: относительный путь -> множество путей-целей."""
    all_files = sorted(p for p in _MODULES_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    by_name = {_dotted(p): p for p in all_files}
    production = {p for p in all_files if _is_production(p)}

    def resolve(name: str) -> Path | None:
        # Точное имя, иначе самый длинный известный префикс (импорт атрибута
        # через точку); вне modules — None.
        parts = name.split(".")
        while parts:
            hit = by_name.get(".".join(parts))
            if hit is not None:
                return hit
            parts.pop()
        return None

    graph: dict[str, set[str]] = {}
    for path in sorted(production):
        rel = path.relative_to(_MODULES_DIR).as_posix()
        targets: set[Path] = set()
        me = _dotted(path)
        package = me if path.name == "__init__.py" else me.rpartition(".")[0]
        collector = _ImportCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for node in collector.found:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    hit = resolve(alias.name)
                    if hit is not None:
                        targets.add(hit)
                continue
            if node.level:
                base_parts = package.split(".")
                if node.level > 1:
                    base_parts = base_parts[: -(node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            for alias in node.names:
                sub = by_name.get(f"{base}.{alias.name}") if alias.name != "*" else None
                hit = sub if sub is not None else resolve(base)
                if hit is not None:
                    targets.add(hit)
        graph[rel] = {t.relative_to(_MODULES_DIR).as_posix() for t in targets if t in production and t != path}
    return graph


def without_sanctioned_seams(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Копия графа без рёбер из :data:`SANCTIONED_SEAMS`."""
    pruned = {src: set(dsts) for src, dsts in graph.items()}
    for src, dst, _reason in SANCTIONED_SEAMS:
        pruned.get(src, set()).discard(dst)
    return pruned


def _tarjan(graph: dict[str, set[str]]) -> list[list[str]]:
    """Сильно связные компоненты, итеративный Тарьян."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in sorted(graph):
        if root in index:
            continue
        work: list[tuple[str, list[str]]] = [(root, sorted(graph[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, pending = work[-1]
            if pending:
                nxt = pending.pop()
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, sorted(graph[nxt])))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                components.append(sorted(comp))
    return components


def measure(graph: dict[str, set[str]]) -> list[list[str]]:
    """SCC размера > 1 по убыванию размера (при равенстве — по первому файлу)."""
    cycles = [c for c in _tarjan(graph) if len(c) > 1]
    return sorted(cycles, key=lambda c: (-len(c), c[0]))


def _describe_growth(cycles: list[list[str]], baseline: _Baseline) -> str:
    """Компоненты, которых нет в базе или которые выросли (по первому файлу и размеру)."""
    known = dict(baseline.components)
    suspects = [c for c in cycles if c[0] not in known or len(c) > known[c[0]]]
    shown = suspects or cycles[:1]
    lines = [f"  SCC из {len(c)} файлов: " + ", ".join(c) for c in shown]
    now = tuple((c[0], len(c)) for c in cycles)
    return f"сейчас {now}\nбаза {baseline.components}\nновые/выросшие компоненты:\n" + "\n".join(lines)


def _check(cycles: list[list[str]], baseline: _Baseline, what: str, label: str) -> None:
    """Равенство с базой: рост — «храповик» с компонентами, сжатие — «подтяни литерал»."""
    got = {
        "count": len(cycles),
        "largest": len(cycles[0]) if cycles else 0,
        "files": sum(len(c) for c in cycles),
    }[what]
    limit = {"count": baseline.scc_count, "largest": baseline.largest, "files": baseline.files_in_scc}[what]
    assert got <= limit, f"[{label}] {what}: {got} > {limit} (храповик)\n{_describe_growth(cycles, baseline)}"
    assert got == limit, (
        f"[{label}] {what}: цикл уменьшился (было {limit}, стало {got}): подтяни литерал до {got}, "
        "это нормальная победа"
    )


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return build_graph()


@pytest.fixture(scope="module")
def strict_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    return measure(graph)


@pytest.fixture(scope="module")
def sanctioned_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    return measure(without_sanctioned_seams(graph))


# --- храповик 1: строгий, все рёбра ---------------------------------------


def test_cycle_count_matches_baseline(strict_cycles: list[list[str]]) -> None:
    _check(strict_cycles, STRICT_BASELINE, "count", "строгий")


def test_largest_cycle_matches_baseline(strict_cycles: list[list[str]]) -> None:
    _check(strict_cycles, STRICT_BASELINE, "largest", "строгий")


def test_files_in_cycles_matches_baseline(strict_cycles: list[list[str]]) -> None:
    _check(strict_cycles, STRICT_BASELINE, "files", "строгий")


# --- храповик 2: без санкционированных швов --------------------------------


def test_sanctioned_cycle_count_matches_baseline(sanctioned_cycles: list[list[str]]) -> None:
    _check(sanctioned_cycles, SANCTIONED_BASELINE, "count", "по швам")


def test_sanctioned_largest_cycle_matches_baseline(sanctioned_cycles: list[list[str]]) -> None:
    _check(sanctioned_cycles, SANCTIONED_BASELINE, "largest", "по швам")


def test_sanctioned_files_in_cycles_matches_baseline(sanctioned_cycles: list[list[str]]) -> None:
    _check(sanctioned_cycles, SANCTIONED_BASELINE, "files", "по швам")


# --- охрана списка швов -----------------------------------------------------


def test_sanctioned_seams_has_exactly_one_entry() -> None:
    edges = [(src, dst) for src, dst, _reason in SANCTIONED_SEAMS]
    assert edges == [("_fallback.py", "logger_module/adapters/std_facade.py")], (
        f"SANCTIONED_SEAMS изменён: {edges!r}. Рост списка — архитектурное решение: запись в "
        "data_schema_module/DECISIONS.md (ADR-DS-009), не правка теста; без неё верни список к одной записи."
    )


def test_sanctioned_seam_edges_exist_in_graph(graph: dict[str, set[str]]) -> None:
    missing = [(src, dst) for src, dst, _reason in SANCTIONED_SEAMS if dst not in graph.get(src, set())]
    assert not missing, (
        f"санкционированных рёбер нет в графе: {missing!r} — исключение протухло, храповик 2 "
        "меряет не то, что заявлено; сними запись или почини модель графа"
    )


if __name__ == "__main__":
    full = build_graph()
    for title, found in (("STRICT", measure(full)), ("SANCTIONED", measure(without_sanctioned_seams(full)))):
        print(f"{title}: SCC>1 {len(found)}; largest {len(found[0]) if found else 0}; ", end="")
        print(f"files in SCC {sum(len(c) for c in found)}; sizes {tuple(len(c) for c in found)}")
        for comp in found:
            print(f"  [{len(comp)}] " + ", ".join(comp))
