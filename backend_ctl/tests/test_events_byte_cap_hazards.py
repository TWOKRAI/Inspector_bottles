# -*- coding: utf-8 -*-
"""Авторский hazard-тест Task 1.3a: байтовая бухгалтерия колец EventHub.

Опасность механизма: у кольца ДВА пути вытеснения — неявный (deque(maxlen) сам
выкидывает левый элемент на append) и явный (popleft по байтам). Если один из
них забудет вычесть размер, сумма поплывёт: вверх — кольцо начнёт пустеть без
причины, вниз (в минус) — байтовый потолок перестанет работать. Проверка — после
КАЖДОГО emit на случайной смеси размеров, где срабатывают оба пути.
"""

from __future__ import annotations

import random

from backend_ctl.events import ALL_PLANE, PLANES, EventHub, _estimate_bytes


def _assert_books(hub: EventHub, cap: int) -> None:
    for key in (ALL_PLANE, *PLANES):
        ring = hub._arrival if key == ALL_PLANE else hub._rings[key]
        sizes = hub._sizes[key]
        total = hub._bytes[key]
        assert total >= 0, f"{key}: сумма ушла в минус ({total})"
        assert len(sizes) == len(ring), f"{key}: размеры разошлись с кольцом ({len(sizes)} vs {len(ring)})"
        assert total == sum(sizes), f"{key}: сумма {total} != фактической {sum(sizes)}"
        assert total <= cap, f"{key}: {total} байт при потолке {cap}"


def test_byte_totals_never_drift_under_mixed_evictions() -> None:
    rng = random.Random(1303)
    cap = 20_000
    hub = EventHub(maxlen=8, max_bytes_per_ring=cap)
    kinds = [
        lambda pad: {"type": "event", "command": "log.record", "data": {"m": pad}},
        lambda pad: {"type": "event", "command": "ui.event", "data": {"m": pad}},
        lambda pad: {"type": "event", "command": "something.else", "data": {"m": pad}},
        lambda pad: {
            "type": "event",
            "command": "state.changed",
            "data": {"changes": [{"path": f"a.{i}", "value": pad} for i in range(3)]},
        },
    ]
    for _ in range(2000):
        # Мелкие (вытесняет maxlen), крупные (вытесняют байты) и одна больше потолка.
        n = rng.choice([10, 100, 3000, 9000, 25_000])
        hub.emit(rng.choice(kinds)("x" * n))
        _assert_books(hub, cap)


def test_estimate_is_json_length() -> None:
    """Литерал оценки из дизайна: длина json.dumps(ensure_ascii=False)."""
    assert _estimate_bytes({"a": "я"}) == len('{"a": "я"}')
