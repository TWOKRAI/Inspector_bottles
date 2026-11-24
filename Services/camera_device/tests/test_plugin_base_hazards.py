# -*- coding: utf-8 -*-
"""Хазард-тесты Task 2.3a (автор): гонки `take_device`, порядок `seq_id`, `set_cycle` при живом владельце,
повторный старт не подменяет план идущего цикла, отказ `build_plan` -> `status: error`, цвет и битый буфер.

Файл БЕЗ `from __future__ import annotations`: аннотации register-класса подкласса должны быть настоящими
объектами (`Annotated[..., FieldMeta]`). Всё, что может зависнуть, идёт в daemon-потоке с дедлайном.
Ожидаемые значения — литералы.
"""

import sys
import threading
import time
from typing import Annotated

import pytest
from pydantic import ValidationError

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.observability_declarations import declared_metrics
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding, PortError, RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing.fake_port import FAKE_BINDINGS, make_port

CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}


def _bounded(fn, seconds: float = 10.0):
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"вызов не вернулся за {seconds} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class _Rig:
    def __init__(self, monkeypatch, cfg: dict, port, plugin_cls=CameraDevicePlugin) -> None:
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        services = MockProcessServices(name="cam_fake", config=cfg)
        self.wm = WorkerManager("test_cam")
        services.worker_manager = self.wm
        self.ctx = PluginContext(services=services, config=cfg, plugin_name=plugin_cls.name)
        self.plugin = plugin_cls()
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def rig(monkeypatch):
    made: list[_Rig] = []

    def factory(cfg: dict | None = None, *, port=None, plugin_cls=CameraDevicePlugin) -> _Rig:
        item = _Rig(monkeypatch, {**CFG, **(cfg or {})}, port or make_port(frame_period_s=0.02), plugin_cls)
        made.append(item)
        return item

    yield factory
    for item in made:
        item.close()


def _names(port) -> list[str]:
    return [call[0] for call in port.calls]


