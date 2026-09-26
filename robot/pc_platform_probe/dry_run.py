"""
Сухой прогон пробы без робота: настоящий ``probe.lua`` в Lua 5.1 (lupa) + локальный Modbus TCP.

Зачем. Визит к роботу дорог; ошибку в Lua или в протоколе пары лучше поймать дома.
Здесь исполняется ТОТ ЖЕ файл probe.lua, что уйдёт в контроллер, а функции DRAS
заменены заглушками. По умолчанию заглушки воспроизводят только известное из v1:
  • function2 (Mirror) получает управление только во время хода function1;
  • MotionStop прерывает текущий MovL/MovP; Override действует на ходу;
  • ПЧ отвечает на Modbus RTU (FC3/FC6) с правильным CRC.
Флаги ``FakeRobot`` включают неудобные варианты контроллера, которые нашло ревью:
  • ``nil_pose``        — геттеры позы возвращают nil (fault);
  • ``axis4`` — имя 4-й оси в WritePoint/ReadPoint (по мануалу RL — «RZ»); ``permissive_axes`` —
    WritePoint молча принимает любое имя и ничего не пишет;
  • ``drop_point_writes`` — WritePoint не падает, но и не пишет (ловится только сверкой ReadPoint);
  • ``tearing``         — блочная запись видна читателю наполовину.
Зелёный сухой прогон доказывает пару, а не платформу: как ведёт себя НАСТОЯЩИЙ контроллер,
выясняет проба на железе.

Запуск:
    uv run --no-project --with lupa --with pymodbus==3.15.0 python dry_run.py [--port 5020] [--lua 54]

Версия Lua контроллера неизвестна точно (в ключевых словах мануала есть goto — значит ≥ 5.2),
поэтому тесты гоняют probe.lua и в 5.1, и в 5.4: поломка на любой из них — повод чинить пробу.
    python pc_probe.py --host 127.0.0.1 --port 5020 safe
"""

from __future__ import annotations

import argparse
import asyncio
import math
import threading
import time
from pathlib import Path

import importlib

from pymodbus.client import ModbusTcpClient
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

HERE = Path(__file__).resolve().parent
SPACE = 0x4000  # адреса ≥ 0x4000 отвечают исключением — как «нет такого адреса»
UNIT = 2
SPEED_MM_S = 100.0  # скорость хода при Override 100 %
ROT_DEG_S = 100.0  # скорость поворота RZ при Override 100 %


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(body: bytes) -> bytes:
    c = crc16(body)
    return body + bytes([c & 0xFF, c >> 8])


