# -*- coding: utf-8 -*-
"""Приёмка C-87, RED 7 (слепой тестер): живой стенд — диск едет ровно, без «ступенек».

Что проверяется: на настоящих объектах (полный трёхпроцессный стенд ``apps/line_sim``:
``robot`` публикует ``sim.belt.encoder`` -> ``scene_source`` читает через настоящий
``state_proxy`` -> MJPEG :8091) шаг положения диска между СОСЕДНИМИ кадрами лежит в пределах
±1 px от среднего шага. До правки диск стоял ~3 кадра и прыгал на 16.5...24.7 px (запись 20
``amendments.md``): такой ряд шагов не проходит порог.

Запуск (по умолчанию тест пропущен; стенд поднимает порты 8766, 5021, 8091, они должны быть
свободны; через ворота машины, класс ``heavy`` — полный стенд)::

    LINE_SIM_LIVE=1 bash <главный-чекаут>/scripts/machine_gate.sh heavy <сессия> \\
        env PYTHONPATH=<корень-дерева> <главный-.venv>/bin/python -m pytest -q -s \\
        Plugins/sim/scene_source/tests/test_acceptance_c87_live_step.py

``-s`` нужен, чтобы увидеть напечатанный список шагов и в зелёном прогоне.

Как установлена смежность кадров (MJPEG-поток не несёт номера кадра). Все кадры читаются ОДНИМ
соединением по порядку; на каждый целый JPEG ставится метка ``time.monotonic()`` в момент его
получения. Пара кадров считается соседней, только если интервал между их метками не больше
``1.5 * медиана интервалов``: пропущенный кадр даёт интервал ~2x, такая пара ИСКЛЮЧАЕТСЯ из
замера (а не засчитывается шагом ~2x). Исключённые пары считаются и попадают в сообщение.
Слабость критерия (пропуск, замаскированный пачкой TCP, виден как нормальный интервал) описана
в отчёте тестера. Требуется не меньше 25 соседних пар (>= 1 с кадров при 25 к/с).

Диск измеряется по центру масс крупнейшей связной области «не фон» (фон — медианный цвет
угла кадра, допуск 40 на канал). Фон плиткой ленты (``background_layers`` в боевом
``pipeline.yaml``) сегментации мешает, поэтому тест пишет во временный ``pipeline.yaml``
копию боевого БЕЗ ``background_layers`` (плагин тогда рисует сплошной фон) — остальное
(проводка, процессы, ``scene_source``) настоящее. Области, касающиеся границы кадра, не
берутся (центр масс обрезанного диска смещён); пара принимается, только если площади областей
различаются не больше чем на 10% и шаг по модулю меньше 150 px (диск ~300 px, шаг спавна
164 мм = ~1340 px — другой диск в эту пару попасть не может).

Порог — литерал ``_STEP_TOLERANCE_PX = 1.0``. Дополнительно требуется движение: ``|среднее| >
2 px`` (иначе остановленная лента — все шаги 0 — прошла бы порог «±1 px» вхолостую).
"""

from __future__ import annotations

import os
import socket
import statistics
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend_ctl.harness import BackendHarness

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("LINE_SIM_LIVE") != "1",
        reason="живой прогон полного стенда сима — только явно, LINE_SIM_LIVE=1",
    ),
]

_APP_DIR = Path(__file__).resolve().parents[4] / "apps" / "line_sim"
_APP_YAML = _APP_DIR / "app.yaml"

_LINE_SIM_PORT = 8766
_MODBUS_PORT = 5021
_MJPEG_PORT = 8091
_MJPEG_URL = "http://127.0.0.1:8091/"

