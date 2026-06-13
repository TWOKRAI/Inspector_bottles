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

Зависимости: pip install pymodbus>=3.7
  ⚠️ Именно >=3.7: параметр device_id= (unit id робота) появился там. На 3.5/3.6
     он молча игнорируется (уходит в **kwargs) → все запросы идут на slave=0, а не
     на ROBOT_UNIT. Проверь версию на ПК робота: python -c "import pymodbus;print(pymodbus.__version__)"
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException

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

# Настройки робота от ПК — расширенный блок 0x1301.. + маркер 0x1300.
# МАСШТАБИРУЕМО: добавить параметр = строка в CFG_FIELDS + регистр/применение в cvt_universal.lua.
REG_CFG_FLAG = 0x1300  # W : МАРКЕР «параметры робота»: 1 = есть настройки
REG_CFG_BASE = 0x1301  # начало блока параметров (= REG_CFG_BASE/CFG_CNT в Lua)
CFG_COUNT = 8  # число регистров в блоке
# имя → (индекс в блоке, масштаб «единицы → регистр», знаковое):
CFG_FIELDS = {
    "speed": (0, 1, False),  # %
    "home_x": (1, 10, True),  # мм → 0.1 мм
    "home_y": (2, 10, True),
    "home_z": (3, 10, True),
    "tracking": (4, 1, False),  # 0/1
    "pick_tol": (5, 10, True),  # мм → 0.1 мм
    "z_pick": (6, 10, True),  # мм → 0.1 мм
    "grip_ms": (7, 1, False),  # мс
}

# Телеметрия робота (робот пишет, ПК читает) — блок 0x1130:
REG_TLM_BASE = 0x1130
TLM_COUNT = 10
(TLM_X, TLM_Y, TLM_Z, TLM_RZ, TLM_MOVING, TLM_TRACKING, TLM_SPD, TLM_CVSPEED, TLM_HB, TLM_MISS) = range(TLM_COUNT)

# Масштабы
XY_SCALE = 10  # мм → регистр (0.1 мм)
XY_LIMIT_MM = 3276.7  # предел signed-16-bit при этом масштабе
FREQ_SCALE = 100  # 0.01 Гц → 6000 = 60.00 Гц
CURRENT_SCALE = 10  # 0.1 А
DCBUS_SCALE = 1  # 1 В

# Порядок 16-битных слов в DW (энкодер). Проверка — команда `cal`.
WORD_ORDER = "little"  # ПОДТВЕРЖДЕНО: [lo, hi]. big давал мусор