class FakeRobot:
    """Заглушки DRAS: регистры, точки, поза, ход с вызовами Mirror, ПЧ по RS-485."""

    def __init__(
        self,
        *,
        nil_pose: bool = False,
        axis4: str = "RZ",
        permissive_axes: bool = False,
        drop_point_writes: bool = False,
        tearing: bool = False,
    ) -> None:
        self.nil_pose, self.axis4, self.permissive_axes, self.tearing = nil_pose, axis4, permissive_axes, tearing
        self.drop_point_writes = drop_point_writes
        self.regs: list[int] = [0] * SPACE
        self.points: dict[object, dict[str, float]] = {}
        self.pose = {"X": 300.0, "Y": -210.0, "Z": -40.0, "R": -100.0}
        self.override = 100
        self.stop = False
        self.mirror = None
        self.rx: list[bytes] = []
        self.writes: list[tuple[str, int]] = []  # журнал записей Lua: ("W"|"M", адрес)
        self.t0 = time.monotonic()
        self.timer0 = time.monotonic()

    # ---- Modbus (сторона Lua) ----
    def read(self, addr, typ):
        addr = int(addr)
        if addr < 0 or addr + (2 if typ == "DW" else 1) > SPACE:
            return None
        if typ == "DW":
            return self.regs[addr] | (self.regs[addr + 1] << 16)
        return self.regs[addr]

    def write(self, addr, typ, value):
        addr, value = int(addr), int(value)
        self._log(("W", addr))
        if typ == "DW":
            value &= 0xFFFFFFFF
            self.regs[addr], self.regs[addr + 1] = value & 0xFFFF, value >> 16
        else:
            self.regs[addr] = value & 0xFFFF

    def multi_read(self, addr, n, _typ):
        addr, n = int(addr), int(n)
        return self.lua.table_from(self.regs[addr : addr + n])

    def multi_write(self, addr, n, _typ, values):
        addr, n = int(addr), int(n)
        self._log(("M", addr))
        vals = [int(values[i + 1]) & 0xFFFF for i in range(n)]
        if self.tearing:  # по одному регистру с паузой: читатель видит смесь
            for i, v in enumerate(vals):
                self.regs[addr + i] = v
                time.sleep(0.0002)
        else:  # присваивание среза атомарно для читателя под GIL
            self.regs[addr : addr + n] = vals

    def _log(self, item: tuple[str, int]) -> None:
        self.writes.append(item)
        if len(self.writes) > 4000:
            del self.writes[:2000]

    # ---- точки и движение ----
    def set_global_point(self, pid, name, x, y, z, r, *_rest):
        pt = {"X": float(x), "Y": float(y), "Z": float(z), "R": float(r)}
        self.points[int(pid)] = pt
        self.points[name] = pt

    def write_point(self, pt, axis, value):
        if self.drop_point_writes:  # WritePoint «принимает» и ничего не пишет
            return
        target = self.points[pt if isinstance(pt, str) else int(pt)]
        if axis in ("X", "Y", "Z"):
            target[axis] = float(value)
        elif axis == self.axis4:
            target["R"] = float(value)
        elif not self.permissive_axes:
            raise ValueError(f"WritePoint: unknown item {axis}")
        # permissive: имя принято и молча проигнорировано

    def read_point(self, pt, item):
        target = self.points[pt if isinstance(pt, str) else int(pt)]
        if item in ("X", "Y", "Z"):
            return target[item]
        if item == "RZ":
            return target["R"]
        if item == "H":
            return 1
        raise ValueError(f"ReadPoint: unknown item {item}")

    def set_local_point(self, pid, *_args):
        if int(pid) not in self.points:  # RL 5-5: локальная точка должна быть заведена в проекте
            raise ValueError(f"SetLocalPoint: point {int(pid)} not established")

    def rsmaster_read(self, slave, addr, qty):
        return tuple((int(addr) + i) & 0xFFFF for i in range(int(qty)))

    def timer_on(self):
        self.timer0 = time.monotonic()

    def timer_read(self):
        return int((time.monotonic() - self.timer0) * 1000)

    def get(self, key):
        return None if self.nil_pose else self.pose[key]

    def move(self, pt, *_pass):
        """Ход: путь копится каждые 10 мс по ТЕКУЩЕЙ скорости (Override на ходу действует)."""
        target = dict(self.points[pt if isinstance(pt, str) else int(pt)])
        start = dict(self.pose)
        dist = math.dist([start[k] for k in "XYZ"], [target[k] for k in "XYZ"])
        span = max(dist / SPEED_MM_S, abs(target["R"] - start["R"]) / ROT_DEG_S)  # «секунды при 100 %»
        done = 0.0
        self.stop = False
        while done < span:
            time.sleep(0.01)
            done = min(span, done + self.override / 100 * 0.01)
            frac = done / span
            for k in self.pose:
                self.pose[k] = start[k] + (target[k] - start[k]) * frac
            if self.mirror is not None:
                self.mirror()  # MultiTask: function2 работает во время хода function1
            if self.stop:
                return
        self.pose.update(target)

    def motion_stop(self):
        self.stop = True

    def set_override(self, v):
        self.override = max(1, int(v))

    # ---- RS-485 к ПЧ ----
    def scm_tx(self, _port, data):
        req = data.encode("latin-1")
        slave, fc = req[0], req[1]
        addr, arg = req[2] * 256 + req[3], req[4] * 256 + req[5]
        if fc == 3:
            body = bytes([slave, 3, 2 * arg]) + b"".join(((addr + i) & 0xFFFF).to_bytes(2, "big") for i in range(arg))
            self.rx.append(with_crc(body))
        elif fc == 6:
            self.rx.append(req)  # штатный ответ FC6 — эхо запроса

    def scm_rx(self, _port):
        if self.rx:
            return 0, self.rx.pop(0).decode("latin-1")
        return 1, ""

    def encoder(self, _cv):
        return int((time.monotonic() - self.t0) * 1000)

    def install(self, lua) -> None:
        self.lua = lua
        g = lua.globals()
        noop = lambda *a: None  # noqa: E731
        stubs = {
            "ReadModbus": self.read, "WriteModbus": self.write,
            "MultiReadModbus": self.multi_read, "MultiWriteModbus": self.multi_write,
            "DELAY": lambda s: time.sleep(float(s)),
            "SetGlobalPoint": self.set_global_point, "WritePoint": self.write_point,
            "ReadPoint": self.read_point, "SetLocalPoint": self.set_local_point,
            "TimerOn": self.timer_on, "TimerRead": self.timer_read, "RSmasterRead": self.rsmaster_read,
            "MovL": self.move, "MovP": self.move, "PASS": lambda: "PASS",
            "MotionStop": self.motion_stop, "Override": self.set_override,
            "RobotX": lambda: self.get("X"), "RobotY": lambda: self.get("Y"),
            "RobotZ": lambda: self.get("Z"), "RobotRZ": lambda: self.get("R"), "RobotHand": lambda: 1,
            "RobotServoOn": noop, "RobotServoOff": noop, "DO": noop, "DI": lambda ch: 0,
            "PassMode": noop, "SetOverlapDistance": noop, "Accur": noop,
            "SpdL": noop, "AccL": noop, "DecL": noop, "SpdJ": noop, "AccJ": noop, "DecJ": noop,
            "SCM_FreePort": lambda *a: 0, "SCM_Tx": self.scm_tx, "SCM_Rx": self.scm_rx,
            "CVT_ChangeMotion": noop, "CVT_SelectMode": noop, "CVT_SetTriggerMode": noop,
            "CVT_CalRobotTrigLine": lambda *a: 0, "CVT_CalZoneEndLine": lambda *a: 0,
            "CVT_SetUserDefineDI": noop, "CVT_Initialization": noop,
            "CVT_GetEncoderPulseCount": self.encoder, "CVT_GetCVSpeed": lambda cv: 0,
            "MultiTask": self.multitask,
        }  # fmt: skip
        # Python-функция в Lua — userdata; у контроллера это function. Оборачиваем, чтобы
        # type(), дамп API и проверки вида type(DI) == "function" видели то же, что на железе.
        as_lua = lua.eval("function(f) return function(...) return f(...) end end")
        for name, fn in stubs.items():
            g[name] = as_lua(fn)

    def multitask(self, motion, mirror):
        self.mirror = mirror
        motion()