#: Литерал порога брифа: шаг в пределах ±1 px от среднего шага.
_STEP_TOLERANCE_PX = 1.0
#: Не меньше стольких соседних пар кадров (1 с при 25 к/с).
_MIN_ADJACENT_PAIRS = 25
#: Лента обязана ехать: |средний шаг| больше этого (px/кадр).
_MIN_MEAN_STEP_PX = 2.0
#: Пара соседняя, если интервал приёма <= этого множителя медианного интервала.
_ADJACENCY_GAP_FACTOR = 1.5
#: Длительность замера (с): диск целиком в кадре не всё время, пар нужно с запасом.
_CAPTURE_SECONDS = 12.0
_BACKGROUND_TOL = 40
_MIN_DISC_AREA_PX = 5000
_MAX_AREA_RATIO_DEV = 0.10
_MAX_SAME_DISC_DX_PX = 150.0


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _assert_port_free(port: int) -> None:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            pytest.fail(f"порт {port} занят до старта теста — {exc}")


def _write_solid_background_app(tmp_path: Path) -> Path:
    """Манифест + ``pipeline.yaml`` во временном каталоге: боевая проводка без ``background_layers``."""
    import yaml

    pipeline_raw = yaml.safe_load((_APP_DIR / "pipeline.yaml").read_text(encoding="utf-8"))
    removed = 0
    for proc in pipeline_raw["processes"]:
        for plugin_cfg in proc.get("plugins", []):
            if plugin_cfg.get("plugin_name") == "scene_source":
                removed += 1 if plugin_cfg.pop("background_layers", None) is not None else 0
    assert removed == 1, f"в боевом pipeline.yaml не нашёлся background_layers у scene_source (убрано {removed})"
    (tmp_path / "pipeline.yaml").write_text(yaml.safe_dump(pipeline_raw, allow_unicode=True), encoding="utf-8")

    app_raw = yaml.safe_load(_APP_YAML.read_text(encoding="utf-8"))
    discovery = app_raw["discovery"]
    # Пути манифеста относительны каталога манифеста; он теперь в tmp_path — делаем абсолютными.
    for key in ("plugin_paths", "service_paths"):
        discovery[key] = [str((_APP_DIR / p).resolve()) for p in discovery.get(key, [])]
    app_raw["pipeline"] = "pipeline.yaml"
    app_raw["system"] = str((_APP_DIR / "system.yaml").resolve())
    tmp_app = tmp_path / "app.yaml"
    tmp_app.write_text(yaml.safe_dump(app_raw, allow_unicode=True), encoding="utf-8")
    return tmp_app


