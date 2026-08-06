# -*- coding: utf-8 -*-
"""Ф0.3 — счётчики потерь доезжают наружу, а не остаются внутри менеджера.

План: plans/observability-unified-routing.md, задача 0.3 (резидуал R4).

Зачем отдельный файл. Счётчик, который считается правильно, но которого никто
не может спросить, — это не наблюдаемость. На этом проекте класс уже стрелял
дважды: правило читало несуществующий ключ ``drops_count`` при реальном
``drops``, и 23% ошибок отправки были невидимы при зелёных тестах на моке.
Поэтому здесь проверяется не арифметика (она в
``channel_routing_module/tests/test_batch_buffer_limits.py``), а маршрут:

    BatchBuffer.stats → LoggerCore.get_stats() → observability_counters()

— то есть ровно то, что отдаёт наружу команда ``introspect.observability``.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import LOSS_COUNTER_KEYS
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    PLANE_COUNTER_KEYS,
    observability_counters,
)


@pytest.fixture(autouse=True)
def _isolate_floors() -> Iterator[None]:
    reset_error_floors()
    yield
    reset_error_floors()


def _config(tmp_path: Path) -> LoggerManagerConfig:
    """Логгер с одним файловым приёмником (Ф7.4: запись синхронна, пачки нет)."""
    return LoggerManagerConfig(
        app_name="counters_unit",
        log_directory=str(tmp_path),
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            )
        },
        default_level="DEBUG",
        scopes={scope: LoggerScopeSchema(channels=["system_file"]) for scope in ("SYSTEM", "BUSINESS", "DEBUG")},
    )


@contextmanager
def _logger(tmp_path: Path, **_ignored: object) -> Iterator[LoggerManager]:
    manager = LoggerManager(manager_name="CountersLogger", config=_config(tmp_path))
    try:
        yield manager
    finally:
        manager.shutdown()


def _overflow(manager: LoggerManager, count: int) -> None:
    for i in range(count):
        manager.info(f"переполняем буфер {i}", module="unit")


# =============================================================================
# Потери на стыке «менеджер → канал»
# =============================================================================
#
# Ф7.4: тесты про ``batch_stats`` (dropped_by_channel, pending, max_pending,
# overflow_policy) сняты вместе с батчингом — они сторожили счётчики буфера,
# которого больше нет. Гарантии, ради которых они писались, живут дальше в
# ``LOSS_COUNTER_KEYS``: «ни одна запись не числится доставленной, если
# приёмника нет» и «потеря видна снаружи под своим именем».
#
# Что при этом ИСЧЕЗЛО и названо честно: залипший сток больше не поглощается
# буфером — он блокирует поток-эмитент. Замер прежнего сценария («сток занят,
# 50 записей») теперь просто виснет. Политика для этого случая — предмет Ф7.2
# (async → sync → drop → flush), а не батчинга.


def test_dead_sink_does_not_report_a_healthy_plane(tmp_path: Path) -> None:
    """Приёмников не осталось — плоскость обязана сообщить о потере, а не молчать.

    Дефект, ради которого тест написан: приёмники сняты, 51 запись числится
    доставленной, ноль байт на диске, все счётчики молчат — команда рапортовала
    здоровую плоскость при стопроцентной потере.

    **Переклассифицировано в 2.8** (прежнее имя —
    ``test_dead_sink_is_reported_as_flush_failed_not_as_delivered``). Снятый
    ОПЕРАТОРОМ приёмник теперь исключается из маршрута, поэтому записи до
    буфера не доходят и `flush_failed` вырасти не может; вместо него растёт
    `records_without_channels` — приёмника не осталось ни одного. Проверяемое
    свойство то же самое и проверяется прямее: **ни одна запись не числится
    доставленной, и потеря видна счётчиком из ``LOSS_COUNTER_KEYS``.**
    """
    with _logger(tmp_path, max_pending=10_000) as manager:
        manager.set_sink_enabled("system_file", False)
        _overflow(manager, 50)
        manager.flush()

        stats = manager.get_stats()
        assert stats["records_without_channels"] == 50
        assert stats["unresolved_channel_records"] == 0


def test_counters_facade_survives_a_broken_manager() -> None:
    """Сломанный get_stats() не должен ронять диагностическую команду."""

    class _Broken:
        def get_stats(self):
            raise RuntimeError("boom")

    counters = observability_counters(logger=_Broken())
    assert "error" in counters["logger"], "отказ диагностируемого проглочен"
    assert "boom" in counters["logger"]["error"]

    # А вот отсутствие менеджера — не отказ: секции просто нет.
    assert observability_counters(logger=None, error=None, stats=None) == {}


# =============================================================================
# Пол ошибок (Ф0.9) — тот же класс невидимости
# =============================================================================


def test_errors_to_floor_reaches_get_stats(tmp_path: Path) -> None:
    """«Ошибка не дошла ни до одного канала» — спрашиваемый снаружи факт.

    До Ф0.3 счётчик жил только в ``self.stats`` и в get_stats() не попадал:
    сломанный маршрут ошибок нельзя было увидеть, не читая файлы на диске.
    """
    with _logger(tmp_path, max_pending=10_000) as manager:
        assert manager.get_stats()["errors_to_floor"] == 0
        assert manager.get_stats()["error_floor"] is None, "пол не должен создаваться заранее"

        manager.set_sink_enabled("system_file", False)  # приёмников не осталось
        manager.error("некуда писать", module="unit")

        stats = manager.get_stats()
        assert stats["errors_to_floor"] == 1
        assert stats["error_floor"]["written"] == 1
        assert stats["error_floor"]["path"].endswith("errors_floor.jsonl")


def test_error_floor_stays_silent_while_channel_is_alive(tmp_path: Path) -> None:
    """Обратная половина: живой канал → пол не трогается, счётчик ноль."""
    with _logger(tmp_path, max_pending=10_000) as manager:
        manager.error("канал жив", module="unit")

        stats = manager.get_stats()
        assert stats["errors_to_floor"] == 0
        assert stats["error_floor"] is None


# =============================================================================
# Регресс-страж имён
# =============================================================================


# Ф7.4: пин имён ключей буфера снят вместе с батчингом — ключ ``buffer`` у
# плоскости логов больше не публикуется (буфера нет). У плоскости статистики он
# остался (AggregationWindow) и пинуется её собственными тестами.


@pytest.mark.parametrize(
    "make_manager",
    [
        pytest.param(
            lambda: LoggerManager(manager_name="KeysAudit", config=LoggerManagerConfig(app_name="audit")),
            id="logger",
        ),
        pytest.param(lambda: ErrorManager(manager_name="KeysAuditErr", config={"app_name": "audit_err"}), id="error"),
        pytest.param(lambda: StatsManager(manager_name="KeysAuditStats", config={"enable_logging": False}), id="stats"),
        pytest.param(lambda: RouterManager(manager_name="KeysAuditRouter"), id="router"),
    ],
)
def test_every_manager_counter_is_published_or_declared_unpublished(make_manager) -> None:
    """Новый счётчик обязан быть виден наружу — или явно объявлен невидимым.

    Комментарий у ``PLANE_COUNTER_KEYS`` называл этот файл своим стражем,
    «сверяющим список с живым словарём». Такого сравнения тут не было ни одного:
    проверялись отдельные счётчики поимённо, а сам список не проверялся ничем.
    Ложное обещание стража хуже его отсутствия — на него ссылаются, когда решают,
    нужен ли новый тест. Найдено слом-инъекцией C6 (снять публикацию нового
    счётчика → не покраснело ничего).

    Направление проверки выбрано «изнутри наружу» намеренно: забывают именно
    его — счётчик заводят в ``self.stats``, а в реестр публикации не вносят, и
    он существует, будучи невидимым (ровно то, что стреляло в Ф0.3 и Ф0.4).

    P5: проверяются ВСЕ наследники базы, а не только логгер. Счётчики потерь
    подняты в ``ChannelRoutingManager``, то есть теперь их имеет и статистика, и
    транспортный ``RouterManager`` — и «видно наружу» обязано быть правдой у
    каждого, иначе инвариант снова окажется верным для двух плоскостей из трёх.
    """
    manager = make_manager()
    try:
        # Не счётчики потерь — публиковать их наружу незачем. Список явный:
        # молчаливое исключение по маске («всё, что не *_records») со временем
        # проглотило бы настоящий счётчик.
        not_published = {
            "module_files_created",  # сколько файлов создано на старте, не потеря
            # Описание менеджера, а не его состояние: спрашивается из конфига.
            "app_name",
            "channels_count",
            "module_channels_count",
            "include_stacktrace",
            # Едет наружу целиком отдельным ключом ``buffer`` (см. _plane_counters).
            "buffer",
            # Описание менеджера базы CRM (статистика, роутер): состав каналов и
            # идентичность, а не состояние наблюдаемости. Спрашивается другими
            # ручками — introspect.status / introspect.router_stats / capabilities.
            "manager_name",
            "process_name",
            "is_initialized",
            "channels",
            "channel_count",
            "channel_info",
            "adapters",
            "router",
            # Список имён метрик статистики: содержимое плоскости, а не её
            # здоровье; едет наружу telemetry-ручками.
            "metric_names",
        }
        # Проверяются ОБА словаря: ``self.stats`` (счётчики) и то, что менеджер
        # добавляет прямо в ``get_stats()`` мимо него.
        #
        # Вторая половина добавлена по находке LIVE-прогона Ф1: ``level_routes``
        # у ErrorManager живёт только в ``get_stats()``, в ``self.stats`` его
        # нет — и страж, смотревший лишь в ``self.stats``, не видел его в
        # принципе. Карта не публиковалась наружу, хотя план называл её
        # «публичным level_routes» и на неё опирался резидуал P2.
        surface = set(manager.stats) | set(manager.get_stats())
        missing = sorted(surface - set(PLANE_COUNTER_KEYS) - not_published)
        assert not missing, (
            f"поля есть в менеджере, но не публикуются наружу: {missing}. "
            f"Добавь в PLANE_COUNTER_KEYS либо в not_published с причиной"
        )
    finally:
        manager.shutdown()


def test_loss_counter_registry_matches_the_base() -> None:
    """Реестр публикации обязан покрывать ВЕСЬ перечень классов потери из базы.

    Два списка в двух модулях — классическая точка расхождения; направление
    проверки то же, что выше, но здесь сверяется объявление, а не живой словарь:
    класс потери, заведённый в базе и забытый в реестре, был бы невидим у всех
    трёх плоскостей сразу.
    """
    missing = sorted(set(LOSS_COUNTER_KEYS) - set(PLANE_COUNTER_KEYS))
    assert not missing, f"классы потери из базы не публикуются наружу: {missing}"


def test_records_without_channels_reaches_the_outside(tmp_path: Path) -> None:
    """Ф4.2: потеря «приёмников не было вовсе» доезжает до introspect.observability.

    Проверяется маршрут целиком, а не ключ в ``get_stats``: счётчик, видимый
    только внутри менеджера, спросить у живого процесса нельзя.
    """
    manager = LoggerManager(
        manager_name="NoChannels",
        config=LoggerManagerConfig(
            app_name="no_channels",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={},  # ни одного приёмника
            default_level="DEBUG",
            scopes={"SYSTEM": LoggerScopeSchema(channels=[])},
        ),
    )
    manager.initialize()
    try:
        manager.info("этой записи некуда идти", module="audit")

        published = observability_counters(logger=manager)["logger"]
        assert published["records_without_channels"] >= 1, (
            f"потеря без приёмников не доехала наружу: опубликовано {published.get('records_without_channels')!r}"
        )
    finally:
        manager.shutdown()