class DryRun:
    """Сервер Modbus + probe.lua в отдельном потоке. ``start()`` / ``stop()``."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5020, lua: str = "51", **flags) -> None:
        self.host, self.port, self.lua_version = host, port, lua
        self.robot = FakeRobot(**flags)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ModbusTcpServer | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._serve, daemon=True, name="dry-run-modbus").start()
        if not self._ready.wait(5):
            raise RuntimeError("Modbus-сервер сухого прогона не поднялся")
        cl = ModbusTcpClient(self.host, port=self.port)  # первый запрос привязывает
        for _ in range(50):  # живой список регистров
            if cl.connect() and not cl.read_holding_registers(0, count=1, device_id=UNIT).isError():
                break
            time.sleep(0.1)
        cl.close()
        threading.Thread(target=self._run_lua, daemon=True, name="dry-run-lua").start()

    def stop(self) -> None:
        if self._loop and self._server:
            asyncio.run_coroutine_threadsafe(self._server.shutdown(), self._loop).result(timeout=5)

    def _serve(self) -> None:
        robot = self.robot

        async def binder(_fc, _start, _addr, _count, registers, _values):
            if registers is not robot.regs:
                registers[:] = robot.regs
                robot.regs = registers
            return None

        device = SimDevice(
            id=UNIT, simdata=[SimData(address=0, count=SPACE, values=0, datatype=DataType.REGISTERS)], action=binder
        )

        async def main() -> None:
            self._loop = asyncio.get_running_loop()
            self._server = ModbusTcpServer(context=device, address=(self.host, self.port))
            self._ready.set()
            await self._server.serve_forever()

        asyncio.run(main())

    def _run_lua(self) -> None:
        runtime = importlib.import_module(f"lupa.lua{self.lua_version}").LuaRuntime
        lua = runtime(encoding="latin-1", unpack_returned_tuples=True)
        self.robot.install(lua)
        lua.execute((HERE / "probe.lua").read_text(encoding="utf-8").encode("utf-8").decode("latin-1"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Сухой прогон probe.lua без робота")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--lua", default="51", choices=["51", "52", "53", "54"])
    a = ap.parse_args()
    run = DryRun(port=a.port, lua=a.lua)
    run.start()
    print(f"сухой прогон: probe.lua работает, Modbus 127.0.0.1:{a.port}, unit {UNIT}. Ctrl+C — выход.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        run.stop()


if __name__ == "__main__":
    main()