@pytest.fixture
def live_backend(tmp_path: Path):
    """Полный стенд ``line_sim`` (сплошной фон) на порту 8766; убивает дерево процессов на выходе."""
    for port in (_LINE_SIM_PORT, _MODBUS_PORT, _MJPEG_PORT):
        _assert_port_free(port)
    tmp_app = _write_solid_background_app(tmp_path)

    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    def _launcher():
        from multiprocess_framework.modules.app_module import build_app

        return build_app(tmp_app)

    harness = BackendHarness(launcher_factory=_launcher, port=_LINE_SIM_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log
        for port in (_LINE_SIM_PORT, _MODBUS_PORT, _MJPEG_PORT):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _port_is_open("127.0.0.1", port, timeout=0.3):
                time.sleep(0.2)
            assert not _port_is_open("127.0.0.1", port, timeout=0.3), (
                f"порт {port} всё ещё принимает соединения после harness.stop() — осиротевший процесс"
            )


def _capture_stream(url: str, seconds: float) -> list[tuple[float, bytes]]:
    """Читать ОДНО соединение MJPEG ``seconds`` секунд; вернуть [(метка приёма, JPEG)] по порядку.

    Только чтение и разбор по маркерам SOI/EOI, без декодирования внутри цикла (декодирование
    1440x1080 задержало бы чтение и исказило метки)."""
    frames: list[tuple[float, bytes]] = []
    conn = urllib.request.urlopen(url, timeout=5.0)
    try:
        buf = b""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            chunk = conn.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start == -1:
                    buf = b""
                    break
                stop = buf.find(b"\xff\xd9", start)
                if stop == -1:
                    buf = buf[start:]
                    break
                frames.append((time.monotonic(), buf[start : stop + 2]))
                buf = buf[stop + 2 :]
    finally:
        conn.close()
    return frames


def _disc(jpeg: bytes) -> tuple[float, int] | None:
    """(центр масс по x, площадь) крупнейшей области «не фон», не касающейся границы; иначе None."""
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    height, width = frame.shape[:2]
    background = np.median(frame[:16, :16].reshape(-1, 3), axis=0)
    diff = np.abs(frame.astype(np.int16) - background.astype(np.int16)).max(axis=2)
    mask = (diff > _BACKGROUND_TOL).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best: tuple[float, int] | None = None
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < _MIN_DISC_AREA_PX or x <= 0 or y <= 0 or x + w >= width or y + h >= height:
            continue
        if best is None or area > best[1]:
            best = (float(centroids[i][0]), area)
    return best


def _describe(steps: list[float], extra: str) -> str:
    if not steps:
        return f"шагов нет; {extra}"
    mean = statistics.fmean(steps)
    stdev = statistics.pstdev(steps)
    return (
        f"шагов={len(steps)} среднее={mean:.3f} stdev={stdev:.3f} min={min(steps):.3f} max={max(steps):.3f}; "
        f"{extra}\nсписок шагов (px): {[round(s, 2) for s in steps]}"
    )


@pytest.mark.timeout(240)
def test_red7_disc_step_between_adjacent_frames_within_one_px_of_mean(live_backend) -> None:
    # Прогрев: ждём первый кадр (сборка стенда), затем даём энкодеру и спавну набрать ход.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            if _capture_stream(_MJPEG_URL, 1.0):
                break
        except OSError:
            time.sleep(0.5)
    else:
        pytest.fail("MJPEG :8091 не отдал ни одного кадра за 30 с")
    time.sleep(2.0)

    frames = _capture_stream(_MJPEG_URL, _CAPTURE_SECONDS)
    assert len(frames) >= _MIN_ADJACENT_PAIRS + 1, f"за {_CAPTURE_SECONDS} с получено всего {len(frames)} кадров"

    gaps = [b[0] - a[0] for a, b in zip(frames, frames[1:])]
    gap_limit = _ADJACENCY_GAP_FACTOR * statistics.median(gaps)
    discs = [_disc(jpeg) for _t, jpeg in frames]

    steps: list[float] = []
    skipped_gap = skipped_disc = 0
    for i in range(1, len(frames)):
        if gaps[i - 1] > gap_limit:
            skipped_gap += 1  # пропущенный кадр: пара не соседняя, шаг ~2x не засчитывается
            continue
        a, b = discs[i - 1], discs[i]
        if a is None or b is None:
            skipped_disc += 1
            continue
        dx = b[0] - a[0]
        if abs(dx) >= _MAX_SAME_DISC_DX_PX or abs(b[1] - a[1]) > _MAX_AREA_RATIO_DEV * a[1]:
            skipped_disc += 1
            continue
        steps.append(dx)

    context = (
        f"кадров={len(frames)}, медианный интервал={statistics.median(gaps) * 1000:.1f} мс, "
        f"исключено по интервалу (пропуск кадра)={skipped_gap}, исключено по диску={skipped_disc}"
    )
    print(f"\n[C-87 live] {_describe(steps, context)}")
    assert len(steps) >= _MIN_ADJACENT_PAIRS, f"мало соседних пар кадров с диском: {_describe(steps, context)}"

    mean = statistics.fmean(steps)
    assert abs(mean) > _MIN_MEAN_STEP_PX, (
        f"лента не едет в кадре (средний шаг {mean:.3f} px): {_describe(steps, context)}"
    )
    worst = max(abs(s - mean) for s in steps)
    assert worst <= _STEP_TOLERANCE_PX, (
        f"шаг диска вышел за ±{_STEP_TOLERANCE_PX} px от среднего (худшее отклонение {worst:.3f}): "
        f"{_describe(steps, context)}"
    )
