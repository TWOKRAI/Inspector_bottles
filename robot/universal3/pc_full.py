"""
ПК-клиент CVT + ПЧ — рабочий pc_cvt.py с добавленным управлением частотником INVT GD20.

Топология: ПК = Modbus TCP master, робот = server (cvt_universal.lua).
Робот сам общается с приводом по RS-485 — ПК только пишет команду в регистры
0x1200..0x1204 и читает зеркало статуса 0x1210.

Протокол CVT (как в рабочем cvt_step4 — НЕ менялся):
    «Детекция» (кадр) → ПК читает REG_ENC (живой энкодер робота) = E_capture
                      → кладёт {X, Y, E_capture} в очередь ПК.
    Подача: когда REG_FREE==1 (робот свободен) и очередь не пуста →
            write REG_X, REG_Y, REG_ECAP → write REG_FLAG=1 (ПОСЛЕДНИМ).

Команда ПЧ: write 0x1200..0x1203 → write REG_VFD_FLAG=1 (ПОСЛЕДНИМ). Робот в
            простое Motion подхватывает, шлёт в привод и обновляет статус 0x1210.

⚠️ DW (энкодер) — порядок слов ПК↔робот должен совпасть. Мусор в `enc` →
   поменяй WORD_ORDER (команда `cal` показывает оба варианта).

Зависимости: pip install pymodbus>=3.7  (device_id= появился там; на 3.5/3.6
   молча игнорируется → запросы уходят на slave=0, а не на ROBOT_UNIT).
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
ROBOT_IP = "192.168.1.7"
ROBOT_PORT = 502
ROBOT_UNIT = 2

# ---- CVT: вход задания (ПК пишет) — ДОЛЖНО совпадать с cvt_universal.lua ----
REG_FLAG = 0x1100  # W : 1 = задание готово (ПК), 0 = принято (робот)
REG_X = 0x1101  # W : X 0.1 мм
REG_Y = 0x1102  # W : Y 0.1 мм
REG_ECAP = 0x1104  # DW: E_capture (энкодер на момент кадра)
REG_STOP = 0x1106  # W : СТОП. 0=нет 1=домой+продолжить 2=домой+выход+серво OFF 3=на месте+выход+серво ON
REG_SERVO = 0x1108  # W : серво (одноразовая). 0=нет 1=включить 2=выключить
REG_FREE = 0x1110  # W : 1 = робот свободен, 0 = занят
REG_ENC = 0x1112  # DW: живой энкодер (робот зеркалит)
# Эхо принятых/вычисленных координат:
ECHO_BASE = 0x1120  # начало блока эха (5 регистров подряд)
ECHO_COUNT = 5

# ---- VFD: команда от ПК ----
REG_CMD_RUN = 0x1200  # 0 = стоп, 1 = пуск
REG_CMD_DIR = 0x1201  # 0 = вперёд (FWD), 1 = назад (REV)
REG_CMD_FREQ = 0x1202  # уставка частоты ×100 (0.01 Гц). Лимит «W»: ≤ 327.67 Гц
REG_CMD_RESET = 0x1203  # 1 = сброс ошибки
REG_VFD_FLAG = 0x1204  # W : МАРКЕР «команда ПЧ»: 1 = есть новая команда
# ---- VFD: зеркало статуса привода (робот пишет), блок 0x1210..0x1217 ----
REG_ST_BASE = 0x1210
ST_COUNT = 8
ST_RUN, ST_OUT_FREQ, ST_CURRENT, ST_DCBUS = 0, 1, 2, 3
ST_FAULT, ST_STATUSW, ST_HEARTBEAT, ST_COMM_ERR = 4, 5, 6, 7

# ---- Телеметрия робота (робот пишет, ПК читает), блок 0x1130..0x113A ----
REG_TLM_BASE = 0x1130
TLM_COUNT = 11
(TLM_X, TLM_Y, TLM_Z, TLM_RZ, TLM_MOVING, TLM_SPD, TLM_CVSPEED, TLM_HAND, TLM_HB, TLM_SERVO, TLM_MISS) = range(
    TLM_COUNT
)

# ---- Параметры робота от ПК (ПК пишет блок + маркер 0x1300) ----
REG_CFG_FLAG = 0x1300  # W : МАРКЕР «параметры»: 1 = есть новые настройки
REG_CFG_BASE = 0x1301  # начало блока (= REG_CFG_BASE/CFG_CNT в Lua)
CFG_COUNT = 11
# имя → (индекс в блоке, масштаб «единицы → регистр», знаковое):
CFG_FIELDS = {
    "speed": (0, 1, False),  # %
    "home_x": (1, 10, True),  # мм → 0.1 мм
    "home_y": (2, 10, True),
    "home_z": (3, 10, True),
    "pick_z": (4, 10, True),  # высота забора, мм (X/Y — с камеры)
    "place_x": (5, 10, True),  # точка скидывания, мм
    "place_y": (6, 10, True),
    "place_z": (7, 10, True),
    "grip_ms": (8, 1, False),  # мс
    "zone_max": (9, 10, True),  # внешний радиус зоны, мм (0 = выкл)
    "zone_min": (10, 10, True),  # внутренний радиус, мм (0 = выкл)
}

XY_SCALE = 10  # мм → регистр (0.1 мм)
XY_LIMIT_MM = 3276.7  # предел signed-16-bit при этом масштабе
FREQ_SCALE = 100  # 0.01 Гц → 6000 = 60.00 Гц
CURRENT_SCALE = 10  # 0.1 А
DCBUS_SCALE = 10  # 0.1 В (привод отдаёт ×10: 3289 → 328.9 В)

# Порядок 16-битных слов в DW. Проверка: команда `cal`.
WORD_ORDER = "little"  # ПОДТВЕРЖДЕНО: [lo, hi]. big давал мусор

FEED_POLL_S = 0.01  # период опроса REG_FREE в фоновом потоке


# =====================  СЛУЖЕБНЫЕ  =================================
def _enable_nodelay(client: ModbusTcpClient) -> None:
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


# =====================  КЛИЕНТ РОБОТА  ============================
class Robot:
    """Доступ к регистрам cvt_universal.lua (CVT + ПЧ). Всё под одним Lock
    (фоновый feeder и команды ПЧ делят сокет; pymodbus не потокобезопасен)."""

    def __init__(self, client: ModbusTcpClient) -> None:
        self._cli = client
        self._lock = threading.Lock()

    # ---- низкоуровневые обёртки ----
    def _read(self, address: int, count: int) -> list[int] | None:
        with self._lock:
            rr = self._cli.read_holding_registers(address, count=count, device_id=ROBOT_UNIT)
        return None if rr.isError() else list(rr.registers)

    def _atomic(self, ops: "list[tuple]") -> bool:
        """Серия записей под ОДНИМ Lock — маркер не отрывается от данных."""
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
        """Эхо: принятые job_x/y и вычисленные px/py/trav (всё в мм)."""
        regs = self._read(ECHO_BASE, ECHO_COUNT)
        if regs is None:
            return None
        r = [_s16(v) / XY_SCALE for v in regs]
        return {"job_x": r[0], "job_y": r[1], "px": r[2], "py": r[3], "trav": r[4]}

    def send_job(self, x_mm: float, y_mm: float, e_capture: int) -> bool:
        """Записать задание и поднять флаг. ПОРЯДОК: координаты+энкодер → флаг последним."""
        if abs(x_mm) > XY_LIMIT_MM or abs(y_mm) > XY_LIMIT_MM:
            print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
            return False
        return self._atomic(
            [
                ("w", REG_X, _to_u16(round(x_mm * XY_SCALE))),
                ("w", REG_Y, _to_u16(round(y_mm * XY_SCALE))),
                ("wm", REG_ECAP, _dw_to_regs(e_capture)),
                ("w", REG_FLAG, 1),  # маркер — последним!
            ]
        )

    def stop(self, mode: int) -> bool:
        """СТОП: 1=домой+продолжить, 2=домой+выход+серво OFF, 3=на месте+выход+серво ON."""
        return self._atomic([("w", REG_STOP, mode)])

    def servo(self, on: bool) -> bool:
        """Включить/выключить серво (применится в простое)."""
        return self._atomic([("w", REG_SERVO, 1 if on else 2)])

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
        """Сброс ошибки. Заодно снимаем RUN, чтобы привод не стартанул после сброса."""
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

    # ================  Параметры робота (блок 0x1300)  ================
    def get_config(self) -> dict | None:
        """Прочитать текущие параметры робота. Ключи — из CFG_FIELDS."""
        regs = self._read(REG_CFG_BASE, CFG_COUNT)
        if regs is None:
            return None
        out = {}
        for name, (idx, scale, signed) in CFG_FIELDS.items():
            v = _s16(regs[idx]) if signed else regs[idx]
            out[name] = v / scale if scale != 1 else v
        return out

    def set_config(self, **fields) -> bool:
        """Read-modify-write: читаем блок, меняем указанные поля, пишем блок + маркер.
        Допустимые имена — ключи CFG_FIELDS."""
        regs = self._read(REG_CFG_BASE, CFG_COUNT)
        if regs is None:
            print("  ! не прочитал блок параметров — робот отвечает?")
            return False
        for name, val in fields.items():
            spec = CFG_FIELDS.get(name)
            if spec is None:
                print(f"  ! неизвестный параметр: {name}")
                continue
            idx, scale, signed = spec
            raw = round(val * scale)
            regs[idx] = _to_u16(raw) if signed else int(raw) & 0xFFFF
        return self._atomic(
            [
                ("wm", REG_CFG_BASE, regs),
                ("w", REG_CFG_FLAG, 1),  # маркер — последним
            ]
        )

    def set_speed(self, pct: int) -> bool:
        if not 1 <= pct <= 100:
            print("  ! скорость 1..100 %")
            return False
        return self.set_config(speed=pct)

    def set_home(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        for v in (x_mm, y_mm, z_mm):
            if abs(v) > XY_LIMIT_MM:
                print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
                return False
        return self.set_config(home_x=x_mm, home_y=y_mm, home_z=z_mm)

    def set_pick_z(self, z_mm: float) -> bool:
        """Высота забора (Z точки GL_PICK); X/Y приходят с камеры."""
        return self.set_config(pick_z=z_mm)

    def set_place(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """Точка скидывания GL_PLACE (X/Y/Z, мм)."""
        for v in (x_mm, y_mm, z_mm):
            if abs(v) > XY_LIMIT_MM:
                print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
                return False
        return self.set_config(place_x=x_mm, place_y=y_mm, place_z=z_mm)

    def set_zone(self, r_max_mm: float, r_min_mm: float | None = None) -> bool:
        """Кольцо досягаемости от базы (мм): внешний радиус и (опц.) внутренний. 0 = выкл."""
        f = {"zone_max": r_max_mm}
        if r_min_mm is not None:
            f["zone_min"] = r_min_mm
        return self.set_config(**f)

    def set_grip_time(self, sec: float) -> bool:
        return self.set_config(grip_ms=round(sec * 1000))

    # ================  Телеметрия робота (робот → ПК)  ================
    def read_telemetry(self) -> "Telemetry | None":
        regs = self._read(REG_TLM_BASE, TLM_COUNT)
        if regs is None:
            return None
        return Telemetry(
            x_mm=_s16(regs[TLM_X]) / XY_SCALE,
            y_mm=_s16(regs[TLM_Y]) / XY_SCALE,
            z_mm=_s16(regs[TLM_Z]) / XY_SCALE,
            rz_deg=_s16(regs[TLM_RZ]) / XY_SCALE,
            moving=regs[TLM_MOVING] == 1,
            spd_pct=regs[TLM_SPD],
            belt_mm_s=_s16(regs[TLM_CVSPEED]),
            hand=regs[TLM_HAND],
            heartbeat=regs[TLM_HB],
            servo=regs[TLM_SERVO] == 1,
            miss_count=regs[TLM_MISS],
        )


@dataclass
class VFDStatus:
    running: bool
    out_freq_hz: float
    current_a: float
    dcbus_v: float
    fault: int
    status_word: int
    heartbeat: int
    comm_errors: int


@dataclass
class Telemetry:
    """Живая телеметрия робота (блок 0x1130)."""

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float
    moving: bool  # True = выполняет задание (занят)
    spd_pct: int  # текущая скорость SPD_MOVE, %
    belt_mm_s: int  # скорость ленты, мм/с
    hand: int  # конфигурация руки: 0 = правая, 1 = левая
    heartbeat: int  # растёт каждую публикацию — контроль «живости» робота
    servo: bool  # True = серво включено
    miss_count: int  # счётчик «объект ушёл за зону»


def _fmt(st: VFDStatus) -> str:
    flag = "RUN " if st.running else "STOP"
    flt = f" FAULT=0x{st.fault:04X}" if st.fault else ""
    return (
        f"[{flag}] f={st.out_freq_hz:6.2f}Hz  I={st.current_a:5.1f}A  "
        f"Udc={st.dcbus_v:6.1f}V  hb={st.heartbeat}  rsErr={st.comm_errors}{flt}"
    )


def _fmt_tlm(t: Telemetry) -> str:
    busy = "ЗАНЯТ" if t.moving else "СВОБ "
    hand = "ЛЕВ" if t.hand == 1 else "ПРАВ"
    srv = "ON " if t.servo else "OFF"
    return (
        f"[{busy}] X={t.x_mm:7.1f} Y={t.y_mm:7.1f} Z={t.z_mm:7.1f} RZ={t.rz_deg:6.1f}  "
        f"рука={hand} серво={srv} спд={t.spd_pct}% лента={t.belt_mm_s}мм/с "
        f"miss={t.miss_count} hb={t.heartbeat}"
    )


# =====================  ОЧЕРЕДЬ + ФОНОВАЯ ПОДАЧА (CVT)  ===========
queue: deque = deque()
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
    <x> <y>   ДЕТЕКЦИЯ: стампит энкодер как E_capture и кладёт в очередь
    enc       энкодер / флаг свободы / длина очереди (разовый)
    mon [сек] ЖИВОЙ опрос энкодера (по умолч. 10 с, Ctrl+C — назад)
    last      что робот ПРИНЯЛ и ВЫЧИСЛИЛ (trav, px/py)
    cal       калибровка порядка слов DW
  СТОП ДВИЖЕНИЯ:
    stop      №1: бросить, домой, ОСТАТЬСЯ в цикле (можно продолжить)
    halt      №2: домой, ВЫЙТИ из цикла, серво OFF
    estop     №3: стоп НА МЕСТЕ, выйти из программы, серво ON
  ТЕЛЕМЕТРИЯ:
    pos       позиция робота X/Y/Z/RZ
    state|st  занят/свободен, рука, скорость, лента, heartbeat
    params    показать текущие параметры робота
  ПАРАМЕТРЫ РОБОТА:
    spd <%>            скорость движений (1..100)
    home <x> <y> <z>   домашняя позиция, мм
    place <x> <y> <z>  точка скидывания, мм
    zpick <мм>         высота забора (X/Y — с камеры)
    zone <макс> [мин]  кольцо досягаемости, мм (по умолч. 500/120; 0=выкл)
    grip <c>           время захвата
    servo on|off       включить/выключить серво
  ЧАСТОТНИК (ПЧ):
    r [Гц]    пуск ВПЕРЁД (без аргумента — последняя частота)
    rev [Гц]  пуск НАЗАД
    f <Гц>    задать частоту на ходу
    s         стоп
    reset     сброс аварии
    vfd       показать статус привода
  q           выход (со стопом привода)"""


