# -*- coding: utf-8 -*-
"""Live-тест fencing — плечо 1 из трёх (Task 5.1 плана backend-ctl-proof-discipline).

**Что доказывает живой прогон: bump.** После замены инстанса соседа (пересоздание
очередей) его ``incarnation`` строго растёт, а ``routing_epoch`` топологии растёт —
это фундамент fencing-token (ADR-PMM-014, ADR-MSG-009): штамп ``_fence`` несёт
incarnation, а приёмный фильтр дропает билет с ``inc`` меньше известного. Именно эту
часть — что счётчик реально бампится на живой замене — и может доказать live.

**Почему НЕ e2e-дроп стейла (урок ``project_fencing_test_race``).** Прежний тест
требовал, чтобы УМИРАЮЩИЙ старый инстанс в окне teardown ещё успел прислать стейл-
билет, который приёмник дропнет (``fence_dropped >= 1``). Но ``restart_process``
добивает старый инстанс с подтверждением смерти ДО бампа — дропать штатно нечего,
исход гонки недоказуем детерминированно. Детерминированная инъекция стейл-билета
невозможна: драйвер входит в хост МИМО receive-мидлвари (``project_backend_ctl_socket_bypasses_mw``,
AGENTS.md «Чего драйвером проверить НЕЛЬЗЯ»), а тестовая «задняя дверь» в очередь
нарушила бы инвариант «одна дверь». Требовать от теста исхода гонки — держать его
вечно флаки-красным и приучаться игнорировать красное. Поэтому инвариант разложен:

- **Плечо 1 (здесь, live):** ``supervision_status`` до/после ``restart`` → incarnation
  строго вырос, epoch вырос. Механизм bump'а исправен и доказан на живой замене.
- **Плечо 2 (unit, ``message_module/tests/test_fencing.py``):** ``make_fence_filter_middleware``
  дропает при ``inc < expected``, прозрачно пропускает ``>=`` / без ``_fence`` / неизвестный
  sender; data-plane не трогает.
- **Плечо 3 (unit, ``process_module/tests/test_message_guards.py``):** пара ON/OFF проводки —
  ``FW_FENCE=1`` вешает штамп+фильтр (стейл дропается, ``fence_dropped++``); ``FW_FENCE=0`` не
  вешает (стейл проходит).

**Вернуть e2e стейл-дроп, если появится «парадная дверь»** — судимый receive-путь драйвера
(inbound через system-очередь хоста): тогда стейл-билет можно инъектировать детерминированно
и снова проверять сам факт дропа, а не только bump. См. «Что сознательно НЕ входит» в плане.

**Почему restart-no-reuse.** Дефолтный restart переиспользует очереди (incarnation НЕ
меняется). Замена инстанса = пересоздание очередей (``restart_reuse_queues=false``) → новый
incarnation. ``routing_epoch`` растёт на КАЖДЫЙ restart (безусловный ``_bump_routing_epoch``).

Собственный порт ≥8790 (изоляция от общих фикстур: ловушка «двух бэкендов»).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import backend_ctl.harness as _harness_mod
from backend_ctl.harness import BackendHarness

_PORT = 8790
_PEER = "preprocessor"  # non-protected → restart пересоздаёт очереди (bump incarnation)


@contextmanager
def _backend(port: int, *, monkeypatch):
    """Headless-бэкенд с ``restart_reuse_queues=false`` (замена → bump incarnation)."""
    # Внедрить restart_reuse_queues=false в конфиг оркестратора (мутабельный dict,
    # читается при start()) — так restart пересоздаёт очереди и бампит incarnation.
    orig_build = _harness_mod.build_headless_launcher

    def _build_no_reuse(**kw):
        launcher = orig_build(**kw)
        launcher._orchestrator_config["restart_reuse_queues"] = False
        return launcher

    monkeypatch.setattr(_harness_mod, "build_headless_launcher", _build_no_reuse)

    harness = BackendHarness(with_base=True, port=port)
    try:
        yield harness.start()
    finally:
        harness.stop()


def _supervision(drv, proc: str) -> dict[str, Any]:
    """(epoch, incarnation процесса) из supervision.status.

    Живой ответ обёрнут в envelope (``result``) — разворачиваем до dict с ключом
    ``processes`` (та же идиома пилинга, что у router_stats-обёрток live-тестов).
    """
    node: Any = drv.supervision_status(proc, timeout=10.0)
    for _ in range(4):
        if isinstance(node, dict) and "processes" in node:
            break
        node = node.get("result") if isinstance(node, dict) else None
    assert isinstance(node, dict) and "processes" in node, f"supervision.status без processes: {node!r}"
    entry = (node.get("processes") or {}).get(proc) or {}
    return {"epoch": node.get("epoch"), "incarnation": entry.get("incarnation")}


def _restart_peer(drv) -> None:
    res = drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=30.0)
    assert isinstance(res, dict), f"process.restart вернул не dict: {res!r}"


@pytest.mark.harness_smoke
def test_incarnation_and_epoch_bump_on_instance_replace(monkeypatch) -> None:
    """Плечо 1: замена инстанса соседа строго поднимает его incarnation и epoch топологии.

    Детерминированно (без гонки): читаем supervision.status ДО и ПОСЛЕ restart-no-reuse
    и сравниваем счётчики. Это тот bump, на котором стоит весь fencing-token — если он
    не растёт, штамп несёт стейл incarnation и приёмный фильтр не сможет отличить старый
    инстанс от нового (плечи 2-3 проверяют сам фильтр/проводку на unit).
    """
    with _backend(_PORT, monkeypatch=monkeypatch) as drv:
        before = _supervision(drv, _PEER)
        assert isinstance(before["incarnation"], int), f"нет incarnation до restart: {before}"
        assert isinstance(before["epoch"], int), f"нет epoch до restart: {before}"

        _restart_peer(drv)

        after = _supervision(drv, _PEER)
        assert isinstance(after["incarnation"], int) and isinstance(after["epoch"], int), after

        assert after["incarnation"] > before["incarnation"], (
            f"incarnation '{_PEER}' не вырос после замены инстанса: "
            f"{before['incarnation']} → {after['incarnation']} (bump не сработал — fencing слеп)"
        )
        assert after["epoch"] > before["epoch"], (
            f"routing_epoch не вырос после restart: {before['epoch']} → {after['epoch']} "
            f"(ожидался безусловный _bump_routing_epoch)"
        )
