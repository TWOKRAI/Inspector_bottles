# -*- coding: utf-8 -*-
"""
RoutedCommandSender (frontend_module) — без импорта frontend_module/__init__.py (PyQt5).

См. ADR-058; логика теста вынесена из ``frontend_module/tests/``, иначе pytest
поднимает пакет ``frontend_module`` раньше тела модуля.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

# Inspector_prototype/multiprocess_prototype/tests/ -> Inspector_prototype/
_INSPECTOR_PROTO_ROOT = Path(__file__).resolve().parents[2]
_FM_ROOT = (
    _INSPECTOR_PROTO_ROOT
    / "multiprocess_framework"
    / "refactored"
    / "modules"
    / "frontend_module"
)


def _ensure_frontend_module_stub() -> None:
    if "frontend_module" in sys.modules:
        return
    pkg = types.ModuleType("frontend_module")
    pkg.__path__ = [str(_FM_ROOT)]
    sys.modules["frontend_module"] = pkg
    core_pkg = types.ModuleType("frontend_module.core")
    core_pkg.__path__ = [str(_FM_ROOT / "core")]
    sys.modules["frontend_module.core"] = core_pkg


def _load_module(qualname: str, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(qualname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {qualname} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)


_ensure_frontend_module_stub()
_load_module("frontend_module.interfaces", _FM_ROOT / "interfaces.py")
_load_module("frontend_module.core.routed_command", _FM_ROOT / "core" / "routed_command.py")

from frontend_module.core.routed_command import RoutedCommandSender


class _FakeMessage:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return self._payload


class _FakeFactory:
    def __init__(self) -> None:
        self.calls: List[tuple[Any, ...]] = []

    def command(
        self,
        targets: Any,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        need_ack: bool = False,
        priority: Any = "normal",
        **kwargs: Any,
    ) -> _FakeMessage:
        self.calls.append((targets, command, args or {}, kwargs))
        return _FakeMessage(
            {
                "type": "command",
                "command": command,
                "args": args or {},
                "extra": kwargs,
            }
        )


class _FakeRouter:
    def __init__(self) -> None:
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def send_message(self, target: str, msg: Dict[str, Any]) -> bool:
        self.calls.append((target, msg))
        return True


def test_send_uses_first_target_and_resolve():
    router = _FakeRouter()
    factory = _FakeFactory()

    def resolve(cmd_id: str) -> List[str]:
        assert cmd_id == "ping"
        return ["worker_b", "worker_a"]

    sender = RoutedCommandSender(
        router=router,
        message_factory=factory,
        resolve_targets=resolve,
        get_args_builder=None,
    )
    ok = sender.send("ping", args={"x": 1}, data=None)
    assert ok is True
    assert router.calls[0][0] == "worker_b"
    assert factory.calls[0][0] == ["worker_b", "worker_a"]
    assert factory.calls[0][1] == "ping"
    assert factory.calls[0][2] == {"x": 1}
    assert factory.calls[0][3]["data"] == {"x": 1}


def test_kwargs_with_builder():
    router = _FakeRouter()
    factory = _FakeFactory()
    catalog = {"set_fps": lambda fps: {"fps": fps}}

    sender = RoutedCommandSender(
        router=router,
        message_factory=factory,
        resolve_targets=lambda _: ["camera"],
        get_args_builder=lambda cid: catalog.get(cid),
    )
    sender.send("set_fps", fps=30)
    assert factory.calls[0][2] == {"fps": 30}


def test_explicit_data_overrides_payload_default():
    router = _FakeRouter()
    factory = _FakeFactory()
    sender = RoutedCommandSender(
        router=router,
        message_factory=factory,
        resolve_targets=lambda _: ["p"],
        get_args_builder=None,
    )
    sender.send("x", args={"a": 1}, data={"blob": True})
    assert factory.calls[0][3]["data"] == {"blob": True}
