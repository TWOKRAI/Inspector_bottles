# -*- coding: utf-8 -*-
"""Task 2.2 — независимый RED, живой стенд (тестер, worktree на 362a319a, ДО реализации).

Гейт ``LINE_SIM_LIVE=1`` — тот же приём, что ``backend_ctl/tests/test_probe_acceptance_app_param.py::
test_live_line_sim_run`` (единственный прецедент этого имени переменной в репозитории, найден
grep'ом, не угадан): полный трёхпроцессный стенд, порт backend_ctl фиксирован (8766 —
``LINE_SIM_PORT`` из того же файла), НИКОГДА не запускать по умолчанию.

Сегодня ``apps/line_sim/pipeline.yaml`` держит процесс ``camera`` на
``Plugins.sources.camera_service.plugin.CameraServicePlugin`` (симулятор-заглушка), а НЕ на
новом ``SceneSourcePlugin`` — переключение проводов на ``scene_source`` входит в Task 2.2
разработчика. Поэтому весь файл сегодня либо падает при сборке стенда (если разработчик ещё
не менял ``pipeline.yaml``+``scene_source`` не существует), либо (после частичной правки)
красен по КОНКРЕТНЫМ причинам, названным в каждом тесте. Источники API:
``backend_ctl.harness.BackendHarness``, ``backend_ctl.driver.BackendDriver.introspect_telemetry``
(докстринг: ``levels.state.plugins.<writer>.<metric>``), ``Services.robot_comm.core.client.RobotClient``
+ ``Services.vfd_comm.core.client.VfdClient`` (мост, ``BRIDGE_MAP`` по умолчанию) — образцы,
``apps/line_sim/tests/test_f1_task11_acceptance.py``.

Догадка тестера: путь мира ``sim.belt.encoder.value`` (лист) — из DESIGN брифа
(``ctx.state_proxy.set("sim.belt.encoder", {"value": ..., ...})``), не из кода.
"""

from __future__ import annotations

import os
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from backend_ctl.harness import BackendHarness
from Plugins.sim.scene_source.plugin import _BACKGROUND_BGR
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.vfd_comm.core.client import VfdClient

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("LINE_SIM_LIVE") != "1",
        reason="живой прогон полного стенда сима — только явно, LINE_SIM_LIVE=1",
    ),
    pytest.mark.timeout(120),
]

_APP_DIR = Path(__file__).resolve().parents[1]
_APP_YAML = _APP_DIR / "app.yaml"

_LINE_SIM_PORT = 8766  # литерал контракта (backend_ctl/tests/test_probe_acceptance_app_param.py)
_ROBOT_HOST = "127.0.0.1"
_MODBUS_PORT = 5021
_ROBOT_UNIT_ID = 2
_MJPEG_PORT = 8091
_MJPEG_URL = "http://127.0.0.1:8091/"
_ENCODER_PATH = "sim.belt.encoder.value"


def _build_line_sim_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_APP_YAML)


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _assert_port_free(port: int) -> None:
    """8766/5021/8091 — литералы контракта, НЕ выводим другой порт при занятости
    (TRAPS брифа: держать 8765 прототипа нетронутым, а не бегать от коллизии)."""
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            pytest.fail(f"порт {port} занят до старта теста — {exc}")


def _command_succeeded(res: Any) -> bool:
    if not isinstance(res, dict):
        return False
    if "success" in res:
        return bool(res.get("success"))
    return res.get("status") == "ok"


def _result_field(res: dict, key: str) -> Any:
    if key in res:
        return res[key]
    nested = res.get("result")
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return None


