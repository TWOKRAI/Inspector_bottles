# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 6.3: плагин `code_reader_sdk`.

Написаны ДО реализации, только по контракту 6.3 из брифа лидера (решения по
дизайну) и по существующим тестам TCP-плагина. Реализации в дереве нет.

Шов для теста — атрибут класса ``CodeReaderSdkPlugin.reader_factory``: тест подменяет
его на ``functools.partial(SdkCodeReader, api=FakeApi(...))``. ``FakeApi`` и
``make_raw`` — из ``test_sdk_reader`` (не копии).

Что здесь ПРЕДПОЛОЖЕНО, а не задано брифом (одно место правки — константы и
хелперы ниже):
  * команды вызываются через ``plugin.commands[<имя>]`` -> имя метода, а не по
    выдуманному имени ``cmd_*``;
  * текст про IDMVS ищется в ``last_error`` из ``get_status``;
  * провал ``take_device`` (busy / not_found) даёт ``status == "error"``;
  * плагин отпускает прибор дедлайном меньше ``_LATE_BLOCK_S`` (см. ниже).

Импорты проекта — внутри функций (``_m``): каждый тест падает сам, а не один
общий сбой сбора модуля. Любое ожидание — с дедлайном; команды и produce()
идут в daemon-потоке с join, тест не может повиснуть (pytest-timeout в venv нет).
"""

from __future__ import annotations

import functools
import importlib
import json
import threading
import time
from functools import lru_cache
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from Services.code_reader.tests.test_sdk_reader import (
    ACCESS_DENIED,
    CORNERS_LIVE,
    ERR,
    FakeApi,
    _quality_fields,
    bad_code as _bad_code,
    code as _code,
    make_raw,
    sdk_error,
    wait_until,
)

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)

PROCESS_NAME = "reader"
TREE_PATH = f"processes.{PROCESS_NAME}.state.code_reader_sdk"

# get_frame FakeApi спит столько; должно ЗАВЕДОМО превышать дедлайн stop() плагина
# (по умолчанию SdkCodeReader.stop: 2.0 c + timeout_ms). Если плагин зовёт stop с
# дедлайном больше — тест «поздней остановки» покажет released=True, и это
# предположение надо пересмотреть (см. отчёт).
_LATE_BLOCK_S = 4.0


def _m(name: str):
    return importlib.import_module(name)


def _plugin_cls():
    return _m("Services.code_reader.plugin.sdk_plugin").CodeReaderSdkPlugin


# --------------------------------------------------------------------------
# Хелперы кадров
# --------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _jpeg(w: int, h: int) -> bytes:
    """Настоящий JPEG: левая половина чёрная, правая белая."""
    img = np.zeros((h, w), np.uint8)
    img[:, w // 2 :] = 255
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _raw(codes, trig: int, *, w: int = 64, h: int = 48, **kw):
    """RawFrame с валидным JPEG; ``trig`` -> trigger_index и frame_num."""
    return make_raw(codes, trigger=trig, frame_num=trig, width=w, height=h, image=_jpeg(w, h), **kw)


class GatedApi(FakeApi):
    """FakeApi, который не отдаёт кадры/ошибки, пока не поднят ``gate``.

    Без затвора кадры сценария проходят за микросекунды — раньше, чем ``take_device``
    успевает опубликовать своё состояние, и эта публикация сама «доставляет» дерево
    (ложная зелень теста «опубликовано сразу»). Закрытый затвор ведёт себя как таймаут
    get_frame без данных, так что остановка остаётся быстрой.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gate = threading.Event()

    def get_frame(self, h, timeout_ms):
        if not self.gate.wait(timeout_ms / 1000):
            return None
        return super().get_frame(h, timeout_ms)


# --------------------------------------------------------------------------
# Стенд: плагин + записывающий state_proxy + подмена reader_factory
# --------------------------------------------------------------------------