def test_два_потока_take_device_дают_один_open(rig, monkeypatch):
    """Гонка двух `take_device`: один `open` в журнале, оба ответа `ok` (создание порта нарочно медленное)."""
    port = make_port(frame_period_s=0.02, open_delay_s=0.2)
    built = rig(port=port)

    def slow_create_port(driver: str):
        time.sleep(0.1)  # окно гонки на ленивом создании сеанса
        return port

    monkeypatch.setattr(plugin_base, "create_port", slow_create_port)
    barrier = threading.Barrier(2)
    answers: list[dict] = []

    def call() -> None:
        barrier.wait(5.0)
        answers.append(built.plugin.cmd_take_device({}))

    threads = [threading.Thread(target=call, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)
        assert not thread.is_alive()
    assert [a["status"] for a in answers] == ["ok", "ok"]
    assert _names(built.port).count("open") == 1


def test_seq_id_строго_растёт_при_on_frame_и_produce_из_разных_потоков(rig):
    """`_on_frame` в одном потоке, `produce()` в другом: `seq_id` строго растёт, итог 500."""
    built = rig()
    plugin = built.plugin
    done = threading.Event()

    def feed() -> None:
        for number in range(1, 501):
            plugin._on_frame(RawFrame(bytearray(8), 4, 2, "mono8", number))
        done.set()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    seen: list[int] = []
    deadline = time.monotonic() + 10.0
    while not done.is_set() and time.monotonic() < deadline:
        seen += [item["seq_id"] for item in plugin.produce()]
    feeder.join(10.0)
    assert done.is_set()
    seen += [item["seq_id"] for item in plugin.produce()]
    assert seen == sorted(set(seen)), "seq_id не строго растёт"
    assert seen[-1] == 500


def test_set_cycle_при_device_held_возвращает_False_и_не_меняет_цикл(rig):
    """Идущий цикл: `set_cycle` -> `False`, `_run`/`_ident` прежние; после остановки — `True` и замена."""
    built = rig()
    assert built.take()["status"] == "ok"
    session = built.plugin._session
    assert session.device_held
    run_before, ident_before = session._run, session._ident
    assert session.set_cycle(None, (), ()) is False
    assert (session._run, session._ident) == (run_before, ident_before)
    assert ident_before is not None and len(run_before) > 0

    assert built.plugin.cmd_release_device({})["status"] == "ok"
    assert not session.device_held
    assert session.set_cycle(None, (), ()) is True
    assert (session._run, session._ident) == ((), None)


def test_второй_take_device_при_grabbing_не_подменяет_план_идущего_цикла(rig):
    """Правка `exposure_time` посреди захвата: повторный `take_device` -> `ok`, в приборе всё ещё 10000.0."""
    built = rig()
    assert built.take()["status"] == "ok"
    run_before = built.plugin._session._run
    built.plugin._reg.exposure_time = 777.0
    assert built.take()["status"] == "ok"
    assert built.plugin._session.state == "grabbing"
    assert built.plugin._session._run == run_before
    assert built.plugin._session.params == {"exposure_time": 10000.0}
    written = [args for name, args, _ in built.port.calls if name == "set_param"]
    assert written == [("ExposureTime", 10000.0)]


class _ExtraRegisters(CameraDeviceRegisters):
    """Безусловное поле группы триггера без значения в плане rest: `build_plan` бросает ValueError."""

    trigger_extra: Annotated[int, FieldMeta("Лишний узел триггера")] = 1


class _BrokenPlanPlugin(CameraDevicePlugin):
    register_class = _ExtraRegisters

    def bindings(self):
        return {**FAKE_BINDINGS, "trigger_extra": Binding("genicam", "TriggerExtra", "int")}


def test_build_plan_бросает_take_device_отвечает_error_без_исключения(rig):
    """`ValueError` из плана -> `{"status": "error"}` с именем поля, прибор не открыт, исключения наружу нет."""
    built = rig(plugin_cls=_BrokenPlanPlugin)
    answer = built.take()
    assert answer["status"] == "error"
    assert "trigger_extra" in answer["error"]
    assert "open" not in _names(built.port)


@pytest.mark.parametrize(
    ("pixel_format", "size", "shape", "produced"),
    [
        pytest.param("rgb8", 24, (2, 4, 3), True, id="rgb8"),
        pytest.param("bgr8", 24, (2, 4, 3), True, id="bgr8"),
        pytest.param("mono8", 8, (2, 4), True, id="mono8"),
        pytest.param("rgb8", 8, None, False, id="rgb8_короткий_буфер"),
        pytest.param("mono16", 16, None, False, id="неизвестный_формат"),
    ],
)
def test_форма_кадра_по_pixel_format_битый_кадр_отбрасывается(rig, pixel_format, size, shape, produced):
    """Цвет — (h, w, 3); битый буфер/неизвестный формат: `produce()` не бросает, item нет, `frames` не растёт."""
    built = rig()
    plugin = built.plugin
    plugin._on_frame(RawFrame(bytearray(size), 4, 2, pixel_format, 1))
    items = plugin.produce()
    if produced:
        assert len(items) == 1
        assert items[0]["frame"].shape == shape
        assert plugin._frames == 1
    else:
        assert items == []
        assert plugin._frames == 0
        assert plugin._reg.frames == 0
        assert plugin.cmd_get_status({})["last_error"] != ""


def test_rest_selftrigger_пишет_период_run(rig):
    """`rest_trigger_source=SelfTrigger`: в покое пишется и период самотриггера из run (40), ошибки плана нет."""
    built = rig({"rest_managed": True, "rest_trigger_mode": "On", "rest_trigger_source": "SelfTrigger"})
    assert built.take()["status"] == "ok"
    assert built.plugin.cmd_release_device({})["status"] == "ok"
    names = _names(built.port)
    tail = built.port.calls[names.index("stop_grabbing") + 1 :]
    assert [args for name, args, _ in tail if name == "set_param"] == [
        ("TriggerMode", "On"),
        ("TriggerSource", "SelfTrigger"),
        ("TriggerSelfTriggerPeriod", 40),
    ]


def test_правка_device_serial_между_циклами_доходит_до_сеанса(rig):
    """Р12: `device_serial` правится после `release_device` -> следующий `take_device` ищет НОВЫЙ серийник."""
    built = rig()
    assert built.take()["status"] == "ok"
    assert built.plugin.cmd_release_device({})["status"] == "ok"
    built.plugin._reg.device_serial = "NOPE"
    assert built.take()["status"] == "error"
    assert built.plugin._session.state == "not_found"
    assert [call[:2] for call in built.port.calls if call[0] == "open"] == [("open", ("serial", "FAKE-0001"))]


@pytest.mark.parametrize(
    "error",
    [PortError("access", "make_port"), ImportError("dll"), OSError("x")],
    ids=["PortError", "ImportError", "OSError"],
)
def test_create_port_бросает_не_ValueError_take_device_отвечает_error(rig, error):
    """Хук вендора бросил не ValueError: `status: error`, исключения наружу нет, сеанс не создан."""

    class _Failing(CameraDevicePlugin):
        def create_port(self):
            raise error

    built = rig(plugin_cls=_Failing)
    answer = built.take()
    assert answer["status"] == "error"
    assert answer["error"] != ""
    assert built.plugin._session is None


# --------------------------------------------------------------------------------------------- #
# T13: очередь кадров источника (`source_queue_frames`, `overwritten`) — гонки и границы (автор)
# --------------------------------------------------------------------------------------------- #


def _mono_frame(number: int) -> RawFrame:
    return RawFrame(bytearray([number % 256]) * 8, 4, 2, "mono8", number)


def test_on_frame_и_produce_из_разных_потоков_кадры_не_теряются_молча(rig):
    """K=4, источник в потоке и опрос без пауз: `доставлено + overwritten == принято`, `seq_id` по порядку.

    Забор `produce()` и запись `_on_frame` под одним замком: кадр либо в items, либо в счёте вытеснения.
    """
    built = rig({"source_queue_frames": 4})
    plugin = built.plugin
    total = 3000
    done = threading.Event()

    def feed() -> None:
        for number in range(1, total + 1):
            plugin._on_frame(_mono_frame(number))
        done.set()

    feeder = threading.Thread(target=feed, daemon=True)
    seen: list[int] = []
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # переключения потоков на каждом шаге: окно гонки между замком и очередью открыто
    try:
        feeder.start()
        deadline = time.monotonic() + 20.0
        while not done.is_set() and time.monotonic() < deadline:
            seen += [item["seq_id"] for item in plugin.produce()]
        feeder.join(10.0)
    finally:
        sys.setswitchinterval(interval)
    assert done.is_set()
    seen += [item["seq_id"] for item in plugin.produce()]
    assert seen == sorted(set(seen)), "seq_id повторился или идёт не по порядку"
    assert seen[-1] == total
    assert len(seen) + plugin._overwritten == total


def test_глубина_один_из_потока_отдаёт_только_последний_кадр_и_считает_остальные(rig):
    """K=1, 500 кадров из потока без опроса: один item (кадр 500), `overwritten == 499`."""
    built = rig({"source_queue_frames": 1})
    plugin = built.plugin
    feeder = threading.Thread(target=lambda: [plugin._on_frame(_mono_frame(n)) for n in range(1, 501)], daemon=True)
    feeder.start()
    feeder.join(10.0)
    assert not feeder.is_alive()
    items = _bounded(plugin.produce)
    assert [item["seq_id"] for item in items] == [500]
    assert plugin._overwritten == 499


@pytest.mark.parametrize("depth", [0, -1, 65, 1000])
def test_глубина_вне_границ_отказ_при_configure(monkeypatch, depth):
    """`source_queue_frames` вне 1..64 не зажимается молча: регистр отказывает при `configure`, очередь не создана.

    Границы живут только в `FieldMeta` поля (один источник): отдельной проверки в плагине нет.
    """
    monkeypatch.setattr(plugin_base, "create_port", lambda driver: make_port(frame_period_s=0.02))
    cfg = {**CFG, "source_queue_frames": depth}
    services = MockProcessServices(name="cam_fake", config=cfg)
    services.worker_manager = WorkerManager("test_cam_depth")
    ctx = PluginContext(services=services, config=cfg, plugin_name=CameraDevicePlugin.name)
    plugin = CameraDevicePlugin()
    with pytest.raises(Exception, match="source_queue_frames|Input should be|меньше|больше"):
        plugin.configure(ctx)
    assert not hasattr(plugin, "_queue")


def test_регистр_source_queue_frames_умолчание_4_и_границы_на_уровне_регистра():
    """Сам регистр (без плагина): умолчание 4; запись 0, -1, 65 отвергается, 1 и 64 принимаются.

    Единственный источник границ — `FieldMeta` поля: снятие `min`/`max` не останется незамеченным. Значение после
    отказа не проверяется: pydantic его не откатывает (`apply_values` откатывает).
    """
    assert CameraDeviceRegisters().source_queue_frames == 4
    for bad in (0, -1, 65):
        with pytest.raises(ValidationError):
            CameraDeviceRegisters().source_queue_frames = bad
    for good in (1, 64):
        reg = CameraDeviceRegisters()
        reg.source_queue_frames = good
        assert reg.source_queue_frames == good


@pytest.mark.parametrize("depth", [1, 64])
def test_глубина_на_границах_принимается(rig, depth):
    """Границы диапазона 1 и 64 допустимы: `configure` проходит, очередь держит ровно столько кадров."""
    built = rig({"source_queue_frames": depth})
    for number in range(1, depth + 3):
        built.plugin._on_frame(_mono_frame(number))
    items = _bounded(built.plugin.produce)
    assert [item["seq_id"] for item in items] == list(range(3, depth + 3))


def test_битый_кадр_в_середине_очереди_остальные_доходят(rig):
    """Кадры 1, 3 хорошие, 2 — короткий буфер: items с seq_id 1 и 3, `dropped == 1`, `frames == 2`."""
    built = rig()
    plugin = built.plugin
    plugin._on_frame(_mono_frame(1))
    plugin._on_frame(RawFrame(bytearray(3), 4, 2, "mono8", 2))
    plugin._on_frame(_mono_frame(3))
    items = _bounded(plugin.produce)
    assert [item["seq_id"] for item in items] == [1, 3]
    assert plugin._dropped == 1
    assert plugin._frames == 2
    assert plugin._overwritten == 0


def test_reset_stats_обнуляет_overwritten_но_не_seq_id(rig):
    """После `reset_stats` счёт вытеснения нулевой, `seq_id` продолжается (Р10)."""
    built = rig({"source_queue_frames": 2})
    plugin = built.plugin
    for number in range(1, 6):
        plugin._on_frame(_mono_frame(number))
    assert plugin._overwritten == 3
    assert plugin.cmd_reset_stats({}) == {"success": True}
    assert plugin._overwritten == 0
    plugin._on_frame(_mono_frame(6))  # в очереди (K=2) были кадры 4, 5: кадр 6 вытесняет 4
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [5, 6]
    assert plugin._overwritten == 1


def test_метрика_pending_читает_длину_очереди(rig, monkeypatch):
    """`pending` — число кадров в очереди (не 0/1): 3 кадра -> 3 до забора, 0 после."""
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)
    built = rig({"source_queue_frames": 4})
    published: list[tuple[str, object]] = []
    publish = built.ctx.publish_metric
    built.ctx.publish_metric = lambda name, value: (published.append((name, value)), publish(name, value))[0]
    plugin = built.plugin
    for number in (1, 2, 3):
        plugin._on_frame(_mono_frame(number))
    plugin._tick()
    assert [value for name, value in published if name == "pending"] == [3]
    _bounded(plugin.produce)
    published.clear()
    plugin._tick()
    assert [value for name, value in published if name == "pending"] == [0]


