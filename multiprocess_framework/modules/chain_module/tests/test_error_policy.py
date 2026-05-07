"""Тесты apply_on_error_policy + IChainLogger Protocol (ADR-CHN-006, ADR-CHN-008).

Покрывают единую on_error политику (skip / fail_region / fail_camera) и
проверку что ObservableMixin-наследник удовлетворяет узкому IChainLogger
через runtime_checkable Protocol.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.chain_module.core.context import ChainContext
from multiprocess_framework.modules.chain_module.core.error_policy import apply_on_error_policy
from multiprocess_framework.modules.chain_module.core.result import ChainResult
from multiprocess_framework.modules.chain_module.interfaces import IChainLogger

from .conftest import FailingOperation, make_step


class _RecordingLogger:
    """Фейк-логгер с тремя публичными методами IChainLogger."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.infos: list[str] = []

    def log_info(self, message: str, **kwargs) -> None:
        self.infos.append(message)

    def log_warning(self, message: str, **kwargs) -> None:
        self.warnings.append(message)

    def log_error(self, message: str, **kwargs) -> None:
        self.errors.append(message)


class TestApplyOnErrorPolicy:
    def _step_and_result(self, on_error: str):
        step = make_step("n1", operation=FailingOperation(), on_error=on_error, operation_ref="op_a")
        result = ChainResult(frame=None)  # type: ignore[arg-type]
        return step, result

    def test_logger_none_does_not_raise(self):
        """ChainContext.logger=None → нет AttributeError, warnings/errors пишутся."""
        step, result = self._step_and_result("skip")
        ctx = ChainContext()
        should_break = apply_on_error_policy(step, RuntimeError("boom"), ctx, result)
        assert should_break is False
        assert "n1" in result.skipped_nodes
        assert any("boom" in w for w in ctx.warnings)

    def test_skip_policy_calls_log_warning(self):
        log = _RecordingLogger()
        step, result = self._step_and_result("skip")
        ctx = ChainContext(logger=log)
        should_break = apply_on_error_policy(step, RuntimeError("boom"), ctx, result)
        assert should_break is False
        assert "n1" in result.skipped_nodes
        assert len(log.warnings) == 1
        assert "boom" in log.warnings[0]
        assert "on_error=skip" in log.warnings[0]
        assert log.errors == []

    def test_fail_region_policy_calls_log_error(self):
        log = _RecordingLogger()
        step, result = self._step_and_result("fail_region")
        ctx = ChainContext(logger=log)
        should_break = apply_on_error_policy(step, RuntimeError("boom"), ctx, result)
        assert should_break is True
        assert result.failed is True
        assert result.fail_level == "region"
        assert len(log.errors) == 1
        assert "boom" in log.errors[0]
        assert log.warnings == []

    def test_fail_camera_policy_calls_log_error(self):
        log = _RecordingLogger()
        step, result = self._step_and_result("fail_camera")
        ctx = ChainContext(logger=log)
        should_break = apply_on_error_policy(step, RuntimeError("boom"), ctx, result)
        assert should_break is True
        assert result.failed is True
        assert result.fail_level == "camera"
        assert len(log.errors) == 1

    def test_unknown_policy_treated_as_fail_camera(self):
        """Любое значение, отличное от skip/fail_region — fail_camera."""
        log = _RecordingLogger()
        step, result = self._step_and_result("nonsense")
        ctx = ChainContext(logger=log)
        should_break = apply_on_error_policy(step, RuntimeError("boom"), ctx, result)
        assert should_break is True
        assert result.fail_level == "camera"

    def test_node_id_override(self):
        """Параметр node_id используется для виртуальных нод DAG."""
        step, result = self._step_and_result("skip")
        ctx = ChainContext()
        apply_on_error_policy(step, RuntimeError("boom"), ctx, result, node_id="virtual_n1")
        assert "virtual_n1" in result.skipped_nodes
        assert "n1" not in result.skipped_nodes


class TestIChainLoggerProtocol:
    def test_simple_namespace_satisfies_protocol(self):
        """SimpleNamespace c тремя методами — валидный IChainLogger (duck-typing)."""
        ns = SimpleNamespace(
            log_info=lambda m, **kw: None,
            log_warning=lambda m, **kw: None,
            log_error=lambda m, **kw: None,
        )
        assert isinstance(ns, IChainLogger)

    def test_observable_mixin_satisfies_protocol(self):
        """ObservableMixin-наследник имеет публичные log_* (ADR-CHN-008) →
        автоматически совместим с IChainLogger."""

        class _Mgr(BaseManager, ObservableMixin):
            def __init__(self) -> None:
                BaseManager.__init__(self, manager_name="TestMgr")
                ObservableMixin.__init__(self, managers={})

            def initialize(self) -> bool:
                return True

            def shutdown(self) -> bool:
                return True

        m = _Mgr()
        assert isinstance(m, IChainLogger)

    def test_recording_logger_satisfies_protocol(self):
        """Тестовый фейк удовлетворяет Protocol — упрощает написание тестов."""
        assert isinstance(_RecordingLogger(), IChainLogger)

    def test_missing_method_does_not_satisfy_protocol(self):
        """Объект без log_error — не IChainLogger."""
        partial = SimpleNamespace(
            log_info=lambda m, **kw: None,
            log_warning=lambda m, **kw: None,
        )
        assert not isinstance(partial, IChainLogger)