def console() -> None:
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")
    _enable_nodelay(client)

    bot = Robot(client)
    last_freq = 10.0  # для «r»/«rev» без аргумента
    th = threading.Thread(target=feeder, args=(bot,), daemon=True)
    th.start()
    print(_HELP)
    try:
        while True:
            try:
                line = input("robot> ").strip().lower()
            except EOFError:
                break
            if not line:
                continue
            if line == "q":
                bot.vfd_stop()
                break
            parts = line.split()
            cmd = parts[0]

            # ---- CVT ----
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
            if cmd == "mon":
                # живой опрос энкодера: mon [сек] (по умолчанию 10). Ctrl+C — назад к prompt.
                secs = 10.0
                if len(parts) == 2:
                    try:
                        secs = float(parts[1])
                    except ValueError:
                        pass
                try:
                    t_end = time.time() + secs
                    while time.time() < t_end:
                        print(
                            f"  enc={bot.read_encoder()}  free={bot.is_free()}  queue={len(queue)}   ",
                            end="\r",
                            flush=True,
                        )
                        time.sleep(0.2)
                    print()
                except KeyboardInterrupt:
                    print("\n  (стоп опроса)")
                continue

            # ---- СТОП ДВИЖЕНИЯ ----
            if cmd == "stop":
                print("  → СТОП-1: домой, остаюсь в цикле" if bot.stop(1) else "  ! не отправилось")
                continue
            if cmd == "halt":
                print("  → СТОП-2: домой, выход, серво OFF" if bot.stop(2) else "  ! не отправилось")
                continue
            if cmd == "estop":
                print("  → СТОП-3: на месте, выход, серво ON" if bot.stop(3) else "  ! не отправилось")
                continue

            # ---- ТЕЛЕМЕТРИЯ ----
            if cmd == "pos":
                t = bot.read_telemetry()
                if t is None:
                    print("  ! нет телеметрии — cvt_universal запущен?")
                else:
                    print(f"  X={t.x_mm:.1f} Y={t.y_mm:.1f} Z={t.z_mm:.1f} RZ={t.rz_deg:.1f}")
                continue
            if cmd in ("state", "st"):
                t = bot.read_telemetry()
                print(("  " + _fmt_tlm(t)) if t else "  ! нет телеметрии — cvt_universal запущен?")
                continue

            # ---- ПАРАМЕТРЫ РОБОТА ----
            if cmd == "params":
                cfg = bot.get_config()
                print(("  " + "  ".join(f"{k}={v}" for k, v in cfg.items())) if cfg else "  ! не прочитал параметры")
                continue
            if cmd == "spd":
                if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
                    print("  ! нужно: spd <%>  (1..100)")
                elif bot.set_speed(int(parts[1])):
                    print(f"  → скорость {parts[1]}% (применится в простое)")
                continue
            if cmd in ("home", "place"):
                if len(parts) != 4:
                    print(f"  ! нужно: {cmd} <x> <y> <z>  (мм)")
                    continue
                try:
                    ax, ay, az = (float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    print("  ! не числа:", line)
                    continue
                ok = bot.set_home(ax, ay, az) if cmd == "home" else bot.set_place(ax, ay, az)
                name = "домашняя" if cmd == "home" else "скидывания"
                if ok:
                    print(f"  → точка {name} X={ax} Y={ay} Z={az} (применится в простое)")
                continue
            if cmd in ("zpick", "grip"):
                if len(parts) != 2:
                    print(f"  ! нужно: {cmd} <число>")
                    continue
                try:
                    val = float(parts[1])
                except ValueError:
                    print("  ! не число:", parts[1])
                    continue
                if cmd == "zpick":
                    ok, unit = bot.set_pick_z(val), "мм высота забора"
                else:
                    ok, unit = bot.set_grip_time(val), "c время захвата"
                if ok:
                    print(f"  → {cmd}={val} ({unit}, применится в простое)")
                continue
            if cmd == "zone":
                if len(parts) not in (2, 3):
                    print("  ! нужно: zone <макс> [мин]  (мм, 0=выкл)")
                    continue
                try:
                    rmax = float(parts[1])
                    rmin = float(parts[2]) if len(parts) == 3 else None
                except ValueError:
                    print("  ! не числа:", line)
                    continue
                if bot.set_zone(rmax, rmin):
                    mn = f" мин={rmin}" if rmin is not None else ""
                    print(f"  → зона: макс={rmax}{mn} мм (применится в простое)")
                continue
            if cmd == "servo":
                if len(parts) != 2 or parts[1] not in ("on", "off"):
                    print("  ! нужно: servo on|off")
                elif bot.servo(parts[1] == "on"):
                    print(f"  → серво {parts[1].upper()} (применится в простое)")
                continue

            # ---- ЧАСТОТНИК (ПЧ) ----
            if cmd in ("r", "rev", "f"):
                arg = None
                if len(parts) > 1:
                    try:
                        arg = float(parts[1])
                    except ValueError:
                        print("  ! не число:", parts[1])
                        continue
                if cmd == "f":
                    if arg is None:
                        print("  ! нужна частота, напр.: f 40")
                        continue
                    bot.vfd_set_freq(arg)
                    last_freq = arg
                else:
                    last_freq = arg if arg is not None else last_freq
                    bot.vfd_run(last_freq, reverse=(cmd == "rev"))
                st = bot.read_status()
                if st:
                    print("  " + _fmt(st))
                continue
            if cmd == "s":
                bot.vfd_stop()
                st = bot.read_status()
                if st:
                    print("  " + _fmt(st))
                continue
            if cmd == "reset":
                bot.vfd_reset_fault()
                st = bot.read_status()
                if st:
                    print("  " + _fmt(st))
                continue
            if cmd == "vfd":
                st = bot.read_status()
                print(("  " + _fmt(st)) if st else "  <нет ответа — запущен ли cvt_universal?>")
                continue

            # ---- FALLBACK: детекция «x y» ----
            if len(parts) != 2:
                print("  ! неизвестная команда\n" + _HELP)
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                print("  ! не числа:", line)
                continue
            enc = bot.read_encoder()  # E_capture в момент «кадра»
            if enc is None:
                print("  ! не прочитал энкодер — робот отвечает? cvt_universal запущен?")
                continue
            with qlock:
                queue.append((x, y, enc))
            print(f"  + детекция в очередь: X={x} Y={y} E_cap={enc}  (в очереди {len(queue)})")
    except KeyboardInterrupt:
        bot.vfd_stop()
    finally:
        stop.set()
        th.join(timeout=1.0)
        client.close()


if __name__ == "__main__":
    console()
