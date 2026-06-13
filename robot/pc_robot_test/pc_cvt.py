"""
ПК-клиент CVT (шаг 4) — очередь на ПК + энкодер-стамп + handshake с роботом.

Топология: ПК = Modbus TCP master, робот = server (cvt_step4.lua).

Протокол (см. cvt_step4.lua):
    «Детекция» (кадр) → ПК читает REG_ENC (живой энкодер робота) = E_capture
                      → кладёт {X, Y, E_capture} в очередь ПК.
    Подача: когда REG_FREE==1 (робот свободен) и очередь не пуста →
            write REG_X, REG_Y, REG_ECAP → write REG_FLAG=1 (ПОСЛЕДНИМ).
            Робот забирает, считает сдвиг ленты по энкодеру, едет.

Очередь и подача — в ФОНОВОМ потоке; консоль (главный поток) принимает
«детекции». Доступ к Modbus сериализован Lock (pymodbus не потокобезопасен).

⚠️ DW (энкодер) — порядок слов ПК↔робот должен совпасть. Если `enc` читается
   мусором — поменяй WORD_ORDER (команда `cal` показывает оба варианта).

Зависимости: pip install pymodbus>=3.5
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque

from pymodbus.client import ModbusTcpClient

# =====================  КОНФИГУРАЦИЯ  ================================
ROBOT_IP = "192.168.1.7"
ROBOT_PORT = 502
ROBOT_UNIT = 2

# Карта регистров — ДОЛЖНА совпадать с cvt_step4.lua
REG_FLAG = 0x1100  # W : 1 = задание готово (ПК), 0 = принято (робот)
REG_X = 0x1101  # W : X 0.1 мм
REG_Y = 0x1102  # W : Y 0.1 мм
REG_ECAP = 0x1104  # DW: E_capture (энкодер на момент кадра)
REG_FREE = 0x1110  # W : 1 = робот свободен, 0 = занят
REG_ENC = 0x1112  # DW: живой энкодер (робот зеркалит)
# Эхо принятых/вычисленных координат (робот пишет в Motion, ПК читает):
REG_ECHO_X = 0x1120  # W : принятый job_x (0.1 мм)
REG_ECHO_Y = 0x1121  # W : принятый job_y
REG_PX = 0x1122  # W : вычисленный px = job_x + trav (0.1 мм)
REG_PY = 0x1123  # W : вычисленный py
REG_TRAV = 0x1124  # W : сдвиг ленты trav (0.1 мм)
ECHO_BASE = 0x1120  # начало блока эха (5 регистров подряд)
ECHO_COUNT = 5

XY_SCALE = 10  # мм → регистр (0.1 мм)
XY_LIMIT_MM = 3276.7  # предел signed-16-bit при этом масштабе

# Порядок 16-битных слов в DW. Если PC и робот трактуют DW по-разному —
# энкодер читается мусором. Проверка: команда `cal`. Поменяй при необходимости.
WORD_ORDER = "little"  # ПОДТВЕРЖДЕНО: [lo, hi] (младшее слово первым). big давал мусор

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
class RobotCVT:
    """Доступ к регистрам cvt_step4.lua. Все обращения под Lock (потокобезопасно)."""

    def __init__(self, client: ModbusTcpClient) -> None:
        self._cli = client
        self._lock = threading.Lock()

    def read_encoder(self) -> int | None:
        """Живой энкодер робота (E_capture в момент кадра)."""
        with self._lock:
            rr = self._cli.read_holding_registers(REG_ENC, count=2, device_id=ROBOT_UNIT)
        return None if rr.isError() else _regs_to_dw(rr.registers)

    def read_enc_raw(self) -> list[int] | None:
        """Сырые 2 регистра энкодера — для калибровки порядка слов."""
        with self._lock:
            rr = self._cli.read_holding_registers(REG_ENC, count=2, device_id=ROBOT_UNIT)
        return None if rr.isError() else list(rr.registers)

    def is_free(self) -> bool | None:
        with self._lock:
            rr = self._cli.read_holding_registers(REG_FREE, count=1, device_id=ROBOT_UNIT)
        return None if rr.isError() else (rr.registers[0] == 1)

    def read_echo(self) -> dict | None:
        """Эхо от робота: принятые job_x/job_y и вычисленные px/py/trav (всё в мм)."""
        with self._lock:
            rr = self._cli.read_holding_registers(ECHO_BASE, count=ECHO_COUNT, device_id=ROBOT_UNIT)
        if rr.isError():
            return None
        r = [_s16(v) / XY_SCALE for v in rr.registers]
        return {"job_x": r[0], "job_y": r[1], "px": r[2], "py": r[3], "trav": r[4]}

    def send_job(self, x_mm: float, y_mm: float, e_capture: int) -> bool:
        """Записать задание и поднять флаг. ПОРЯДОК: координаты+энкодер → флаг последним."""
        if abs(x_mm) > XY_LIMIT_MM or abs(y_mm) > XY_LIMIT_MM:
            print(f"  ! координата вне ±{XY_LIMIT_MM} мм")
            return False
        with self._lock:
            ok = not self._cli.write_register(REG_X, _to_u16(round(x_mm * XY_SCALE)), device_id=ROBOT_UNIT).isError()
            ok = (
                not self._cli.write_register(REG_Y, _to_u16(round(y_mm * XY_SCALE)), device_id=ROBOT_UNIT).isError()
            ) and ok
            ok = (
                not self._cli.write_registers(REG_ECAP, _dw_to_regs(e_capture), device_id=ROBOT_UNIT).isError()
            ) and ok
            ok = (not self._cli.write_register(REG_FLAG, 1, device_id=ROBOT_UNIT).isError()) and ok  # последним!
        return ok


# =====================  ОЧЕРЕДЬ + ФОНОВАЯ ПОДАЧА  =================
queue: deque = deque()  # {x, y, enc} — задания с ПК
qlock = threading.Lock()
stop = threading.Event()


def feeder(bot: RobotCVT) -> None:
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
                    # обратная связь: что робот принял и что вычислил
                    e = bot.read_echo()
                    if e:
                        print(
                            f"     ← робот: принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                            f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
                        )
        time.sleep(FEED_POLL_S)


# =====================  КОНСОЛЬ  ==================================
_HELP = """Команды:
  <x> <y>   ДЕТЕКЦИЯ: стампит текущий энкодер как E_capture и кладёт в очередь
  enc       показать энкодер / флаг свободы / длину очереди
  last      что робот ПРИНЯЛ (job_x/y) и ВЫЧИСЛИЛ (trav, px/py)
  cal       калибровка порядка слов DW (сравни с энкодером на роботе)
  q         выход"""


def console() -> None:
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")
    _enable_nodelay(client)

    bot = RobotCVT(client)
    th = threading.Thread(target=feeder, args=(bot,), daemon=True)
    th.start()
    print(_HELP)
    try:
        while True:
            try:
                line = input("cvt> ").strip().lower()
            except EOFError:
                break
            if not line:
                continue
            if line == "q":
                break

            if line == "enc":
                e = bot.read_encoder()
                f = bot.is_free()
                print(f"  enc={e}  free={f}  queue={len(queue)}")
                continue

            if line == "last":
                e = bot.read_echo()
                if e is None:
                    print("  ! нет ответа от робота")
                else:
                    print(
                        f"  принял X={e['job_x']:.1f} Y={e['job_y']:.1f} | "
                        f"trav={e['trav']:.1f} → цель px={e['px']:.1f} py={e['py']:.1f}"
                    )
                continue

            if line == "cal":
                raw = bot.read_enc_raw()
                if raw is None:
                    print("  ! нет ответа от робота")
                    continue
                big = struct.unpack(">i", struct.pack(">HH", raw[0], raw[1]))[0]
                lit = struct.unpack(">i", struct.pack(">HH", raw[1], raw[0]))[0]
                print(f"  сырые регистры: {raw}")
                print(f"    WORD_ORDER='big'    → {big}")
                print(f"    WORD_ORDER='little' → {lit}")
                print(
                    f"  Сейчас стоит '{WORD_ORDER}'. Выбери тот, что совпадает с "
                    f"энкодером на роботе (его значение видно в DRAStudio/print)."
                )
                continue

            # «детекция»: x y → стампим энкодер и в очередь
            parts = line.split()
            if len(parts) != 2:
                print("  ! нужно: <x> <y>  (или enc / cal / q)\n" + _HELP)
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                print("  ! не числа:", line)
                continue

            enc = bot.read_encoder()  # E_capture в момент «кадра»
            if enc is None:
                print("  ! не прочитал энкодер — робот отвечает? cvt_step4 запущен?")
                continue
            with qlock:
                queue.append((x, y, enc))
            print(f"  + детекция в очередь: X={x} Y={y} E_cap={enc}  (в очереди {len(queue)})")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        th.join(timeout=1.0)
        client.close()


if __name__ == "__main__":
    console()
