# -*- coding: utf-8 -*-
"""Live-тест F.1 (доказательство Task A.1 на живом бэкенде): subtree-delete чистит
поддерево в read-model driver'а.

A.1 (закрыт, ``telemetry_read_model.py::_purge_subtree``) чинил проблему: сервер
(``tree_store.delete()``) шлёт ОДНУ ``Delta(new_value=MISSING)`` на КОРЕНЬ поддерева —
до фикса ``ingest(deleted=True)`` убирал только точный ключ, все листья под удалённым
узлом (``processes.cam.state.fps`` и т.п.) оставались в read-model НАВСЕГДА. Unit-тест
(``telemetry_readmodel_module/tests``) это уже доказал через прямой вызов ``ingest()``.
Здесь — то же самое, но СКВОЗЬ реальный сокет: живой ProcessManager, настоящая команда
``state.delete`` (не синтетическая дельта), настоящий driver ``telemetry_snapshot()`` —
то же generic-ядро ``TelemetryReadModel``, что использует GUI ``TelemetryViewModel``
(A.1 явно затрагивает обоих потребителей).

Путь синтетический (не завязан на реальный процесс/регистр) и намеренно ВНЕ
``processes.*``: ADR-SS-019 (``TopologyGateMiddleware``,
``state_store_module/middleware/topology_gate.py``) отклоняет запись в
``processes.<name>.*``, если ``<name>`` не значится в текущей топологии — а
синтетическое имя вроде ``_selftest_subtree`` там заведомо не значится, и
``state.merge``/``state.delete`` получили бы ``{'status': 'rejected', 'reason':
'topology_gate'}`` вместо применения к дереву. Namespace вне ``processes.*``
иммунен к гейту по построению (``_process_name()`` возвращает ``None``, если
первый сегмент пути не ``processes`` — гейт для такого пути не применяется) и
не пишет в поддерево реального процесса — этого достаточно, чтобы тест остался
изолирован от топологии рецепта и register-схем. Read-model driver'а
путь-агностичен (``TelemetryReadModel.ingest`` не фильтрует по корню, см.
``driver.py:_ingest_state_changed``), так что снимок и subtree-delete работают
на любом корне.

Собственный порт 8785 (≥8770; ловушка «двух бэкендов» — свой порт изолирует, см.
backend_ctl/AGENTS.md, project_concurrent_backends_trap).
"""

from __future__ import annotations

import time
from backend_ctl.protocol import unwrap

import pytest

from backend_ctl.harness import BackendHarness
from multiprocess_framework.modules.state_store_module.core.delta import STATE_ENVELOPE_MARKER

_PORT = 8785
_ROOT = "selftest.subtree_probe"


def _merge(drv, path: str, data: dict, *, timeout: float = 8.0) -> dict:
    """state.merge с явным маркером конверта (ADR-SS-017: STATE_ENVELOPE_MARKER).

    Без маркера обработчик неоднозначен: ``data`` конверта САМА содержит ключ
    ``data`` (payload merge'а) — без явного маркера это принимается за форму «полное
    сообщение с вложенным data» (envelope = наш payload), и ``path`` теряется.
    """
    args = {"path": path, "data": data, "source": "backend_ctl", STATE_ENVELOPE_MARKER: True}
    return unwrap(drv.send_command("ProcessManager", "state.merge", args, timeout=timeout), leaf=True)


def _wait_metrics(drv, deadline: float, *, present: tuple[str, ...] = (), absent: tuple[str, ...] = ()) -> dict:
    """Дождаться снимка телеметрии, где все ``present`` есть, а все ``absent`` — нет."""
    snap = drv.telemetry_snapshot()
    while time.time() < deadline:
        metrics = snap.get("metrics", {})
        if all(p in metrics for p in present) and all(a not in metrics for a in absent):
            return snap
        time.sleep(0.2)
        snap = drv.telemetry_snapshot()
    return snap


@pytest.mark.harness_smoke
def test_subtree_delete_cleans_read_model() -> None:
    """state.delete родителя чистит ВСЕ листья поддерева в telemetry_snapshot driver'а (A.1)."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()
        sub = unwrap(drv.state_subscribe(f"{_ROOT}.**", timeout=8.0), leaf=True)
        assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"

        # Поддерево-жертва: два листа под "a" — мержим ПРЯМО в узел "{_ROOT}.a" плоскими
        # скалярами, чтобы TreeStore.merge дал ДВЕ отдельные дельты-листа (leaf1/leaf2),
        # а не одну дельту с целым dict'ом (тот путь — только когда значение САМО dict
        # и узел ещё не существовал — см. TreeStore._merge_recursive). Сосед "a2" — та же
        # ступень дерева, общий строковый префикс "a" — регресс-граница A.1 (не должен
        # пострадать при удалении "a").
        merged = _merge(drv, f"{_ROOT}.a", {"leaf1": 1, "leaf2": 2})
        assert merged.get("status") == "ok", f"state.merge (жертва) не ok: {merged}"

        merged_sibling = _merge(drv, f"{_ROOT}.a2", {"leaf": 99})
        assert merged_sibling.get("status") == "ok", f"state.merge (сосед) не ok: {merged_sibling}"

        leaf1 = f"{_ROOT}.a.leaf1"
        leaf2 = f"{_ROOT}.a.leaf2"
        sibling = f"{_ROOT}.a2.leaf"

        snap = _wait_metrics(drv, time.time() + 15.0, present=(leaf1, leaf2, sibling))
        metrics = snap.get("metrics", {})
        assert leaf1 in metrics, f"read-model не наполнился leaf1: {sorted(metrics)}"
        assert leaf2 in metrics, f"read-model не наполнился leaf2: {sorted(metrics)}"
        assert sibling in metrics, f"read-model не наполнился соседом a2.leaf: {sorted(metrics)}"

        # --- Удаление поддерева-родителя ЕДИНОЙ командой (сервер шлёт ОДНУ дельту на "{_ROOT}.a") ---
        deleted = unwrap(
            drv.send_command("ProcessManager", "state.delete", {"path": f"{_ROOT}.a"}, timeout=8.0), leaf=True
        )
        assert deleted.get("status") == "ok" and deleted.get("changed") is True, f"state.delete не ok: {deleted}"

        snap = _wait_metrics(drv, time.time() + 15.0, absent=(leaf1, leaf2))
        metrics = snap.get("metrics", {})
        assert leaf1 not in metrics, (
            f"A.1 регресс: leaf1 остался в read-model driver'а после subtree-delete: {sorted(metrics)}"
        )
        assert leaf2 not in metrics, (
            f"A.1 регресс: leaf2 остался в read-model driver'а после subtree-delete: {sorted(metrics)}"
        )
        # Сосед с общим строковым префиксом "a"/"a2" НЕ задет (граница по точке-разделителю).
        assert sibling in metrics, (
            f"сосед {sibling!r} с общим строковым префиксом пострадал от subtree-delete "
            f"(граница по точке-разделителю сломана): {sorted(metrics)}"
        )
    finally:
        harness.stop()
