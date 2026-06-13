"""
ПК-клиент управления частотным преобразователем INVT Goodrive20 (GD20)
ЧЕРЕЗ робота Delta SCARA.

Канал — ТОЛЬКО Modbus TCP (без Socket / свободного протокола §12.4 мануала).
Топология (см. robot_vfd_bridge.lua):

    ПК (этот скрипт) = Modbus TCP MASTER
    Робот           = встроенный Modbus-сервер (slave, порт 502)
    Робот ⇄ GD20    = RS-485 Modbus RTU (это делает Lua-скрипт на роботе)

ПК НЕ говорит с приводом напрямую. ПК пишет уставки (пуск/стоп, частоту,
сброс ошибки) в ВНУТРЕННИЕ Modbus-регистры робота и читает оттуда же
зеркало статуса привода. По мануалу робота (Robot Language §12.1) внутренние
регистры робота: 0x1000–0x1FFF (не сохраняются при выключении). Робот читает
их через ReadModbus, мы — как обычные holding-регистры по Modbus TCP.

Все значения — одиночные 16-битные регистры («W» в терминах мануала, §12.1),
поэтому упаковка DW / порядок слов здесь НЕ нужны.

Зависимости:  pip install pymodbus>=3.6
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient

# =====================  КОНФИГУРАЦИЯ  ================================
ROBOT_IP = "192.168.1.7"  # IP робота (его встроенный Modbus-сервер) — сверьте на вкладке Ethernet IP
ROBOT_PORT = 502
ROBOT_UNIT = 2  # station/unit id Modbus-TCP-slave робота (подтверждён тестом)

# ---- Карта внутренних регистров робота — ДОЛЖНА совпадать с robot_vfd_bridge.lua ----
# ПК ПИШЕТ команды (робот читает ReadModbus и шлёт в VFD по RS-485):
REG_CMD_RUN = 0x1200  # 0 = стоп, 1 = пуск
REG_CMD_DIR = 0x1201  # 0 = вперёд (FWD), 1 = назад (REV)
REG_CMD_FREQ = 0x1202  # уставка частоты ×100 (0.01 Гц). Лимит «W»: ≤ 327.67 Гц
REG_CMD_RESET = 0x1203  # 1 = сброс ошибки (робот выполнит импульс и обнулит)

# ПК ЧИТАЕТ статус (робот зеркалит сюда ответ VFD):
REG_ST_BASE = 0x1210  # начало блока статуса (8 слов подряд)
ST_COUNT = 8
# смещения внутри блока:
ST_RUN = 0  # 0x1210  1 = привод вращается
ST_OUT_FREQ = 1  # 0x1211  выходная частота ×100 (из GD20 0x3001)
ST_CURRENT = 2  # 0x1212  ток ×10 (из GD20 0x3004; сверьте масштаб модели)
ST_DCBUS = 3  # 0x1213  напряжение шины DC, В (из GD20 0x3002)
ST_FAULT = 4  # 0x1214  код ошибки VFD (0 = нет)
ST_STATUSW = 5  # 0x1215  состояние VFD (GD20 0x2100: 1=вперёд 2=назад 3=стоп 4=авария)
ST_HEARTBEAT = 6  # 0x1216  инкремент каждый успешный опрос (контроль «живости»)
ST_COMM_ERR = 7  # 0x1217  накопительный счётчик ошибок RS-485 робот↔VFD

# Масштабы (целые в регистрах ↔ инженерные единицы), под INVT GD20
FREQ_SCALE = 100  # 0.01 Гц  → 6000 = 60.00 Гц
CURRENT_SCALE = 10  # 0.1 А (диапазон GD20 0.0…3000.0 А)
DCBUS_SCALE = 1  # 1 В (диапазон GD20 0…2000 В)


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


# =====================  КЛИЕНТ  =====================================
class VFDOverRobot:
    """Управление VFD по Modbus TCP через регистры робота-моста."""

    def __init__(self, client: ModbusTcpClient) -> None:
        self._cli = client

    # ---- запись уставок (PC → робот → VFD) ----
    def _w(self, address: int, value: int) -> bool:
        rr = self._cli.write_register(address, int(value), device_id=ROBOT_UNIT)
        return not rr.isError()

    def run(self, freq_hz: float, reverse: bool = False) -> bool:
        """Задать частоту и пустить привод (FWD по умолчанию)."""
        ok = self._w(REG_CMD_FREQ, round(freq_hz * FREQ_SCALE))
        ok = self._w(REG_CMD_DIR, 1 if reverse else 0) and ok
        ok = self._w(REG_CMD_RUN, 1) and ok
        return ok

    def set_freq(self, freq_hz: float) -> bool:
        """Изменить частоту «на ходу»."""
        return self._w(REG_CMD_FREQ, round(freq_hz * FREQ_SCALE))

    def stop(self) -> bool:
        return self._w(REG_CMD_RUN, 0)

    def reset_fault(self) -> bool:
        """Запросить сброс ошибки. Робот выполнит импульс и обнулит регистр."""
        return self._w(REG_CMD_RESET, 1)

    # ---- чтение статуса (VFD → робот → PC) ----
    def read_status(self) -> VFDStatus | None:
        rr = self._cli.read_holding_registers(REG_ST_BASE, count=ST_COUNT, device_id=ROBOT_UNIT)
        if rr.isError():
            return None
        r = rr.registers
        return VFDStatus(
            running=r[ST_RUN] == 1,
            out_freq_hz=r[ST_OUT_FREQ] / FREQ_SCALE,
            current_a=r[ST_CURRENT] / CURRENT_SCALE,
            dcbus_v=r[ST_DCBUS] / DCBUS_SCALE,
            fault=r[ST_FAULT],
            status_word=r[ST_STATUSW],
            heartbeat=r[ST_HEARTBEAT],
            comm_errors=r[ST_COMM_ERR],
        )


# =====================  ДЕМО / ТОЧКА ВХОДА  =========================
def _fmt(st: VFDStatus) -> str:
    flag = "RUN " if st.running else "STOP"
    flt = f" FAULT=0x{st.fault:04X}" if st.fault else ""
    return (
        f"[{flag}] f={st.out_freq_hz:6.2f}Hz  I={st.current_a:5.1f}A  "
        f"Udc={st.dcbus_v:6.1f}V  hb={st.heartbeat}  rsErr={st.comm_errors}{flt}"
    )


def main() -> None:
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")

    vfd = VFDOverRobot(client)
    try:
        # Контроль живости моста: heartbeat должен расти, иначе Lua-скрипт не запущен.
        st0 = vfd.read_status()
        if st0 is None:
            raise SystemExit("Робот не отвечает на чтение регистров — проверьте Modbus-сервер")
        print("Старт. " + _fmt(st0))

        # --- демонстрационная последовательность ---
        print("Пуск 25.00 Гц вперёд…")
        vfd.run(25.0)
        for _ in range(20):  # ~2 c мониторинга разгона
            st = vfd.read_status()
            if st:
                print("  " + _fmt(st))
            time.sleep(0.1)

        print("Изменение частоты → 45.00 Гц…")
        vfd.set_freq(45.0)
        for _ in range(20):
            st = vfd.read_status()
            if st:
                print("  " + _fmt(st))
            time.sleep(0.1)

        print("Стоп.")
        vfd.stop()
        time.sleep(0.5)
        st = vfd.read_status()
        if st:
            print("Финал. " + _fmt(st))

    except KeyboardInterrupt:
        vfd.stop()
    finally:
        client.close()


# =====================  ИНТЕРАКТИВНАЯ КОНСОЛЬ  =====================
_HELP = """Команды:
  r [Гц]    пуск ВПЕРЁД (без аргумента — последняя частота)
  rev [Гц]  пуск НАЗАД
  f <Гц>    задать частоту на ходу
  s         стоп
  reset     сброс аварии
  ?         показать статус (или просто Enter)
  q         выход (со стопом)"""


def console() -> None:
    """Управление с клавиатуры + показ частоты/состояния/аварии перед каждым вводом."""
    client = ModbusTcpClient(ROBOT_IP, port=ROBOT_PORT)
    if not client.connect():
        raise SystemExit(f"Нет связи с роботом {ROBOT_IP}:{ROBOT_PORT}")

    vfd = VFDOverRobot(client)
    last_freq = 25.0  # частота по умолчанию для «r» без аргумента
    print(_HELP)
    try:
        while True:
            # 1) показать текущее состояние (частота / RUN-STOP / авария)
            st = vfd.read_status()
            print(("  " + _fmt(st)) if st else "  <нет ответа от робота — запущен ли Lua-мост?>")

            # 2) принять команду
            try:
                line = input("vfd> ").strip().lower()
            except EOFError:
                break
            if not line or line == "?":
                continue

            parts = line.split()
            cmd = parts[0]
            arg = None
            if len(parts) > 1:
                try:
                    arg = float(parts[1])
                except ValueError:
                    print("  ! не число:", parts[1])
                    continue

            # 3) выполнить
            if cmd == "q":
                vfd.stop()
                break
            elif cmd == "s":
                vfd.stop()
            elif cmd == "reset":
                vfd.reset_fault()
            elif cmd == "f":
                if arg is None:
                    print("  ! нужна частота, напр.: f 40")
                    continue
                vfd.set_freq(arg)
                last_freq = arg
            elif cmd == "r":
                last_freq = arg if arg is not None else last_freq
                vfd.run(last_freq, reverse=False)
            elif cmd == "rev":
                last_freq = arg if arg is not None else last_freq
                vfd.run(last_freq, reverse=True)
            else:
                print("  ? неизвестная команда.\n" + _HELP)
    except KeyboardInterrupt:
        vfd.stop()
    finally:
        client.close()


if __name__ == "__main__":
    # По умолчанию — интерактивная консоль. Демо-последовательность: main().
    console()
