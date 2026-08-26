# -*- coding: utf-8 -*-
"""Ф5 (Task 5.2/5.3), итерация 2 — обход порта обязан быть СЛЫШЕН, и боевая
сборка проверяется НАСТОЯЩИМИ объектами, не двойниками.

Найдено владельцем (разбор спора, 2026-08-26): в первой итерации
``attach_observation_port`` был опциональным и НИЧЕМ не сторожился — ни
счётчиком, ни голосом. «Единственный писатель чисел» было свойством
ПРОВОДКИ («там, где не забыли подключить»), а не построения. Кроме того,
единственная проверка боевой сборки шла через ``MockProcessServices``/
``_MockObservationPort`` (``process_module/plugins/testing.py``) — тонкий
дубль, форвардящий напрямую в ``stats_manager``; переименуй кто-нибудь
``attach_observation_port``, и все тесты, построенные на двойнике, остались
бы зелёными (сам двойник ничего не зовёт под этим именем).

Этот файл закрывает обе находки:

1. :func:`test_create_all_wires_stats_to_the_observation_manager_end_to_end` —
   поднимает ``ProcessManagers.create_all()`` с НАСТОЯЩИМИ ``StatsManager``/
   ``ObservationManager`` (не двойниками) и проверяет ПОВЕДЕНИЕ: число,
   опубликованное через ``bundle.observation``, обязано долететь до
   ``bundle.stats``. Переименование ``attach_observation_port`` уронило бы
   этот тест ДВАЖДЫ — сначала ``create_all()`` самим ``AttributeError``
   (проводка), затем (если бы проводку залатали иначе) отсутствием доставки.
2. Парный тест счётчика обходов (владелец, п.1 разбора): в боевой сборке
   ``observation_bypasses`` обязан быть пустым словарём (:func:`test_...zero`);
   у менеджера, построенного ВНЕ сборки (standalone), — обязан считать и
   именовать КАЖДЫЙ обход (:func:`test_...counts_every_bypass`).
"""

from __future__ import annotations

from typing import Any

from ...base_manager import ObservableMixin
from ...statistics_module import StatsManager
from ..managers.process_managers import ProcessManagers


# --------------------------------------------------------------------------- #
# Минимальный, но НАСТОЯЩИЙ процесс — только то, что реально читают
# _create_*/register_all (see process_managers.py). Ни одного менеджера не
# подменяем: create_all() строит их САМ, реальными классами.
# --------------------------------------------------------------------------- #


class _BootHandler:
    def get_managers_config(self) -> dict:
        return {}


class _BootProcess(ObservableMixin):
    """Процесс в виде, достаточном для ``ProcessManagers.create_all()``.

    Не двойник менеджеров (их здесь нет вовсе) — двойник ОКРУЖЕНИЯ, которое
    ``_create_*``-методы читают до того, как менеджеры появились
    (``name``/``config_handler``/``config_manager``/``queue_registry``,
    прочитано по коду ``process_managers.py``).
    """

    def __init__(self, name: str) -> None:
        ObservableMixin.__init__(self)
        self.name = name
        self.config_handler = _BootHandler()
        self.config_manager = None
        self.queue_registry = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return default


def _shutdown_bundle(bundle: Any) -> None:
    for manager in (
        bundle.worker,
        bundle.logger,
        bundle.router,
        bundle.command,
        bundle.stats,
        bundle.console,
        bundle.error,
        bundle.observation,
    ):
        shutdown = getattr(manager, "shutdown", None)
        if callable(shutdown):
            shutdown()


# --------------------------------------------------------------------------- #
# 1. Боевая проводка — поведением, настоящими объектами.
# --------------------------------------------------------------------------- #


