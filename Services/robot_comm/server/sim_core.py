"""Чистая логика фейк-робота — общее ядро FakeRobotTransport и TCP sim_robot.

Эмулирует поведение ``cvt_universal_full.lua`` НАД массивом регистров: как и
настоящий Lua Motion-цикл, ``tick()`` поллит флаги mailbox и реагирует:

- job_flag=1  -> принять задание (flag->0, free->0, echo), через job_ticks free->1;
- cfg_flag=1  -> применить конфиг (flag->0);
- vfd_flag=1  -> обновить зеркало ПЧ 0x1210+ (hb++), flag->0 — ВКЛЮЧАЯ
  заморозку зеркала без команд (как в реальном Lua, ревью п.1);
- draw_flag=1 -> busy=1, prog++ по тикам, через draw_ticks busy->0;
- stop/servo  -> мгновенная реакция;
- каждый tick: энкодер += enc_rate; heartbeat телеметрии растёт только при
  free=1 (как в реальном Lua — во время job телеметрия «стоит»).

Никакого pymodbus и сети — только list[int]. Хранилище можно подменить
(``attach``) на живой список TCP-сервера.
"""

from __future__ import annotations

from Services.robot_comm.core.registers import (
    REG_CFG_FLAG,
    REG_DRAW_ABORT,
    REG_DRAW_BUSY,
    REG_DRAW_FLAG,
    REG_DRAW_PROG,
    REG_ENC,
    REG_FREE,
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    REG_PLACE_FLAG,
    REG_PLACE_X,
    REG_PLACE_Y,
    REG_PLACE_Z,
    REG_RET_BUSY,
    REG_RET_FLAG,
    REG_RET_X,
    REG_RET_Y,
    REG_RET_Z,
    REG_SERVO,
    REG_SPACE_SIZE,
    REG_STOP,
    REG_TLM_BASE,
    SERVO_ON,
)

# Mailbox ПЧ — сторона РОБОТА (Lua-мост). Клиентская карта живёт в vfd_comm;
# здесь адреса продублированы осознанно: sim эмулирует Lua-скрипт, а не клиента.
_REG_VFD_CMD_RUN = 0x1200
_REG_VFD_CMD_DIR = 0x1201
_REG_VFD_CMD_FREQ = 0x1202
_REG_VFD_CMD_RESET = 0x1203
_REG_VFD_FLAG = 0x1204
_REG_VFD_ST_BASE = 0x1210  # RUN, OUT_FREQ, CURRENT, DCBUS, FAULT, STATUSW, HB, COMM_ERR

# Индексы телеметрии (блок 0x1130)
_TLM_X, _TLM_Y, _TLM_Z, _TLM_RZ, _TLM_MOVING, _TLM_SPD = 0, 1, 2, 3, 4, 5
_TLM_HB, _TLM_SERVO = 8, 9

# Правдоподобные показания «ПЧ» для зеркала
_SIM_CURRENT_RAW = 150  # 15.0 А (scale 10)
_SIM_DCBUS_RAW = 5400  # 540.0 В (scale 10)


