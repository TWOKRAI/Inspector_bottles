# -*- coding: utf-8 -*-
"""Hazard-тесты автора для StreamSourceBackend (Task 1.2a плана line-sim).

Приёмочные тесты (``test_stream_source_acceptance.py``) пинят наблюдаемый контракт
плагина/схемы. Эти тесты — про опасности самого механизма ``StreamSourceBackend``,
видимые только автору, учитывая КАК он устроен:

  - ``start()`` всегда создаёт НОВЫЙ ``cv2.VideoCapture`` и освобождает предыдущий
    (``_release_capture()``) — повторный ``start()`` без ``close()`` не должен течь
    handle'ами (см. DESIGN брифа: "утечка VideoCapture?").
  - ``stop()`` не освобождает ``VideoCapture`` (симметрично ``FileSourceBackend``) —
    ``stop()`` -> ``start()`` без ``close()`` обязан пересоздать соединение, а не
    молча продолжать работу со старым (возможно, оборванным) ``cap``.
  - ``capture_frame()`` после ``close()`` не должен падать (backend "мёртв", но
    вызов должен быть безопасным no-op, а не AttributeError/segfault).
  - пустой ``stream_url`` — ``cv2.VideoCapture("")`` не должен ни зависать, ни
    бросать из ``start()``.

Никакой реальной сети/сервера здесь не поднимаем — ``cv2.VideoCapture`` мокается,
чтобы тесты были быстрыми и детерминированными (это ОТДЕЛЬНАЯ ценность от
приёмочных, которые проверяют реальный cv2+сеть).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from Plugins.sources.camera_service.backends.stream_source import StreamSourceBackend


def _fake_cap(opened: bool = True, read_ok: bool = True) -> MagicMock:
    cap = MagicMock()
    cap.isOpened.return_value = opened
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    cap.read.return_value = (read_ok, frame if read_ok else None)
    cap.grab.return_value = read_ok
    cap.retrieve.return_value = (read_ok, frame if read_ok else None)
    return cap


def test_repeated_start_releases_previous_videocapture() -> None:
    """Повторный start() на живом backend'е обязан освободить старый VideoCapture.

    Опасность: если start() просто перезаписывает self._cap новым объектом без
    вызова .release() на старом, старый VideoCapture (файловый дескриптор/сокет)
    остаётся открытым — утечка handle'ов при каждом set_camera_type туда-обратно
    или при восстановлении после обрыва (см. DESIGN брифа).
    """
    caps = [_fake_cap(), _fake_cap()]
    with patch("cv2.VideoCapture", side_effect=caps):
        backend = StreamSourceBackend(stream_url="http://example.invalid/stream")
        backend.start()
        first_cap = backend._cap
        backend.start()  # повторный старт БЕЗ close()

    assert first_cap.release.called, "старый VideoCapture не освобождён при повторном start() — утечка handle"
    assert backend._cap is caps[1], "после второго start() backend должен работать с НОВЫМ VideoCapture"


def test_stop_then_start_without_close_reopens_capture() -> None:
    """stop() -> start() без close() должен создать НОВОЕ соединение, не переиспользовать старое.

    Опасность: если start() no-op'ает, когда self._cap уже не None (наивная проверка
    "если backend уже создан — ничего не делаем"), backend после обрыва не сможет
    восстановиться на cmd_start_capture без промежуточного close() (см. сценарий
    test_stream_broken_recovers_after_restart_capture в приёмочных).
    """
    caps = [_fake_cap(), _fake_cap()]
    with patch("cv2.VideoCapture", side_effect=caps):
        backend = StreamSourceBackend(stream_url="http://example.invalid/stream")
        backend.start()
        backend.stop()
        assert backend._cap is caps[0], "stop() не должен освобождать VideoCapture (симметрично FileSourceBackend)"
        backend.start()

    assert backend._cap is caps[1], "start() после stop() (без close()) обязан пересоздать VideoCapture"
    assert caps[0].release.called, "старый (потенциально оборванный) VideoCapture должен быть освобождён"


def test_capture_frame_after_close_is_safe_noop() -> None:
    """capture_frame() после close() не должен падать — backend "мёртв", но безопасен.

    Опасность: close() обнуляет self._cap; если capture_frame() не проверяет это,
    следующий вызов упадёт AttributeError на None вместо штатного [] от produce().
    """
    with patch("cv2.VideoCapture", return_value=_fake_cap()):
        backend = StreamSourceBackend(stream_url="http://example.invalid/stream")
        backend.start()
        backend.close()

    assert backend.capture_frame() is None, "capture_frame() после close() должен тихо вернуть None, не падать"


def test_empty_stream_url_does_not_raise_on_start() -> None:
    """Пустой stream_url — start() не должен бросать (симметрично контракту 'start() никогда не бросает').

    Опасность: пустая строка — валидный (хоть и бессмысленный) вход с границы процесса
    (Dict at Boundary, дефолт schema-поля stream_url=""); start() обязан вести себя
    так же терпимо, как с недоступным URL, а не по-разному в зависимости от формы строки.
    """
    with patch("cv2.VideoCapture", return_value=_fake_cap(opened=False, read_ok=False)) as spy:
        backend = StreamSourceBackend(stream_url="")
        backend.start()  # не должен бросить

    spy.assert_called_once()
    assert spy.call_args[0][0] == "", "пустая строка должна дойти до cv2.VideoCapture как есть, без подстановки"


def test_backend_lock_discipline_on_type_switch(tmp_path) -> None:
    """cmd_set_camera_type stream<->simulator под _backend_lock не должен звать backend вне лока.

    Опасность именно этого механизма: CameraServicePlugin._do_switch_camera_type()
    держит _backend_lock раздельными блоками (stop/close, потом create/start) — если
    между ними другой поток (message_processor) успеет прочитать self._backend, он
    увидит None ровно в момент переключения. Тест пинит НАБЛЮДАЕМЫЙ эффект: после
    переключения на stream и обратно на simulator backend всегда согласован с
    self._camera_type (не бывает "тип simulator, а backend всё ещё StreamSourceBackend").
    """
    from unittest.mock import MagicMock as _MM

    from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
    from Plugins.sources.camera_service.plugin import CameraServicePlugin

    with patch("cv2.VideoCapture", return_value=_fake_cap()):
        state = HealthState(log_only=False)
        ctx = _MM()
        ctx.config = {"camera_type": "stream", "stream_url": "http://example.invalid/stream"}
        ctx.health = HealthReporter(state, source="camera_service")
        plugin = CameraServicePlugin()
        plugin.configure(ctx)
        plugin.cmd_start_capture({})

        assert plugin._camera_type == "stream"
        assert type(plugin._backend).__name__ == "StreamSourceBackend"

        result = plugin.cmd_set_camera_type({"camera_type": "simulator"})
        assert result["status"] == "ok"
        assert plugin._camera_type == "simulator"
        assert type(plugin._backend).__name__ == "SimulatorBackend", (
            "после переключения на simulator backend обязан быть SimulatorBackend, а не оставшийся StreamSourceBackend"
        )

        result = plugin.cmd_set_camera_type({"camera_type": "stream"})
        assert result["status"] == "ok"
        assert plugin._camera_type == "stream"
        assert type(plugin._backend).__name__ == "StreamSourceBackend"


# --------------------------------------------------------------------------- #
# OPENCV_FFMPEG_CAPTURE_OPTIONS — что видит ffmpeg в момент открытия          #
# --------------------------------------------------------------------------- #
#
# Польза переменной замерена (см. докстринг `_ensure_ffmpeg_low_latency`): без неё
# после обрыва доезжает 2 кадра за 0.11 с, с ней — 1 кадр за 0.06 с. Разница в один
# кадр зависит от машины, порог на неё был бы флаки — поэтому сторожим вход ffmpeg,
# а не тайминг: значение в окружении В МОМЕНТ конструктора `cv2.VideoCapture`
# (именно оттуда OpenCV её читает). Имя хелпера и `setdefault` не проверяем.

_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
_LOW_LATENCY = "fflags;nobuffer|flags;low_delay"


def _env_seen_by_videocapture(monkeypatch) -> list:
    import os

    seen: list = []

    def _fake_capture(*args, **_kwargs):
        # Переменная действует только на FFmpeg-бэкенд: без CAP_FFMPEG OpenCV вправе
        # выбрать другой, и значение в окружении ничего бы не значило.
        assert args[1:2] == (cv2.CAP_FFMPEG,), f"поток открыт не через FFmpeg: {args!r}"
        seen.append(os.environ.get(_ENV))
        return MagicMock()

    monkeypatch.setattr(
        "Plugins.sources.camera_service.backends.stream_source.cv2.VideoCapture", _fake_capture
    )
    return seen


def test_videocapture_opens_with_low_latency_ffmpeg_options(monkeypatch) -> None:
    """Стрим открывается с низколатентными опциями — и при первом, и при повторном start()."""
    # setenv перед delenv: иначе monkeypatch не запомнит «переменной не было», и значение,
    # выставленное кодом, утечёт во все следующие тесты сессии.
    monkeypatch.setenv(_ENV, "x")
    monkeypatch.delenv(_ENV)
    seen = _env_seen_by_videocapture(monkeypatch)

    backend = StreamSourceBackend("http://127.0.0.1:1/")
    backend.start()
    backend.start()

    assert seen == [_LOW_LATENCY, _LOW_LATENCY]


def test_foreign_ffmpeg_options_are_not_overwritten(monkeypatch) -> None:
    """Значение, выставленное кем-то раньше (оператор, другой плагин), не перебивается."""
    monkeypatch.setenv(_ENV, "rtsp_transport;tcp")
    seen = _env_seen_by_videocapture(monkeypatch)

    StreamSourceBackend("http://127.0.0.1:1/").start()

    assert seen == ["rtsp_transport;tcp"]


def test_import_does_not_touch_process_environment() -> None:
    """Радиус — только стрим: импорт плагина (его делает КАЖДЫЙ процесс camera_service,
    включая hikvision/webcam/file) окружение не меняет. Чистый интерпретатор, иначе
    модуль уже импортирован этим же процессом."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if k != _ENV}
    code = (
        "import os, Plugins.sources.camera_service.plugin; "
        f"print(os.environ.get({_ENV!r}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=Path(__file__).resolve().parents[4],  # корень репо: пакет Plugins ищется от cwd
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "None"