def test_create_all_wires_stats_to_the_observation_manager_end_to_end() -> None:
    """``ProcessManagers.create_all()`` реальными объектами: число доезжает.

    ``bundle.observation`` — настоящий ``ObservationManager`` (не сентинел, не
    двойник). Публикуем через НЕГО (ровно так, как это делал бы
    ``PluginContext``/дорога 1), и проверяем, что число появилось у
    ``bundle.stats`` (ровно тот менеджер, что резолвируется слотом
    ``"stats"`` для 57 боевых вызывающих дороги 3). Если бы ``create_all()``
    не звал ``attach_observation_port`` (или звал не то), либо это упало бы
    здесь же (менеджер не подключён — метод не существует/не тот объект),
    либо запись не долетела бы до ``get_metric`` — оба исхода тест ловит.
    """
    process = _BootProcess("boot_wiring")
    bundle = ProcessManagers(process).create_all()
    try:
        assert bundle.stats.observation_bypasses == {}, (
            f"боевая сборка обязана дать НОЛЬ обходов до единой записи: {bundle.stats.observation_bypasses!r}"
        )

        for _ in range(3):
            bundle.observation.record_metric("boot.wiring.ok", 1)
        bundle.stats.flush()

        metric = bundle.stats.get_metric("boot.wiring.ok")
        assert metric is not None, "число, опубликованное через bundle.observation, не долетело до bundle.stats вовсе"
        assert metric["count"] == 3.0, f"ожидалось 3.0, получено {metric!r}"

        assert bundle.stats.observation_bypasses == {}, (
            f"боевая сборка: обходов быть не должно и ПОСЛЕ записи, а получено {bundle.stats.observation_bypasses!r}"
        )
    finally:
        _shutdown_bundle(bundle)


# --------------------------------------------------------------------------- #
# 2. Обход порта — считается и говорится (владелец, разбор спора, п.1).
# --------------------------------------------------------------------------- #


def _standalone_manager() -> StatsManager:
    mgr = StatsManager(
        manager_name="standalone_no_attach",
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize()
    return mgr


def test_boot_assembly_has_zero_observation_bypasses() -> None:
    """Половина пары: боевая сборка — ноль обходов, буквально повтор основной
    проверки выше отдельным, узким тестом (для читателя, который ищет ИМЕННО
    этот критерий, а не весь сценарий проводки)."""
    process = _BootProcess("boot_zero_bypasses")
    bundle = ProcessManagers(process).create_all()
    try:
        bundle.stats.record_metric("any.metric", 1)
        bundle.stats.gauge("any.gauge", 1)
        bundle.stats.flush()
        assert bundle.stats.observation_bypasses == {}, (
            f"боевая сборка: writes через слот 'stats' не обязаны обходить порт, а обошли: "
            f"{bundle.stats.observation_bypasses!r}"
        )
    finally:
        _shutdown_bundle(bundle)


def test_standalone_manager_without_attach_counts_and_names_every_bypass() -> None:
    """Другая половина пары: менеджер вне сборки — обход считается ПО МЕТОДУ,
    накопительно (не сбрасывается на первом же голосе), и голос — один раз.
    """
    mgr = _standalone_manager()
    try:
        assert mgr.observation_bypasses == {}, "до единой записи обходов нет вовсе"

        mgr.record_metric("x", 1)
        mgr.record_metric("x", 1)
        mgr.gauge("y", 5)
        mgr.record_timing("z", 0.01)
        mgr.histogram("w", 2.0)

        bypasses = mgr.observation_bypasses
        assert bypasses == {"record_metric": 2, "gauge": 1, "record_timing": 1, "histogram": 1}, (
            f"счётчик обходов не совпал с фактическими вызовами: {bypasses!r}"
        )

        # Данные при этом реально записались (фолбэк рабочий, а не просто
        # считающий) — обход не значит потерю.
        assert mgr.get_metric("x") is not None and mgr.get_metric("x")["count"] == 2.0
    finally:
        mgr.shutdown()


def test_a_manager_with_attach_never_bypasses_regardless_of_a_neighbor_without_it() -> None:
    """Обход — свойство КОНКРЕТНОГО менеджера, не процесса целиком: подключение
    одного соседа не обнуляет и не заражает счётчик другого, ни в сборке, ни
    вручную (регрессия на "поделили состояние по ошибке").
    """
    from ...statistics_module.observation.observation_manager import ObservationManager

    port = ObservationManager(manager_name="port_for_pairing")
    assert port.initialize()
    attached = StatsManager(
        manager_name="attached",
        config={"enable_logging": False, "channels": {"file_stats": {"enabled": False}}},
    )
    assert attached.initialize()
    detached = _standalone_manager()
    try:
        assert attached.attach_observation_port(port) is True

        attached.record_metric("a", 1)
        detached.record_metric("b", 1)

        assert attached.observation_bypasses == {}, "подключённый менеджер не должен считать обходов вовсе"
        assert detached.observation_bypasses == {"record_metric": 1}, "отключённый — обязан считать СВОЙ обход"
    finally:
        attached.shutdown()
        detached.shutdown()
        port.shutdown()