class RobotSimCore:
    """Конечный автомат фейк-робота над массивом регистров.

    Args:
        word_order:   Порядок слов DW (должен совпадать с клиентом).
        accept_ticks: Тиков до принятия задания (flag->0).
        job_ticks:    Тиков исполнения задания (после принятия, до free->1).
        draw_ticks:   Тиков прохода рисования (busy 1->0).
        enc_rate:     Прирост энкодера за тик.
    """

    def __init__(
        self,
        *,
        word_order: str = "little",
        accept_ticks: int = 1,
        job_ticks: int = 2,
        draw_ticks: int = 3,
        return_ticks: int = 2,
        enc_rate: int = 7,
    ) -> None:
        self._word_order = word_order
        self._accept_ticks = accept_ticks
        self._job_ticks = job_ticks
        self._draw_ticks = draw_ticks
        self._return_ticks = return_ticks
        self._enc_rate = enc_rate

        self.regs: list[int] = [0] * REG_SPACE_SIZE
        self._encoder = 0
        self._accept_countdown: int | None = None
        self._job_countdown: int | None = None
        self._draw_countdown: int | None = None
        self._ret_countdown: int | None = None
        self.regs[REG_FREE] = 1
        self.regs[REG_TLM_BASE + _TLM_SPD] = 50
        self.regs[REG_TLM_BASE + _TLM_SERVO] = 1
        self._write_encoder()

    # ------------------------------------------------------------------ #
    # Хранилище
    # ------------------------------------------------------------------ #

    def attach(self, regs: list[int]) -> None:
        """Подменить хранилище на внешний живой список (TCP-сервер).

        Текущее состояние копируется в новый список, дальше core мутирует его.
        """
        regs[: len(self.regs)] = self.regs
        self.regs = regs

    def read(self, address: int, count: int = 1) -> list[int]:
        """Прочитать блок регистров."""
        return list(self.regs[address : address + count])

    def write(self, address: int, values: list[int]) -> None:
        """Записать блок регистров (чистое хранение — реакция в tick())."""
        for i, v in enumerate(values):
            self.regs[address + i] = int(v) & 0xFFFF

    # ------------------------------------------------------------------ #
    # «Motion-цикл» — один тик
    # ------------------------------------------------------------------ #

    def tick(self) -> None:
        """Одна итерация цикла робота: энкодер, поллинг флагов, таймеры."""
        self._encoder += self._enc_rate
        self._write_encoder()
        if self.regs[REG_FREE] == 1:
            # heartbeat телеметрии живёт ТОЛЬКО в idle (как в Lua)
            self.regs[REG_TLM_BASE + _TLM_HB] = (self.regs[REG_TLM_BASE + _TLM_HB] + 1) % 32767

        self._handle_stop_servo()
        self._handle_job()
        self._handle_config()
        self._handle_vfd()
        self._handle_draw()
        self._handle_return()

    # --- обработчики (порядок как в Lua Motion) ---

    def _handle_stop_servo(self) -> None:
        if self.regs[REG_STOP] != 0:
            self.regs[REG_STOP] = 0
            self.regs[REG_JOB_FLAG] = 0
            self.regs[REG_FREE] = 1
            self._accept_countdown = self._job_countdown = None
        servo_cmd = self.regs[REG_SERVO]
        if servo_cmd != 0:
            self.regs[REG_SERVO] = 0
            self.regs[REG_TLM_BASE + _TLM_SERVO] = 1 if servo_cmd == SERVO_ON else 0

    def _handle_job(self) -> None:
        if self.regs[REG_JOB_FLAG] == 1 and self._accept_countdown is None and self._job_countdown is None:
            # новое задание: занят, эхо
            self.regs[REG_FREE] = 0
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            self._set_echo()
            self._accept_countdown = self._accept_ticks
        if self._accept_countdown is not None:
            self._accept_countdown -= 1
            if self._accept_countdown <= 0:
                self.regs[REG_JOB_FLAG] = 0  # принял
                self._accept_countdown = None
                self._job_countdown = self._job_ticks
        elif self._job_countdown is not None:
            self._job_countdown -= 1
            if self._job_countdown <= 0:
                # задание выполнено: позиция = место УКЛАДКИ (place_flag=1) либо координаты
                # задания (старое поведение). R на роботе возвращается к base — телеметрию RZ
                # не двигаем. place_flag сбрасываем (как Lua после чтения).
                if self.regs[REG_PLACE_FLAG] == 1:
                    self.regs[REG_TLM_BASE + _TLM_X] = self.regs[REG_PLACE_X]
                    self.regs[REG_TLM_BASE + _TLM_Y] = self.regs[REG_PLACE_Y]
                    self.regs[REG_TLM_BASE + _TLM_Z] = self.regs[REG_PLACE_Z]
                    self.regs[REG_PLACE_FLAG] = 0
                else:
                    self.regs[REG_TLM_BASE + _TLM_X] = self.regs[REG_JOB_X]
                    self.regs[REG_TLM_BASE + _TLM_Y] = self.regs[REG_JOB_Y]
                self.regs[REG_TLM_BASE + _TLM_MOVING] = 0
                self.regs[REG_FREE] = 1
                self._job_countdown = None

    def _handle_config(self) -> None:
        if self.regs[REG_CFG_FLAG] == 1:
            self.regs[REG_CFG_FLAG] = 0  # блок уже в регистрах — «применили»

    def _handle_vfd(self) -> None:
        """Мост ПЧ: зеркало обновляется ТОЛЬКО по команде (как в реальном Lua).

        Это сознательно воспроизводит ограничение из ревью п.1: без пульса
        VFD_FLAG зеркало (включая heartbeat) заморожено.
        """
        if self.regs[_REG_VFD_FLAG] != 1:
            return
        run = self.regs[_REG_VFD_CMD_RUN] == 1
        reverse = self.regs[_REG_VFD_CMD_DIR] == 1
        freq = self.regs[_REG_VFD_CMD_FREQ]
        if self.regs[_REG_VFD_CMD_RESET] == 1:
            self.regs[_REG_VFD_CMD_RESET] = 0
        st = _REG_VFD_ST_BASE
        self.regs[st + 0] = 1 if run else 0
        self.regs[st + 1] = freq if run else 0
        self.regs[st + 2] = _SIM_CURRENT_RAW if run else 0
        self.regs[st + 3] = _SIM_DCBUS_RAW
        self.regs[st + 4] = 0  # fault
        self.regs[st + 5] = (2 if reverse else 1) if run else 3
        self.regs[st + 6] = (self.regs[st + 6] + 1) % 32767  # heartbeat моста
        self.regs[_REG_VFD_FLAG] = 0

    def _handle_draw(self) -> None:
        if self.regs[REG_DRAW_ABORT] == 1:
            self.regs[REG_DRAW_ABORT] = 0
            self.regs[REG_DRAW_BUSY] = 0
            self.regs[REG_DRAW_FLAG] = 0
            self._draw_countdown = None
            return
        if self.regs[REG_DRAW_FLAG] == 1 and self._draw_countdown is None:
            self.regs[REG_DRAW_FLAG] = 0
            self.regs[REG_DRAW_BUSY] = 1
            self.regs[REG_DRAW_PROG] = 0
            self._draw_countdown = self._draw_ticks
        elif self._draw_countdown is not None:
            self.regs[REG_DRAW_PROG] += 1
            self._draw_countdown -= 1
            if self._draw_countdown <= 0:
                self.regs[REG_DRAW_BUSY] = 0
                self._draw_countdown = None

    def _handle_return(self) -> None:
        """RETURN (mode=3): ret_flag 1→0 (приём) → ret_busy 1 (старт) → ret_busy 0 (готово).

        Handshake идентичен рисованию. По завершении позиция = координата слота (забор) —
        для проверок в тестах (реальный Lua после забора ещё едет на ленту и домой).
        """
        if self.regs[REG_RET_FLAG] == 1 and self._ret_countdown is None:
            self.regs[REG_RET_FLAG] = 0  # принял
            self.regs[REG_RET_BUSY] = 1  # старт
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            self._ret_countdown = self._return_ticks
        elif self._ret_countdown is not None:
            self._ret_countdown -= 1
            if self._ret_countdown <= 0:
                self.regs[REG_TLM_BASE + _TLM_X] = self.regs[REG_RET_X]
                self.regs[REG_TLM_BASE + _TLM_Y] = self.regs[REG_RET_Y]
                self.regs[REG_TLM_BASE + _TLM_Z] = self.regs[REG_RET_Z]
                self.regs[REG_TLM_BASE + _TLM_MOVING] = 0
                self.regs[REG_RET_BUSY] = 0  # готово
                self._ret_countdown = None

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    def _set_echo(self) -> None:
        """Эхо-блок: job_x, job_y, px, py, trav (sim: цель = задание, trav=0)."""
        x, y = self.regs[REG_JOB_X], self.regs[REG_JOB_Y]
        self.write(0x1120, [x, y, x, y, 0])

    def _write_encoder(self) -> None:
        value = self._encoder & 0xFFFFFFFF
        hi, lo = (value >> 16) & 0xFFFF, value & 0xFFFF
        pair = [hi, lo] if self._word_order == "big" else [lo, hi]
        self.regs[REG_ENC] = pair[0]
        self.regs[REG_ENC + 1] = pair[1]

    @property
    def encoder(self) -> int:
        """Текущее значение энкодера (для assert'ов в тестах)."""
        return self._encoder

    @property
    def job_ecap(self) -> list[int]:
        """Сырые слова E_capture последнего задания (проверка word order)."""
        return self.read(REG_JOB_ECAP, 2)
