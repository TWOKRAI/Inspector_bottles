# -*- coding: utf-8 -*-
"""Тесты SystemBlueprint.check_structure() / check() — граница циклов (RS-5, Fable-ревью итер.1).

Контекст: RS-5 (C-4) добавил детекцию циклов графа wires в отдельный
``check_structure()`` — gate на запись рецепта (Save/load-from-file). Ревью
нашло два бага в первой версии:

1. Wire ВНУТРИ одного процесса (напр. ``p1.pluginA.out -> p1.pluginB.in``)
   схлопывался в process-level self-edge ``(p1, p1)`` -> ложный «цикл»,
   хотя это легальный явный внутрипроцессный роутинг между плагинами.
2. Детекция циклов случайно просочилась в ``check()`` (полная pre-launch
   валидация, вызывается на boot/switch из ``backend/assembly/assembler.py``)
   — межпроцессная обратная связь (request/response пара p1<->p2) легальна
   на этом уровне и не должна внезапно становиться BlueprintInvalid.

Оба случая закрыты здесь регресс-тестами.
"""

from __future__ import annotations

from ...process_manager_module.topology.blueprint import SystemBlueprint


def _bp(processes: list[dict], wires: list[dict]) -> SystemBlueprint:
    return SystemBlueprint.model_validate({"processes": processes, "wires": wires})


class TestCheckStructureCycles:
    """check_structure() — Save/load-gate: дубли имён + циклы графа процессов."""

    def test_internal_process_wire_is_not_a_cycle(self) -> None:
        """Wire между двумя плагинами ОДНОГО процесса — не self-loop цикл (находка 1)."""
        bp = _bp(
            processes=[{"process_name": "p1", "plugins": []}],
            wires=[{"source": "p1.pluginA.out", "target": "p1.pluginB.in"}],
        )
        assert bp.check_structure() == []

    def test_two_process_cycle_is_rejected(self) -> None:
        """p1 -> p2 -> p1 (межпроцессный цикл) — отклоняется gate-валидацией."""
        bp = _bp(
            processes=[{"process_name": "p1", "plugins": []}, {"process_name": "p2", "plugins": []}],
            wires=[
                {"source": "p1.a.out", "target": "p2.b.in"},
                {"source": "p2.c.out", "target": "p1.d.in"},
            ],
        )
        errors = bp.check_structure()
        assert any("цикл" in e for e in errors)

    def test_linear_wires_no_cycle(self) -> None:
        """p1 -> p2 -> p3 (линейный граф, без обратной связи) — без ошибок."""
        bp = _bp(
            processes=[
                {"process_name": "p1", "plugins": []},
                {"process_name": "p2", "plugins": []},
                {"process_name": "p3", "plugins": []},
            ],
            wires=[
                {"source": "p1.a.out", "target": "p2.b.in"},
                {"source": "p2.c.out", "target": "p3.d.in"},
            ],
        )
        assert bp.check_structure() == []

    def test_duplicate_process_names_detected(self) -> None:
        """Дубли имён процессов ловятся check_structure() (как и раньше)."""
        bp = _bp(
            processes=[{"process_name": "worker", "plugins": []}, {"process_name": "worker", "plugins": []}],
            wires=[],
        )
        errors = bp.check_structure()
        assert any("worker" in e for e in errors)


class TestCheckDoesNotGateOnCycles:
    """check() (полный pre-launch/boot-контракт) — характеризация: НЕ расширен циклами (находка 2)."""

    def test_two_process_cycle_passes_check_boot_contract_unchanged(self) -> None:
        """p1<->p2 (легальная request/response обратная связь) НЕ даёт ошибку 'цикл' в check().

        check() по-прежнему может вернуть wire-ошибки о несовместимости портов
        (тут PluginRegistry пуст — ожидаемо, не относится к этому тесту), но
        среди них НЕ должно быть сообщения о цикле — это контракт boot/switch
        (``backend/assembly/assembler.py``), который RS-5 обещал не менять.
        """
        bp = _bp(
            processes=[{"process_name": "p1", "plugins": []}, {"process_name": "p2", "plugins": []}],
            wires=[
                {"source": "p1.a.out", "target": "p2.b.in"},
                {"source": "p2.c.out", "target": "p1.d.in"},
            ],
        )
        errors = bp.check()
        assert not any("цикл" in e for e in errors)

    def test_duplicate_process_names_still_detected_by_check(self) -> None:
        """check() продолжает ловить дубли имён процессов (не тронуто RS-5)."""
        bp = _bp(
            processes=[{"process_name": "worker", "plugins": []}, {"process_name": "worker", "plugins": []}],
            wires=[],
        )
        errors = bp.check()
        assert any("worker" in e for e in errors)
