# -*- coding: utf-8 -*-
"""Тесты ProcessConfig.extras (C6 рычаг 1) — domain-opaque bag + typed-приоритет.

as_generic_config() читает typed-поле, если непусто, иначе extras[key]. Типизированные
поля (chain_targets/source_target_fps/inspector/io_peek) остаются как shorthand и имеют
приоритет над одноимёнными ключами в extras — 100% back-compat со старыми рецептами.
"""

from __future__ import annotations

import pytest

from ...process_manager_module.topology.blueprint import ProcessConfig


class TestTypedPath:
    """Типизированные поля напрямую (back-compat старых рецептов)."""

    def test_chain_targets_typed(self):
        cfg = ProcessConfig(process_name="p", chain_targets=["gui", "sink"])
        assert cfg.as_generic_config().chain_targets == ["gui", "sink"]

    def test_source_fps_typed(self):
        cfg = ProcessConfig(process_name="p", source_target_fps=30.0)
        assert cfg.as_generic_config().source_target_fps == 30.0

    def test_inspector_typed(self):
        insp = {"mode": "join", "inputs": ["frame", "overlay"]}
        cfg = ProcessConfig(process_name="p", inspector=insp)
        assert cfg.as_generic_config().inspector == insp

    def test_io_peek_typed(self):
        peek = {"enabled": True, "rate_hz": 2.0}
        cfg = ProcessConfig(process_name="p", io_peek=peek)
        assert cfg.as_generic_config().io_peek == peek


class TestExtrasPath:
    """Тот же ключ из extras, когда typed-поле пусто."""

    def test_chain_targets_extras(self):
        cfg = ProcessConfig(process_name="p", extras={"chain_targets": ["gui"]})
        assert cfg.as_generic_config().chain_targets == ["gui"]

    def test_source_fps_extras(self):
        cfg = ProcessConfig(process_name="p", extras={"source_target_fps": 12.5})
        assert cfg.as_generic_config().source_target_fps == 12.5

    def test_inspector_extras(self):
        insp = {"mode": "join"}
        cfg = ProcessConfig(process_name="p", extras={"inspector": insp})
        assert cfg.as_generic_config().inspector == insp

    def test_io_peek_extras(self):
        peek = {"enabled": False}
        cfg = ProcessConfig(process_name="p", extras={"io_peek": peek})
        assert cfg.as_generic_config().io_peek == peek

    def test_unknown_domain_key_ignored_by_framework(self):
        """Новый доменный ключ в extras не ломает build (framework его не знает по имени)."""
        cfg = ProcessConfig(process_name="p", extras={"roi_selector": {"x": 1}})
        gc = cfg.as_generic_config()
        assert gc.process_name == "p"  # build прошёл без ошибок


class TestTypedPriorityOverExtras:
    """При обоих заданных typed-поле побеждает extras (shorthand-приоритет)."""

    def test_chain_targets_typed_wins(self):
        cfg = ProcessConfig(
            process_name="p",
            chain_targets=["typed"],
            extras={"chain_targets": ["extras"]},
        )
        assert cfg.as_generic_config().chain_targets == ["typed"]

    def test_source_fps_typed_wins(self):
        cfg = ProcessConfig(
            process_name="p",
            source_target_fps=40.0,
            extras={"source_target_fps": 5.0},
        )
        assert cfg.as_generic_config().source_target_fps == 40.0

    def test_inspector_typed_wins(self):
        cfg = ProcessConfig(
            process_name="p",
            inspector={"mode": "fanin"},
            extras={"inspector": {"mode": "join"}},
        )
        assert cfg.as_generic_config().inspector == {"mode": "fanin"}

    def test_source_fps_typed_default_value_wins_over_extras(self):
        """Fable MED-4: рецепт ЯВНО пинует source_target_fps=25.0 (== дефолт), extras=10.0.

        Старый sentinel `!= 25.0` считал явный пин «незаданным» → extras 10.0 молча
        побеждал. model_fields_set видит явное присвоение → typed (25.0) выигрывает.
        Существующий test_source_fps_typed_wins (40.0) обходил это окно дефекта.
        """
        cfg = ProcessConfig(
            process_name="p",
            source_target_fps=25.0,
            extras={"source_target_fps": 10.0},
        )
        # typed 25.0 явно задан → побеждает; в base_kwargs 25.0 не пробрасывается (== дефолт)
        assert cfg.as_generic_config().source_target_fps == 25.0

    def test_explicit_empty_chain_targets_wins_over_extras(self):
        """Явный пустой chain_targets=[] (typed задан) не даёт extras перекрыть."""
        cfg = ProcessConfig(
            process_name="p",
            chain_targets=[],
            extras={"chain_targets": ["from_extras"]},
        )
        assert cfg.as_generic_config().chain_targets == []


class TestConflictWarning:
    """Fable LOW-5: конфликт typed≠extras при обоих заданных — warning."""

    def test_conflict_logs_warning(self):
        import loguru

        msgs: list[str] = []
        sink_id = loguru.logger.add(lambda m: msgs.append(str(m)), level="WARNING")
        try:
            cfg = ProcessConfig(
                process_name="pc",
                chain_targets=["typed"],
                extras={"chain_targets": ["extras"]},
            )
            cfg.as_generic_config()
        finally:
            loguru.logger.remove(sink_id)
        assert any("chain_targets" in m and "pc" in m for m in msgs), "конфликт должен логироваться"

    def test_no_warning_when_extras_matches(self):
        import loguru

        msgs: list[str] = []
        sink_id = loguru.logger.add(lambda m: msgs.append(str(m)), level="WARNING")
        try:
            cfg = ProcessConfig(
                process_name="pc",
                chain_targets=["same"],
                extras={"chain_targets": ["same"]},
            )
            cfg.as_generic_config()
        finally:
            loguru.logger.remove(sink_id)
        assert not any("chain_targets" in m for m in msgs)


class TestRoundTripTable:
    """Round-trip таблица: chain_targets проходит и через typed, и через extras путь."""

    @pytest.mark.parametrize(
        "targets",
        [
            ["gui"],
            ["gui", "sink"],
            ["a", "b", "c", "d"],
            ["proc_0", "proc_1"],
        ],
    )
    def test_chain_targets_typed_roundtrip(self, targets):
        cfg = ProcessConfig(process_name="p", chain_targets=list(targets))
        assert cfg.as_generic_config().chain_targets == list(targets)

    @pytest.mark.parametrize(
        "targets",
        [
            ["gui"],
            ["gui", "sink"],
            ["a", "b", "c", "d"],
            ["proc_0", "proc_1"],
        ],
    )
    def test_chain_targets_extras_roundtrip(self, targets):
        # непустой список: пустой == typed-дефолт, extras-путь тогда не активируется
        cfg = ProcessConfig(process_name="p", extras={"chain_targets": list(targets)})
        assert cfg.as_generic_config().chain_targets == list(targets)
