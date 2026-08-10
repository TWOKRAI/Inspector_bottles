# -*- coding: utf-8 -*-
"""Страж адресуемости ``chain_targets`` (план D8, 2026-08-10).

Провод (``wires``) судится по портам плагинов и неизвестный адрес уже отвергает;
``chain_targets`` — ДРУГАЯ ось (маршрут между процессами), и её не судил никто.
Расхождение стоило шторма: ``stitcher.chain_targets: [gui]`` при отсутствующем
процессе ``gui`` давал отказ доставки на КАЖДЫЙ кадр — 1418 отказов за 30 с на
стенде ``webcam_sketch``, и ни строки о причине в самой топологии.

Судится ровно первый сегмент адреса: ниже процесса (воркер и глубже) резолв
происходит на приёме, и топология про него ничего не знает.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint


def _blueprint(processes: list) -> SystemBlueprint:
    return SystemBlueprint.model_validate({"name": "t", "processes": processes, "wires": []})


class TestUnaddressableChainTargets:
    def test_target_without_a_declared_process_is_named(self) -> None:
        bp = _blueprint(
            [
                {"process_name": "producer", "plugins": [], "chain_targets": ["ghost"]},
            ]
        )

        errors = bp._unaddressable_chain_targets()

        assert len(errors) == 1, errors
        # Отказ обязан нести АДРЕС: и кто адресует, и кого — иначе разбор упирается
        # в чтение всей топологии (прецедент Ф8.5: WARNING без адреса ключа).
        assert "producer" in errors[0] and "ghost" in errors[0], errors[0]

    def test_declared_target_is_silent(self) -> None:
        bp = _blueprint(
            [
                {"process_name": "producer", "plugins": [], "chain_targets": ["consumer"]},
                {"process_name": "consumer", "plugins": []},
            ]
        )

        assert bp._unaddressable_chain_targets() == []

    def test_worker_level_address_judges_only_the_process_segment(self) -> None:
        """``proc.worker`` — законный иерархический адрес: воркер резолвится на
        приёме, и требовать его объявления в топологии было бы требованием того,
        чего топология не описывает."""
        bp = _blueprint(
            [
                {"process_name": "producer", "plugins": [], "chain_targets": ["consumer.worker_1"]},
                {"process_name": "consumer", "plugins": []},
            ]
        )

        assert bp._unaddressable_chain_targets() == []

    def test_worker_level_address_on_a_missing_process_still_fails(self) -> None:
        """Пара к предыдущему: снисхождение к нижним уровням не должно
        превращаться в снисхождение к процессу."""
        bp = _blueprint([{"process_name": "producer", "plugins": [], "chain_targets": ["ghost.worker_1"]}])

        errors = bp._unaddressable_chain_targets()

        assert len(errors) == 1 and "ghost" in errors[0], errors

    @pytest.mark.parametrize("target", ["all", "broadcast"])
    def test_broadcast_targets_are_not_process_names(self, target: str) -> None:
        bp = _blueprint([{"process_name": "producer", "plugins": [], "chain_targets": [target]}])

        assert bp._unaddressable_chain_targets() == []

    def test_orchestrator_is_addressable_though_not_in_processes(self) -> None:
        """Оркестратора нет в ``processes``, но адресовать его законно."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            ORCHESTRATOR_PROCESS_NAME,
        )

        bp = _blueprint([{"process_name": "producer", "plugins": [], "chain_targets": [ORCHESTRATOR_PROCESS_NAME]}])

        assert bp._unaddressable_chain_targets() == []

    def test_check_carries_the_verdict_not_only_the_helper(self) -> None:
        """Свойство должно быть у ТОЙ проверки, что зовут сборщики на boot/switch.

        Иначе страж существует и зелен, а сборка его не спрашивает — класс
        «названный механизм ≠ обязательство».
        """
        bp = _blueprint([{"process_name": "producer", "plugins": [], "chain_targets": ["ghost"]}])

        errors = bp.check()

        assert any("ghost" in err for err in errors), errors

    def test_every_bad_target_is_named_not_just_the_first(self) -> None:
        """Молчание про второй адрес заставило бы чинить топологию по одному
        кругу сборки на ошибку."""
        bp = _blueprint(
            [
                {"process_name": "a", "plugins": [], "chain_targets": ["ghost_1", "ghost_2"]},
                {"process_name": "b", "plugins": [], "chain_targets": ["ghost_3"]},
            ]
        )

        errors = bp._unaddressable_chain_targets()

        assert len(errors) == 3, errors
        joined = " ".join(errors)
        assert all(name in joined for name in ("ghost_1", "ghost_2", "ghost_3"))