@pytest.fixture
def line_sim_live_backend(tmp_path: Path):
    """Полный стенд ``apps/line_sim`` на ФИКСИРОВАННОМ порту 8766 (не случайном — контракт
    брифа), под ``LINE_SIM_LIVE=1``. Убивает всё дерево процессов на выходе (TRAPS: осиротевшие
    процессы — известная проблема прошлых прогонов, ``docs/reviews/2026-09-21_line-sim-
    observability-acceptance.md`` §8)."""
    for port in (_LINE_SIM_PORT, _MODBUS_PORT, 8091):
        _assert_port_free(port)

    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_LINE_SIM_PORT)
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log
        for port in (_LINE_SIM_PORT, _MODBUS_PORT, 8091):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _port_is_open("127.0.0.1", port, timeout=0.3):
                time.sleep(0.2)
            assert not _port_is_open("127.0.0.1", port, timeout=0.3), (
                f"порт {port} всё ещё принимает соединения после harness.stop() — осиротевший процесс"
            )


def _get_encoder(drv: Any) -> int:
    res = drv.send_command("ProcessManager", "state.get", {"path": _ENCODER_PATH}, timeout=5.0)
    assert _command_succeeded(res), f"state.get({_ENCODER_PATH!r}) не удался: {res!r}"
    value = _result_field(res, "value")
    assert isinstance(value, int), f"state.get({_ENCODER_PATH!r}) вернул не int: {value!r}"
    return value


def _make_vfd_client() -> tuple[RobotClient, VfdClient]:
    robot = RobotClient(RobotConfig(host=_ROBOT_HOST, port=_MODBUS_PORT, unit_id=_ROBOT_UNIT_ID))
    assert robot.connect() is True, "RobotClient.connect() к 5021 не удался"
    return robot, VfdClient(transport=robot)


#: Допуск канала для маски «не фон» (JPEG — с потерями, фон в кадре не ровно
#: ``_BACKGROUND_BGR``).
_SPRITE_COLOR_TOL = 40


def _sprite_centroid_x_by_color(frame: np.ndarray, tol: int = _SPRITE_COLOR_TOL) -> float:
    """Центр масс столбцов кадра по пикселям, отличным от фона сцены (±tol/канал).

    Решение ведущего 2026-09-21 (взамен общего диффа против эталона): дифф
    против кадра-эталона путал «объект сдвинулся» с «фон рядом чуть другой»
    (JPEG-артефакты, шум кодека). Правка 2026-09-23 (Task 3.4): цвет спрайта-заглушки
    (`SPRITE_BGR`) исчез вместе с заглушкой — маска берёт всё, что не фон, то есть
    объекты каталога любого цвета.
    """
    b, g, r = _BACKGROUND_BGR
    frame_i = frame.astype(np.int16)
    background = (
        (np.abs(frame_i[:, :, 0] - b) <= tol)
        & (np.abs(frame_i[:, :, 1] - g) <= tol)
        & (np.abs(frame_i[:, :, 2] - r) <= tol)
    )
    mask = ~background
    weights = mask.sum(axis=0).astype(float)
    assert weights.sum() > 0, f"объектов не видно: весь кадр — фон {_BACKGROUND_BGR} (±{tol}/канал)"
    return float(np.average(np.arange(frame.shape[1]), weights=weights))


def _not_background_column_profile(frame: np.ndarray, tol: int = _SPRITE_COLOR_TOL) -> np.ndarray:
    """Профиль «не фон» по столбцам — то же условие маски, что у
    :func:`_sprite_centroid_x_by_color`, но без взвешенного среднего (само среднее
    и есть уязвимость P5, см. :func:`_profile_shift_px`)."""
    b, g, r = _BACKGROUND_BGR
    frame_i = frame.astype(np.int16)
    background = (
        (np.abs(frame_i[:, :, 0] - b) <= tol)
        & (np.abs(frame_i[:, :, 1] - g) <= tol)
        & (np.abs(frame_i[:, :, 2] - r) <= tol)
    )
    return (~background).sum(axis=0).astype(float)


