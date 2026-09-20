# -*- coding: utf-8 -*-
"""Приёмочные RED-тесты (Task 1.2 плана line-sim) для нового типа камеры ``stream``.

Независимый тестер, БЕЗ реализации (worktree на коммите ДО неё) — контракт ниже собран из
брифа lead'а (секция DESIGN), не из кода. ``camera_type: "stream"`` и поле ``stream_url``
сегодня НЕ существуют в ``CameraServiceConfig`` — при вызове ``create_backend("stream", ...)``
неизвестный тип молча падает на ``SimulatorBackend`` (см. ``backends/__init__.py:37-38``),
поэтому большинство тестов здесь падают AssertionError (наблюдаемое поведение — не то,
что заявлено критерием), не ImportError — форма RED для ``public-api-change``.

Контракт (из брифа, НЕ из кода):
  - ``camera_type: "stream"`` — новый вариант ``CameraTypeStr``;
  - ``stream_url: str`` — новое поле конфига (НЕ ``url``);
  - бэкенд для ``stream`` открывает URL как есть, БЕЗ сторожа ``os.path.isfile``
    (тот сейчас только в ``FileSourceBackend.start()``, ``file_source.py:35``);
  - ошибка стрима НЕ пробрасывается наружу из ``CameraServicePlugin.produce()``
    (``plugin.py:143-166``) — уходит в ``ctx.health.report_error(...)``, ``produce()``
    возвращает ``[]`` (тот же contain→report→degrade, что для остальных backend'ов,
    см. ``tests/test_health_fault.py``).

Харнесс — ``ctx = MagicMock()`` + реальный ``HealthReporter``/``HealthState``, тот же приём,
что ``tests/test_health_fault.py::_make_plugin_with_health`` (уже в этом каталоге, не мой
файл). ``ctx.config`` — простой dict (обхожу pydantic-валидацию ``CameraServiceConfig``
намеренно: контракт схемы РІП НЕ входит в предсказанные REDS брифа, только поведение
плагина/backend'а через прямой dict-конфиг, как делает существующий ``test_health_fault.py``).

Источник MJPEG для тестов — ``_MjpegTestServer`` НИЖЕ: минимальная тестовая фикстура
(``http.server.ThreadingHTTPServer``), НЕ продакшн-код и НЕ ``Plugins/sim/mjpeg_sink``
(тот вне области этого файла, см. FILES брифа) — просто живой сетевой источник, чтобы
``camera_type: stream`` было к чему подключиться.

Что НЕ проверяю (см. финальный отчёт, «что осталось непокрытым»):
  - точное имя поля backend-kwargs (``stream_url`` -> ``create_backend(**kwargs)``) —
    проверяю только конечное наблюдаемое поведение (produce()/cv2.VideoCapture), не
    внутренний путь передачи;
  - baseline ``camera_service`` тестов (0 failed, N passed) — измеряю отдельно, число
    называю в отчёте, не здесь.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from Plugins.sources.camera_service.plugin import CameraServicePlugin

pytestmark = pytest.mark.timeout(45)

_BOUNDARY = "testboundary"


def _make_test_frame(width: int = 64, height: int = 48, value: int = 90) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


class _MjpegTestHandler(BaseHTTPRequestHandler):
    """Тестовая MJPEG-раздача одного статического кадра в цикле (не продакшн-код)."""

    def log_message(self, *_args) -> None:  # тише в выводе pytest
        pass

    def do_GET(self) -> None:  # noqa: N802 — имя метода диктует BaseHTTPRequestHandler
        frame = self.server.test_frame  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
        self.end_headers()
        try:
            while not self.server.stop_flag.is_set():  # type: ignore[attr-defined]
                ok, jpg = cv2.imencode(".jpg", frame)
                if not ok:
                    break
                body = jpg.tobytes()
                self.wfile.write(f"--{_BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode())
                self.wfile.write(body)
                self.wfile.write(b"\r\n")
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # клиент отвалился/сервер остановлен — не тест-код


class _MjpegTestServer:
    """Живой тестовый MJPEG-источник на свободном (или явном) порту."""

    def __init__(self, frame: np.ndarray | None = None, port: int = 0) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _MjpegTestHandler)
        self._server.test_frame = frame if frame is not None else _make_test_frame()  # type: ignore[attr-defined]
        self._server.stop_flag = threading.Event()  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._stopped = False

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._server.stop_flag.set()  # type: ignore[attr-defined]
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)


def _assert_frame_from_test_server(frame: np.ndarray, expected_value: int = 90, tol: int = 20) -> None:
    """Пин на СОДЕРЖИМОЕ, не только форму: кадр должен быть СПЛОШНЫМ серым
    ``(expected_value, expected_value, expected_value)`` (``_make_test_frame()``), а не
    красным прямоугольником ``SimulatorBackend`` (BGR ``[0, 0, 200]`` — см.
    ``backends/simulator.py::FrameGenerator.generate_frame``).

    Проверка ПО КАНАЛАМ (не общий скаляр-mean по всем 3 каналам сразу), иначе первая
    версия этой проверки ложно ЗЕЛЕНЕЛА: на тесном кадре (64x48) прямоугольник 100x100
    закрывает весь холст BGR=[0,0,200], а mean по всем каналам (0+0+200)/3≈66.7 случайно
    попадает в допуск вокруг 90 — измерено при втором прогоне этого файла. По каналам
    B/G симулятора (~0) далеко от 90, дискриминатор надёжен независимо от размера кадра.
    """
    means = [float(np.mean(frame[:, :, ch])) for ch in range(3)]
    bad = [(ch, m) for ch, m in enumerate(means) if abs(m - expected_value) > tol]
    assert not bad, (
        f"среднее по каналам BGR={means} не близко к сплошному ({expected_value},)*3 (±{tol}) "
        f"по каналам {bad} — похоже на SimulatorBackend-заглушку (красный прямоугольник "
        f"BGR=[0,0,200] на чёрном холсте), а не на реальный кадр с тестового MJPEG-сервера"
    )


def _make_plugin_with_health(config: dict) -> tuple[CameraServicePlugin, HealthState, object]:
    """Собрать плагин с реальным health поверх mock-контекста (см. test_health_fault.py)."""
    state = HealthState(log_only=False)
    ctx = MagicMock()
    ctx.config = config
    ctx.health = HealthReporter(state, source="camera_service")
    plugin = CameraServicePlugin()
    plugin.configure(ctx)
    return plugin, state, ctx


# --------------------------------------------------------------------------- #
# Критерий 1: camera_type=stream -> produce() отдаёт BGR-кадр                 #
# --------------------------------------------------------------------------- #


def test_stream_produce_returns_bgr_frame() -> None:
    """Пин: живой MJPEG stream_url -> produce() отдаёт item с frame формы (H,W,3) uint8.

    Провал сегодня: camera_type='stream' неизвестен create_backend() -> молчаливый
    fallback на SimulatorBackend (Plugins/sources/camera_service/backends/__init__.py:37-38),
    который тоже отдаёт валидный (H,W,3) uint8 кадр нужного размера — формальная форма
    ПРОЙДЁТ. Различитель — ``_assert_frame_from_test_server``: кадр должен быть похож на
    сплошной тестовый цвет сервера, а не на чёрный холст симулятора.
    """
    server = _MjpegTestServer()
    server.start()
    try:
        width, height = 64, 48
        plugin, _state, _ctx = _make_plugin_with_health(
            {
                "camera_type": "stream",
                "stream_url": server.url,
                "resolution_width": width,
                "resolution_height": height,
            }
        )
        plugin.cmd_start_capture({})

        deadline = time.monotonic() + 10.0
        items: list = []
        while time.monotonic() < deadline and not items:
            items = plugin.produce()
            if not items:
                time.sleep(0.1)

        assert items, f"produce() не вернул кадр за 10с (camera_type=stream, url={server.url})"
        item = items[0]
        frame = item.get("frame")
        assert frame is not None, f"item без ключа 'frame': {item!r}"
        assert frame.shape == (height, width, 3), f"неверная форма кадра: {frame.shape}"
        assert frame.dtype == np.uint8, f"неверный dtype кадра: {frame.dtype}"
        assert item.get("width") == width and item.get("height") == height, (
            f"item.width/height не совпадают с конфигом: {item!r}"
        )
        _assert_frame_from_test_server(frame)
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# Критерий 1 (edge): недоступный stream_url -> report_error, не исключение    #
# --------------------------------------------------------------------------- #


def test_stream_bad_url_reports_error_not_raises() -> None:
    """Пин: stream_url недоступен -> produce() возвращает [] и НЕ бросает; ctx.health получил
    отказ (contain -> report -> degrade, тот же контракт, что у остальных backend'ов).

    Провал сегодня: camera_type='stream' -> SimulatorBackend fallback -> produce() отдаёт
    валидный кадр (result != []), health.error_count остаётся 0 — AssertionError, не
    ImportError/SyntaxError.
    """
    bad_url = "http://127.0.0.1:1/nonexistent-stream"  # порт 1 отказывает в соединении быстро
    plugin, state, _ctx = _make_plugin_with_health({"camera_type": "stream", "stream_url": bad_url})

    start_errors: list[Exception] = []

    def _start() -> None:
        try:
            plugin.cmd_start_capture({})
        except Exception as exc:  # noqa: BLE001 — ловим ЛЮБОЕ исключение из фонового потока теста
            start_errors.append(exc)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "cmd_start_capture завис (>5с) на заведомо недоступном URL"
    if start_errors:
        pytest.fail(
            f"cmd_start_capture бросил исключение при недоступном stream_url "
            f"(критерий пинит produce(), но старт тоже не должен падать): {start_errors[0]!r}"
        )

    deadline = time.monotonic() + 10.0
    saw_error = False
    while time.monotonic() < deadline:
        result = plugin.produce()
        assert result == [], f"produce() должен вернуть [] при недоступном stream_url, получили {result!r}"
        if state.error_count >= 1:
            saw_error = True
            break
        time.sleep(0.2)

    assert saw_error, (
        f"ctx.health.report_error не был вызван за 10с при недоступном stream_url: error_count={state.error_count}"
    )


# --------------------------------------------------------------------------- #
# Критерий 2: os.path.isfile НЕ применяется для stream (имя + эффект)         #
# --------------------------------------------------------------------------- #


def test_stream_does_not_call_isfile() -> None:
    """Пин: при camera_type=stream ``os.path.isfile`` ни разу не вызывается — И produce()
    реально отдал живой кадр с MJPEG-сервера (наблюдаемый эффект).

    Обе половины обязательны (см. докстринг DESIGN брифа): шпион на имя один сторожит
    ИМЯ функции, а не свойство — сегодня, ДО реализации, camera_type='stream' падает на
    SimulatorBackend, который тоже не зовёт isfile, так что без второй половины (реальный
    кадр со стрима) этот тест был бы ЗЕЛЁНЫМ уже сейчас и ничего бы не пиннил.
    """
    server = _MjpegTestServer()
    server.start()
    try:
        with patch("os.path.isfile") as spy_isfile:
            plugin, _state, _ctx = _make_plugin_with_health({"camera_type": "stream", "stream_url": server.url})
            plugin.cmd_start_capture({})

            deadline = time.monotonic() + 10.0
            items: list = []
            while time.monotonic() < deadline and not items:
                items = plugin.produce()
                if not items:
                    time.sleep(0.1)

            assert items, (
                "produce() не вернул кадр за 10с — без живого кадра проверка 'isfile не "
                "вызван' не пиннит ничего (могла остаться SimulatorBackend-заглушка)"
            )
            _assert_frame_from_test_server(items[0]["frame"])
        spy_isfile.assert_not_called()
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# Критерий 2 (наблюдаемый эффект): cv2.VideoCapture открыт той же строкой URL #
# --------------------------------------------------------------------------- #


def test_stream_opens_videocapture_with_same_url() -> None:
    """Пин: cv2.VideoCapture открывается РОВНО значением stream_url (без транформаций).

    Провал сегодня: SimulatorBackend fallback никогда не зовёт cv2.VideoCapture ->
    AssertionError "ни разу не был вызван".
    """
    server = _MjpegTestServer()
    server.start()
    try:
        real_video_capture = cv2.VideoCapture
        seen_calls: list[tuple[tuple, dict]] = []

        def _spy(*args, **kwargs):
            seen_calls.append((args, kwargs))
            return real_video_capture(*args, **kwargs)

        with patch("cv2.VideoCapture", side_effect=_spy):
            plugin, _state, _ctx = _make_plugin_with_health({"camera_type": "stream", "stream_url": server.url})
            plugin.cmd_start_capture({})
            # дать backend'у реально попытаться прочитать (некоторые реализации
            # открывают VideoCapture лениво на первом capture_frame(), а не в start()).
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not seen_calls:
                plugin.produce()
                time.sleep(0.1)

        assert seen_calls, "cv2.VideoCapture ни разу не был вызван при camera_type=stream"
        args, kwargs = seen_calls[0]
        opened_with = args[0] if args else kwargs.get("filename", kwargs.get("index"))
        assert opened_with == server.url, (
            f"cv2.VideoCapture открыт с {opened_with!r}, ожидали ровно stream_url={server.url!r}"
        )
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# Краевой случай: обрыв стрима -> report_error -> восстановление после        #
# повторного start_capture (стоп/старт того же backend'а)                     #
# --------------------------------------------------------------------------- #


def test_stream_broken_recovers_after_restart_capture() -> None:
    """Пин: источник стрима падает -> produce() не виснет и не бросает (report_error);
    после stop_capture -> сервер снова слушает ТОТ ЖЕ порт -> start_capture -> кадры
    возобновляются.

    Хрупко (см. финальный отчёт): пересоздаём сервер на том же порту — на некоторых ОС
    возможен TIME_WAIT, из-за которого повторный bind на тот же порт временно откажет
    (ThreadingHTTPServer.allow_reuse_address=1 смягчает это, не устраняет полностью).
    """
    server = _MjpegTestServer()
    server.start()
    port = server.port
    try:
        plugin, state, _ctx = _make_plugin_with_health(
            {"camera_type": "stream", "stream_url": f"http://127.0.0.1:{port}/"}
        )
        plugin.cmd_start_capture({})

        deadline = time.monotonic() + 10.0
        items: list = []
        while time.monotonic() < deadline and not items:
            items = plugin.produce()
            if not items:
                time.sleep(0.1)
        assert items, "produce() не отдал ни одного кадра до обрыва — тест обрыва непоказателен"

        # --- обрыв: источник падает ---
        server.stop()

        deadline = time.monotonic() + 8.0
        saw_error = False
        while time.monotonic() < deadline:
            result_holder: dict = {}

            def _call() -> None:
                result_holder["r"] = plugin.produce()

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            t.join(timeout=3.0)
            assert not t.is_alive(), "produce() завис (>3с) после обрыва стрима"
            result = result_holder.get("r")
            assert result == [], f"produce() после обрыва должен вернуть [], получили {result!r}"
            if state.error_count >= 1:
                saw_error = True
                break
            time.sleep(0.3)
        assert saw_error, f"report_error не зафиксирован за 8с после обрыва стрима: error_count={state.error_count}"

        # --- восстановление: тот же порт снова слушает ---
        plugin.cmd_stop_capture({})
        server2 = _MjpegTestServer(port=port)
        server2.start()
        try:
            plugin.cmd_start_capture({})
            deadline = time.monotonic() + 10.0
            recovered: list = []
            while time.monotonic() < deadline and not recovered:
                recovered = plugin.produce()
                if not recovered:
                    time.sleep(0.2)
            assert recovered, f"после restart_capture кадры не возобновились за 10с (порт {port})"
        finally:
            server2.stop()
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# Дыра, дописанная ВЕДУЩИМ после приёмки тестера (2026-09-21)                 #
# --------------------------------------------------------------------------- #
#
# Тестер честно назвал это в своём отчёте: харнесс выше кормит плагин СЫРЫМ dict
# (``ctx.config``), обходя pydantic, поэтому ни один тест файла не касается схемы
# ``CameraServiceConfig``. Без пина ниже реализация может пройти ВСЮ приёмку, не тронув
# ``config.py``: бэкенд заработает, а боевой рецепт с ``camera_type: stream`` упадёт на
# валидации конфига — приёмка зелёная, стенд мёртвый.
#
# Вторая половина — про молчаливый откат: ``create_backend`` неизвестный тип НЕ
# отвергает, а подменяет симулятором (``backends/__init__.py:37-38``). Именно этот
# откат заставил тестера переписать проверку цвета: без ``"stream"`` в ``CAMERA_TYPES``
# камера отдаёт валидные кадры заглушки и выглядит рабочей.


def test_stream_is_declared_in_config_schema_and_factory() -> None:
    """Пин: ``stream`` — полноправный тип в СХЕМЕ и в таблице фабрики, не только в бэкенде.

    Провал сегодня: ``CameraTypeStr`` не содержит ``"stream"`` → pydantic отвергает
    конфиг; ``CAMERA_TYPES`` не содержит ``"stream"`` → молчаливый откат на симулятор.
    """
    from Plugins.sources.camera_service.backends import CAMERA_TYPES
    from Plugins.sources.camera_service.config import CameraServiceConfig

    assert "stream" in CAMERA_TYPES, (
        f"'stream' не объявлен в CAMERA_TYPES={CAMERA_TYPES} — create_backend() молча "
        f"подменит его симулятором (backends/__init__.py:37-38) вместо отказа"
    )

    cfg = CameraServiceConfig(camera_type="stream", stream_url="http://127.0.0.1:8090/")
    assert cfg.camera_type == "stream"
    assert cfg.stream_url == "http://127.0.0.1:8090/", (
        f"поле конфига должно называться stream_url (не url): получили {cfg!r}"
    )

    # Round-trip через dict — граница процессов возит именно его (правило Dict at Boundary).
    restored = CameraServiceConfig(**cfg.model_dump())
    assert restored.camera_type == "stream" and restored.stream_url == cfg.stream_url


def test_unknown_camera_type_is_rejected_by_schema() -> None:
    """Негативный контроль к предыдущему: схема не пропускает произвольный тип.

    Без него первый тест согласится с реализацией, которая расширила ``CameraTypeStr``
    до голого ``str`` — тогда 'stream' "проходит", но проходит и любая опечатка, а
    молчаливый откат на симулятор остаётся.
    """
    import pydantic

    from Plugins.sources.camera_service.config import CameraServiceConfig

    with pytest.raises(pydantic.ValidationError):
        CameraServiceConfig(camera_type="strem")  # опечатка в 'stream'
