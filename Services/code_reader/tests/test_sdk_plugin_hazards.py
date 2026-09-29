# -*- coding: utf-8 -*-
"""Hazard-тесты автора плагина `code_reader_sdk` (Task 6.3).

Только то, что ломается в ЭТОМ механизме при том, как он построен: гонка потока
захвата с `produce()` на одном замке, `release_device` под нагрузкой и из колбэка,
момент чтения `reader_factory`. Приёмку по контракту держит слепой набор
`test_sdk_plugin.py` — здесь его не дублируем.

Любое ожидание — с дедлайном (daemon-поток + join): pytest-timeout в venv нет.
"""

from __future__ import annotations

import functools
import sys
import threading
import time

from Services.code_reader.core.result import ReadStatus
from Services.code_reader.core.sdk_frame import SdkFrame
from Services.code_reader.core.sdk_reader import SdkCodeReader
from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin
from Services.code_reader.tests.test_sdk_plugin import (  # noqa: F401 — make_plugin это pytest-фикстура
    PROCESS_NAME,
    RecordingProxy,
    _bounded,
    _cmd,
    _raw,
    _status,
    make_plugin,
)
from Services.code_reader.tests.test_sdk_reader import FakeApi, wait_until

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


def _configure(config: dict) -> tuple[CodeReaderSdkPlugin, PluginContext]:
    """Плагин, сконфигурированный по текущему `reader_factory` класса (без start)."""
    services = MockProcessServices(name=PROCESS_NAME, config=config, state_proxy=RecordingProxy())
    ctx = PluginContext(services=services, config=config)
    plugin = CodeReaderSdkPlugin()
    plugin.configure(ctx)
    return plugin, ctx


def _tiny_frame(trigger: int = 1) -> SdkFrame:
    """Кадр 2×2 mono8 без кодов: декод дешёвый, тест меряет учёт, а не JPEG."""
    return SdkFrame(
        trigger_index=trigger,
        frame_num=trigger,
        width=2,
        height=2,
        pixel_format="mono8",
        image=bytes(4),
        codes=(),
        no_read_num=0,
        status=ReadStatus.NO_CODE,
    )


class FloodApi(FakeApi):
    """get_frame отдаёт кадр немедленно и всегда: поток захвата почти не выходит из `_on_frame`."""

    def get_frame(self, h, timeout_ms):
        return _raw([], 1, w=8, h=8)


# --------------------------------------------------------------------------
# 1. Учёт кадров при гонке потоков захвата и produce()
# --------------------------------------------------------------------------


def test_frame_accounting_holds_under_capture_produce_race(make_plugin):  # noqa: F811
    """Свойство: каждый кадр либо выдан produce(), либо учтён в `dropped`; seq_id не повторяются.

    Ломается, если `seq`/`dropped`/очередь меняются не под одним замком: инкременты теряются
    (ревью Ф2 TCP-плагина: 175 потерянных приращений на 160 000 срабатываний). Потоки захвата
    имитируем вызовом `_on_frame` (читатель не запускаем), переключение потоков — на каждой
    микросекунде, иначе под GIL 3.12 гонка не проявляется.
    """
    w = make_plugin(FakeApi(), timeout_ms=20)
    threads_n, per_thread = 4, 2500
    total = threads_n * per_thread
    delivered: list[int] = []
    producers_done = threading.Event()
    frame = _tiny_frame()

    def push() -> None:
        for _ in range(per_thread):
            w.plugin._on_frame(frame)

    def drain() -> None:
        while not producers_done.is_set():
            delivered.extend(i["seq_id"] for i in w.plugin.produce())
        delivered.extend(i["seq_id"] for i in w.plugin.produce())

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        pushers = [threading.Thread(target=push, daemon=True) for _ in range(threads_n)]
        drainer = threading.Thread(target=drain, daemon=True)
        drainer.start()
        for t in pushers:
            t.start()
        for t in pushers:
            t.join(60.0)
        producers_done.set()
        drainer.join(60.0)
    finally:
        sys.setswitchinterval(old_interval)
    assert not any(t.is_alive() for t in (*pushers, drainer)), "потоки не завершились за дедлайн"

    assert len(delivered) == len(set(delivered)), "seq_id повторился"
    assert len(delivered) + _status(w)["dropped"] == total, (
        f"учёт разошёлся: выдано {len(delivered)} + dropped {_status(w)['dropped']} != {total}"
    )
    assert w.plugin._seq == total, f"seq потерял приращения: {w.plugin._seq} != {total}"


# --------------------------------------------------------------------------
# 2. release_device не держит замок плагина, пока ждёт поток захвата
# --------------------------------------------------------------------------


