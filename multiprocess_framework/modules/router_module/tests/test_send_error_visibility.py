# -*- coding: utf-8 -*-
"""
Задача 6.7 (находка живого прогона Н-1, 2026-08-03): RouterManager терял
~0.37% data-сообщений молча — 45 ошибок за 7.7 минут на трёх процессах, ни
одной строки в логах и ни одной записи в плоскости ошибок. Ветка «маршрут не
нашёлся» только увеличивала общий счётчик ``errors`` и возвращала error-dict.

Тесты фиксируют КОНТРАКТ (акс. критерии задачи 6.7), а не согласие с
реализацией:
    1. Ошибка отправки видна в плоскости логов — реальный LoggerManager,
       зарегистрированный как менеджер ``logger``, пишет строку в файл.
    2. Ошибка видна в плоскости ошибок — реальный ErrorManager
       (``track_error``), зарегистрированный как менеджер ``error``.
    3. В тексте записи читается ПРИЧИНА без чтения исходников (имя команды
       присутствует в тексте).
    4. Общий счётчик ``errors`` продолжает расти (совместимость), результат —
       dict со ``status == "error"``.
    5. Три пер-причинных счётчика (``errors_no_route``,
       ``errors_delivery_failed``, ``errors_exception``) различают три
       независимых сценария и не путают их друг с другом.
    6. Сумма приростов трёх пер-причинных счётчиков равна приросту общего
       ``errors``.
    7. Троттлинг: 200 одинаковых ошибок → число ERROR-строк в логе НЕ равно
       200 (единицы), счётчик при этом учитывает все 200.
    8. Троттлинг — по причине: шторм одной причины не глушит первую ошибку
       другой причины.

ЗАПРЕЩЕНО (условие независимого тестировщика): читать исходный текст
``core/router_manager.py`` и текущий git diff. Харнесс собран по образцу
``test_router_manager.py`` / ``test_door_counters.py`` (RouterManager,
QueueChannel, фейковые queue_registry) и README ``logger_module`` /
``error_module`` (конструкторы LoggerManager/ErrorManager, конфиг вида
{"channels": {...}, "scopes": {...}}). Привязка реальных logger/error к
RouterManager — через ``register_manager()``, публичный метод
``IObservableMixin`` (контракт ``base_manager``, не внутренность роутера).
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue


from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.logger_module import LoggerManager
from multiprocess_framework.modules.error_module import ErrorManager


# ---------------------------------------------------------------------------
# Вспомогательные инструменты
# ---------------------------------------------------------------------------


def _make_logger(tmp_path: Path, name: str = "log") -> tuple:
    """Реальный LoggerManager: SYSTEM-скоуп (WARNING+, куда попадает ERROR
    через self._log_error) пишет в файл на диске."""
    log_path = tmp_path / f"{name}.log"
    lm = LoggerManager(
        manager_name=f"lm_{name}",
        config={
            "app_name": "send_error_visibility",
            "default_level": "DEBUG",
            "channels": {
                "file": {"type": "file", "enabled": True, "file_path": str(log_path)},
            },
            "scopes": {
                "SYSTEM": {"channels": ["file"]},
            },
        },
    )
    lm.initialize()
    return lm, log_path


def _make_error_manager(tmp_path: Path, name: str = "err") -> tuple:
    """Реальный ErrorManager: ERROR-уровень маршрутизируется в errors_file
    (см. README error_module — _level_to_channel['ERROR'] = 'errors_file')."""
    err_path = tmp_path / f"{name}_errors.log"
    em = ErrorManager(
        manager_name=f"em_{name}",
        config={
            "app_name": "send_error_visibility",
            "default_level": "WARNING",
            "channels": {
                "errors_file": {"type": "file", "enabled": True, "file_path": str(err_path)},
            },
        },
    )
    em.initialize()
    return em, err_path


def _router_with_observability(tmp_path: Path, queue_registry=None, name: str = "r") -> tuple:
    """RouterManager с реальными logger/error, привязанными через публичный
    register_manager() (IObservableMixin).

    Возвращает (router, logger_mgr, log_path, error_mgr, err_path).
    """
    logger_mgr, log_path = _make_logger(tmp_path, name)
    error_mgr, err_path = _make_error_manager(tmp_path, name)
    router = RouterManager(manager_name=f"router_{name}", queue_registry=queue_registry)
    router.register_manager("logger", logger_mgr)
    router.register_manager("error", error_mgr)
    return router, logger_mgr, log_path, error_mgr, err_path


def _error_lines(path: Path) -> list:
    """Строки лога уровня ERROR (без DEBUG-диагностики вроде 'no route for
    key_field=...', которая тоже пишется на каждый send и не относится к
    троттлингу из АС7/АС8)."""
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if "[ERROR]" in ln]


class _DeliveryFailQueueRegistry:
    """queue_registry, чей send_to_queue всегда отказывает: адресат ЕСТЬ
    (targets указаны явно), но доставка проваливается — сценарий
    errors_delivery_failed, отличный от errors_no_route (адресата нет вовсе).
    Форма — как ``_PartialFakeQueueRegistry(present=())`` из
    test_router_manager.py (A-2, доказанный сценарий полного отказа)."""

    def send_to_queue(self, target, qtype, msg, *args, **kwargs) -> bool:
        return False


class _RaisingChannel(QueueChannel):
    """Канал, чей send() кидает исключение — сценарий errors_exception
    («на пути отправки бросается исключение»), отличный от no_route/
    delivery_failed (там доставка явно отвергается, не падает)."""

    def send(self, message):
        raise RuntimeError("boom: канал сломан")


# ---------------------------------------------------------------------------
# АС1 + АС3: ошибка видна в плоскости логов, причина читается в тексте
# ---------------------------------------------------------------------------


class TestLogPlaneVisibility:
    def test_no_route_error_writes_error_line_to_log_file(self, tmp_path):
        router, logger_mgr, log_path, _error_mgr, _err_path = _router_with_observability(tmp_path)

        result = router.send({"type": "event", "command": "marker_no_route_671"})
        logger_mgr.shutdown()

        assert result.get("status") == "error"
        error_lines = _error_lines(log_path)
        assert len(error_lines) >= 1, "ни одной ERROR-записи не ушло в LoggerManager"
        # АС3: причина читается без чтения исходников — имя команды в тексте.
        assert any("marker_no_route_671" in ln for ln in error_lines)


# ---------------------------------------------------------------------------
# АС2: ошибка видна в плоскости ошибок (ErrorManager.track_error)
# ---------------------------------------------------------------------------


class TestErrorPlaneVisibility:
    def test_no_route_error_reaches_error_manager_file(self, tmp_path):
        router, logger_mgr, _log_path, error_mgr, err_path = _router_with_observability(tmp_path)

        router.send({"type": "event", "command": "marker_error_plane_672"})
        logger_mgr.shutdown()
        error_mgr.shutdown()

        assert err_path.exists(), "ErrorManager ни разу не принял запись — плоскость ошибок пуста"
        content = err_path.read_text(encoding="utf-8")
        assert content.strip() != "", "errors-файл пуст: track_error не вызывался"
        assert "marker_error_plane_672" in content


# ---------------------------------------------------------------------------
# АС4: общий счётчик errors растёт, status == "error" (совместимость)
# ---------------------------------------------------------------------------


class TestGeneralErrorCounterCompat:
    def test_errors_counter_increments_and_status_is_error(self, tmp_path):
        router, *_ = _router_with_observability(tmp_path)

        before = router.get_stats()["router"].get("errors", 0)
        result = router.send({"type": "event", "command": "marker_general_673"})
        after = router.get_stats()["router"]["errors"]

        assert result.get("status") == "error"
        assert after == before + 1


# ---------------------------------------------------------------------------
# АС5: три пер-причинных счётчика различают сценарии
# ---------------------------------------------------------------------------


class TestPerCauseCounters:
    def test_no_route_increments_only_errors_no_route(self, tmp_path):
        router, *_ = _router_with_observability(tmp_path)
        stats0 = router.get_stats()["router"]

        router.send({"type": "event", "command": "marker_no_route_674"})  # нет channel, нет targets

        stats1 = router.get_stats()["router"]
        assert stats1["errors_no_route"] == stats0.get("errors_no_route", 0) + 1
        assert stats1["errors_delivery_failed"] == stats0.get("errors_delivery_failed", 0)
        assert stats1["errors_exception"] == stats0.get("errors_exception", 0)

    def test_delivery_failed_increments_only_errors_delivery_failed(self, tmp_path):
        qr = _DeliveryFailQueueRegistry()
        router, *_ = _router_with_observability(tmp_path, queue_registry=qr)
        stats0 = router.get_stats()["router"]

        router.send({"type": "event", "command": "marker_delivery_failed_675", "targets": ["proc_x"]})

        stats1 = router.get_stats()["router"]
        assert stats1["errors_delivery_failed"] == stats0.get("errors_delivery_failed", 0) + 1
        assert stats1["errors_no_route"] == stats0.get("errors_no_route", 0)
        assert stats1["errors_exception"] == stats0.get("errors_exception", 0)

    def test_exception_increments_only_errors_exception(self, tmp_path):
        router, *_ = _router_with_observability(tmp_path)
        router.register_channel(_RaisingChannel("boom_channel", Queue()))
        stats0 = router.get_stats()["router"]

        router.send({"type": "event", "command": "marker_exception_676", "channel": "boom_channel"})

        stats1 = router.get_stats()["router"]
        assert stats1["errors_exception"] == stats0.get("errors_exception", 0) + 1
        assert stats1["errors_no_route"] == stats0.get("errors_no_route", 0)
        assert stats1["errors_delivery_failed"] == stats0.get("errors_delivery_failed", 0)


# ---------------------------------------------------------------------------
# АС6: сумма трёх пер-причинных счётчиков == прирост общего errors
# ---------------------------------------------------------------------------


class TestCounterArithmetic:
    def test_sum_of_per_cause_equals_general_errors_delta(self, tmp_path):
        qr = _DeliveryFailQueueRegistry()
        router, *_ = _router_with_observability(tmp_path, queue_registry=qr)
        router.register_channel(_RaisingChannel("boom_channel2", Queue()))

        stats0 = router.get_stats()["router"]
        router.send({"type": "event", "command": "a_no_route_marker"})
        router.send({"type": "event", "command": "b_delivery_failed_marker", "targets": ["proc_y"]})
        router.send({"type": "event", "command": "c_exception_marker", "channel": "boom_channel2"})
        stats1 = router.get_stats()["router"]

        delta_errors = stats1["errors"] - stats0.get("errors", 0)
        delta_sum = (
            (stats1["errors_no_route"] - stats0.get("errors_no_route", 0))
            + (stats1["errors_delivery_failed"] - stats0.get("errors_delivery_failed", 0))
            + (stats1["errors_exception"] - stats0.get("errors_exception", 0))
        )
        assert delta_sum == 3
        assert delta_sum == delta_errors


# ---------------------------------------------------------------------------
# АС7 + АС8: троттлинг — по записи, не по учёту; и по причине, не глобально
# ---------------------------------------------------------------------------


class TestThrottling:
    def test_storm_of_identical_errors_throttles_log_lines_but_not_counters(self, tmp_path):
        router, logger_mgr, log_path, _error_mgr, _err_path = _router_with_observability(tmp_path)
        n = 200

        for _ in range(n):
            router.send({"type": "event", "command": "storm_no_route_marker"})
        logger_mgr.shutdown()

        stats = router.get_stats()["router"]
        assert stats["errors_no_route"] == n, "счётчик обязан учитывать ВСЕ 200, даже если запись троттлится"

        error_lines = _error_lines(log_path)
        assert len(error_lines) < n, f"троттлинга нет: {len(error_lines)} ERROR-строк на {n} одинаковых ошибок"
        assert len(error_lines) < 10, f"троттлинг слишком мягкий: {len(error_lines)} ERROR-строк (ожидались единицы)"

    def test_storm_of_one_cause_does_not_silence_first_error_of_another_cause(self, tmp_path):
        qr = _DeliveryFailQueueRegistry()
        router, logger_mgr, log_path, _error_mgr, _err_path = _router_with_observability(tmp_path, queue_registry=qr)

        for _ in range(200):
            router.send({"type": "event", "command": "storm_no_route_marker_2"})

        count_before = len(_error_lines(log_path))

        # Первая ошибка ДРУГОЙ причины (delivery_failed, не no_route) обязана
        # дать свою запись — троттлинг per-cause, а не общий на роутер.
        router.send(
            {
                "type": "event",
                "command": "distinct_delivery_failed_marker",
                "targets": ["proc_z"],
            }
        )
        logger_mgr.shutdown()

        error_lines_after = _error_lines(log_path)
        assert len(error_lines_after) > count_before, (
            "троттлинг общий, а не по причине — заглушил первую ошибку другого рода"
        )
        assert any("distinct_delivery_failed_marker" in ln for ln in error_lines_after)