def _profile_shift_px(profile_a: np.ndarray, profile_b: np.ndarray) -> float:
    """Сдвиг (px) профиля ``profile_b`` относительно ``profile_a`` — пик 1-D
    кросс-корреляции ``np.correlate(a - mean, b - mean, mode="full")``.

    Фикс ревью P5: центр масс по цвету — среднее координат столбцов «не фон»,
    и при НЕСКОЛЬКИХ одинаковых объектах на ленте (реальный движок Task 3.4, не
    один спрайт-заглушка Task 2.2) это среднее инвариантно к сдвигу на период
    между объектами — сцена «едет», а центр масс стоит на месте (замер ревью:
    320.8 -> 317.3 px за 3с при пороге ``> 1.0``, движущаяся лента читалась как
    стоящая, и наоборот). Кросс-корреляция профилей ловит РЕАЛЬНЫЙ сдвиг паттерна,
    а не среднее координат.
    """
    a0 = profile_a - profile_a.mean()
    b0 = profile_b - profile_b.mean()
    corr = np.correlate(a0, b0, mode="full")
    lag = int(np.argmax(corr)) - (len(b0) - 1)
    return float(lag)


def _capture_frame_http(url: str, timeout_s: float = 5.0) -> np.ndarray:
    """Прочитать РОВНО один JPEG-кадр сырым HTTP из multipart-потока, декодировать.

    Решение ведущего 2026-09-21: ``cv2.VideoCapture`` на живом MJPEG держит
    собственный внутренний буфер приёма — два ``cap.read()`` подряд не
    гарантируют СВЕЖИЕ, РАЗНЕСЁННЫЕ ВО ВРЕМЕНИ кадры (замер разработчика:
    сырой HTTP-опрос того же потока показывал РАЗНЫЕ байты на каждом снятии,
    пока ``cv2.VideoCapture`` в тесте отдавал один и тот же кадр). Здесь —
    свежее соединение на каждый вызов, чтения нет буфера, который можно
    спутать со старым кадром.
    """
    deadline = time.monotonic() + timeout_s
    conn = urllib.request.urlopen(url, timeout=timeout_s)
    try:
        buf = b""
        while time.monotonic() < deadline:
            chunk = conn.read(8192)
            if not chunk:
                break
            buf += chunk
            start = buf.find(b"\xff\xd8")  # JPEG SOI
            if start == -1:
                continue
            end = buf.find(b"\xff\xd9", start)  # JPEG EOI
            if end == -1:
                continue
            jpeg_bytes = buf[start : end + 2]
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                return frame
            buf = buf[end + 2 :]
    finally:
        conn.close()
    pytest.fail(f"не удалось прочитать один JPEG-кадр с {url} за {timeout_s}с")


# --------------------------------------------------------------------------- #
# Критерий: энкодер строго растёт в дереве состояний                          #
# --------------------------------------------------------------------------- #


def test_state_get_encoder_grows(line_sim_live_backend) -> None:
    """Пин: два снятия ``state.get(sim.belt.encoder.value)`` с интервалом 1с, второе строго
    больше первого."""
    _harness, drv = line_sim_live_backend
    first = _get_encoder(drv)
    time.sleep(1.0)
    second = _get_encoder(drv)
    assert second > first, f"encoder не вырос за 1с: {first} -> {second}"


# --------------------------------------------------------------------------- #
# Критерий: команда ПЧ «стоп» замораживает энкодер, «пуск» возобновляет рост  #
# --------------------------------------------------------------------------- #


