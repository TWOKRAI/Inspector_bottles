# -*- coding: utf-8 -*-
"""Доезжают ли НАШИ числа до порта наблюдений — проверка парой, а не одним числом.

**Зачем.** `ctx.record_metric` возвращает `None` на всех дорогах (подтверждено
грепом полосы closure: `plugins/base.py:619`, `observability_hub.py:192`,
`protocols.py:45`, `stats_manager.py:1043`). Значит по одному вызову отличить
«приёмник принял» от «значение записано» нечем, и экспортёр может publish'ить в
никуда, ничего об этом не зная. Для тождества потерь Task 3.4 это смертельно:
оно собирается ИЗ этих чисел.

**Различитель — пара, а не одно число.** У порта наблюдений есть собственные
счётчики (`observability_reload.py:1165-1195`, все в `PLANE_COUNTER_KEYS`), и
`numbers_delivered` сам по себе растёт ОДИНАКОВО при живом приёмнике и при нуле
приёмников. Живая числовая плоскость — это `delivered > 0` **И** `no_sink == 0`.
Тот же класс, что наш 404: одно число выглядит здоровым по обе стороны дефекта.

**Что здесь измеряется:**

1. дельта `numbers_delivered` вокруг заведомой публикации — раздача состоялась;
2. `numbers_dropped_no_sink` — не выросла: раздача дошла хоть до кого-то;
3. `numbers_dropped_by_sink_error` — не выросла: приёмник не упал;
4. `observation_bypasses` — словарь ПО МЕТОДУ; в боевой сборке обязан быть пуст,
   непустой назовёт нашу дорогу как «ушла мимо порта вовсе» и это находка.

**Ограничение, названное заранее** (полоса closure, подтверждено дважды): эти
числа живут ТОЛЬКО на дороге опроса (`introspect.observability` → `get_stats()`),
в числовую плоскость они не попадают. Снять дельту можно живьём, восстановить
задним числом по истории — нельзя. У наблюдаемости самой наблюдаемости истории нет.

**Запуск (стенд 8765 эксклюзивен):**

    "$PWD/../../../.venv/Scripts/python.exe" tools/otel_stand/plane_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROCESS = "otel_export"
TOPOLOGY = "multiprocess_prototype/backend/topology/otel_export.yaml"
_SETTLE_SEC = 12.0

#: Ключи, ради которых проба заведена. Литералы: имя, разошедшееся с портом,
#: обязано ломать пробу, а не тихо возвращать ноль.
DELIVERED = "numbers_delivered"
NO_SINK = "numbers_dropped_no_sink"
SINK_ERROR = "numbers_dropped_by_sink_error"
BYPASSES = "observation_bypasses"


def _introspect(drv: Any) -> dict[str, Any]:
    raw = drv.send_command(PROCESS, "introspect.observability", {"full": True}) or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else {}


def _find(node: Any, key: str) -> Any:
    """Найти ключ на ЛЮБОЙ глубине ответа: форма ответа — не наше знание.

    Догадка о форме уже подводила эту оснастку не раз; поэтому ищем по имени, а
    не по заранее выдуманному пути, и печатаем, что нашли.
    """
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find(item, key)
            if found is not None:
                return found
    return None


def _verdict(name: str, ok: bool | None, detail: str) -> tuple[str, bool | None]:
    label = {True: "ДОКАЗАНО   ", False: "ОПРОВЕРГНУТО", None: "НЕ ДОКАЗАНО"}[ok]
    print(f"[{label}] {name}\n              {detail}")
    return name, ok


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("INSPECTOR_LOG_DIR", str(Path("logs_plane_probe").resolve()))

    from backend_ctl.driver import BackendDriver

    from multiprocess_prototype.main import bootstrap

    results: list[tuple[str, bool | None]] = []
    print(f"[proof] поднимаю топологию: {TOPOLOGY} (коллектор не нужен — меряем НАШУ плоскость)")
    launcher = bootstrap(TOPOLOGY)
    launcher.start()
    if not launcher.wait_until_ready(timeout=45.0):
        print("[proof] ОТКАЗ ИЗМЕРЕНИЯ: система не готова за 45 с")
        launcher.shutdown()
        return 2

    try:
        with BackendDriver(port=8765) as drv:
            print(f"[proof] даю хвосту натечь {_SETTLE_SEC} с...")
            time.sleep(_SETTLE_SEC)

            before = _introspect(drv)
            d_before = int(_find(before, DELIVERED) or 0)
            n_before = int(_find(before, NO_SINK) or 0)
            e_before = int(_find(before, SINK_ERROR) or 0)
            print(f"[proof] до: delivered={d_before} no_sink={n_before} sink_error={e_before}")

            # Заведомая публикация: status форсирует её, а хвост тем временем
            # продолжает течь и бампить `received`.
            drv.send_command(PROCESS, "otel_export.status")
            time.sleep(6.0)
            drv.send_command(PROCESS, "otel_export.status")

            after = _introspect(drv)
            d_after = int(_find(after, DELIVERED) or 0)
            n_after = int(_find(after, NO_SINK) or 0)
            e_after = int(_find(after, SINK_ERROR) or 0)
            bypasses = _find(after, BYPASSES)
            print(f"[proof] после: delivered={d_after} no_sink={n_after} sink_error={e_after}")
            print(f"[proof] observation_bypasses = {bypasses!r}")

            results.append(
                _verdict(
                    "раздача чисел СОСТОЯЛАСЬ (delivered растёт)",
                    d_after > d_before,
                    f"numbers_delivered {d_before} -> {d_after} (+{d_after - d_before})",
                )
            )
            results.append(
                _verdict(
                    "числа дошли ХОТЬ ДО КОГО-ТО (no_sink не растёт)",
                    (n_after - n_before) == 0 if d_after > d_before else None,
                    f"numbers_dropped_no_sink {n_before} -> {n_after}. "
                    "Пара к предыдущему: delivered растёт одинаково и при нуле приёмников, "
                    "поэтому живую плоскость от мёртвой отличает только пара",
                )
            )
            results.append(
                _verdict(
                    "приёмник не падал (by_sink_error не растёт)",
                    (e_after - e_before) == 0,
                    f"numbers_dropped_by_sink_error {e_before} -> {e_after}",
                )
            )
            results.append(
                _verdict(
                    "числа не уходят МИМО порта (observation_bypasses пуст)",
                    not bypasses,
                    f"observation_bypasses={json.dumps(bypasses, ensure_ascii=False)}"
                    + ("" if not bypasses else " — словарь по МЕТОДУ назовёт нашу дорогу; это находка"),
                )
            )
    finally:
        print("[proof] останавливаю систему...")
        launcher.shutdown()

    proven = sum(1 for _n, ok in results if ok is True)
    refuted = [n for n, ok in results if ok is False]
    unknown = [n for n, ok in results if ok is None]
    print(f"\n[proof] ИТОГ: доказано {proven} из {len(results)}")
    for name in refuted:
        print(f"[proof]   ОПРОВЕРГНУТО: {name}")
    for name in unknown:
        print(f"[proof]   НЕ ДОКАЗАНО: {name}")
    return 1 if refuted else (2 if unknown else 0)


if __name__ == "__main__":
    sys.exit(main())
