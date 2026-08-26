# -*- coding: utf-8 -*-
"""Ф5-добор, блокер З6: «менеджера нет» и «слот не удалось спросить» — РАЗНЫЕ ответы.

Правка S2 завела ``_safe_get_manager``, чтобы диагностическая команда не падала
из-за латентного дефекта соседнего процесса (``ProcessManagerProcess.get_manager``
бросает ``AttributeError: … no attribute '_registry'``). Глушила она отказ в
``None`` — и этажом ниже ``_plane_counters(None)`` тоже отдаёт ``None``, отчего
секция ``observation`` ПРОПАДАЛА из ответа целиком. Воспроизведено ревьюером:

    вход:     services, чей get_manager бросает AttributeError
    выход:    observability_counters(...).keys() == []          — «плоскости нет»
    контроль: services, чей get_stats бросает →
              {'observation': {'error': "RuntimeError(...)"}}

То есть ``_plane_counters`` эти два факта различает НАМЕРЕННО (её собственный
комментарий), а хелпер этажом выше их снова слил: правка, чинившая падение
команды, взамен сделала отказ невидимым.

**Три состояния судятся ВМЕСТЕ, по одному тесту на каждое**, и это не
избыточность: сторож, знающий только про отказ, зелен и у реализации, которая
рисует секцию ``observation`` ВСЕГДА — в том числе процессу, у которого порта
нет и не должно быть.
"""

from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
    _safe_get_manager,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_counters,
)

_LOOKUP_FAILURE = "'ProcessManagerProcess' object has no attribute '_registry'"


class _ServicesWithBrokenLookup:
    """Держатель, чей ``get_manager`` вызываем, но БРОСАЕТ (репродукция S2/З6)."""

    def __init__(self) -> None:
        self.calls = 0

    def get_manager(self, name: str) -> Any:
        self.calls += 1
        raise AttributeError(_LOOKUP_FAILURE)


class _ServicesWithoutTheSlot:
    """Держатель, у которого слота просто НЕТ — законное «менеджера нет»."""

    def get_manager(self, name: str) -> Any:
        return None


class _ServicesWithoutGetManager:
    """Держатель без ``get_manager`` вовсе — тоже «менеджера нет», не отказ."""


class _BrokenManager:
    """Менеджер, чей ``get_stats`` бросает — контроль, дорога которого УЖЕ работала."""

    def get_stats(self) -> dict:
        raise RuntimeError("менеджер сломан")


class TestZ6LookupFailureKeepsTheSectionWithAReason:
    def test_a_throwing_get_manager_leaves_the_section_with_its_cause(self) -> None:
        svc = _ServicesWithBrokenLookup()
        marker = _safe_get_manager(svc, "observation")

        assert svc.calls == 1, f"якорь: ``get_manager`` обязан был быть ПОЗВАН, вызовов {svc.calls}"
        assert marker is not None, "отказ не имеет права выглядеть как отсутствие менеджера"

        counters = observability_counters(observation=marker)

        assert list(counters.keys()) == ["observation"], (
            f"секция обязана остаться в ответе, получено {sorted(counters)!r}"
        )
        section = counters["observation"]
        assert "error" in section, f"секция обязана нести ПРИЧИНУ отказа, получено {section!r}"
        assert "_registry" in section["error"], (
            f"причина обязана называть исходный отказ, а не общие слова: {section['error']!r}"
        )

    def test_a_missing_slot_still_produces_no_section(self) -> None:
        """Контроль-пара: «менеджера нет» обязано остаться отсутствием секции.

        Без этого теста предыдущий был бы зелен и у реализации, которая рисует
        секцию всегда, — то есть у другого дефекта того же класса.
        """
        for svc in (_ServicesWithoutTheSlot(), _ServicesWithoutGetManager()):
            manager = _safe_get_manager(svc, "observation")
            assert manager is None, f"{type(svc).__name__}: ожидалось None, получено {manager!r}"
            counters = observability_counters(observation=manager)
            assert list(counters.keys()) == [], (
                f"{type(svc).__name__}: секции быть не должно, получено {sorted(counters)!r}"
            )

    def test_a_broken_manager_keeps_its_own_wording(self) -> None:
        """Контроль ревьюера: дорога «менеджер сломан» не изменилась."""
        counters = observability_counters(observation=_BrokenManager())
        section = counters["observation"]
        assert "RuntimeError" in section["error"], f"получено {section!r}"

    def test_a_live_port_still_reports_real_counters(self) -> None:
        """Якорь, дающий НЕНУЛЕВОЕ: здоровый порт отдаёт счётчики, а не «error».

        Без него все три теста выше зелены и у реализации, у которой секция
        ``observation`` не бывает исправной НИКОГДА.
        """
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        port = ObservationManager(manager_name="z6_live_port")
        assert port.initialize()
        try:
            counters = observability_counters(observation=port)
            section = counters["observation"]
            assert "error" not in section, f"здоровый порт не отказ, получено {section!r}"
            assert "numbers_delivered" in section, f"счётчики чисел обязаны ехать наружу: {sorted(section)!r}"
            assert "numbers_dropped_no_sink" in section, (
                "новый счётчик потерь обязан быть спрашиваем у ЖИВОГО процесса — "
                f"иначе различитель живой/мёртвой плоскости наружу не выходит: {sorted(section)!r}"
            )
        finally:
            port.shutdown()


# --------------------------------------------------------------------------- #
# Сквозь настоящую команду: то же свойство на дороге, по которой ходит оператор
# --------------------------------------------------------------------------- #


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: Optional[dict] = None) -> dict:
        return self.handlers[command](data or {})


class _ServicesForCommand:
    """Минимальные services + ``get_manager``, чьё поведение задаётся снаружи."""

    def __init__(self, *, raises: bool) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.name = "camera_0"
        self._raises = raises
        self.calls = 0

    def get_manager(self, name: str) -> Any:
        self.calls += 1
        if self._raises:
            raise AttributeError(_LOOKUP_FAILURE)
        return None

    def get_config(self, key, default=None):
        return default

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _dispatch(*, raises: bool) -> dict:
    svc = _ServicesForCommand(raises=raises)
    BuiltinCommands(svc)._register_introspect_commands()
    result = svc.command_manager.dispatch("introspect.observability", {})
    assert svc.calls >= 1, "якорь: команда обязана была спросить слот"
    return result


class TestZ6ThroughTheRealCommand:
    def test_the_operator_sees_the_failure_instead_of_silence(self) -> None:
        result = _dispatch(raises=True)
        assert result["success"] is True, "диагностическая команда не имеет права падать"
        section = result["counters"].get("observation")
        assert section is not None, (
            f"оператор обязан УВИДЕТЬ отказ слота, а не пустое место: counters={result['counters']!r}"
        )
        assert "_registry" in section.get("error", ""), f"получено {section!r}"

    def test_a_process_without_the_slot_gets_no_section(self) -> None:
        result = _dispatch(raises=False)
        assert result["success"] is True
        assert "observation" not in result["counters"], (
            f"у процесса без порта секции быть не должно, получено {sorted(result['counters'])!r}"
        )