def test_release_device_does_not_hold_plugin_lock_while_stopping(make_plugin):  # noqa: F811
    """Свойство: `release_device` под потоком захвата, забрасывающим кадры, укладывается в дедлайн.

    Ломается, если `reader.stop()` (он ждёт поток до `timeout + timeout_ms`) вызывается под
    `self._lock`: поток захвата стоит на этом же замке в `_on_frame`, join упирается в дедлайн
    (~2.1 с), команда отвечает `released: False`.
    """
    w = make_plugin(FloodApi(), timeout_ms=100)
    assert _cmd(w, "take_device")["status"] == "ok"
    assert wait_until(lambda: _status(w)["dropped"] > 0, 3.0), "кадры не пошли"

    t0 = time.perf_counter()
    res = _cmd(w, "release_device", deadline=10.0)
    elapsed = time.perf_counter() - t0

    assert res["released"] is True, f"прибор не отпущен: {res}"
    assert elapsed < 1.0, f"release_device занял {elapsed:.2f} с (join упёрся в замок?)"
    assert _status(w)["device_state"] == "stopped"


# --------------------------------------------------------------------------
# 3. release_device из колбэка потока захвата
# --------------------------------------------------------------------------


def test_release_device_from_inside_callback_returns_and_releases_once(monkeypatch):
    """Свойство: команда из колбэка потока захвата не виснет на join самого себя и честно
    отвечает «ещё отпускается»; прибор потом закрывается ровно один раз.

    Ломается, если плагин ждёт поток захвата сам (`join` без проверки текущего потока) или
    отвечает `released: True` при живом потоке.
    """
    api = FakeApi(script=[_raw([], 1, w=8, h=8)])
    seen: list[dict] = []
    box: dict = {}

    def factory(on_frame, on_error, **kw):
        def wrapped(frame):
            on_frame(frame)
            seen.append(box["plugin"].cmd_release_device({}))  # ВНУТРИ потока захвата

        return SdkCodeReader(wrapped, on_error, api=api, **kw)

    monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", factory)
    plugin, ctx = _configure({"auto_start": False, "timeout_ms": 20})
    box["plugin"] = plugin
    try:
        assert _bounded(lambda: plugin.cmd_take_device({}))["status"] == "ok"
        assert wait_until(lambda: bool(seen), 5.0), "команда из колбэка не вернулась (повисла на себе?)"
        assert seen[0]["released"] is False  # поток захвата ещё жив: это он и вызвал команду
        assert seen[0]["device_held"] is True

        assert wait_until(lambda: plugin.cmd_get_status({})["device_held"] is False, 5.0)
        assert api.count("close") == 1
        assert api.count("stop_grabbing") == 1
    finally:
        _bounded(lambda: plugin.shutdown(ctx), 15.0)


# --------------------------------------------------------------------------
# 4. reader_factory читается в момент создания читателя, из класса
# --------------------------------------------------------------------------


class _StubReader:
    """Читатель-заглушка: фиксирует, с чем его создали; на приборы не ходит."""

    def __init__(self, on_frame, on_error, **kw):
        self.kw = kw

    def stats(self):
        return {
            "frames": 0,
            "ok": 0,
            "no_code": 0,
            "bad_code": 0,
            "errors": 0,
            "state": "stopped",
            "last_error": None,
            "device": None,
            "device_held": False,
        }

    def start(self):
        return True

    def stop(self, timeout: float = 2.0):
        return None


def test_reader_factory_is_read_at_configure_time_and_gets_register_values(monkeypatch):
    """Свойство: фабрика берётся из атрибута КЛАССА при `configure()`, а не связывается при
    импорте/декорировании; `device_ip` "" -> None, `timeout_ms` — из register.

    Ломается, если плагин импортировал `SdkCodeReader` напрямую (подмена атрибута игнорируется:
    боевой читатель полез бы в DLL) или передаёт "" вместо None (читатель искал бы прибор с IP "").
    """
    monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", _StubReader)
    first, _ = _configure({"auto_start": False, "timeout_ms": 250})
    assert isinstance(first._reader, _StubReader)
    assert first._reader.kw == {"device_ip": None, "timeout_ms": 250}

    second_factory = functools.partial(_StubReader)  # другой объект: смена атрибута видна новому плагину
    monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", second_factory)
    second, _ = _configure({"auto_start": False, "device_ip": "10.0.0.7"})
    assert isinstance(second._reader, _StubReader)
    assert second._reader.kw["device_ip"] == "10.0.0.7"
    assert first._reader is not second._reader  # созданный ранее читатель остался прежним


def test_default_reader_factory_is_sdk_code_reader():
    """Боевое значение шва — сам `SdkCodeReader` (иначе плагин без подмены не соберёт читателя)."""
    assert CodeReaderSdkPlugin.__dict__["reader_factory"] is SdkCodeReader
