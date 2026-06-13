"""
ПК-клиент УНИВЕРСАЛЬНЫЙ — объединяет pc_cvt.py + pc_vfd_control.py.
Одна консоль для робота Delta SCARA через cvt_universal.lua:

    ПК (этот скрипт) = Modbus TCP master
    робот            = встроенный Modbus-сервер (slave, :502)
    робот ⇄ GD20     = RS-485 Modbus RTU (делает Lua на роботе)

Три канала через МАРКЕРЫ (ПК пишет уставку в регистры → ставит флаг → робот
в задаче Motion подхватывает):
    • CVT pick-place  — координаты {X,Y,E_capture}, маркер 0x1100
    • частотник (ПЧ)  — пуск/стоп/частота/сброс, маркер 0x1204
    • параметры робота — скорость + домашняя позиция, маркер 0x1300

Один ModbusTcpClient + один Lock на всё (фоновый feeder CVT и команды
VFD/config делят сокет; pymodbus не потокобезопасен).

⚠️ DW (энкодер) — порядок слов ПК↔робот должен совпасть. Мусор в `enc` →
   поменяй WORD_ORDER (команда `cal` показывает оба варианта).

Зависимости: pip install pymodbus>=3.6
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient

# =====================  КОНФИГУРАЦИЯ  ================================
ROBOT_IP = "192.168.1.7"  # IP робота (его встроенный Modbus-сервер)
ROBOT_PORT = 502
ROBOT_UNIT = 2  # station/unit id Modbus-TCP-slave робота

# ---- Карта регистров — ДОЛЖНА совпадать с cvt_universal.lua ----
# CVT: вход задания (ПК пишет):
REG_JOB_FLAG = 0x1100  # W : МАРКЕР «координаты»: 1 = задание готово
REG_X = 0x1101  # W : X 0.1 мм
REG_Y = 0x1102  # W : Y 0.1 мм
REG_ECAP = 0x1104  # DW: E_capture (энкодер на момент кадра)
REG_ABORT = 0x1106  # W : 1 = аварийный стоп движения (робот зовёт MotionStop)
# CVT: выход состояния (робот пишет):
REG_FREE = 0x1110  # W : 1 = робот свободен, 0 = занят
REG_ENC = 0x1112  # DW: живой энкодер (робот зеркалит)
# CVT: эхо принятых/вычисленных координат:
ECHO_BASE = 0x1120  # начало блока эха (5 регистров подряд)
ECHO_COUNT = 5

# VFD: команда от ПК:
REG_CMD_RUN = 0x1200  # 0 = стоп, 1 = пуск
REG_CMD_DIR = 0x1201  # 0 = вперёд (FWD), 1 = назад (REV)
REG_CMD_FREQ = 0x1202  # уставка частоты ×100 (0.01 Гц). Лимит «W»: ≤ 327.67 Гц
REG_CMD_RESET = 0x1203  # 1 = сброс ошибки
REG_VFD_FLAG = 0x1204  # W : МАРКЕР «команда ПЧ»: 1 = есть новая команда
# VFD: статус (робот зеркалит ответ привода):
REG_ST_BASE = 0x1210  # начало блока статуса (8 слов подряд)
ST_COUNT = 8
ST_RUN, ST_OUT_FREQ, ST_CURRENT, ST_DCBUS = 0, 1, 2, 3
ST_FAULT, ST_STATUSW, ST_HEARTBEAT, ST_COMM_ERR = 4, 5, 6, 7

# Настройки робота от ПК:
REG_CFG_FLAG = 0x1300  # W : МАРКЕР «параметры робота»: 1 = есть настройки
REG_CFG_SPD = 0x1301  # W : скорость SPD_MOVE, %
REG_CFG_HOME_X = 0x1302  # W : домашняя X, 0.1 мм
REG_CFG_HOME_Y = 0x1303  # W : домашняя Y, 0.1 мм
REG_CFG_HOME_Z = 0x1304  # W : домашняя Z, 0.1 мм

# Масштабы
XY_SCALE = 10  # мм → регистр (0.1 мм)
XY_LIMIT_MM = 3276.7  # предел signed-16-bit при этом масштабе
FREQ_SCALE = 100  # 0.01 Гц → 6000 = 60.00 Гц
CURRENT_SCALE = 10  # 0.1 А
DCBUS_SCALE = 1  # 1 В

# Порядок 16-битных слов в DW (энкодер). Проверка — команда `cal`.
WORD_ORDER = "little"  # ПОДТВЕРЖДЕНО: [lo, hi]. big давал мусор

FEED_POLL_S = 0.01  # период опроса REG_FREE в фоновом потоке


# =====================  СЛУЖЕБНЫЕ  =================================
def _enable_nodelay(client: ModbusTcpClient) -> None:
    """Отключить алгоритм Нейгла (TCP_NODELAY) — иначе ~40 мс скачки задержки."""
    sock = getattr(client, "socket", None)
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


def _to_u16(value: int) -> int:
    """signed int16 → беззнаковое слово (two's complement)."""
    return int(value) & 0xFFFF


def _dw_to_regs(value: int) -> list[int]:
    """signed int32 → два регистра в порядке WORD_ORDER."""
    hi, lo = struct.unpack(">HH", struct.pack(">i", int(value)))
    return [hi, lo] if WORD_ORDER == "big" else [lo, hi]


def _regs_to_dw(regs: list[int]) -> int:
    """два регистра → signed int32 в порядке WORD_ORDER."""
    hi, lo = (regs[0], regs[1]) if WORD_ORDER == "big" else (regs[1], regs[0])
    return struct.unpack(">i", struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF))[0]


