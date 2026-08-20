# -*- coding: utf-8 -*-
"""К4 «порта наблюдений»: засев не оставляет плоского листа-призрака.

**Тест переформулирован координатором и перенесён сюда — это важно знать, чтобы
не считать его дубликатом.** Независимый тестер написал К4 как
``test_flat_none_ghost_does_not_survive_a_full_publish_cycle_forever``
(``multiprocess_framework/modules/process_module/tests/
test_observation_port_readmodel_ghost_acceptance.py``): он клал плоский ``None``
в ``TreeStore`` РУКОЙ и требовал, чтобы этот лист СНЯЛ цикл публикации.

Та формулировка пришпиливала механизм, которого нет и не задумано. Публикатор
мержит ровно своё поддерево ``processes.<P>.state.plugins.<писатель>.*`` — он не
видит сиблинга ``state.frame_count`` и не имеет повода его трогать. Значит тест
остался бы красным при любом качестве исправления. Тестер этого знать не мог:
``bootstrap.py`` был у него в списке запрещённых файлов, и он честно раскрыл в
шапке, что имитирует засев прямой записью.

Настоящий источник призрака — ЗАСЕВ начального дерева
(:func:`build_initial_state` → ``_build_process_entry``). До Ф1 плоский
``frame_count: None`` был безвреден: живой тик перетирал его числом. После Ф1
лист уехал в поддерево писателя, перетирать плоский адрес стало НЕЧЕМУ, и он
остался бы в дереве вечным ``None`` РЯДОМ с настоящим числом. Диагноз «пути
нет» превратился бы в «путь есть, но мёртв», а это разные диагнозы.

Поэтому тест: (а) гоняет НАСТОЯЩИЙ засев и утверждает, что плоского листа в нём
нет; (б) в паре — позитивный якорь: настоящий лист под писателем появляется и
равен литералу. Место — прототипные тесты, потому что засев живёт в прототипе,
а фреймворку импортировать прототип запрещено (слои).
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.observability_declarations import forget_declarations
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_prototype.backend.state.bootstrap import build_initial_state

_TOPOLOGY = {
    "name": "ghost-seed",
    "processes": [
        {"process_name": "camera_0", "plugins": [{"plugin_name": "capture"}]},
        {"process_name": "consumer_0", "plugins": []},
    ],
    "wires": [],
}


def _seeded_state(process: str) -> dict:
    """Секция ``state`` процесса из НАСТОЯЩЕГО засева."""
    tree = build_initial_state(_TOPOLOGY, {})
    return tree["processes"][process]["state"]


# --------------------------------------------------------------------------- #
# Харнесс тика: настоящий heartbeat поверх настоящего TreeStore.
# --------------------------------------------------------------------------- #


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class _StopAfter:
    def __init__(self, clock: _FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout: float | None = None) -> None:
        self._clock.advance(timeout)


class _NeverPaused:
    def is_set(self) -> bool:
        return False


class _TreeBackedProxy:
    def __init__(self, tree: TreeStore) -> None:
        self.tree = tree

    def merge(self, path: str, data: dict) -> None:
        self.tree.merge(path, data)

    def set(self, path: str, value: Any) -> None:
        self.tree.set(path, value)


class _WriterServices:
    def __init__(self, name: str, tree: TreeStore) -> None:
        self.name = name
        self.worker_manager = None
        self.router_manager = None
        self.command_manager = None
        self.memory_manager = None
        self._config: dict = {}
        self._state_proxy = _TreeBackedProxy(tree)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...
    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...

    def send_message(self, target: str, message: dict) -> bool:
        return True


@pytest.fixture()
def declared_frame_count():
    """Объявление метрики живёт в процесс-глобальном каталоге — снимаем за собой."""
    yield
    forget_declarations("metric", names={"frame_count"})


class TestSeedLeavesNoFlatGhost:
    def test_seed_has_no_flat_frame_count_leaf(self) -> None:
        """Плоского ``state.frame_count`` в засеве больше нет.

        Литерал имени, не производная от кода: тест обязан покраснеть, если имя
        вернут в засев под любым значением — включая ``0``, которое выглядит
        безобиднее ``None``, а врёт сильнее (``None`` рисуется «—»,
        ноль — уверенным измерением).
        """
        state = _seeded_state("camera_0")
        assert "frame_count" not in state, (
            f"засев вернул плоский лист frame_count — после Ф1 его некому перетереть; "
            f"фактическая секция state: {state!r}"
        )

    def test_seed_still_carries_the_framework_keys(self) -> None:
        """Пара-контроль: засев не опустел — фреймворковые ключи на месте.

        Без него предыдущий тест зелен и на пустом словаре, то есть согласился бы
        с ответом «засева нет вовсе». Литералы, а не ``len``.
        """
        state = _seeded_state("camera_0")
        assert state["status"] == "stopped"
        assert state["pid"] is None
        assert state["error"] is None
        # ``fps`` — агрегат ФРЕЙМВОРКА (частота цикла воркера), он не переезжал и
        # засев по-прежнему перетирается живым тиком. Остаётся ``None``, а не
        # ``0.0``: ноль обязан означать измеренный ноль (блокер ревью 2026-08-18).
        assert state["fps"] is None

    def test_seed_is_the_same_for_a_process_without_plugins(self) -> None:
        """Засев одинаков для всех процессов — призрак не прячется у безплагинного."""
        assert _seeded_state("consumer_0") == _seeded_state("camera_0")

    def test_real_tick_puts_the_leaf_under_its_writer_on_top_of_the_seed(self, declared_frame_count) -> None:
        """Позитивный якорь в паре с негативом: настоящий лист есть и равен литералу.

        Дерево наполняется НАСТОЯЩИМ засевом, поверх идёт НАСТОЯЩИЙ тик heartbeat
        с публикацией через ``PluginContext``. Проверяются оба факта разом: под
        писателем лежит ``7``, а плоского сиблинга рядом не возникло. Порознь эти
        два утверждения слепы — «плоского нет» верно и на пустом дереве.
        """
        tree = TreeStore()
        tree.merge("", build_initial_state(_TOPOLOGY, {}))

        clock = _FakeClock()
        services = _WriterServices("camera_0", tree)
        hb = ProcessHeartbeat(services, clock=clock)

        ctx = PluginContext(services=services, plugin_name="capture")
        ctx.declare_metric("frame_count")
        ctx.publish_metric("frame_count", 7)
        hb._loop(_StopAfter(clock, t_end=clock.t + 0.01), _NeverPaused())

        subtree = tree.get_subtree("processes.camera_0.state")
        assert subtree["plugins"]["capture"]["frame_count"] == 7, (
            f"лист под писателем не появился/не равен литералу 7; поддерево: {subtree!r}"
        )
        assert "frame_count" not in subtree, f"рядом с настоящим листом возник плоский призрак; поддерево: {subtree!r}"