FEED_POLL_S = 0.01  # период опроса REG_FREE в фоновом потоке
JOB_WAIT_S = 20.0  # макс ожидание завершения задания (должно быть > job-watchdog робота)


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

    # ---- низкоуровневые обёртки под Lock (+авто-реконнект при обрыве TCP) ----
    def _reconnect(self, err: Exception) -> None:
        """Восстановить TCP после обрыва. Зовётся ИЗ-ПОД self._lock."""
        print(f"  ! обрыв связи с роботом ({err}); переподключение…")
        try:
            self._cli.connect()
            _enable_nodelay(self._cli)
        except OSError:
            pass

    def _read(self, address: int, count: int) -> list[int] | None:
        with self._lock:
            try:
                rr = self._cli.read_holding_registers(address, count=count, device_id=ROBOT_UNIT)
            except (ConnectionException, OSError) as e:
                self._reconnect(e)
                return None
        return None if rr.isError() else list(rr.registers)

    def _write(self, address: int, value: int) -> bool:
        with self._lock:
            try:
                rr = self._cli.write_register(address, int(value), device_id=ROBOT_UNIT)
            except (ConnectionException, OSError) as e:
                self._reconnect(e)
                return False
        return not rr.isError()

    def _atomic(self, ops: "list[tuple]") -> bool:
        """Серия записей под ОДНИМ Lock — чтобы маркер не отрывался от данных и
        фоновый feeder не вклинился между регистрами. ops: ('w', addr, val) | ('wm', addr, [vals])."""
        ok = True
        with self._lock:
            try:
                for kind, addr, val in ops:
                    if kind == "wm":
                        rr = self._cli.write_registers(addr, val, device_id=ROBOT_UNIT)
                    else:
                        rr = self._cli.write_register(addr, int(val), device_id=ROBOT_UNIT)
                    ok = (not rr.isError()) and ok
            except (ConnectionException, OSError) as e:
                self._reconnect(e)
                return False
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

    def job_accepted(self) -> bool | None:
        """True = робот квитировал приём задания (JOB_FLAG=0 → координаты прочитаны).
        None = нет ответа (НЕ трактовать как «принял»)."""
        regs = self._read(REG_JOB_FLAG, 1)
        return None if regs is None else (regs[0] == 0)

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

    # ================  Параметры робота (масштабируемый блок)  ================
    def get_config(self) -> dict | None:
        """Прочитать текущие параметры робота (весь блок). Ключи — из CFG_FIELDS."""
        regs = self._read(REG_CFG_BASE, CFG_COUNT)
        if regs is None:
            return None
        out = {}
        for name, (idx, scale, signed) in CFG_FIELDS.items():
            v = _s16(regs[idx]) if signed else regs[idx]
            out[name] = v / scale if scale != 1 else v
        return out

    def set_config(self, **fields) -> bool:
        """Задать параметры робота. Read-modify-write: читаем блок, меняем указанные
        поля, пишем блок целиком + маркер (остальные значения сохраняются).
        Допустимые имена — ключи CFG_FIELDS (добавить параметр = одна строка там)."""
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

    # ---- удобные обёртки над set_config ----
    def set_speed(self, pct: int) -> bool:
        """Скорость движений SPD_MOVE, % (1..100)."""
        if not 1 <= pct <= 100:
            print("  ! скорость 1..100 %")
            return False
        return self.set_config(speed=pct)

    def set_home(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """Домашняя позиция GL_HOME (X/Y/Z, мм). Применится когда робот свободен."""
        for v in (x_mm, y_mm, z_mm):
            if abs(v) > XY_LIMIT_MM:
                print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
                return False
        return self.set_config(home_x=x_mm, home_y=y_mm, home_z=z_mm)

    def set_tracking(self, on: bool) -> bool:
        """Включить/выключить отслеживание (приём CVT-заданий)."""
        return self.set_config(tracking=1 if on else 0)

    def set_precision(self, tol_mm: float) -> bool:
        """Допуск ловли, мм (0 = не используется)."""
        return self.set_config(pick_tol=tol_mm)

    def set_z_pick(self, z_mm: float) -> bool:
        """Высота захвата Z_PICK, мм."""
        return self.set_config(z_pick=z_mm)

    def set_grip_time(self, sec: float) -> bool:
        """Время захвата, c."""
        return self.set_config(grip_ms=round(sec * 1000))

    # ================  Телеметрия (робот → ПК)  ================
    def read_telemetry(self) -> "Telemetry | None":
        """Живая телеметрия: позиция, состояние, скорости (блок 0x1130)."""
        regs = self._read(REG_TLM_BASE, TLM_COUNT)
        if regs is None:
            return None
        return Telemetry(
            x_mm=_s16(regs[TLM_X]) / XY_SCALE,
            y_mm=_s16(regs[TLM_Y]) / XY_SCALE,
            z_mm=_s16(regs[TLM_Z]) / XY_SCALE,
            rz_deg=_s16(regs[TLM_RZ]) / XY_SCALE,
            moving=regs[TLM_MOVING] == 1,
            tracking=regs[TLM_TRACKING] == 1,
            spd_pct=regs[TLM_SPD],
            belt_mm_s=regs[TLM_CVSPEED],
            heartbeat=regs[TLM_HB],
            miss_count=regs[TLM_MISS],
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


@dataclass
class Telemetry:
    """Живая телеметрия робота (блок 0x1130)."""

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float
    moving: bool  # True = выполняет задание (занят)
    tracking: bool  # True = отслеживание включено
    spd_pct: int  # текущая скорость SPD_MOVE, %
    belt_mm_s: int  # скорость ленты, мм/с
    heartbeat: int  # растёт каждую публикацию — контроль «живости» робота
    miss_count: int  # счётчик «не успел взять» (объект/рука за зоной)


def _fmt_tlm(t: Telemetry) -> str:
    busy = "ЗАНЯТ" if t.moving else "СВОБ "
    trk = "ON " if t.tracking else "OFF"
    return (
        f"[{busy}] X={t.x_mm:7.1f} Y={t.y_mm:7.1f} Z={t.z_mm:7.1f} RZ={t.rz_deg:6.1f}  "
        f"отслеж={trk} спд={t.spd_pct}% лента={t.belt_mm_s}мм/с hb={t.heartbeat}"
    )


def _fmt(st: VFDStatus) -> str:
    flag = "RUN " if st.running else "STOP"
    flt = f" FAULT=0x{st.fault:04X}" if st.fault else ""
    return (
        f"[{flag}] f={st.out_freq_hz:6.2f}Hz  I={st.current_a:5.1f}A  "
        f"Udc={st.dcbus_v:6.1f}V  hb={st.heartbeat}  rsErr={st.comm_errors}{flt}"
    )


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
  ТЕЛЕМЕТРИЯ:
    pos          позиция робота X/Y/Z/RZ
    state | st   занят/свободен, отслеживание, скорость, лента, heartbeat
    params       показать текущие параметры робота
  ПАРАМЕТРЫ РОБОТА:
    spd <%>      скорость движений (1..100)
    home <x> <y> <z>   домашняя позиция, мм
    track on|off включить/выключить отслеживание
    prec <мм>    допуск ловли (0 = выкл)
    zpick <мм>   высота захвата Z_PICK
    grip <c>     время захвата
  q              выход (со стопом привода)"""


class Console:
    """Состояние интерактивной сессии управления роботом.

    Инкапсулирует всё, что раньше было модульными глобалами + функцией feeder:
        • bot          — единый клиент робота (Robot)
        • queue/qlock  — очередь CVT-заданий и Lock к ней
        • stop/th      — событие останова и фоновый поток feeder
        • last_freq    — последняя заданная частота (для «r»/«rev» без аргумента)

    Команды REPL раскладываются через таблицу `_dispatch` (имя→метод-обработчик),
    обработчик принимает `parts` (список токенов строки) и сам печатает вывод.
    Сначала пробуется таблица команд, затем fallback-детекция «x y», затем unknown.
    """

    def __init__(self, client: ModbusTcpClient) -> None:
        self._client = client
        self.bot = Robot(client)
        self.queue: deque = deque()  # (x, y, enc) — задания с ПК
        self.qlock = threading.Lock()
        self.stop = threading.Event()
        self.last_freq = 25.0  # частота по умолчанию для «r» без аргумента
        self._th = threading.Thread(target=self.feeder, daemon=True)
        # таблица команд: имя/алиас → метод-обработчик(parts)
        self._dispatch = {
            # CVT
            "enc": self._cmd_enc,
            "last": self._cmd_last,
            "cal": self._cmd_cal,
            "abort": self._cmd_abort,
            # ЧАСТОТНИК (ПЧ)
            "r": self._cmd_drive,
            "rev": self._cmd_drive,
            "f": self._cmd_drive,
            "s": self._cmd_drive,
            "reset": self._cmd_drive,
            "vfd": self._cmd_vfd,
            # ТЕЛЕМЕТРИЯ / СОСТОЯНИЕ
            "pos": self._cmd_pos,
            "state": self._cmd_state,
            "st": self._cmd_state,
            "params": self._cmd_params,
            # ПАРАМЕТРЫ РОБОТА
            "spd": self._cmd_spd,
            "home": self._cmd_home,
            "track": self._cmd_track,
            "prec": self._cmd_field,
            "zpick": self._cmd_field,
            "grip": self._cmd_field,
        }

    # =====================  ФОНОВАЯ ПОДАЧА (CVT)  =====================
    def feeder(self) -> None:
        """Фоновый поток: когда робот свободен — отдать задание и проследить исход."""
        while not self.stop.is_set():
            if self.bot.is_free():
                with self.qlock:
                    job = self.queue.popleft() if self.queue else None
                if job is not None:
                    self._deliver(job)
            time.sleep(FEED_POLL_S)

    def _wait(self, cond, timeout: float) -> bool:
        """Ждать, пока cond() == True, до timeout (или stop). False = не дождались."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.stop.is_set():
                return False
            if cond():
                return True
            time.sleep(0.01)
        return False

    def _miss_count(self) -> int | None:
        t = self.bot.read_telemetry()
        return t.miss_count if t else None

    def _deliver(self, job: tuple) -> None:
        """Отдать одно задание и сообщить исход: принял / не успел взять / не отдалось."""
        x, y, enc = job
        miss0 = self._miss_count()  # счётчик промахов ДО задания

        if not self.bot.send_job(x, y, enc):
            print(f"  ! не отдалось (связь?) — верну в очередь: X={x} Y={y}")
            with self.qlock:
                self.queue.appendleft(job)
            return
        print(f"  → отдал роботу: X={x} Y={y} E_cap={enc}  (в очереди {len(self.queue)})")

        # 1) робот ЗАБРАЛ координаты? (JOB_FLAG→0; None ≠ «забрал»). Иначе — вернуть в очередь.
        if not self._wait(lambda: self.bot.job_accepted() is True, 1.0):
            print("  ! робот не принял задание за 1 с — верну в очередь")
            with self.qlock:
                self.queue.appendleft(job)
            return

        e = self.bot.read_echo()
        if e:
            print(
                f"     ← робот принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
            )

        # 2) дождаться завершения (FREE→1) и определить исход по счётчику промахов
        if not self._wait(lambda: self.bot.is_free() is True, JOB_WAIT_S):
            print("  ! задание не завершилось вовремя (робот завис?)")
            return
        miss1 = self._miss_count()
        if miss0 is not None and miss1 is not None and miss1 != miss0:
            print("  ✗ робот НЕ успел взять (объект/рука за зоной) — следующий")
        else:
            print("  ✓ цикл завершён")

    # =====================  ПАРСИНГ АРГУМЕНТОВ  ======================
    @staticmethod
    def _floats(parts: list[str], n: int) -> list[float] | None:
        """Распарсить ровно n float из parts[1:1+n]. None при ошибке (с печатью «! не числа»)."""
        try:
            return [float(p) for p in parts[1 : 1 + n]]
        except ValueError:
            print("  ! не числа:", " ".join(parts))
            return None

    # =====================  CVT  =====================================
    def _cmd_abort(self, parts: list[str]) -> None:
        print("  → MotionStop" if self.bot.abort() else "  ! не отправилось")

    def _cmd_enc(self, parts: list[str]) -> None:
        print(f"  enc={self.bot.read_encoder()}  free={self.bot.is_free()}  queue={len(self.queue)}")

    def _cmd_last(self, parts: list[str]) -> None:
        e = self.bot.read_echo()
        if e is None:
            print("  ! нет ответа от робота")
        else:
            print(
                f"  принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
            )

    def _cmd_cal(self, parts: list[str]) -> None:
        raw = self.bot.read_enc_raw()
        if raw is None:
            print("  ! нет ответа от робота")
            return
        big = struct.unpack(">i", struct.pack(">HH", raw[0], raw[1]))[0]
        lit = struct.unpack(">i", struct.pack(">HH", raw[1], raw[0]))[0]
        print(f"  сырые регистры: {raw}")
        print(f"    WORD_ORDER='big'    → {big}")
        print(f"    WORD_ORDER='little' → {lit}")
        print(f"  Сейчас стоит '{WORD_ORDER}'. Выбери тот, что совпадает с энкодером на роботе.")

    # =====================  ТЕЛЕМЕТРИЯ / СОСТОЯНИЕ  =================
    def _cmd_pos(self, parts: list[str]) -> None:
        t = self.bot.read_telemetry()
        if t is None:
            print("  ! нет телеметрии — cvt_universal запущен?")
        else:
            print(f"  X={t.x_mm:.1f} Y={t.y_mm:.1f} Z={t.z_mm:.1f} RZ={t.rz_deg:.1f}")

    def _cmd_state(self, parts: list[str]) -> None:
        t = self.bot.read_telemetry()
        print(("  " + _fmt_tlm(t)) if t else "  ! нет телеметрии — cvt_universal запущен?")

    def _cmd_params(self, parts: list[str]) -> None:
        cfg = self.bot.get_config()
        if cfg is None:
            print("  ! не прочитал параметры")
        else:
            print("  " + "  ".join(f"{k}={v}" for k, v in cfg.items()))

    def _cmd_track(self, parts: list[str]) -> None:
        if len(parts) != 2 or parts[1] not in ("on", "off"):
            print("  ! нужно: track on|off")
            return
        if self.bot.set_tracking(parts[1] == "on"):
            print(f"  → отслеживание {parts[1].upper()} (применится в простое)")

    def _cmd_field(self, parts: list[str]) -> None:
        """prec / zpick / grip — один float, разные обёртки set_config."""
        cmd = parts[0]
        if len(parts) != 2:
            print(f"  ! нужно: {cmd} <число>")
            return
        try:
            val = float(parts[1])
        except ValueError:
            print("  ! не число:", parts[1])
            return
        if cmd == "prec":
            ok, unit = self.bot.set_precision(val), "мм допуск ловли"
        elif cmd == "zpick":
            ok, unit = self.bot.set_z_pick(val), "мм высота захвата"
        else:
            ok, unit = self.bot.set_grip_time(val), "c время захвата"
        if ok:
            print(f"  → {cmd}={val} ({unit}, применится в простое)")

    # =====================  ЧАСТОТНИК (ПЧ)  =========================
    def _cmd_vfd(self, parts: list[str]) -> None:
        st = self.bot.read_status()
        print(("  " + _fmt(st)) if st else "  <нет ответа — запущен ли cvt_universal?>")

    def _cmd_drive(self, parts: list[str]) -> None:
        """r / rev / f / s / reset — управление приводом, в конце печатает статус."""
        cmd = parts[0]
        arg = None
        if len(parts) > 1:
            try:
                arg = float(parts[1])
            except ValueError:
                print("  ! не число:", parts[1])
                return
        if cmd == "s":
            self.bot.vfd_stop()
        elif cmd == "reset":
            self.bot.vfd_reset_fault()
        elif cmd == "f":
            if arg is None:
                print("  ! нужна частота, напр.: f 40")
                return
            self.bot.vfd_set_freq(arg)
            self.last_freq = arg
        elif cmd == "r":
            self.last_freq = arg if arg is not None else self.last_freq
            self.bot.vfd_run(self.last_freq, reverse=False)
        elif cmd == "rev":
            self.last_freq = arg if arg is not None else self.last_freq
            self.bot.vfd_run(self.last_freq, reverse=True)
        st = self.bot.read_status()
        if st:
            print("  " + _fmt(st))

    # =====================  ПАРАМЕТРЫ РОБОТА  ======================
    def _cmd_spd(self, parts: list[str]) -> None:
        if len(parts) != 2 or not parts[1].isdigit():
            print("  ! нужно: spd <%>  (1..100)")
            return
        if self.bot.set_speed(int(parts[1])):
            print(f"  → скорость {parts[1]}% (применится когда робот свободен)")

    def _cmd_home(self, parts: list[str]) -> None:
        if len(parts) != 4:
            print("  ! нужно: home <x> <y> <z>  (мм)")
            return
        coords = self._floats(parts, 3)
        if coords is None:
            return
        hx, hy, hz = coords
        if self.bot.set_home(hx, hy, hz):
            print(f"  → домашняя позиция X={hx} Y={hy} Z={hz} (применится в простое)")

    # =====================  FALLBACK: детекция «x y»  ==============
    def _detect(self, parts: list[str]) -> None:
        """Нераспознанная команда из ровно 2 числовых токенов → задание в очередь."""
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            print("  ! не числа:", " ".join(parts), "\n" + _HELP)
            return
        enc = self.bot.read_encoder()  # E_capture в момент «кадра»
        if enc is None:
            print("  ! не прочитал энкодер — робот отвечает? cvt_universal запущен?")
            return
        with self.qlock:
            self.queue.append((x, y, enc))
        print(f"  + детекция в очередь: X={x} Y={y} E_cap={enc}  (в очереди {len(self.queue)})")

    # =====================  REPL  ==================================
    def run(self) -> None:
        """Главный цикл: запустить feeder, печатать справку, обрабатывать ввод.
        В finally — остановить feeder и закрыть клиент."""
        self._th.start()
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

                # выход
                if cmd == "q":
                    self._safe_stop()
                    break

                # сперва таблица команд, затем fallback-детекция, затем unknown
                handler = self._dispatch.get(cmd)
                if handler is not None:
                    handler(parts)
                elif len(parts) == 2:
                    self._detect(parts)
                else:
                    print("  ? неизвестная команда.\n" + _HELP)
        except KeyboardInterrupt:
            self._safe_stop()
        finally:
            self.stop.set()
            self._th.join(timeout=1.0)
            self._client.close()

    def _safe_stop(self) -> None:
        """Стоп привода с подтверждением: ждём running==False до 0.5 с, потом выходим."""
        self.bot.vfd_stop()
        if not self._wait(lambda: (st := self.bot.read_status()) is not None and not st.running, 0.5):
            print("  ! привод не подтвердил стоп за 0.5 с — проверь ПЧ вручную")


def console() -> None:
    """Точка входа: подключиться к роботу и запустить интерактивную консоль."""
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")
    _enable_nodelay(client)
    Console(client).run()


if __name__ == "__main__":
    console()