def _s16(value: int) -> int:
    """беззнаковый регистр (0..65535) → signed int16 (−32768..32767)."""
    return value - 0x10000 if value >= 0x8000 else value


# =====================  ЕДИНЫЙ КЛИЕНТ РОБОТА  =====================
class Robot:
    """Доступ ко всем регистрам cvt_universal.lua. Один Lock на весь сокет
    (CVT-feeder в фоне + VFD/config из главного потока сериализованы)."""

    def __init__(self, client: ModbusTcpClient) -> None:
        self._cli = client
        self._lock = threading.Lock()

    # ---- низкоуровневые обёртки под Lock ----
    def _read(self, address: int, count: int) -> list[int] | None:
        with self._lock:
            rr = self._cli.read_holding_registers(address, count=count, device_id=ROBOT_UNIT)
        return None if rr.isError() else list(rr.registers)

    def _write(self, address: int, value: int) -> bool:
        with self._lock:
            rr = self._cli.write_register(address, int(value), device_id=ROBOT_UNIT)
        return not rr.isError()

    def _atomic(self, ops: "list[tuple]") -> bool:
        """Серия записей под ОДНИМ Lock — чтобы маркер не отрывался от данных и
        фоновый feeder не вклинился между регистрами. ops: ('w', addr, val) | ('wm', addr, [vals])."""
        ok = True
        with self._lock:
            for kind, addr, val in ops:
                if kind == "wm":
                    rr = self._cli.write_registers(addr, val, device_id=ROBOT_UNIT)
                else:
                    rr = self._cli.write_register(addr, int(val), device_id=ROBOT_UNIT)
                ok = (not rr.isError()) and ok
        return ok

    # ================  CVT  ================
    def read_encoder(self) -> int | None:
        regs = self._read(REG_ENC, 2)
        return None if regs is None else _regs_to_dw(regs)

    def read_enc_raw(self) -> list[int] | None:
        return self._read(REG_ENC, 2)

    def is_free(self) -> bool | None:
        regs = self._read(REG_FREE, 1)
        return None if regs is None else (regs[0] == 1)

    def read_echo(self) -> dict | None:
        """Эхо от робота: принятые job_x/y и вычисленные px/py/trav (всё в мм)."""
        regs = self._read(ECHO_BASE, ECHO_COUNT)
        if regs is None:
            return None
        r = [_s16(v) / XY_SCALE for v in regs]
        return {"job_x": r[0], "job_y": r[1], "px": r[2], "py": r[3], "trav": r[4]}

    def abort(self) -> bool:
        """Аварийный стоп текущего движения робота (робот выполнит MotionStop)."""
        return self._write(REG_ABORT, 1)

    def send_job(self, x_mm: float, y_mm: float, e_capture: int) -> bool:
        """Записать задание и поднять маркер. ПОРЯДОК: координаты+энкодер → флаг последним."""
        if abs(x_mm) > XY_LIMIT_MM or abs(y_mm) > XY_LIMIT_MM:
            print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
            return False
        return self._atomic(
            [  # маркер JOB_FLAG — последним, всё под одним Lock
                ("w", REG_X, _to_u16(round(x_mm * XY_SCALE))),
                ("w", REG_Y, _to_u16(round(y_mm * XY_SCALE))),
                ("wm", REG_ECAP, _dw_to_regs(e_capture)),
                ("w", REG_JOB_FLAG, 1),
            ]
        )

    # ================  VFD (ПЧ)  ================
    def vfd_run(self, freq_hz: float, reverse: bool = False) -> bool:
        """Задать частоту и пустить привод (FWD по умолчанию)."""
        return self._atomic(
            [
                ("w", REG_CMD_FREQ, round(freq_hz * FREQ_SCALE)),
                ("w", REG_CMD_DIR, 1 if reverse else 0),
                ("w", REG_CMD_RUN, 1),
                ("w", REG_VFD_FLAG, 1),  # маркер — последним
            ]
        )

    def vfd_set_freq(self, freq_hz: float) -> bool:
        """Изменить частоту «на ходу»."""
        return self._atomic(
            [
                ("w", REG_CMD_FREQ, round(freq_hz * FREQ_SCALE)),
                ("w", REG_VFD_FLAG, 1),
            ]
        )

    def vfd_stop(self) -> bool:
        return self._atomic(
            [
                ("w", REG_CMD_RUN, 0),
                ("w", REG_VFD_FLAG, 1),
            ]
        )

    def vfd_reset_fault(self) -> bool:
        """Запросить сброс ошибки. Заодно снимаем RUN, чтобы привод не стартанул после сброса."""
        return self._atomic(
            [
                ("w", REG_CMD_RUN, 0),
                ("w", REG_CMD_RESET, 1),
                ("w", REG_VFD_FLAG, 1),
            ]
        )

    def read_status(self) -> "VFDStatus | None":
        regs = self._read(REG_ST_BASE, ST_COUNT)
        if regs is None:
            return None
        return VFDStatus(
            running=regs[ST_RUN] == 1,
            out_freq_hz=regs[ST_OUT_FREQ] / FREQ_SCALE,
            current_a=regs[ST_CURRENT] / CURRENT_SCALE,
            dcbus_v=regs[ST_DCBUS] / DCBUS_SCALE,
            fault=regs[ST_FAULT],
            status_word=regs[ST_STATUSW],
            heartbeat=regs[ST_HEARTBEAT],
            comm_errors=regs[ST_COMM_ERR],
        )

    # ================  Параметры робота  ================
    def set_speed(self, pct: int) -> bool:
        """Скорость движений SPD_MOVE, % (1..100)."""
        if not 1 <= pct <= 100:
            print("  ! скорость 1..100 %")
            return False
        return self._atomic(
            [
                ("w", REG_CFG_SPD, pct),
                ("w", REG_CFG_FLAG, 1),  # маркер — последним
            ]
        )

    def set_home(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """Домашняя позиция GL_HOME (X/Y/Z, мм). Применится когда робот свободен."""
        for v in (x_mm, y_mm, z_mm):
            if abs(v) > XY_LIMIT_MM:
                print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
                return False
        return self._atomic(
            [
                ("w", REG_CFG_HOME_X, _to_u16(round(x_mm * XY_SCALE))),
                ("w", REG_CFG_HOME_Y, _to_u16(round(y_mm * XY_SCALE))),
                ("w", REG_CFG_HOME_Z, _to_u16(round(z_mm * XY_SCALE))),
                ("w", REG_CFG_FLAG, 1),  # маркер — последним
            ]
        )


@dataclass
class VFDStatus:
    """Расшифрованный статус привода (из зеркала в регистрах робота)."""

    running: bool
    out_freq_hz: float
    current_a: float
    dcbus_v: float
    fault: int
    status_word: int
    heartbeat: int
    comm_errors: int


def _fmt(st: VFDStatus) -> str:
    flag = "RUN " if st.running else "STOP"
    flt = f" FAULT=0x{st.fault:04X}" if st.fault else ""
    return (
        f"[{flag}] f={st.out_freq_hz:6.2f}Hz  I={st.current_a:5.1f}A  "
        f"Udc={st.dcbus_v:6.1f}V  hb={st.heartbeat}  rsErr={st.comm_errors}{flt}"
    )


# =====================  ОЧЕРЕДЬ + ФОНОВАЯ ПОДАЧА (CVT)  ===========
queue: deque = deque()  # {x, y, enc} — задания с ПК
qlock = threading.Lock()
stop = threading.Event()


def feeder(bot: Robot) -> None:
    """Фоновый поток: когда робот свободен и очередь не пуста — отдать одно задание."""
    while not stop.is_set():
        if bot.is_free():
            with qlock:
                job = queue.popleft() if queue else None
            if job is not None:
                x, y, enc = job
                if bot.send_job(x, y, enc):
                    print(f"  → отдал роботу: X={x} Y={y} E_cap={enc}  (в очереди {len(queue)})")
                    # дождаться, что робот забрал (FREE→0), иначе задвоим задание
                    t0 = time.time()
                    while time.time() - t0 < 1.0 and bot.is_free():
                        time.sleep(0.005)
                    e = bot.read_echo()
                    if e:
                        print(
                            f"     ← робот: принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                            f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
                        )
        time.sleep(FEED_POLL_S)


# =====================  КОНСОЛЬ  ==================================
_HELP = """Команды:
  CVT:
    <x> <y>      ДЕТЕКЦИЯ: стампит энкодер как E_capture и кладёт в очередь
    enc          энкодер / флаг свободы / длина очереди
    last         что робот ПРИНЯЛ и ВЫЧИСЛИЛ (trav, px/py)
    cal          калибровка порядка слов DW
    abort        АВАРИЙНЫЙ СТОП текущего движения (MotionStop на роботе)
  ЧАСТОТНИК (ПЧ):
    r [Гц]       пуск ВПЕРЁД (без аргумента — последняя частота)
    rev [Гц]     пуск НАЗАД
    f <Гц>       задать частоту на ходу
    s            стоп
    reset        сброс аварии
    vfd          показать статус привода
  ПАРАМЕТРЫ РОБОТА:
    spd <%>      скорость движений (1..100)
    home <x> <y> <z>   домашняя позиция, мм
  q              выход (со стопом привода)"""


def console() -> None:
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")
    _enable_nodelay(client)

    bot = Robot(client)
    th = threading.Thread(target=feeder, args=(bot,), daemon=True)
    th.start()

    last_freq = 25.0  # частота по умолчанию для «r» без аргумента
    print(_HELP)
    try:
        while True:
            try:
                line = input("robot> ").strip().lower()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0]

            # ---- выход ----
            if cmd == "q":
                bot.vfd_stop()
                break

            # ---- аварийный стоп ----
            if cmd == "abort":
                print("  → MotionStop" if bot.abort() else "  ! не отправилось")
                continue

            # ---- CVT: запросы ----
            if cmd == "enc":
                print(f"  enc={bot.read_encoder()}  free={bot.is_free()}  queue={len(queue)}")
                continue
            if cmd == "last":
                e = bot.read_echo()
                if e is None:
                    print("  ! нет ответа от робота")
                else:
                    print(
                        f"  принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                        f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
                    )
                continue
            if cmd == "cal":
                raw = bot.read_enc_raw()
                if raw is None:
                    print("  ! нет ответа от робота")
                    continue
                big = struct.unpack(">i", struct.pack(">HH", raw[0], raw[1]))[0]
                lit = struct.unpack(">i", struct.pack(">HH", raw[1], raw[0]))[0]
                print(f"  сырые регистры: {raw}")
                print(f"    WORD_ORDER='big'    → {big}")
                print(f"    WORD_ORDER='little' → {lit}")
                print(f"  Сейчас стоит '{WORD_ORDER}'. Выбери тот, что совпадает с энкодером на роботе.")
                continue

            # ---- ЧАСТОТНИК ----
            if cmd == "vfd":
                st = bot.read_status()
                print(("  " + _fmt(st)) if st else "  <нет ответа — запущен ли cvt_universal?>")
                continue
            if cmd in ("r", "rev", "f", "s", "reset"):
                arg = None
                if len(parts) > 1:
                    try:
                        arg = float(parts[1])
                    except ValueError:
                        print("  ! не число:", parts[1])
                        continue
                if cmd == "s":
                    bot.vfd_stop()
                elif cmd == "reset":
                    bot.vfd_reset_fault()
                elif cmd == "f":
                    if arg is None:
                        print("  ! нужна частота, напр.: f 40")
                        continue
                    bot.vfd_set_freq(arg)
                    last_freq = arg
                elif cmd == "r":
                    last_freq = arg if arg is not None else last_freq
                    bot.vfd_run(last_freq, reverse=False)
                elif cmd == "rev":
                    last_freq = arg if arg is not None else last_freq
                    bot.vfd_run(last_freq, reverse=True)
                st = bot.read_status()
                if st:
                    print("  " + _fmt(st))
                continue

            # ---- ПАРАМЕТРЫ РОБОТА ----
            if cmd == "spd":
                if len(parts) != 2 or not parts[1].isdigit():
                    print("  ! нужно: spd <%>  (1..100)")
                    continue
                if bot.set_speed(int(parts[1])):
                    print(f"  → скорость {parts[1]}% (применится когда робот свободен)")
                continue
            if cmd == "home":
                if len(parts) != 4:
                    print("  ! нужно: home <x> <y> <z>  (мм)")
                    continue
                try:
                    hx, hy, hz = float(parts[1]), float(parts[2]), float(parts[3])
                except ValueError:
                    print("  ! не числа:", line)
                    continue
                if bot.set_home(hx, hy, hz):
                    print(f"  → домашняя позиция X={hx} Y={hy} Z={hz} (применится в простое)")
                continue

            # ---- CVT: детекция «x y» ----
            if len(parts) == 2:
                try:
                    x, y = float(parts[0]), float(parts[1])
                except ValueError:
                    print("  ! не числа:", line, "\n" + _HELP)
                    continue
                enc = bot.read_encoder()  # E_capture в момент «кадра»
                if enc is None:
                    print("  ! не прочитал энкодер — робот отвечает? cvt_universal запущен?")
                    continue
                with qlock:
                    queue.append((x, y, enc))
                print(f"  + детекция в очередь: X={x} Y={y} E_cap={enc}  (в очереди {len(queue)})")
                continue

            print("  ? неизвестная команда.\n" + _HELP)
    except KeyboardInterrupt:
        bot.vfd_stop()
    finally:
        stop.set()
        th.join(timeout=1.0)
        client.close()


if __name__ == "__main__":
    console()
