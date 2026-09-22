"""Чистая логика фейк-робота — общее ядро FakeRobotTransport и TCP sim_robot.

Эмулирует поведение ``cvt_universal_full.lua`` НАД массивом регистров: как и
настоящий Lua Motion-цикл, ``tick()`` поллит флаги mailbox и реагирует:

- job_flag=1  -> принять задание (flag->0, free->0, echo), через job_ticks free->1;
- cfg_flag=1  -> применить конфиг (flag->0);
- vfd_flag=1  -> обновить зеркало ПЧ 0x1210+ (hb++), flag->0 — ВКЛЮЧАЯ
  заморозку зеркала без команд (как в реальном Lua, ревью п.1);
- draw_flag=1 -> busy=1, prog++ по тикам, через draw_ticks busy->0;
- man_flag=1  -> man_busy=1, free=0, через manual_ticks man_busy->0, free->1,
  поза обновляется (как реальный MovL в Lua);
- stop/servo  -> мгновенная реакция;
- каждый tick: энкодер += enc_rate; heartbeat телеметрии растёт только при
  free=1 (как в реальном Lua — во время job телеметрия «стоит»).

Опциональный ``on_event`` callback получает строки-события, зеркалящие print()
прошивки. Для CLI (run_sim_robot) передаётся print — консоль показывает
«мысли» робота. Для тестов/библиотеки — None (молча).
"""

from __future__ import annotations

from typing import Callable

from Services.robot_comm.core.registers import (
    REG_CFG_BASE,
    REG_CFG_FLAG,
    REG_DRAW_ABORT,
    REG_DRAW_BUSY,
    REG_DRAW_COUNT,
    REG_DRAW_DONE_N,
    REG_DRAW_FLAG,
    REG_DRAW_HOME,
    REG_DRAW_PROG,
    REG_ENC,
    REG_FREE,
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    REG_MAN_ABS,
    REG_MAN_BUSY,
    REG_MAN_DX,
    REG_MAN_DY,
    REG_MAN_FLAG,
    REG_MAN_SPD,
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
    REG_TOOL_BUSY,
    REG_TOOL_CUR,
    REG_TOOL_FLAG,
    REG_TOOL_TARGET,
    SERVO_ON,
    XY_SCALE,
)
from Services.robot_comm.server.belt import BeltDrive

# Период Motion-цикла — единственный источник истины (ревью Task 2.1, п.3:
# раньше дублировался в sim_robot.py; sim_robot.py уже импортирует
# RobotSimCore из этого модуля на уровне модуля, поэтому обратного импорта
# `sim_robot.TICK_INTERVAL_S -> sim_core` здесь нет и не может возникнуть цикл).
TICK_INTERVAL_S = 0.01

# Масштаб регистра частоты ПЧ (см. Services/vfd_comm/protocols/gd20_bridge.yaml
# cmd_freq.scale) — 0.01 Гц на LSB, т.е. RAW*100.
_VFD_FREQ_SCALE = 100.0

# Mailbox ПЧ — сторона РОБОТА (Lua-мост). Клиентская карта живёт в vfd_comm;
# здесь адреса продублированы осознанно: sim эмулирует Lua-скрипт, а не клиента.
_REG_VFD_CMD_RUN = 0x1200
_REG_VFD_CMD_DIR = 0x1201
_REG_VFD_CMD_FREQ = 0x1202
_REG_VFD_CMD_RESET = 0x1203
_REG_VFD_FLAG = 0x1204
_REG_VFD_ST_BASE = 0x1210  # RUN, OUT_FREQ, CURRENT, DCBUS, FAULT, STATUSW, HB, COMM_ERR

#: Начало блока команды ПЧ в mailbox (RUN, DIR, FREQ — 3 регистра подряд,
#: тот же порядок, что читает watchdog jog в ``SimRobotHostPlugin``, Task
#: 2.3a). Публичный алиас ``_REG_VFD_CMD_RUN`` — потребители вне этого
#: модуля (плагин) не должны дублировать адрес 0x1200 у себя.
VFD_CMD_ADDR = _REG_VFD_CMD_RUN

