# -*- coding: utf-8 -*-
"""Тесты «контактной книжки» (Ф1 Task 1.9): driver.capabilities + dump + CI-gate.

Юнит: парсинг карточек (вложенный result-конверт), fan-out по топологии из PM,
детерминизм рендера YAML/MD. Live (harness_smoke): свод с живого бэкенда +
**drift-gate** — runtime-дамп обязан совпадать с закоммиченным
docs/contracts/CAPABILITIES.yaml (дрейф код⇄документ = красный).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_ctl.driver import BackendDriver, Capabilities, ProcessCapabilities
from backend_ctl.dump_capabilities import DEFAULT_OUT_DIR, YAML_NAME, render_md, render_yaml, to_dump

# ---------------------------------------------------------------------------
# Канонированные ответы (форма реального конверта: {success, result: {...}})
# ---------------------------------------------------------------------------

_PM_CARD = {
    "success": True,
    "result": {
        "success": True,
        "process": "ProcessManager",
        "commands": [
            {"name": "process.list", "description": "Список всех процессов и статусов", "tags": ["system"]},
        ],
        "router_handlers": ["heartbeat"],
        "registers": {},
        "processes": {
            "preprocessor": {"class": "pkg.Preprocessor"},
            "analyzer": {"class": "pkg.Analyzer"},
        },
        "channels": [{"name": "backend_ctl", "kind": "SocketChannel"}],
    },
}


def _child_card(name: str) -> dict:
    return {
        "success": True,
        "result": {
            "success": True,
            "process": name,
            "commands": [
                {"name": "worker.pause_all", "description": "Пауза воркеров", "tags": ["system"]},
            ],
            "router_handlers": ["state.changed"],
            "registers": {"resize": ["algo", "scale_factor"]},
        },
    }


def _fake_driver(responses: dict) -> BackendDriver:
    """Driver без сокета: send_command подменён канонированными ответами."""
    drv = BackendDriver()
    drv.send_command = lambda target, command, args=None, **kw: responses.get(  # type: ignore[method-assign]
        target, {"success": False, "error": "timeout"}
    )
    return drv


# ---------------------------------------------------------------------------
# ProcessCapabilities.from_response
# ---------------------------------------------------------------------------


class TestProcessCapabilities:
    def test_parses_nested_result_envelope(self) -> None:
        card = ProcessCapabilities.from_response(_child_card("preprocessor"))
        assert card.ok is True
        assert card.process == "preprocessor"
        assert card.commands[0]["name"] == "worker.pause_all"
        assert card.registers == {"resize": ["algo", "scale_factor"]}
        assert card.router_handlers == ["state.changed"]

    def test_defaults_on_error_response(self) -> None:
        card = ProcessCapabilities.from_response({"success": False, "error": "timeout"})
        assert card.ok is False
        assert card.commands == []
        assert card.registers == {}


# ---------------------------------------------------------------------------
# driver.capabilities — fan-out
# ---------------------------------------------------------------------------


class TestCapabilitiesFanOut:
    def test_collects_pm_and_all_topology_processes(self) -> None:
        drv = _fake_driver(
            {
                "ProcessManager": _PM_CARD,
                "preprocessor": _child_card("preprocessor"),
                "analyzer": _child_card("analyzer"),
            }
        )
        caps = drv.capabilities()
        assert caps.ok is True
        assert set(caps.processes) == {"ProcessManager", "preprocessor", "analyzer"}
        assert set(caps.topology) == {"preprocessor", "analyzer"}
        assert caps.channels == [{"name": "backend_ctl", "kind": "SocketChannel"}]

    def test_missing_child_marks_not_ok_but_keeps_others(self) -> None:
        drv = _fake_driver({"ProcessManager": _PM_CARD, "preprocessor": _child_card("preprocessor")})
        caps = drv.capabilities()
        assert caps.ok is False  # analyzer не ответил
        assert caps.processes["analyzer"].ok is False
        assert caps.processes["preprocessor"].ok is True


# ---------------------------------------------------------------------------
# to_dump / render_* — детерминизм
# ---------------------------------------------------------------------------


def _sample_caps() -> Capabilities:
    drv = _fake_driver(
        {
            "ProcessManager": _PM_CARD,
            "preprocessor": _child_card("preprocessor"),
            "analyzer": _child_card("analyzer"),
        }
    )
    return drv.capabilities()


class TestDumpRendering:
    def test_dump_is_deterministic(self) -> None:
        d1, d2 = to_dump(_sample_caps()), to_dump(_sample_caps())
        assert d1 == d2
        assert render_yaml(d1) == render_yaml(d2)
        assert render_md(d1) == render_md(d2)

    def test_yaml_roundtrip_and_no_runtime_values(self) -> None:
        import yaml

        dump = to_dump(_sample_caps())
        loaded = yaml.safe_load(render_yaml(dump))
        assert loaded == dump
        assert loaded["version"] == 1
        # регистры — только имена полей (контракт), не значения
        assert loaded["processes"]["preprocessor"]["registers"]["resize"] == ["algo", "scale_factor"]

    def test_md_lists_processes_and_commands(self) -> None:
        md = render_md(to_dump(_sample_caps()))
        assert "`preprocessor`" in md
        assert "`worker.pause_all`" in md
        assert "python -m backend_ctl.dump_capabilities" in md


# ---------------------------------------------------------------------------
# Live: свод с живого бэкенда + CI-gate на дрейф (harness_smoke)
# ---------------------------------------------------------------------------


@pytest.mark.harness_smoke
def test_capabilities_live_covers_smoke_proof_scenario(headless_backend) -> None:
    """Acceptance Ф1.9: по одному своду видно всё, что нужно сценарию smoke_proof.

    smoke_proof проверяет наличие приёмника register_update у preprocessor (плагин
    с register_schema) и его отсутствие у process_negative. Тот же диагноз читается
    из ОДНОГО вызова capabilities() — без чтения исходников.
    """
    caps = headless_backend.capabilities(timeout=8.0)
    assert caps.processes["ProcessManager"].ok is True
    assert "preprocessor" in caps.topology and "process_negative" in caps.topology

    pre = caps.processes["preprocessor"]
    neg = caps.processes["process_negative"]
    assert pre.ok and neg.ok
    pre_cmds = {c["name"] for c in pre.commands}
    neg_cmds = {c["name"] for c in neg.commands}
    assert "register_update" in pre_cmds  # есть регистры → есть приёмник
    assert pre.registers  # структура регистров видна (цели register_update)
    assert "register_update" not in neg_cmds or not neg.registers  # negative — без schema
    # описания команд едут из metadata регистраций
    card = {c["name"]: c for c in pre.commands}.get("introspect.capabilities")
    assert card and card["description"]


@pytest.mark.harness_smoke
def test_dump_matches_committed(headless_backend) -> None:
    """CI-gate: закоммиченный CAPABILITIES.yaml == runtime-свод (дрейф = красный).

    При осознанном изменении контракта: python -m backend_ctl.dump_capabilities.
    """
    yaml_path = Path(__file__).resolve().parents[2] / DEFAULT_OUT_DIR / YAML_NAME
    assert yaml_path.exists(), f"нет {yaml_path} — сгенерируй: python -m backend_ctl.dump_capabilities"

    caps = headless_backend.capabilities(timeout=8.0)
    bad = sorted(n for n, c in caps.processes.items() if not c.ok)
    assert not bad, f"процессы не ответили на introspect.capabilities: {bad}"

    actual = render_yaml(to_dump(caps))
    expected = yaml_path.read_text(encoding="utf-8")
    assert actual == expected, (
        "ДРЕЙФ книжки: runtime-свод != docs/contracts/CAPABILITIES.yaml — "
        "перегенерируй: python -m backend_ctl.dump_capabilities"
    )


class TestParamsSchemaV1:
    """Ф4.2 шаг 6: params_schema в дампе (v1)."""

    def test_command_dump_includes_sorted_params_schema(self) -> None:
        from backend_ctl.dump_capabilities import _command_dump

        c = {
            "name": "wire.configure",
            "description": "d",
            "tags": ["system"],
            "params_schema": [
                {"name": "wire_key", "type": "str", "required": True},
                {"name": "role", "type": "str", "required": False},
            ],
        }
        d = _command_dump(c)
        assert [f["name"] for f in d["params_schema"]] == ["role", "wire_key"]  # sorted
        assert {f["name"]: f["required"] for f in d["params_schema"]} == {"wire_key": True, "role": False}

    def test_command_dump_omits_empty_params_schema(self) -> None:
        from backend_ctl.dump_capabilities import _command_dump

        d = _command_dump({"name": "x", "description": "", "tags": []})
        assert "params_schema" not in d  # обратная совместимость: команда без контракта

    def test_params_schema_of_unwraps_optional(self) -> None:
        from multiprocess_framework.modules.process_module.commands.command_contracts import (
            WireConfigureParams,
            params_schema_of,
        )

        fields = {f["name"]: f for f in params_schema_of(WireConfigureParams)}
        assert fields["wire_key"]["type"] == "str"  # Optional[str] развёрнут в str
        assert fields["buffer_slots"]["type"] == "int"
        assert fields["wire_key"]["required"] is False