def test_vfd_stop_freezes_and_start_resumes(line_sim_live_backend) -> None:
    """Пин: ``VfdClient.stop()`` -> два снятия энкодера подряд равны; ``run(freq_hz>0)`` ->
    рост возобновляется."""
    _harness, drv = line_sim_live_backend
    robot, vfd = _make_vfd_client()
    try:
        assert vfd.stop() is True, "VfdClient.stop() не подтверждён транспортом"
        time.sleep(0.3)  # дать Lua/мосту применить команду

        frozen_a = _get_encoder(drv)
        time.sleep(1.0)
        frozen_b = _get_encoder(drv)
        assert frozen_a == frozen_b, f"encoder продолжил расти после stop(): {frozen_a} -> {frozen_b}"

        assert vfd.run(freq_hz=20.0) is True, "VfdClient.run(freq_hz=20.0) не подтверждён"
        time.sleep(0.3)

        resumed_a = _get_encoder(drv)
        time.sleep(1.0)
        resumed_b = _get_encoder(drv)
        assert resumed_b > resumed_a, f"encoder не возобновил рост после run(): {resumed_a} -> {resumed_b}"
    finally:
        robot.disconnect()


# --------------------------------------------------------------------------- #
# Критерий: MJPEG-кадры — спрайт едет, пока лента едет, и стоит, пока стоп    #
# --------------------------------------------------------------------------- #


def test_mjpeg_sprite_follows_belt(line_sim_live_backend) -> None:
    """Пин (фикс ревью P5, заменяет центр масс — см. :func:`_profile_shift_px`): паттерн
    объектов сцены в кадрах ``http://127.0.0.1:8091/`` сдвигается больше чем на 2 px,
    пока лента едет, и не больше чем на 1 px, пока лента стоит (после команды ПЧ «стоп»).

    Измерение — каждый кадр читается свежим HTTP-соединением (:func:`_capture_frame_http`,
    решение ведущего 2026-09-21), сдвиг — 1-D кросс-корреляция профиля «не фон» по столбцам
    (:func:`_profile_shift_px`), НЕ центр масс: с несколькими одинаковыми объектами (Task 3.4)
    центр масс инвариантен к сдвигу на период между ними и тест был вакуумным (не ловил ни
    едущую, ни стоящую ленту — см. докстринг :func:`_profile_shift_px`)."""
    _harness, drv = line_sim_live_backend
    robot, vfd = _make_vfd_client()
    try:
        moving_a = _capture_frame_http(_MJPEG_URL)
        time.sleep(0.3)
        moving_b = _capture_frame_http(_MJPEG_URL)
        lag = _profile_shift_px(_not_background_column_profile(moving_a), _not_background_column_profile(moving_b))
        assert abs(lag) > 2.0, f"паттерн объектов не сдвинулся, пока лента едет (лаг корреляции={lag})"

        assert vfd.stop() is True
        time.sleep(0.5)
        stopped_a = _capture_frame_http(_MJPEG_URL)
        time.sleep(1.0)
        stopped_b = _capture_frame_http(_MJPEG_URL)
        stop_lag = _profile_shift_px(
            _not_background_column_profile(stopped_a), _not_background_column_profile(stopped_b)
        )
        assert abs(stop_lag) <= 1.0, f"паттерн объектов продолжил ехать после stop() (лаг корреляции={stop_lag})"
    finally:
        robot.disconnect()


# --------------------------------------------------------------------------- #
# Краевой случай: только camera (без robot) — кадры идут, ошибок нет         #
# --------------------------------------------------------------------------- #


