"""Приёмочные тесты Tree и store ядра scripts/atlas (Task 1.2, RED).

Purpose: слепые тесты (REDS 8, 9): materialize() убирает каталог при выходе и
    при исключении; запрос modules_without_contract_test укладывается в 100 мс
    на синтетической базе (100 модулей, 2000 коммитов, 20000 рёбер).
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

# модули, тронутые коммитами с time >= 2950 (индексы 50..99), без контрактного теста (индекс % 4 != 0)
EXPECTED_WITHOUT_CONTRACT = [
    "m050", "m051", "m053", "m054", "m055", "m057", "m058", "m059", "m061", "m062",
    "m063", "m065", "m066", "m067", "m069", "m070", "m071", "m073", "m074", "m075",
    "m077", "m078", "m079", "m081", "m082", "m083", "m085", "m086", "m087", "m089",
    "m090", "m091", "m093", "m094", "m095", "m097", "m098", "m099",
]  # fmt: skip


def test_materialize_removes_dir_on_exit_and_on_exception(repo):
    from scripts.atlas.tree import Tree

    repo.write("a.md", "committed\n")
    repo.write("docs/x.md", "doc\n")
    repo.commit("init")
    repo.write("a.md", "uncommitted edit\n")  # дерево — это ref, а не рабочий каталог

    def scenario():
        tree = Tree(repo.path, "HEAD")
        assert sorted(tree.files()) == ["a.md", "docs/x.md"]
        assert tree.read("a.md") == b"committed\n"

        with tree.materialize() as normal:
            assert isinstance(normal, Path)
            assert (normal / "a.md").read_bytes() == b"committed\n"
            assert (normal / "docs" / "x.md").read_bytes() == b"doc\n"
        assert not normal.exists()

        seen: list[Path] = []
        with pytest.raises(RuntimeError, match="boom"):
            with tree.materialize() as failing:
                seen.append(failing)
                assert failing.is_dir()
                raise RuntimeError("boom")
        assert seen and not seen[0].exists()

    run_with_deadline(scenario)


def test_modules_without_contract_test_query_under_100ms(tmp_path):
    from scripts.atlas.schema import AdapterOutput, Edge, Node
    from scripts.atlas.store import connect, modules_without_contract_test, write_build

    def fill() -> AdapterOutput:
        nodes = [
            Node(kind="module", id=f"m{i:03d}", path=f"modules/m{i:03d}", status=None, time=None) for i in range(100)
        ]
        nodes += [Node(kind="plan", id=f"p{j}", path=f"plans/p{j}/plan.md", status=None, time=None) for j in range(9)]
        # коммит i трогает модуль i % 100, время 1000 + i
        nodes += [Node(kind="commit", id=f"{i:040x}", path=None, status=None, time=1000 + i) for i in range(2000)]
        edges = [
            Edge(kind="touches", src=f"commit:{i:040x}", dst=f"module:m{i % 100:03d}", via="path") for i in range(2000)
        ]
        # тесты: индекс % 4 == 0 — контрактный; % 4 == 1 — не контрактный (m057 — похожий каталог-двойник)
        for i in range(100):
            if i % 4 == 0:
                tpath = f"modules/m{i:03d}/tests/contract/test_c.py"
            elif i % 4 == 1:
                sub = "contract_helpers" if i == 57 else "unit"
                tpath = f"modules/m{i:03d}/tests/{sub}/test_u.py"
            else:
                continue
            nodes.append(Node(kind="test", id=f"{tpath}::test_t", path=tpath, status=None, time=None))
            edges.append(Edge(kind="tests", src=f"test:{tpath}::test_t", dst=f"module:m{i:03d}", via="path"))
        filler = [
            Edge(kind="refs", src=f"commit:{i:040x}", dst=f"plan:p{j}", via="trailer:Refs")
            for i in range(2000)
            for j in range(9)
        ]
        edges += filler[: 20000 - len(edges)]
        assert len(edges) == 20000
        return AdapterOutput(nodes=nodes, edges=edges, findings=[])

    def scenario() -> None:
        con = connect(tmp_path / "atlas.sqlite")
        build_id = write_build(con, "a" * 40, "main", "fp", fill())
        other_id = write_build(con, "b" * 40, "main", "fp", AdapterOutput(nodes=[], edges=[], findings=[]))
        assert isinstance(build_id, int)

        # граница since_ts включительная: коммит 1950 (time 2950) трогает m050, коммит 1949 (2949) не считается
        assert modules_without_contract_test(con, build_id, 2950) == EXPECTED_WITHOUT_CONTRACT
        assert modules_without_contract_test(con, other_id, 2950) == []

        modules_without_contract_test(con, build_id, 2950)  # прогрев
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            result = modules_without_contract_test(con, build_id, 2950)
            samples.append(time.perf_counter() - started)
            assert result == EXPECTED_WITHOUT_CONTRACT
        median_ms = statistics.median(samples) * 1000
        assert median_ms < 100, (
            f"медиана 5 запросов {median_ms:.1f} мс >= 100 мс (замеры, мс: {[round(s * 1000, 1) for s in samples]})"
        )

    run_with_deadline(scenario)
