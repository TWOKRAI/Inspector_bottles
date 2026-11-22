"""RN1 — слепые RED-тесты: чтение УЗЛА из read-model, хранящей листья.

Контракт по брифу ``plans/2026-10-27_system-run-state/tasks/RN1.md`` (ЛИТЕРАЛЫ, DESIGN 1-2):

* ``TelemetryReadModel.read_node(path) -> tuple[bool, Any]`` — один вызов ``snapshot(path)``;
* чистые функции ``node_from_snapshot(snap, path)`` и ``assemble_leaves(leaves)``,
  публичный экспорт из ``multiprocess_framework.modules.telemetry_readmodel_module``.

Импорт чистых функций ЛЕНИВЫЙ (внутри тестов): иначе весь файл упал бы ImportError
на сборке, и страж границы ядра (зелёный на базе) был бы неотличим от «модуля ещё нет».
Настоящий ``TelemetryReadModel`` без подмен; ожидаемые значения — литералы из брифа.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

_DEADLINE_SEC = 5.0


def _node_from_snapshot() -> Callable[[dict, str], tuple]:
    from multiprocess_framework.modules.telemetry_readmodel_module import node_from_snapshot

    return node_from_snapshot


def _assemble_leaves() -> Callable[[dict], dict]:
    from multiprocess_framework.modules.telemetry_readmodel_module import assemble_leaves

    return assemble_leaves


def _poll(m: TelemetryReadModel, values: dict[str, Any]) -> None:
    """Влить ответ опроса, запрошенный ПОСЛЕ последней записи (его не отвергает защита)."""
    m.ingest_poll_snapshot(values, requested_at_seq=m.write_seq)


class _CountingModel(TelemetryReadModel):
    """Настоящая модель; публичный ``snapshot`` лишь считает вызовы (поведение не меняется)."""

    def __init__(self) -> None:
        super().__init__()
        self.snapshot_calls: list[str] = []

    def snapshot(self, prefix: str = "") -> dict[str, Any]:
        self.snapshot_calls.append(prefix)
        return super().snapshot(prefix)


# --------------------------------------------------------------------------- #
#  узел собирается из листьев                                                  #
# --------------------------------------------------------------------------- #


def test_node_dict_assembled_from_leaves_flat() -> None:
    """Свойство: dict-узел, разложенный на листья, читается как вложенный dict.

    Убивает мутанта: ``read_node`` возвращает лист/``None`` вместо сборки узла (откат на ``get``).
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("a.n") == (True, {"x": 3})


def test_node_dict_assembled_from_leaves_two_level() -> None:
    """Свойство: двухуровневый узел собирается с сохранением вложенности.

    Убивает мутанта: плоская сборка без разбиения ключей по ``.`` / потеря вложенности.
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"p": {"q": 1}, "r": 2})
    assert m.read_node("a.n") == (True, {"p": {"q": 1}, "r": 2})


def test_leaf_read_returns_value() -> None:
    """Свойство: путь-лист даёт ``(True, значение)``.

    Убивает мутанта: ``read_node`` на листе возвращает ``{}``/сборку вместо значения.
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("a.n.x") == (True, 3)


def test_leaf_with_none_value_is_found() -> None:
    """Свойство: лист со значением ``None`` НАЙДЕН (не «нет пути»).

    Убивает мутанта: проверка ``snap.get(path) is not None`` вместо ``path in snap``.
    """
    m = TelemetryReadModel()
    m.ingest("a.n.x", None)
    assert m.read_node("a.n.x") == (True, None)


# --------------------------------------------------------------------------- #
#  лист-предок побеждает потомков                                               #
# --------------------------------------------------------------------------- #


def test_leaf_ancestor_wins_over_descendants_inside_subtree() -> None:
    """Свойство: ``a.n.p`` = 5 и потомок ``a.n.p.q`` -> узел ``{"p": 5}`` (не бросает).

    Убивает мутанта: слепая сборка без правила «лист-предок побеждает» (исключение/``{"p": {"q": 1}}``).
    """
    m = TelemetryReadModel()
    m.ingest("a.n.p", 5)
    _poll(m, {"a.n.p.q": 1})
    assert m.snapshot("a.n") == {"a.n.p": 5, "a.n.p.q": 1}  # предпосылка: смесь достижима
    assert m.read_node("a.n") == (True, {"p": 5})


def test_leaf_ancestor_read_directly_returns_leaf() -> None:
    """Свойство: чтение самого листа-предка даёт ``(True, 5)``, потомок не подменяет.

    Убивает мутанта: при ключах-потомках ``read_node`` собирает dict вместо возврата листа.
    """
    m = TelemetryReadModel()
    m.ingest("a.n.p", 5)
    _poll(m, {"a.n.p.q": 1})
    assert m.read_node("a.n.p") == (True, 5)


def test_leaf_ancestor_wins_independent_of_write_order() -> None:
    """Свойство: результат не зависит от порядка записи (сначала потомок, затем лист-предок).

    Убивает мутанта: сборка зависит от порядка обхода ключей снимка.
    """
    m = TelemetryReadModel()
    m.ingest("a.n.p.q", 1)
    _poll(m, {"a.n.p": 5})
    assert m.snapshot("a.n") == {"a.n.p.q": 1, "a.n.p": 5}  # предпосылка: смесь достижима
    assert m.read_node("a.n") == (True, {"p": 5})
    assert m.read_node("a.n.p") == (True, 5)