def test_camera_alone_serves_frames(tmp_path: Path) -> None:
    """Пин (ревью Task 2.2 итерация 1 — снят xfail, тест выполняется по-настоящему):
    процесс ``camera`` без ``robot`` -> MJPEG отдаёт кадры (спрайт стоит в spawn —
    энкодер растить некому), в ``errors.log``/``critical.log`` (ОБЩИЕ для всех
    процессов, в корне ``log_dir`` — ``ACCEPTANCE_CHECKLIST.md:61``, не per-process)
    нет ни строки.

    Фикстурные ``app.yaml``/``pipeline.yaml`` пишутся в ``tmp_path`` ИЗ РЕАЛЬНЫХ
    файлов (``yaml.safe_load`` + фильтр процесса ``robot``) — не рукописная копия:
    расхождение с настоящей проводкой (класс плагина, порт mjpeg, observability)
    исключено по построению, а не по надежде переписать её дважды одинаково.

    ``discovery.plugin_paths`` и ``system`` — АБСОЛЮТНЫЕ пути на реальные
    ``Plugins/sim``/``apps/line_sim/system.yaml``: относительный путь исходного
    ``app.yaml`` (``../../Plugins/sim``) резолвится от каталога МАНИФЕСТА
    (``manifest.py:_resolve``), а манифест этого теста лежит в ``tmp_path``, на
    другой глубине от репозитория."""
    import yaml

    for port in (_LINE_SIM_PORT, _MJPEG_PORT, _MODBUS_PORT):
        _assert_port_free(port)

    pipeline_raw = yaml.safe_load((_APP_YAML.parent / "pipeline.yaml").read_text(encoding="utf-8"))
    # pult (Task 2.3b) — клиент robot: без него опрос belt.status пишет no_route в
    # errors.log, а случай про камеру, не про пульт, — вырезается вместе с robot.
    pipeline_raw["processes"] = [p for p in pipeline_raw["processes"] if p["process_name"] not in ("robot", "pult")]
    assert {p["process_name"] for p in pipeline_raw["processes"]} == {"camera", "mjpeg"}, (
        f"фильтр процессов robot/pult промахнулся: {pipeline_raw['processes']!r}"
    )
    (tmp_path / "pipeline.yaml").write_text(yaml.safe_dump(pipeline_raw, allow_unicode=True), encoding="utf-8")

    _camera_proc = next(p for p in pipeline_raw["processes"] if p["process_name"] == "camera")
    _scene_cfg = next(pl for pl in _camera_proc["plugins"] if pl["plugin_name"] == "scene_source")
    pipeline_raw_height = _scene_cfg["resolution_height"]
    pipeline_raw_width = _scene_cfg["resolution_width"]

    app_raw = yaml.safe_load(_APP_YAML.read_text(encoding="utf-8"))
    app_raw["discovery"]["plugin_paths"] = [str((_APP_DIR / "../../Plugins/sim").resolve())]
    app_raw["discovery"]["service_paths"] = []
    app_raw["pipeline"] = "pipeline.yaml"
    app_raw["system"] = str((_APP_DIR / "system.yaml").resolve())
    tmp_app_yaml = tmp_path / "app.yaml"
    tmp_app_yaml.write_text(yaml.safe_dump(app_raw, allow_unicode=True), encoding="utf-8")

    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    def _build_camera_alone_launcher():
        from multiprocess_framework.modules.app_module import build_app

        return build_app(tmp_app_yaml)

    harness = BackendHarness(launcher_factory=_build_camera_alone_launcher, port=_LINE_SIM_PORT)
    try:
        harness.start()

        frame = _capture_frame_http(_MJPEG_URL)
        # Литералы = resolution_height/width из apps/line_sim/pipeline.yaml. Сверяем с
        # конфигом отдельной проверкой, чтобы тест не «соглашался с любым ответом»:
        # размер кадра и конфиг стенда должны совпасть ОБА с числами ниже.
        # Task 5.3b: сим подогнан под кадр боевого рецепта (1440x1080) — литералы
        # правятся осознанно (сам тест просил это в старом комментарии), не подгонкой.
        assert (pipeline_raw_height, pipeline_raw_width) == (1080, 1440), (
            f"pipeline.yaml сменил размер кадра ({pipeline_raw_height}x{pipeline_raw_width}) — "
            "поправь литералы в этом тесте осознанно, а не подгонкой"
        )
        assert frame.shape == (1080, 1440, 3), f"неожиданный размер кадра: {frame.shape}"

        # Без robot общий мир пуст, значит энкодера НЕТ вовсе — а не «энкодер стоит».
        # Гейт `_world_ready` (ревью Task 3.3a, находка 4) обязан в этом случае не дать
        # спавнеру тикнуть: объект на выдуманном spawn_encoder=0 раньше рождался и уезжал
        # в sim.objects. Проверяем наблюдаемое следствие: кадр — чистый фон, без объектов.
        uniq = np.unique(frame.reshape(-1, 3), axis=0)
        assert len(uniq) == 1, (
            f"без robot на кадре есть что-то кроме фона ({len(uniq)} различных цветов) — "
            "спавнер тикнул до появления мира (объект-призрак)"
        )
        assert tuple(int(v) for v in uniq[0]) == _BACKGROUND_BGR, (
            f"цвет фона на кадре {tuple(int(v) for v in uniq[0])} != _BACKGROUND_BGR={_BACKGROUND_BGR}"
        )

        errors_path = log_dir / "errors.log"
        critical_path = log_dir / "critical.log"
        errors_text = errors_path.read_text(encoding="utf-8") if errors_path.is_file() else ""
        critical_text = critical_path.read_text(encoding="utf-8") if critical_path.is_file() else ""
        assert errors_text == "", f"errors.log не пуст без robot: {errors_text!r}"
        assert critical_text == "", f"critical.log не пуст без robot: {critical_text!r}"
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log
        for port in (_LINE_SIM_PORT, _MJPEG_PORT, _MODBUS_PORT):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _port_is_open("127.0.0.1", port, timeout=0.3):
                time.sleep(0.2)
            assert not _port_is_open("127.0.0.1", port, timeout=0.3), (
                f"порт {port} всё ещё принимает соединения после harness.stop() — осиротевший процесс"
            )


