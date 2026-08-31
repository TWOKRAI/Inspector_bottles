# -*- coding: utf-8 -*-
"""Инцидент ``report_error`` доезжает до стора при ЛЮБОЙ раскладке плоскостей.

Сторож находки Major 1 ревью Task 1.3a. Меряется **число строк в сторе**, а не
наличие маркера, — и это не оформление: находку поймали именно счётом строк.
Маркер ``origin=error_manager`` на голосе выглядел здоровым в обеих раскладках,
а исход был разный:

    ДО починки: контроль (есть ErrorManager) rows=1
                опыт   (нет ErrorManager)   rows=0   ← инцидент исчезал ЦЕЛИКОМ

Причина была в том, что маркер — утверждение о ЧУЖОЙ строке («факт уже уехал в
плоскость ошибок, стор получит его оттуда»), а ставился он безусловно. Процесс
без ErrorManager (секции ``error`` в конфиге нет → ``_create_error_manager``
вернул ``None``) второй дороги не имеет: логгер-tap видел маркер, пропускал
голос — и не оставалось ничего.

Харнес РЕАЛЬНЫЙ (``LoggerManager`` / ``ErrorManager`` / ``ObservabilityStore`` /
``ProcessModule``), потому что дефект жил в стыке трёх механизмов: кто ставит
маркер, кто владеет им у стора и что происходит, когда владельца нет. Ни один
из них по отдельности его не показывал.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import Mock

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    unwire_observability_store,
    wire_observability_store,
)


class _CapturingRouter:
    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        return None


def _manager_config(tmp_path, app: str) -> Dict[str, Any]:
    """Форма конфига менеджера — та же, что у соседних приёмочных тестов."""
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{app}.log")}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


def _dump(rows: List[Dict[str, Any]]) -> str:
    return "\n".join(f"  kind={r.get('kind')} severity={r.get('severity')} msg={r.get('message')!r}" for r in rows)


class _Stand:
    """Живой процесс с настоящим стором. ``with_error_manager`` — единственная развилка."""

    def __init__(self, tmp_path, name: str, with_error_manager: bool) -> None:
        self.name = name
        self.logger = LoggerManager(manager_name=f"L_{name}", config=_manager_config(tmp_path, f"log_{name}"))
        self.logger.initialize()
        self.errors = None
        if with_error_manager:
            self.errors = ErrorManager(manager_name=f"E_{name}", config=_manager_config(tmp_path, f"err_{name}"))
            self.errors.initialize()

        self.process = ProcessModule(name)
        self.process.router_manager = _CapturingRouter()
        self.process.logger_manager = self.logger
        self.process.error_manager = self.errors
        self.process._observability_hub = Mock()
        self.process.register_manager("logger", self.logger, enabled=True)
        if self.errors is not None:
            # Ровно как ``ProcessManagers.register_all``: слот 'error' регистрируется
            # ТОЛЬКО когда менеджер создан. Это и есть раскладка находки.
            self.process.register_manager("error", self.errors, enabled=True)

        self.store, self.taps = wire_observability_store(
            error_manager=self.errors,
            logger_manager=self.logger,
            db_path=str(tmp_path / f"{name}.db"),
            process=name,
            min_level="INFO",
        )

    def report_one_incident(self) -> float:
        ts = time.time()
        try:
            raise RuntimeError("камера отвалилась")
        except RuntimeError as exc:
            get_or_create_health_state(self.process).report_error(exc, context="grab_frame")
        return ts

    def rows(self, since: float) -> List[Dict[str, Any]]:
        return self.store.list_records(process=self.name, since=since - 1.0, limit=50)

    def close(self) -> None:
        unwire_observability_store(self.store, self.taps)
        self.logger.shutdown()
        if self.errors is not None:
            self.errors.shutdown()


class TestOneIncidentIsOneRowWhicheverPlanesExist:
    def test_a_process_without_error_manager_keeps_the_incident(self, tmp_path) -> None:
        """ОПЫТ находки: плоскости ошибок нет — инцидент обязан остаться в сторе.

        Литерал 1, а не «больше нуля»: ноль был дефектом, а двойка означала бы,
        что дедуп путей развалился в другую сторону.
        """
        stand = _Stand(tmp_path, "no_em", with_error_manager=False)
        try:
            ts = stand.report_one_incident()
            rows = stand.rows(ts)
            assert len(rows) == 1, (
                f"инцидент процесса без ErrorManager обязан оставить РОВНО одну строку "
                f"в сторе, получено {len(rows)}:\n{_dump(rows)}"
            )
        finally:
            stand.close()

    def test_a_process_with_error_manager_keeps_exactly_one_row(self, tmp_path) -> None:
        """КОНТРОЛЬ: та же строка кода, обе плоскости на месте — по-прежнему одна строка.

        Без него «одна строка в опыте» доказывалось бы и починкой, снявшей дедуп
        путей целиком: там опыт дал бы 1, а контроль — 2.
        """
        stand = _Stand(tmp_path, "with_em", with_error_manager=True)
        try:
            ts = stand.report_one_incident()
            rows = stand.rows(ts)
            assert len(rows) == 1, (
                f"инцидент процесса с ErrorManager обязан дать РОВНО одну строку, получено {len(rows)}:\n{_dump(rows)}"
            )
            assert rows[0]["kind"] == "error", f"дорога факта обязана приехать kind=error: {rows[0]}"
        finally:
            stand.close()

    def test_five_repeats_without_an_error_manager_leave_one_row_known_ceiling(self, tmp_path) -> None:
        """Окно голоса не имеет права стать окном СТОРА и там, где владелец — логгер-tap.

        Повтор одного отказа схлопывается в один ГОЛОС (окно), но у процесса без
        ErrorManager стор наполняется именно голосами. Проверяется, что дорога
        голоса при этом не превращает пять инцидентов в одну строку молча:
        число строк здесь названо литералом 1 сознательно — это ИЗВЕСТНЫЙ
        потолок раскладки без плоскости ошибок, а не желаемое поведение. Он
        назван тестом, чтобы починка, поднимающая его до пяти, была замечена как
        изменение контракта, а не проехала молча.
        """
        stand = _Stand(tmp_path, "no_em_burst", with_error_manager=False)
        try:
            ts = time.time()
            for _ in range(5):
                try:
                    raise RuntimeError("камера отвалилась")
                except RuntimeError as exc:
                    get_or_create_health_state(stand.process).report_error(exc, context="grab_frame", throttle=10_000.0)
            # Строки СТАТУСА («[health] status → …», их пишет открывшийся breaker)
            # из счёта исключены: они не инциденты, и их число зависит от порога
            # breaker'а, а не от механизма окна.
            incidents = [r for r in stand.rows(ts) if "[health] status" not in str(r.get("message"))]
            assert len(incidents) == 1, (
                f"голос дросселируется окном — строк инцидента в сторе ожидается 1, "
                f"получено {len(incidents)}:\n{_dump(incidents)}"
            )
            assert stand.process._health_state.snapshot()["errors"] == 5, "факт окном не дросселируется"
        finally:
            stand.close()