# Индексы телеметрии (блок 0x1130)
_TLM_X, _TLM_Y, _TLM_Z, _TLM_RZ, _TLM_MOVING, _TLM_SPD = 0, 1, 2, 3, 4, 5
_TLM_HB, _TLM_SERVO = 8, 9

# Правдоподобные показания «ПЧ» для зеркала
_SIM_CURRENT_RAW = 150  # 15.0 А (scale 10)
_SIM_DCBUS_RAW = 5400  # 540.0 В (scale 10)


def _s16(v: int) -> float:
    """Конвертировать unsigned 16-bit значение в signed, делить на XY_SCALE."""
    if v > 32767:
        v -= 65536
    return v / XY_SCALE


class RobotSimCore:
    """Конечный автомат фейк-робота над массивом регистров.

    Args:
        word_order:   Порядок слов DW (должен совпадать с клиентом).
        accept_ticks: Тиков до принятия задания (flag->0).
        job_ticks:    Тиков исполнения задания (после принятия, до free->1).
        draw_ticks:   Тиков прохода рисования (busy 1->0).
        manual_ticks: Тиков ручного хода (man_busy 1->0).
        enc_rate:     Прирост энкодера за тик БЕЗ команды ПЧ (см. belt).
        belt:         Модель ленты (Task 2.1). None -> BeltDrive.from_enc_rate(enc_rate, ...) —
                      старое поведение воспроизводится побитово, пока не пришла команда ПЧ.
        on_event:     Callback для событий (print-зеркало прошивки). None = молча.
    """

    def __init__(
        self,
        *,
        word_order: str = "little",
        accept_ticks: int = 1,
        job_ticks: int = 2,
        draw_ticks: int = 3,
        return_ticks: int = 2,
        toolchange_ticks: int = 3,
        manual_ticks: int = 2,
        enc_rate: int = 7,
        belt: BeltDrive | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self._word_order = word_order
        self._accept_ticks = accept_ticks
        self._job_ticks = job_ticks
        self._draw_ticks = draw_ticks
        self._return_ticks = return_ticks
        self._toolchange_ticks = toolchange_ticks
        self._manual_ticks = manual_ticks
        self._on_event = on_event
        # Лента — отдельная модель (Task 2.1, line-sim Ф2): без явной инъекции
        # воспроизводит старое поведение enc_rate побитово (см. BeltDrive.from_enc_rate).
        self._belt = belt if belt is not None else BeltDrive.from_enc_rate(enc_rate, TICK_INTERVAL_S)

        self.regs: list[int] = [0] * REG_SPACE_SIZE
        self._encoder = 0
        self._accept_countdown: int | None = None
        self._job_countdown: int | None = None
        self._draw_countdown: int | None = None
        self._ret_countdown: int | None = None
        self._tool_countdown: int | None = None
        self._man_countdown: int | None = None
        # Запомненные координаты CVT-задания (для событий)
        self._job_x: float = 0.0
        self._job_y: float = 0.0
        self._job_ecap: int = 0
        self._job_has_place: bool = False
        self._job_place_x: float = 0.0
        self._job_place_y: float = 0.0
        self._job_place_rz: float = 0.0
        # Запомненные координаты MANUAL (для событий + позиция)
        self._man_tx: float = 0.0
        self._man_ty: float = 0.0
        self._man_spd: int = 0
        self._man_abs: int = 0
        self.regs[REG_FREE] = 1
        self.regs[REG_TLM_BASE + _TLM_SPD] = 50
        self.regs[REG_TLM_BASE + _TLM_SERVO] = 1
        self._write_encoder()

    # ------------------------------------------------------------------ #
    # События (зеркало print() прошивки)
    # ------------------------------------------------------------------ #

    def _emit(self, msg: str) -> None:
        """Эмитировать событие (вызвать on_event если задан)."""
        if self._on_event is not None:
            self._on_event(msg)

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

    def command_vfd(
        self,
        *,
        run: bool | None = None,
        freq_hz: float | None = None,
        reverse: bool | None = None,
    ) -> None:
        """Записать частичную команду ПЧ в mailbox — тем же путём (``self.write``),
        что и Modbus-запись инспектора (Task 2.3a, ``SimRobotHostPlugin``):
        оба мастера пишут один и тот же mailbox, побеждает последний
        записавший (см. ``belt.py`` DESIGN п.6, план line-sim Ф2 §Task 2.3a).

        Post: пишутся ТОЛЬКО переданные поля (партиальность — как у
        ``VfdClient``: ``stop()`` пишет только ``cmd_run``), затем VFD_FLAG —
        ОТДЕЛЬНЫМ, последним вызовом ``self.write``. Применяется на ближайшем
        ``tick()`` (:meth:`_handle_vfd`), не немедленно — тот же контракт,
        что у прямой Modbus-записи.
        """
        if run is not None:
            self.write(_REG_VFD_CMD_RUN, [1 if run else 0])
        if reverse is not None:
            self.write(_REG_VFD_CMD_DIR, [1 if reverse else 0])
        if freq_hz is not None:
            self.write(_REG_VFD_CMD_FREQ, [round(freq_hz * _VFD_FREQ_SCALE)])
        self.write(_REG_VFD_FLAG, [1])

    # ------------------------------------------------------------------ #
    # «Motion-цикл» — один тик
    # ------------------------------------------------------------------ #

    def tick(self, dt_s: float | None = None) -> None:
        """Одна итерация цикла робота: энкодер, поллинг флагов, таймеры.

        Args:
            dt_s: Реальный интервал с прошлого тика (Task 2.1b, line-sim Ф2:
                  измеряет вызывающая сторона — `SimRobotServer._ticker`).
                  ``None`` -> `TICK_INTERVAL_S` (старое поведение, все прямые
                  вызовы/тесты без аргумента не меняются). Влияет только на
                  ленту (`self._belt.advance`) — счётчики шагов остальных
                  обработчиков (job/draw/manual/…) по-прежнему считаются
                  тиками, не временем.
        """
        dt = dt_s if dt_s is not None else TICK_INTERVAL_S
        if self.regs[REG_FREE] == 1:
            # heartbeat телеметрии живёт ТОЛЬКО в idle (как в Lua) — читает
            # REG_FREE ДО обработчиков этого тика (как раньше).
            self.regs[REG_TLM_BASE + _TLM_HB] = (self.regs[REG_TLM_BASE + _TLM_HB] + 1) % 32767

        self._handle_stop_servo()
        self._handle_job()
        self._handle_config()
        self._handle_vfd()
        # Энкодер — ПОСЛЕ _handle_vfd: пульс VFD_FLAG применяет команду к belt
        # (_handle_vfd -> belt.command) и приращение ЭТОГО ЖЕ тика уже должно
        # идти по новой скорости — таково ограничение прошивки, «скорость
        # меняется только в момент пульса», а не с задержкой в один тик.
        self._encoder += self._belt.advance(dt)
        self._write_encoder()
        self._handle_draw()
        self._handle_return()
        self._handle_toolchange()
        self._handle_manual()

    # --- обработчики (порядок как в Lua Motion) ---

    def _handle_stop_servo(self) -> None:
        # --- STOP ---
        stop_mode = self.regs[REG_STOP]
        if stop_mode != 0:
            self.regs[REG_STOP] = 0
            self.regs[REG_JOB_FLAG] = 0
            self.regs[REG_FREE] = 1
            self._accept_countdown = self._job_countdown = None
            # Если MANUAL был в процессе — сбросить
            if self._man_countdown is not None:
                self.regs[REG_MAN_BUSY] = 0
                self._man_countdown = None
            self._emit(f"[STOP] mode {stop_mode} выполнен")
        # --- SERVO ---
        servo_cmd = self.regs[REG_SERVO]
        if servo_cmd != 0:
            self.regs[REG_SERVO] = 0
            on = servo_cmd == SERVO_ON
            self.regs[REG_TLM_BASE + _TLM_SERVO] = 1 if on else 0
            self._emit(f"[SERVO] {'ON' if on else 'OFF'}")

    def _handle_job(self) -> None:
        if self.regs[REG_JOB_FLAG] == 1 and self._accept_countdown is None and self._job_countdown is None:
            # новое задание: занят, эхо
            self.regs[REG_FREE] = 0
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            # Запомнить координаты для события
            self._job_x = _s16(self.regs[REG_JOB_X])
            self._job_y = _s16(self.regs[REG_JOB_Y])
            self._job_ecap = self.regs[REG_JOB_ECAP]
            self._job_has_place = self.regs[REG_PLACE_FLAG] == 1
            if self._job_has_place:
                self._job_place_x = _s16(self.regs[REG_PLACE_X])
                self._job_place_y = _s16(self.regs[REG_PLACE_Y])
                self._job_place_z = _s16(self.regs[REG_PLACE_Z])
                self._job_place_rz = _s16(self.regs[0x1143])  # PLACE_RZ
            self._set_echo()
            self._accept_countdown = self._accept_ticks
        if self._accept_countdown is not None:
            self._accept_countdown -= 1
            if self._accept_countdown <= 0:
                self.regs[REG_JOB_FLAG] = 0  # принял
                self._accept_countdown = None
                self._job_countdown = self._job_ticks
                # Событие: задание принято (зеркало момента FLAG->0 в Lua)
                if self._job_has_place:
                    self._emit(
                        f"[CVT]  задание принято: pick({self._job_x:.1f},{self._job_y:.1f})"
                        f" e={self._job_ecap}"
                        f" -> place(x{self._job_place_x:.1f}, y{self._job_place_y:.1f},"
                        f" z{self._job_place_z:.1f}, r{self._job_place_rz:.0f}°)"
                    )
                else:
                    self._emit(
                        f"[CVT]  задание принято: pick({self._job_x:.1f},{self._job_y:.1f})"
                        f" e={self._job_ecap} -> GL_PLACE"
                    )
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
                self._emit("[CVT]  выполнено -> робот свободен")

    def _handle_config(self) -> None:
        if self.regs[REG_CFG_FLAG] == 1:
            self.regs[REG_CFG_FLAG] = 0  # блок уже в регистрах — «применили»
            # Событие: зеркало handle_config() Lua (SPD, HOME, PICKZ, PLACE, GRIP, ZONE)
            base = REG_CFG_BASE
            spd = self.regs[base + 0]
            hx = _s16(self.regs[base + 1])
            hy = _s16(self.regs[base + 2])
            hz = _s16(self.regs[base + 3])
            pz = _s16(self.regs[base + 4])
            qx = _s16(self.regs[base + 5])
            qy = _s16(self.regs[base + 6])
            qz = _s16(self.regs[base + 7])
            grip_ms = self.regs[base + 8]
            zmax = _s16(self.regs[base + 9])
            zmin = _s16(self.regs[base + 10])
            self._emit(
                f"[CFG]  SPD={spd}"
                f" HOME={hx},{hy},{hz}"
                f" PICKZ={pz}"
                f" PLACE={qx},{qy},{qz}"
                f" GRIP={grip_ms / 1000.0}"
                f" ZONE={zmin}..{zmax}"
            )

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
        # RAW*100 -> Гц (см. gd20_bridge.yaml cmd_freq.scale) — скорость ленты
        # меняется ТОЛЬКО здесь, по пульсу VFD_FLAG (ограничение прошивки,
        # разгон/торможение по рампе вне области задачи, см. belt.py).
        self._belt.command(run=run, freq_hz=freq / _VFD_FREQ_SCALE, reverse=reverse)
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
            # Стоп: прошивка сама потребляет abort и чистит управляющие регистры
            # (паритет с execute_path-финалом + client.draw_flush) → следующий старт с нуля.
            self.regs[REG_DRAW_ABORT] = 0
            self.regs[REG_DRAW_BUSY] = 0
            self.regs[REG_DRAW_FLAG] = 0
            self.regs[REG_DRAW_COUNT] = 0
            self.regs[REG_DRAW_PROG] = 0
            self.regs[REG_DRAW_DONE_N] = 0
            # Заезд домой по REG_DRAW_HOME (паритет с idle-DRAW abort веткой прошивки):
            # прошивка потребляет флаг и едет домой; здесь моделируем потребление флага.
            self.regs[REG_DRAW_HOME] = 0
            self._draw_countdown = None
            return
        if self.regs[REG_DRAW_FLAG] == 1 and self._draw_countdown is None:
            self.regs[REG_DRAW_FLAG] = 0
            self.regs[REG_DRAW_BUSY] = 1
            self.regs[REG_DRAW_PROG] = 0
            self._draw_countdown = self._draw_ticks
            self._emit("[DRAW] проход начат")
        elif self._draw_countdown is not None:
            self.regs[REG_DRAW_PROG] += 1
            self._draw_countdown -= 1
            if self._draw_countdown <= 0:
                self.regs[REG_DRAW_BUSY] = 0
                # Read-back ACK: эхо реально выполненного числа точек = заявленному count
                # (паритет с прошивкой). Тест может переопределить, чтобы проверить retry.
                self.regs[REG_DRAW_DONE_N] = self.regs[REG_DRAW_COUNT]
                prog = self.regs[REG_DRAW_PROG]
                self._draw_countdown = None
                self._emit(f"[DRAW] проход завершён ({prog} точек)")

    def _handle_return(self) -> None:
        """RETURN (mode=3): ret_flag 1->0 (приём) -> ret_busy 1 (старт) -> ret_busy 0 (готово).

        Handshake идентичен рисованию. По завершении позиция = координата слота (забор) —
        для проверок в тестах (реальный Lua после забора ещё едет на ленту и домой).
        """
        if self.regs[REG_RET_FLAG] == 1 and self._ret_countdown is None:
            self.regs[REG_RET_FLAG] = 0  # принял
            self.regs[REG_RET_BUSY] = 1  # старт
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            self._ret_countdown = self._return_ticks
            rx = _s16(self.regs[REG_RET_X])
            ry = _s16(self.regs[REG_RET_Y])
            self._emit(f"[RET]  возврат слота ({rx:.1f},{ry:.1f}) -> лента")
        elif self._ret_countdown is not None:
            self._ret_countdown -= 1
            if self._ret_countdown <= 0:
                self.regs[REG_TLM_BASE + _TLM_X] = self.regs[REG_RET_X]
                self.regs[REG_TLM_BASE + _TLM_Y] = self.regs[REG_RET_Y]
                self.regs[REG_TLM_BASE + _TLM_Z] = self.regs[REG_RET_Z]
                self.regs[REG_TLM_BASE + _TLM_MOVING] = 0
                self.regs[REG_RET_BUSY] = 0  # готово
                self._ret_countdown = None
                self._emit("[RET]  выполнено -> робот свободен")

    def _handle_toolchange(self) -> None:
        """TOOLCHANGE (mode=4): tool_flag 1->0 (приём) -> tool_busy 1 -> tool_busy 0 (готово).

        Handshake идентичен RETURN/DRAW. По завершении REG_TOOL_CUR = REG_TOOL_TARGET.
        """
        if self.regs[REG_TOOL_FLAG] == 1 and self._tool_countdown is None:
            target = self.regs[REG_TOOL_TARGET]
            cur = self.regs[REG_TOOL_CUR]
            if target == cur:
                # Lua: «инструмент N уже стоит» — мгновенный ответ без движения
                self.regs[REG_TOOL_FLAG] = 0
                self.regs[REG_TOOL_BUSY] = 0
                self._emit(f"[TOOL] инструмент {target} уже стоит")
                return
            self.regs[REG_TOOL_FLAG] = 0  # принял
            self.regs[REG_TOOL_BUSY] = 1  # старт
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            self._tool_countdown = self._toolchange_ticks
            self._emit(f"[TOOL] смена {cur} -> {target}")
        elif self._tool_countdown is not None:
            self._tool_countdown -= 1
            if self._tool_countdown <= 0:
                # смена завершена — текущий инструмент = целевой
                target = self.regs[REG_TOOL_TARGET]
                self.regs[REG_TOOL_CUR] = target
                self.regs[REG_TLM_BASE + _TLM_MOVING] = 0
                self.regs[REG_TOOL_BUSY] = 0  # готово
                self._tool_countdown = None
                self._emit(f"[TOOL] установлен инструмент {target}")

    def _handle_manual(self) -> None:
        """MANUAL (mode=2): man_flag 1->0 (приём) -> man_busy=1, free=0 -> man_busy=0, free=1.

        Эмулирует run_manual() Lua: робот «доезжает» к целевой позиции (обновление
        телеметрии x/y) и ставит man_busy=0, free=1. Нужно для проверки калибровки.
        """
        if self.regs[REG_MAN_FLAG] == 1 and self._man_countdown is None:
            self.regs[REG_MAN_FLAG] = 0  # принял
            self.regs[REG_MAN_BUSY] = 1
            self.regs[REG_FREE] = 0
            self.regs[REG_TLM_BASE + _TLM_MOVING] = 1
            # Вычислить целевую позицию (как Lua run_manual)
            dx = _s16(self.regs[REG_MAN_DX])
            dy = _s16(self.regs[REG_MAN_DY])
            self._man_spd = self.regs[REG_MAN_SPD]
            self._man_abs = self.regs[REG_MAN_ABS]
            if self._man_abs == 1:
                # абсолютный режим: ехать в (dx, dy) как координаты
                self._man_tx = dx
                self._man_ty = dy
            else:
                # относительный: текущая поза + смещение
                cur_x = _s16(self.regs[REG_TLM_BASE + _TLM_X])
                cur_y = _s16(self.regs[REG_TLM_BASE + _TLM_Y])
                self._man_tx = cur_x + dx
                self._man_ty = cur_y + dy
            self._man_countdown = self._manual_ticks
        elif self._man_countdown is not None:
            self._man_countdown -= 1
            if self._man_countdown <= 0:
                # «доехал»: обновить позицию
                # Пишем в регистры как signed *10 (формат телеметрии)
                def _to_reg(v: float) -> int:
                    raw = int(round(v * XY_SCALE))
                    return raw & 0xFFFF

                self.regs[REG_TLM_BASE + _TLM_X] = _to_reg(self._man_tx)
                self.regs[REG_TLM_BASE + _TLM_Y] = _to_reg(self._man_ty)
                self.regs[REG_TLM_BASE + _TLM_MOVING] = 0
                self.regs[REG_MAN_BUSY] = 0
                self.regs[REG_FREE] = 1
                self._man_countdown = None
                self._emit(
                    f"[MANUAL] -> ({self._man_tx:.1f},{self._man_ty:.1f}) spd={self._man_spd} abs={self._man_abs}"
                )

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
    def belt(self) -> BeltDrive:
        """Модель ленты — публичный доступ для команд ``belt.*`` (Task 2.3a,
        ``SimRobotHostPlugin``): ``belt.calibrate``/``belt.status`` читают
        ``state``/``mm_s_at_max_freq`` отсюда напрямую. ``belt_mm_s``/
        ``encoder`` остаются отдельными аксессорами горячего пути публикации
        (Task 2.2) — не заменяются этим свойством."""
        return self._belt

    @property
    def belt_mm_s(self) -> float:
        """Точная текущая скорость ленты, мм/с (см. ``BeltDrive.mm_s``).

        Единственный публичный аксессор скорости (ревью Task 2.2 line-sim):
        раньше потребители снаружи модуля (``Plugins.sim.robot_host``) не
        имели доступа к ``self._belt`` и считали ``mm_s`` производной энкодера
        между своими собственными тиками публикации — на пульсе смены команды
        ПЧ такая производная даёт смешанное среднее за интервал, а не точную
        мгновенную скорость. Эта дыра не входила в область Task 2.1/2.1b
        (`sim_core.py` тогда не трогали снаружи), закрывается здесь.
        """
        return self._belt.mm_s

    @property
    def job_ecap(self) -> list[int]:
        """Сырые слова E_capture последнего задания (проверка word order)."""
        return self.read(REG_JOB_ECAP, 2)