def test_leaf_at_node_path_wins_over_descendant_leaf() -> None:
    """Свойство: ``a.n`` = 5 и потомок ``a.n.x`` = 1 -> ``read_node("a.n") == (True, 5)``.

    Убивает мутанта: ветка «есть ключи с префиксом» проверяется раньше ветки «путь — лист».
    """
    m = TelemetryReadModel()
    m.ingest("a.n", 5)
    _poll(m, {"a.n.x": 1})
    assert m.snapshot("a.n") == {"a.n": 5, "a.n.x": 1}  # предпосылка: смесь достижима
    assert m.read_node("a.n") == (True, 5)


# --------------------------------------------------------------------------- #
#  граница — точка, не префикс строки                                           #
# --------------------------------------------------------------------------- #


def test_boundary_is_dot_not_prefix() -> None:
    """СТРАЖ ЯДРА (зелёный на базе): ``snapshot("a.n")`` не захватывает ``a.n2.*``.

    Фильтр границы живёт в ``snapshot``, не в ``read_node``; на базе ``read_node`` нет, поэтому
    страж проверяет сам снимок. Убивает мутанта ядра: срез по строковому префиксу без точки.
    """
    m = TelemetryReadModel()
    m.ingest("a.n.x", 1)
    m.ingest("a.n2.y", 2)
    assert m.snapshot("a.n") == {"a.n.x": 1}
    assert m.snapshot("a.n2") == {"a.n2.y": 2}


def test_boundary_read_node_dot_not_prefix() -> None:
    """Литерал брифа через ``read_node``: ``a.n`` -> ``{"x": 1}``, ``a.n2`` -> ``{"y": 2}``.

    Убивает мутанта: срез ключей по ``len(path)`` вместо ``len(path)+1`` (дал бы ``{".x": 1}``-подобный мусор).
    """
    m = TelemetryReadModel()
    m.ingest("a.n.x", 1)
    m.ingest("a.n2.y", 2)
    assert m.read_node("a.n") == (True, {"x": 1})
    assert m.read_node("a.n2") == (True, {"y": 2})


# --------------------------------------------------------------------------- #
#  отсутствие / пустой путь                                                     #
# --------------------------------------------------------------------------- #


def test_missing_path_is_not_found() -> None:
    """Свойство: отсутствующий ``a.zz`` при живых соседях -> ``(False, None)``.

    Убивает мутанта: ``read_node`` возвращает ``(True, {})`` для пустого снимка.
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("a.zz") == (False, None)


def test_empty_path_is_not_found() -> None:
    """Свойство: пустой путь — не «весь снимок»: ``read_node("") == (False, None)``.

    Убивает мутанта: пустой путь отдаёт весь собранный снимок.
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("") == (False, None)


def test_empty_path_cut_before_snapshot() -> None:
    """Свойство: пустой путь отсекается ДО ``snapshot`` (полная копия не берётся).

    Убивает мутанта: убрать ``if not path`` в методе (тогда ``snapshot("")`` вызван — ``calls == [""]``).
    """
    m = _CountingModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("") == (False, None)
    assert m.snapshot_calls == []


def test_read_node_makes_exactly_one_snapshot_call() -> None:
    """Свойство (DESIGN 2): ``read_node`` = ровно один ``snapshot(path)``.

    Убивает мутанта: второй проход (``snapshot("")`` или повторный ``snapshot(path)``) в методе.
    """
    m = _CountingModel()
    m.ingest("a.n", {"x": 3})
    assert m.read_node("a.n") == (True, {"x": 3})
    assert m.snapshot_calls == ["a.n"]


# --------------------------------------------------------------------------- #
#  известные расхождения с живым state.get (P3r, п.8)                           #
# --------------------------------------------------------------------------- #


def test_known_divergences_from_live_state_get_literals() -> None:
    """Свойство: расхождения зафиксированы литералами (чтобы их не «починили» случайно).

    (а) пустой dict-узел исчезает; (б) пустой вложенный dict теряется; (в) ключ с точкой раскладывается.
    Убивает мутанта: «восстановление» пустых узлов / экранирование точки в ``read_node``.
    """
    m_empty = TelemetryReadModel()
    m_empty.ingest("a.n", {})
    assert m_empty.read_node("a.n") == (False, None)

    m_nested = TelemetryReadModel()
    m_nested.ingest("a.n", {"x": 3, "e": {}})
    assert m_nested.read_node("a.n") == (True, {"x": 3})

    m_dot = TelemetryReadModel()
    m_dot.ingest("a.n", {"k.dot": 1})
    assert m_dot.read_node("a.n") == (True, {"k": {"dot": 1}})


# --------------------------------------------------------------------------- #
#  чистые функции (прямой тест)                                                 #
# --------------------------------------------------------------------------- #


