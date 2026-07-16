"""Сборка телеметрии процесса в один merge-payload (E6/Task 5.7) + publisher-gate (PC 1.2).

Раньше ``ProcessHeartbeat._publish_metrics_to_tree`` слал **3W+2** отдельных
``proxy.set`` (по 3 на воркер + 2 агрегатных) — каждый ``set`` = отдельное
IPC-сообщение в StateStoreManager. Этот helper собирает те же листья в один
вложенный dict под общим префиксом ``processes.<name>`` → публикатор шлёт **один**
``proxy.merge`` (глубокий merge сохраняет сиблинги ``health.*`` и пр.), снижая
число телеметрийных сообщений ~в W раз.

PC 1.2 (publisher-gate): ``build_worker_telemetry`` принимает ``allowed_metrics`` —
множество суффиксов метрик, которым РАЗРЕШЕНО попасть в payload на этом тике
(вкл/выкл из ``TelemetryPublishConfig`` ∧ «созрел» интервал). ``None`` → всё
разрешено (обратная совместимость: нет конфига → поведение как раньше). Решение
«вкл/выкл + созрел ли интервал» принимает ``TelemetryGate`` (per-метрика rate-limit
по паттерну ``plugins/io_peek.py`` — ``_next_due``). ``status`` воркеров вне гейта —
публикуется всегда (инвариант плана «errors/status always-on»).

Чистые функции + тонкий gate (не mixin — сегодня единственный потребитель heartbeat):
тестируется без Qt/IPC, публикатор остаётся тонким.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional

# Суффиксы метрик, подлежащих publisher-gate (вкл/выкл + частота). ``status``
# воркеров и health/errors СЮДА не входят — они публикуются всегда (инвариант плана).
GATED_METRICS: tuple[str, ...] = ("fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm")


def build_worker_telemetry(
    workers: dict,
    name: str,
    allowed_metrics: Optional[Iterable[str]] = None,
) -> tuple[str, dict] | None:
    """Собрать (path, merge_data) телеметрии процесса из снимка воркеров.

    Формирует те же листья, что раньше писались россыпью ``proxy.set``, но как
    один вложенный dict для ``proxy.merge(path, data)``:

        path = f"processes.{name}"
        data = {
            "workers": {wname: {"status", "effective_hz"?, "cycle_duration_ms"?}, ...},
            "state":   {"fps"?, "latency_ms"?},   # агрегат
        }

    Правила (паритет с прежней логикой при ``allowed_metrics=None``):
      - per-worker: ``status`` — всегда (если не None, вне гейта); ``effective_hz`` —
        при hz>0 И если метрика разрешена; ``cycle_duration_ms`` — при lat>0 И если
        разрешена; воркер без единого поля не попадает в payload;
      - агрегат ``state``: ``fps`` = max(hz) по running-воркерам с hz>0 (если ``fps``
        разрешён); ``latency_ms`` = max(cycle_duration_ms) среди них (если ``latency_ms``
        разрешён); нет hz>0 → без агрегата;
      - округление до 1 знака сохранено (fps/hz/latency).

    Publisher-gate (PC 1.2): ``allowed_metrics`` — множество суффиксов, которым
    разрешено попасть в payload на этом тике. Выключенная/зажатая частотой метрика
    в него не входит → НЕ кладётся в merge (не грузим дерево/IPC/GUI) и по возможности
    НЕ считается в источнике (агрегат fps/latency пропускается целиком, если обе
    его метрики запрещены). Тайминг цикла воркера (``cycle_metrics``) считается
    независимо от этого гейта — его не трогаем.

    Args:
        workers: снимок ``get_all_workers_status()`` (dict wname -> статус-dict).
        name:    имя процесса-владельца (префикс пути в дереве).
        allowed_metrics: разрешённые суффиксы метрик (``None`` → все разрешены,
            обратная совместимость).

    Returns:
        ``(path, data)`` для ``proxy.merge`` — ЛИБО ``None``, если публиковать нечего
        (пустой снимок / ни одного воркера с полями и без агрегата).

    Pre:
        - ``workers`` — mapping; нестандартные значения (не dict) пропускаются.
    Post:
        - чистая функция: ``workers`` не мутируется;
        - если результат не None — ``data`` непустой (нет пустого merge-сообщения).
    """
    # None → всё разрешено (нет конфига → как раньше). Иначе — членство в множестве.
    allowed = None if allowed_metrics is None else set(allowed_metrics)

    def _ok(metric: str) -> bool:
        return allowed is None or metric in allowed

    hz_ok = _ok("effective_hz")
    lat_ok = _ok("cycle_duration_ms")
    fps_ok = _ok("fps")
    plat_ok = _ok("latency_ms")
    # Считать агрегат вообще, только если хоть одна из его метрик разрешена — иначе
    # не грузим источник лишним проходом (max по списку).
    collect_aggregate = fps_ok or plat_ok

    workers_payload: dict[str, dict] = {}
    hz_values: list[float] = []
    latency_values: list[float] = []

    for wname, w in workers.items():
        if not isinstance(w, dict):
            continue
        status = w.get("status")
        hz = w.get("effective_hz")
        lat = w.get("cycle_duration_ms")

        # Per-worker: status — всегда (вне гейта); частоту/цикл — при измерении И если разрешено.
        wp: dict = {}
        if status is not None:
            wp["status"] = status
        if hz_ok and isinstance(hz, (int, float)) and hz > 0:
            wp["effective_hz"] = round(hz, 1)
        if lat_ok and isinstance(lat, (int, float)) and lat > 0:
            wp["cycle_duration_ms"] = round(lat, 1)
        if wp:
            workers_payload[wname] = wp

        # Агрегат процесса: только running-воркеры с реальной частотой (и только если
        # агрегатные метрики вообще нужны — иначе не считаем).
        if collect_aggregate and status == "running" and isinstance(hz, (int, float)) and hz > 0:
            hz_values.append(float(hz))
            if isinstance(lat, (int, float)) and lat > 0:
                latency_values.append(float(lat))

    data: dict = {}
    if workers_payload:
        data["workers"] = workers_payload
    if hz_values:
        state: dict = {}
        if fps_ok:
            state["fps"] = round(max(hz_values), 1)
        if plat_ok and latency_values:
            state["latency_ms"] = round(max(latency_values), 1)
        if state:
            data["state"] = state

    if not data:
        return None
    return f"processes.{name}", data


class TelemetryGate:
    """Publisher-side гейт публикации метрик: вкл/выкл + per-метрика rate-limit.

    Держит ``TelemetryPublishConfig`` (duck-typed по ``.resolve(metric) -> (enabled,
    interval)``) и ``_next_due`` по суффиксу метрики — тот же паттерн, что
    ``IoPeekPublisher`` (``plugins/io_peek.py``). На каждый тик heartbeat метод
    ``due_metrics(now)`` возвращает подмножество :data:`GATED_METRICS`, которые
    (а) ``enabled`` по конфигу И (б) «созрели» (прошёл ``interval_sec`` с прошлой
    выдачи), и продвигает их ``_next_due``. Выключенные метрики не возвращаются
    никогда → не считаются и не публикуются.

    ``status`` воркеров и health/errors через гейт НЕ проходят (публикуются всегда,
    инвариант плана). Даже если heartbeat тикает чаще ``interval_sec``, метрика
    выходит не чаще своего интервала.

    Продвижение ``_next_due`` происходит в момент ВЫДАЧИ разрешения (grant), а не
    факта наличия данных: если на «созревшем» тике у метрики не оказалось данных,
    следующая публикация подождёт интервал. Для телеметрии (данные на каждом тике
    активного процесса) это несущественно и держит gate чистым/тестируемым.

    Args:
        config: объект с методом ``resolve(metric_name) -> (enabled, interval_sec)``.
        clock:  источник монотонного времени (для тестов с фейк-часами).
    """

    def __init__(self, config: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._next_due: dict[str, float] = {}

    @property
    def config(self) -> Any:
        """Текущий ``TelemetryPublishConfig`` gate (Task 1.1).

        Публичный источник эффективной секции для дельта-переконфигурации
        (``mode="merge"``): ``ProcessHeartbeat.current_telemetry_publish`` сериализует
        его в dict-базу, поверх которой мержится дельта. Раньше состояние читалось
        только через приватное ``_config``.
        """
        return self._config

    def due_metrics(self, now: Optional[float] = None) -> set[str]:
        """Разрешённые к публикации на этом тике метрики (enabled ∧ созрел интервал).

        Продвигает ``_next_due`` для выданных метрик. ``now`` — для инъекции времени
        в тестах (по умолчанию ``clock()``).
        """
        if now is None:
            now = self._clock()
        allowed: set[str] = set()
        for metric in GATED_METRICS:
            enabled, interval = self._config.resolve(metric)
            if not enabled:
                continue
            if now < self._next_due.get(metric, 0.0):
                continue
            allowed.add(metric)
            self._next_due[metric] = now + interval
        return allowed


__all__ = ["build_worker_telemetry", "TelemetryGate", "GATED_METRICS"]