# --------------------------------------------------------------------------- #
# Критерий: introspect_telemetry.levels видит belt_mm_s/encoder писателя      #
# --------------------------------------------------------------------------- #


def test_introspect_telemetry_levels(line_sim_live_backend) -> None:
    """Пин: ``levels.state.plugins.sim_robot_host`` содержит ``belt_mm_s`` и ``encoder``;
    после ``stop()`` ПЧ ``belt_mm_s == 0``. Без опроса ``sim_robot.status``.

    Разворот конверта — решение ведущего 2026-09-21: ``drv.introspect_telemetry``
    отдаёт СЫРОЙ ответ команды (конверт ``{..., "result": {..., "levels": ...}}``),
    ``levels`` живёт в ``result``, а не на верхнем уровне ответа — та же дорога,
    что уже здесь есть, :func:`_result_field`."""
    _harness, drv = line_sim_live_backend
    res = drv.introspect_telemetry("robot")
    plugins = (_result_field(res, "levels") or {}).get("state", {}).get("plugins", {})
    writer = plugins.get("sim_robot_host")
    assert isinstance(writer, dict), f"levels.state.plugins.sim_robot_host отсутствует/не dict: {res!r}"
    assert "belt_mm_s" in writer, f"нет belt_mm_s в levels писателя sim_robot_host: {writer!r}"
    assert "encoder" in writer, f"нет encoder в levels писателя sim_robot_host: {writer!r}"
    # На ходу до первой команды ПЧ — лента по умолчанию (enc_rate=7 за тик 0.01 с):
    # 7 × 0.144473 / 0.01 = 101.1311 мм/с. Без этой строки публикация «всегда 0»
    # проходила живой тест зелёной (инъекция L2 ведущего, 2026-09-22).
    assert writer["belt_mm_s"] == pytest.approx(101.1311, abs=0.5), f"belt_mm_s на ходу: {writer!r}"

    robot, vfd = _make_vfd_client()
    try:
        assert vfd.stop() is True
        time.sleep(1.5)  # дать телеметрийному тику (interval_sec=1.0, system.yaml) обновиться
        res2 = drv.introspect_telemetry("robot")
        writer2 = (_result_field(res2, "levels") or {}).get("state", {}).get("plugins", {}).get("sim_robot_host", {})
        assert writer2.get("belt_mm_s") == 0, f"belt_mm_s != 0 после stop(): {writer2!r}"
    finally:
        robot.disconnect()