def test_реальный_сеанс_фейк_порт_кадры_учтены_без_молчаливых_потерь(rig):
    """`take_device` на фейк-порту (50 кадров/с), опрос реже кадров: доставлено + overwritten == принято.

    Владелец останавливается ДО последнего `produce()`: `release_device` чистит очередь (граница сеанса), и к его
    вызову в очереди уже нечего терять.
    """
    built = rig({"source_queue_frames": 2})
    plugin = built.plugin
    assert built.take()["status"] == "ok"
    seen: list[int] = []
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        seen += [item["seq_id"] for item in plugin.produce()]
        time.sleep(0.07)  # между опросами ~3 кадра при очереди 2: вытеснение неизбежно
    plugin._session.stop(2.0)  # владелец остановлен: новых кадров нет
    seen += [item["seq_id"] for item in plugin.produce()]
    assert plugin.cmd_release_device({})["status"] == "ok"
    assert seen == sorted(set(seen))
    assert plugin._overwritten > 0
    assert plugin._seq == len(seen) + plugin._overwritten


# --------------------------------------------------------------------------------------------- #
# T13, правки ревью стадии 5: атомарность забора, apply, каталог метрик, сбой не-ValueError, границы сеанса
# --------------------------------------------------------------------------------------------- #


class _HookedLock:
    """Обёртка замка: после ближайшего выхода из блока `with` один раз зовёт `after_exit` (уже без замка)."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.after_exit = None

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self._inner.release()
        hook, self.after_exit = self.after_exit, None
        if hook is not None:
            hook()


def test_produce_снимок_и_очистка_очереди_одним_блоком_замка_кадр_между_ними_не_теряется(rig, monkeypatch):
    """Кадр, пришедший сразу после снятия очереди в `produce()`, остаётся для следующего забора (без гонки).

    Детерминированно: обёртка `plugin._lock` вызывает `_on_frame` (кадр 4) ровно один раз — на первом выходе из
    блока замка внутри `produce()`. Окно `_tick` закрыто (`_TICK_S` огромный), поэтому первый блок замка в
    `produce()` — снимок очереди. Если снятие и `clear` стоят в двух блоках, кадр 4 приходит между ними и затирается.
    """
    monkeypatch.setattr(plugin_base, "_TICK_S", 1e9)
    built = rig({"source_queue_frames": 4})
    plugin = built.plugin
    for number in (1, 2, 3):
        plugin._on_frame(_mono_frame(number))
    hooked = _HookedLock(plugin._lock)
    plugin._lock = hooked
    fired: list[int] = []
    hooked.after_exit = lambda: (fired.append(1), plugin._on_frame(_mono_frame(4)))
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [1, 2, 3]
    assert fired == [1], "кадр между блоками замка должен прийти ровно один раз"
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [4]
    assert plugin._overwritten == 0


def test_source_queue_frames_применяется_при_рестарте_apply_restart():
    """Глубина очереди читается один раз при старте процесса: в регистре `apply == "restart"`, не `live`."""
    meta = CameraDeviceRegisters.get_all_fields_meta()["source_queue_frames"]
    assert meta.apply == "restart"


def test_метрика_overwritten_объявлена_в_каталоге_уровней(rig):
    """`configure` вносит `overwritten` в каталог объявленных метрик (по нему GUI строит строки уровней)."""
    rig()
    assert "overwritten" in declared_metrics()


def test_не_ValueError_из_сборки_item_в_середине_пачки_считается_отброшенным_остальные_доходят(rig, monkeypatch):
    """K=4, кадры 1..4; RuntimeError на seq 3: items 1, 2, 4, `dropped == 1`, `produce` не бросает."""
    built = rig({"source_queue_frames": 4})
    plugin = built.plugin
    original = plugin._build_item

    def flaky(seq, *rest):
        if seq == 3:
            raise RuntimeError("сбой сборки")
        return original(seq, *rest)

    monkeypatch.setattr(plugin, "_build_item", flaky)
    for number in (1, 2, 3, 4):
        plugin._on_frame(_mono_frame(number))
    items = _bounded(plugin.produce)
    assert [item["seq_id"] for item in items] == [1, 2, 4]
    assert plugin._dropped == 1
    assert plugin._frames == 3
    assert plugin._overwritten == 0
    assert "RuntimeError" in plugin._item_error
    assert _bounded(plugin.produce) == []


def test_release_device_чистит_очередь_seq_продолжается(rig):
    """take, кадры 1..3, release: очередь пуста (кадры прошлого сеанса не отдаются); после нового take seq идёт с 4."""
    built = rig(port=make_port(frame_period_s=30.0))  # свои кадры порт не шлёт: в очереди только заведённые
    plugin = built.plugin
    assert built.take()["status"] == "ok"
    for number in (1, 2, 3):
        plugin._on_frame(_mono_frame(number))
    assert _bounded(lambda: plugin.cmd_release_device({}))["status"] == "ok"
    assert _bounded(plugin.produce) == []
    assert built.take()["status"] == "ok"
    plugin._on_frame(_mono_frame(4))
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [4]


def test_take_device_нового_сеанса_чистит_очередь_seq_продолжается(rig):
    """Кадры 1..3 пришли до старта сеанса: `take_device` начинает сеанс с пустой очереди, seq продолжается."""
    built = rig(port=make_port(frame_period_s=30.0))
    plugin = built.plugin
    for number in (1, 2, 3):
        plugin._on_frame(_mono_frame(number))
    assert built.take()["status"] == "ok"
    assert _bounded(plugin.produce) == []
    plugin._on_frame(_mono_frame(4))
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [4]


def test_повторный_take_device_при_идущем_захвате_очередь_не_чистит(rig):
    """Второй `take_device` при живом владельце цикл не меняет: кадры очереди остаются (молча терять их нельзя)."""
    built = rig(port=make_port(frame_period_s=30.0))
    plugin = built.plugin
    assert built.take()["status"] == "ok"
    for number in (1, 2):
        plugin._on_frame(_mono_frame(number))
    assert built.take()["status"] == "ok"
    assert [item["seq_id"] for item in _bounded(plugin.produce)] == [1, 2]


def test_release_device_очередь_пуста_после_каждого_цикла_владелец_ещё_шлёт_кадры(rig):
    """Порт шлёт кадры (50/с): после `release_device` очередь пуста в каждом из 25 циклов take/release.

    Чистка идёт ПОСЛЕ `session.stop` (владелец остановлен): до остановки он успевает положить ещё кадр.
    """
    built = rig(port=make_port(frame_period_s=0.02))
    plugin = built.plugin
    for cycle in range(25):
        assert built.take()["status"] == "ok"
        time.sleep(0.05)
        assert _bounded(lambda: plugin.cmd_release_device({}))["status"] == "ok"
        assert len(plugin._queue) == 0, f"цикл {cycle}: после release в очереди {len(plugin._queue)} кадров"


def test_чистка_очереди_на_границе_сеанса_пишет_число_кадров_в_журнал(rig):
    """3 кадра до `take_device`: одна строка журнала со словом «сброшено» и числом 3; пустая очередь — без строки."""
    built = rig(port=make_port(frame_period_s=30.0))
    plugin = built.plugin
    messages: list[str] = []
    log_info = built.ctx.log_info
    built.ctx.log_info = lambda text, *args, **kwargs: (messages.append(str(text)), log_info(text, *args, **kwargs))[1]
    for number in (1, 2, 3):
        plugin._on_frame(_mono_frame(number))
    assert built.take()["status"] == "ok"
    cleared = [text for text in messages if "сброшено кадров" in text]
    assert len(cleared) == 1 and cleared[0].endswith(": 3"), cleared
    assert _bounded(lambda: plugin.cmd_release_device({}))["status"] == "ok"  # очередь пуста: новой строки нет
    assert len([text for text in messages if "сброшено кадров" in text]) == 1