class RecordingProxy:
    """Пишет merge(path, data); потокобезопасен (append в list атомарен)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.calls.append((path, dict(data)))

    def tree(self) -> dict:
        """Последнее опубликованное состояние по ТОЧНОМУ пути плагина (пусто, если не публиковал)."""
        mine = [d for p, d in list(self.calls) if p == TREE_PATH]
        return mine[-1] if mine else {}

    def after(self, baseline: int) -> list[dict]:
        """Публикации по пути плагина, сделанные ПОСЛЕ ``baseline`` (= len(calls) в момент снимка)."""
        return [d for p, d in list(self.calls)[baseline:] if p == TREE_PATH]

    def seen(self, key: str) -> list:
        return [d[key] for p, d in list(self.calls) if p == TREE_PATH and key in d]


def _bounded(fn, deadline: float = 15.0):
    """Выполнить fn в daemon-потоке; не вернулся за deadline — тест падает, а не висит."""
    box: dict = {}

    def run() -> None:
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["e"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {deadline} c (завис)")
    if "e" in box:
        raise box["e"]
    return box["r"]


def _cmd(w, name: str, data: dict | None = None, deadline: float = 15.0) -> dict:
    """Команда плагина по имени из ``plugin.commands`` (dict in -> dict out)."""
    method = getattr(w.plugin, w.plugin.commands[name])
    return _bounded(lambda: method(data or {}), deadline)


def _collect(w, count: int, timeout: float = 5.0) -> list[dict]:
    """Слить produce() до ``count`` items или до дедлайна."""
    items: list[dict] = []
    end = time.monotonic() + timeout
    while len(items) < count and time.monotonic() < end:
        items.extend(w.plugin.produce())
        if len(items) < count:
            time.sleep(0.01)
    return items


def _status(w) -> dict:
    return _cmd(w, "get_status")


@pytest.fixture
def make_plugin(monkeypatch):
    """Фабрика плагинов на FakeApi + гарантированный shutdown (в daemon-потоке, с дедлайном)."""
    made: list = []

    def factory(api, **cfg):
        cls = _plugin_cls()
        sdk_reader = _m("Services.code_reader.core.sdk_reader")
        monkeypatch.setattr(cls, "reader_factory", functools.partial(sdk_reader.SdkCodeReader, api=api))
        config = {"auto_start": False, **cfg}
        proxy = RecordingProxy()
        services = MockProcessServices(name=PROCESS_NAME, config=config, state_proxy=proxy)
        ctx = PluginContext(services=services, config=config)
        plugin = cls()
        plugin.configure(ctx)
        plugin.start(ctx)
        state = {"down": False}

        def shutdown() -> None:
            if state["down"]:
                return
            state["down"] = True
            _bounded(lambda: plugin.shutdown(ctx), 15.0)

        w = SimpleNamespace(plugin=plugin, api=api, proxy=proxy, ctx=ctx, shutdown=shutdown, state=state)
        made.append(w)
        return w

    yield factory
    for w in made:
        if not w.state["down"]:
            w.state["down"] = True
            t = threading.Thread(target=w.plugin.shutdown, args=(w.ctx,), daemon=True)
            t.start()
            t.join(15.0)


# --------------------------------------------------------------------------
# RED 1. Регистрация и порты
# --------------------------------------------------------------------------


def test_registered_as_source_with_ports():
    mod = _m("Services.code_reader.plugin.sdk_plugin")
    regs = _m("Services.code_reader.plugin.sdk_registers")
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    entry = PluginRegistry.get("code_reader_sdk")
    assert entry is not None
    assert entry.category == "source"
    assert entry.plugin_class is mod.CodeReaderSdkPlugin
    assert "code_reader_sdk" in {e.name for e in PluginRegistry.filter("source")}
    assert mod.CodeReaderSdkPlugin.name == "code_reader_sdk"

    ports = {p.name: p for p in mod.CodeReaderSdkPlugin.outputs}
    assert set(ports) == {"code", "frame"}
    assert ports["code"].optional is False  # обязательный
    assert ports["frame"].optional is True  # картинка не обязательна
    assert mod.CodeReaderSdkPlugin.inputs == []

    # Регистры: класс подключён и несёт объявленные поля с литеральными значениями по умолчанию.
    assert mod.CodeReaderSdkPlugin.register_class is regs.CodeReaderSdkRegisters
    fields = set(regs.CodeReaderSdkRegisters.model_fields)
    assert {
        "device_ip",
        "reader_id",
        "auto_start",
        "timeout_ms",
        "device_state",
        "last_code",
        "last_status",
        "total_reads",
        "no_reads",
        "bad_reads",
        "frames",
        "errors",
        "dropped",
        "last_error",
    } <= fields
    reg = regs.CodeReaderSdkRegisters()
    assert reg.device_ip == ""
    assert reg.reader_id == "id3013"
    assert reg.timeout_ms == 500
    assert isinstance(reg.auto_start, bool)


# --------------------------------------------------------------------------
# RED 2. Порядок и плоская форма item (как у TCP-плагина)
# --------------------------------------------------------------------------


def test_items_follow_trigger_order_with_tcp_shape(make_plugin):
    script = [
        _raw([_code("QR-15MM")], 1),
        _raw([_code("QR-20MM")], 2),
        _raw([_bad_code()], 3, no_read=1),
        _raw([], 4),
    ]
    w = make_plugin(FakeApi(script=script), reader_id="line-3", timeout_ms=20)
    assert _cmd(w, "take_device")["status"] == "ok"
    items = _collect(w, 4)

    assert [i["trigger_index"] for i in items] == [1, 2, 3, 4]
    assert [i["code"] for i in items] == ["QR-15MM", "QR-20MM", "", ""]
    assert [i["status"] for i in items] == ["ok", "ok", "bad_code", "no_code"]
    assert [i["seq_id"] for i in items] == [1, 2, 3, 4]
    assert {i["reader_id"] for i in items} == {"line-3"}
    assert all(isinstance(i["ts"], float) and i["ts"] > 0 for i in items)
    ts = [i["ts"] for i in items]
    assert ts == sorted(ts)
    # На кадр приходится один item, а не по item на код: кадр bad_code содержит 1 запись, no_code — 0.
    assert [len(i["codes"]) for i in items] == [1, 1, 1, 0]


# --------------------------------------------------------------------------
# RED 3. Картинка декодируется в серый массив
# --------------------------------------------------------------------------


def test_frame_is_decoded_gray_array(make_plugin):
    w = make_plugin(FakeApi(script=[_raw([_code("QR-15MM")], 1, w=1280, h=1024)]), timeout_ms=20)
    _cmd(w, "take_device")
    (item,) = _collect(w, 1)

    img = item["frame"]
    assert isinstance(img, np.ndarray)
    assert img.dtype == np.uint8
    assert img.shape == (1024, 1280)
    # Не нули и не перевёрнуто: левая четверть тёмная, правая светлая (как в _jpeg).
    assert img[:, :320].mean() < 40
    assert img[:, -320:].mean() > 215


# --------------------------------------------------------------------------
# RED 4. Никаких bytes; JSON без кадра; углы и качество
# --------------------------------------------------------------------------


def _walk(obj, path="item"):
    """Рекурсивно: bytes/bytearray/memoryview в item недопустимы (JPEG не едет по конвейеру)."""
    assert not isinstance(obj, (bytes, bytearray, memoryview)), f"байты в {path}"
    if isinstance(obj, np.ndarray):
        return  # кадр — массив, не байты; внутрь не заходим
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk(k, f"{path}.<key {k!r}>")
            _walk(v, f"{path}[{k!r}]")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]")


def test_item_has_no_bytes_and_is_json_without_frame(make_plugin):
    with_quality = _code("QR-20MM", get_quality=True, quality=_quality_fields())
    # Первая запись нечитаема: item["code"] — текст ПЕРВОГО ЧИТАЕМОГО кода, а не первой записи.
    raw = _raw([_bad_code(), _code("QR-15MM"), with_quality], 1, no_read=1)
    w = make_plugin(FakeApi(script=[raw]), timeout_ms=20)
    _cmd(w, "take_device")
    (item,) = _collect(w, 1)

    _walk(item)
    assert "frame" in item  # иначе «JSON без frame» ничего не доказывает
    json.dumps({k: v for k, v in item.items() if k != "frame"})  # numpy-скаляры/bytes/enum уронят

    assert item["code"] == "QR-15MM"
    assert item["status"] == "ok"
    assert (item["trigger_index"], item["frame_num"], item["no_read_num"]) == (1, 1, 1)
    assert item["pixel_format"] == "jpeg"

    bad, ok, graded = item["codes"]
    assert (bad["text"], bad["status"], bad["bar_type"]) == ("", "bad_code", 1001)
    assert (ok["text"], ok["status"], ok["bar_type"]) == ("QR-15MM", "ok", 2)
    for c in (bad, ok, graded):
        assert [list(p) for p in c["corners"]] == CORNERS_LIVE  # 4 пары, порядок прибора
        assert len(c["corners"]) == 4
        assert all(len(p) == 2 and all(type(v) is int for v in p) for p in c["corners"])
    assert ok["angle_deg"] == pytest.approx(15.5)
    assert ok["ppm"] == pytest.approx(12.3)
    assert ok["algo_ms"] == 25
    assert ok["quality"] is None  # прибор оценку не считал (get_quality false)
    assert bad["quality"] is None
    assert isinstance(graded["quality"], dict)  # оценка есть -> dict, не MappingProxy/dataclass
    assert graded["quality"]["overall"] == 4
    assert graded["quality"]["score"] == 88
    assert graded["quality"]["grades"]["decode"] == 11


# --------------------------------------------------------------------------
# RED 5. Битый JPEG: код доезжает, кадр — нет
# --------------------------------------------------------------------------


def test_broken_jpeg_keeps_code_drops_frame(make_plugin):
    broken = make_raw([_code("QR-15MM")], trigger=1, frame_num=1)  # image=b"\xff\xd8fake\xff\xd9" — не JPEG
    good = _raw([_code("QR-20MM")], 2)
    w = make_plugin(FakeApi(script=[broken, good]), timeout_ms=20)
    errors_before = _status(w)["errors"]
    _cmd(w, "take_device")
    items = _collect(w, 2)

    assert [i["code"] for i in items] == ["QR-15MM", "QR-20MM"]
    assert [i["status"] for i in items] == ["ok", "ok"]
    assert "frame" not in items[0]  # ключа нет, а не None: порт frame optional
    assert isinstance(items[1]["frame"], np.ndarray)  # следующий хороший кадр не потерян
    assert _status(w)["errors"] > errors_before


# --------------------------------------------------------------------------
# RED 6. Переполнение очереди: dropped и немедленная публикация
# --------------------------------------------------------------------------


def test_overflow_counts_dropped_and_publishes_before_produce(make_plugin):
    script = [_raw([_code(f"C{i}")], i) for i in range(1, 10)]  # 9 кадров > глубина 8
    api = GatedApi(script=script)
    w = make_plugin(api, timeout_ms=20)
    _cmd(w, "take_device")
    baseline = len(w.proxy.calls)  # публикация take_device уже позади
    api.gate.set()  # только теперь кадры пошли из потока захвата

    # produce() НЕ зовём: дерево обязано показать потерю само (ждать слива бессмысленно).
    assert wait_until(lambda: any(d.get("dropped") == 1 for d in w.proxy.after(baseline)), 5.0), (
        f"dropped=1 не опубликован без produce(); после take_device опубликовано: {w.proxy.after(baseline)}"
    )
    time.sleep(0.1)  # dropped не должен уйти выше единицы (десятого кадра нет)
    assert _status(w)["dropped"] == 1
    assert w.proxy.tree()["dropped"] == 1

    items = w.plugin.produce()
    assert len(items) == 8  # глубина очереди 8
    assert [i["trigger_index"] for i in items] == list(range(2, 10))  # выброшен самый старый (1)


# --------------------------------------------------------------------------
# RED 7. produce() не блокирует
# --------------------------------------------------------------------------


def test_produce_does_not_block(make_plugin):
    api = FakeApi(block_s=1.0)  # get_frame в потоке захвата висит секунду
    w = make_plugin(api, timeout_ms=200)
    _cmd(w, "take_device")
    assert wait_until(lambda: api.in_flight > 0, 3.0), "поток захвата не вошёл в get_frame"

    def timed_calls() -> tuple[list, float]:
        worst, last = 0.0, None
        for _ in range(5):
            t0 = time.perf_counter()
            last = w.plugin.produce()
            worst = max(worst, time.perf_counter() - t0)
        return last, worst

    last, worst = _bounded(timed_calls, 5.0)
    assert last == []
    assert worst < 0.05, f"produce() занял {worst * 1000:.0f} мс при заблокированном get_frame"


# --------------------------------------------------------------------------
# RED 8. take_device: четыре исхода
# --------------------------------------------------------------------------


def test_take_device_states(make_plugin):
    # успех -> running, прибор держим, в дерево состояние ушло по пути плагина
    ok = make_plugin(FakeApi(), timeout_ms=20)
    assert _cmd(ok, "take_device")["status"] == "ok"
    st = _status(ok)
    assert st["device_state"] == "running"
    assert st["device_held"] is True
    assert wait_until(lambda: ok.proxy.tree().get("device_state") == "running", 3.0)

    # отказ доступа на open -> busy, ошибка называет IDMVS
    busy = make_plugin(FakeApi(open_error=sdk_error(ACCESS_DENIED, "OpenDevice")), timeout_ms=20)
    assert _cmd(busy, "take_device")["status"] == "error"
    st = _status(busy)
    assert st["device_state"] == "busy"
    assert st["device_held"] is False
    assert "idmvs" in st["last_error"].lower()
    assert wait_until(lambda: busy.proxy.tree().get("device_state") == "busy", 3.0)
    assert "idmvs" in busy.proxy.tree()["last_error"].lower()

    # нет приборов -> not_found
    none = make_plugin(FakeApi(entries=[]), timeout_ms=20)
    assert _cmd(none, "take_device")["status"] == "error"
    assert _status(none)["device_state"] == "not_found"
    assert none.api.count("open") == 0

    # повторный take_device при running — ok и БЕЗ второго open
    again = make_plugin(FakeApi(), timeout_ms=20)
    assert _cmd(again, "take_device")["status"] == "ok"
    assert _cmd(again, "take_device")["status"] == "ok"
    assert _status(again)["device_state"] == "running"
    assert again.api.count("open") == 1


# --------------------------------------------------------------------------
# RED 9. release_device: честно говорит о поздней остановке
# --------------------------------------------------------------------------


def test_release_device_reports_late_stop(make_plugin):
    # Контроль: прибор не блокирует -> отпущен сразу, held False.
    fast = make_plugin(FakeApi(), timeout_ms=20)
    _cmd(fast, "take_device")
    res = _cmd(fast, "release_device")
    assert res["released"] is True
    assert res["device_held"] is False
    assert _status(fast)["device_held"] is False
    assert fast.api.count("close") == 1

    # Блокирующий get_frame дольше дедлайна stop(): released False, device_held True,
    # пока поток не вернётся; потом device_held сам становится False, close ровно один.
    api = FakeApi(block_s=_LATE_BLOCK_S)
    w = make_plugin(api, timeout_ms=100)
    _cmd(w, "take_device")
    assert wait_until(lambda: api.in_flight > 0, 3.0), "поток захвата не вошёл в get_frame"

    res = _cmd(w, "release_device", deadline=20.0)
    assert res["released"] is False
    assert res["device_held"] is True
    assert _status(w)["device_held"] is True
    assert api.count("close") == 0, "close под идущим get_frame"

    assert wait_until(lambda: _status(w)["device_held"] is False, _LATE_BLOCK_S + 6.0), (
        "device_held не сбросился после выхода потока"
    )
    assert api.count("close") == 1


# --------------------------------------------------------------------------
# RED 10. Три ошибки -> error, без автопереподключения; take_device возвращает; close на open
# --------------------------------------------------------------------------


def test_error_after_three_failures_no_autoreconnect_then_take_device(make_plugin):
    api = GatedApi(script=[sdk_error(ERR)] * 3)
    w = make_plugin(api, timeout_ms=10)
    assert _cmd(w, "take_device")["status"] == "ok"
    baseline = len(w.proxy.calls)
    api.gate.set()  # ошибки идут из потока захвата уже после публикации take_device

    assert wait_until(lambda: _status(w)["device_state"] == "error", 5.0), "три ошибки подряд не дали error"
    # Само состояние error и причина обязаны прийти в дерево ПОСЛЕ ошибок (а не задним числом от take_device).
    assert wait_until(
        lambda: any(d.get("device_state") == "error" and d.get("last_error") for d in w.proxy.after(baseline)),
        3.0,
    ), f"error и last_error не опубликованы; после take_device: {w.proxy.after(baseline)}"
    assert _status(w)["last_error"]

    # Автопереподключения нет: плагин сам open больше не зовёт (produce-проходы его не будят).
    assert api.count("open") == 1
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        w.plugin.produce()
        time.sleep(0.02)
    assert api.count("open") == 1, "плагин переоткрыл прибор сам"

    # Поток захвата вышел -> прибор не удерживается; take_device возвращает его.
    assert wait_until(lambda: _status(w)["device_held"] is False, 5.0)
    assert _cmd(w, "take_device")["status"] == "ok"
    assert _status(w)["device_state"] == "running"
    assert wait_until(lambda: w.proxy.tree().get("device_state") == "running", 3.0)
    assert api.count("open") == 2

    # shutdown: close ровно один на каждый open (первый закрыт при выходе потока из error).
    w.shutdown()
    assert api.count("close") == api.count("open") == 2