def test_node_from_snapshot_dot_boundary_on_dirty_snapshot() -> None:
    """Свойство: чистая функция сама режет границу-точку на ГРЯЗНОМ снимке.

    Убивает мутанта: убрать фильтр ``startswith(path + ".")`` (настоящий ``snapshot`` уже чистый,
    поэтому через модель мутант не виден — только прямой вызов).
    """
    assert _node_from_snapshot()({"a.n.x": 1, "a.n2.y": 2}, "a.n") == (True, {"x": 1})


def test_node_from_snapshot_empty_path_not_found() -> None:
    """Свойство: пустой путь -> ``(False, None)`` и в чистой функции.

    Убивает мутанта: пустой путь трактуется как корень (``"" + "."`` префикс).
    """
    assert _node_from_snapshot()({"a.n.x": 1}, "") == (False, None)


def test_assemble_leaves_ancestor_wins() -> None:
    """Свойство: ``{("p",): 5, ("p","q"): 1}`` -> ``{"p": 5}``.

    Убивает мутанта: убрать «лист-предок побеждает» в ``assemble_leaves``.
    """
    assert _assemble_leaves()({("p",): 5, ("p", "q"): 1}) == {"p": 5}


def test_assemble_leaves_ancestor_wins_reversed_insertion_order() -> None:
    """Свойство: тот же результат при обратном порядке вставки ключей (порядконезависимость).

    Убивает мутанта: победитель определяется порядком обхода dict.
    """
    assert _assemble_leaves()({("p", "q"): 1, ("p",): 5}) == {"p": 5}


def test_assemble_leaves_nested_and_sibling() -> None:
    """Свойство: ``{("p","q"): 1, ("r",): 2}`` -> ``{"p": {"q": 1}, "r": 2}``.

    Убивает мутанта: плоская сборка без вложенности.
    """
    assert _assemble_leaves()({("p", "q"): 1, ("r",): 2}) == {"p": {"q": 1}, "r": 2}


# --------------------------------------------------------------------------- #
#  гонка под ОДНИМ внешним локом (контрактный тест)                             #
# --------------------------------------------------------------------------- #

_RACE_SEC = 0.5


def _race_value(i: int) -> dict[str, Any]:
    """Форма узла с инвариантом ``x == y`` и меняющимся числом листьев (0..4 лишних)."""
    node: dict[str, Any] = {"x": i, "y": i}
    for j in range(i % 5):
        node[f"k{j}"] = j
    return node


def test_race_under_external_lock() -> None:
    """Свойство: писатель и читатель под ОДНИМ внешним ``threading.Lock`` — читатель видит только
    целые опубликованные узлы (``x == y``, узел найден) и не бросает.

    Контрактный тест: красный лишь по отсутствию метода. Ловит только то, что вызов под внешним
    локом не виснет и не бросает (например, нереентрантный лок внутри модуля). Два чтения снимка
    он НЕ ловит (это ``test_read_node_makes_exactly_one_snapshot_call``); реальную гонку несёт
    контроль ``backend_ctl/tests/test_p3r_node_read.py::test_red7_race_read_node_never_torn_nor_raises``.
    """
    m = TelemetryReadModel()
    lock = threading.Lock()
    m.ingest("a.n", _race_value(0))  # узел существует до старта потоков
    problems: list[str] = []
    stop = threading.Event()
    reads = [0]

    def writer() -> None:
        try:
            for i in range(1, 6000):
                if stop.is_set():
                    break
                with lock:
                    m.ingest("a.n", _race_value(i))
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"писатель упал: {exc!r}")

    def reader() -> None:
        try:
            deadline = time.monotonic() + _RACE_SEC
            while time.monotonic() < deadline and not problems:
                with lock:
                    found, value = m.read_node("a.n")
                reads[0] += 1
                if found is not True:
                    problems.append(f"узел пропал посреди записи: {(found, value)!r}")
                elif not isinstance(value, dict) or "x" not in value or value.get("x") != value.get("y"):
                    problems.append(f"рваное чтение: {value!r}")
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"читатель упал: {exc!r}")

    w = threading.Thread(target=writer, daemon=True, name="rn1-race-writer")
    r = threading.Thread(target=reader, daemon=True, name="rn1-race-reader")
    w.start()
    r.start()
    r.join(_RACE_SEC + _DEADLINE_SEC)
    stop.set()
    w.join(_DEADLINE_SEC)
    if r.is_alive() or w.is_alive():
        problems.append("зависание потока гонки")
    if reads[0] == 0:
        problems.append("читатель не сделал ни одного чтения")
    assert problems == []


@pytest.mark.parametrize("path", ["a.n", "a.n.x", "a.zz", ""])
def test_read_node_does_not_mutate_model(path: str) -> None:
    """Свойство: чтение не меняет модель (``write_seq`` и снимок прежние).

    Убивает мутанта: ``read_node`` пишет в модель (кэширует собранный узел).
    """
    m = TelemetryReadModel()
    m.ingest("a.n", {"x": 3})
    before_seq = m.write_seq
    m.read_node(path)
    assert m.write_seq == before_seq
    assert m.snapshot("") == {"a.n.x": 3}
