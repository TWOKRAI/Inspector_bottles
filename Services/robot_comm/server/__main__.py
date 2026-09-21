"""CLI: поднять TCP-симулятор робота.

Примеры::

    python -m Services.robot_comm.server                      # 2.5 с на pick-place
    python -m Services.robot_comm.server --gui                # + окно-монитор обмена
    python -m Services.robot_comm.server --job-ms 20          # «мгновенный» робот (для e2e)
    python -m Services.robot_comm.server --host 0.0.0.0 --port 502

ВНИМАНИЕ, ТАЙМИНГ. Дефолт CLI — 2.5 с на задание, как у железа. Это не
косметика: при «мгновенном» роботе очередь заданий в драйвере рассасывается
быстрее, чем успевает накопиться, и дефект «одна деталь → три задания»
на симуляторе не воспроизводится. Ускорять — осознанно, флагом.
"""

from __future__ import annotations

import argparse

from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_robot import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    TICK_INTERVAL_S,
    run_sim_robot,
)

#: Реалистичные значения железа (Delta SCARA на стенде), мс.
DEFAULT_JOB_MS = 2500  # полный цикл pick-place: подвод, захват, укладка, дом
DEFAULT_ACCEPT_MS = 20  # от job_flag=1 до сброса в 0 (робот подхватил mailbox)
DEFAULT_BELT_FREQ_MAX_HZ = 50.0  # верхняя граница частоты ПЧ (см. gd20_bridge.yaml cmd_freq.max)


def _ms_to_ticks(ms: float) -> int:
    """Миллисекунды → тики Motion-цикла (минимум один тик)."""
    return max(1, round(ms / (TICK_INTERVAL_S * 1000)))


def main() -> None:
    """Точка входа CLI симулятора."""
    parser = argparse.ArgumentParser(description="Фейк-робот Delta (Modbus-TCP slave, карта universal3)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--unit", type=int, default=ROBOT_UNIT_ID)
    parser.add_argument("--gui", action="store_true", help="окно-монитор обмена (две колонки, счёт дублей)")
    parser.add_argument("--job-ms", type=float, default=DEFAULT_JOB_MS, help="длительность pick-place, мс")
    parser.add_argument("--accept-ms", type=float, default=DEFAULT_ACCEPT_MS, help="приём задания (flag 1->0), мс")
    parser.add_argument(
        "--belt-mm-s",
        type=float,
        default=None,
        help=(
            "скорость ленты на 100%% частоты ПЧ, мм/с (мод. BeltDrive — Task 2.1); "
            "не задано -> старое поведение (постоянная скорость по enc_rate, как без ПЧ); "
            "задано -> лента СТОИТ, пока не придёт первая живая команда пуска ПЧ"
        ),
    )
    args = parser.parse_args()

    # Task 2.1: без --belt-mm-s — старое поведение (RobotSimCore(enc_rate=...)
    # по умолчанию, как у голого SimRobotServer()), belt в core_kwargs не
    # передаём вовсе. С --belt-mm-s — модель BeltDrive, скорость задаёт живая
    # команда ПЧ (mailbox 0x1200..0x1204); до первой команды лента стоит
    # (mm_s=0) — как настоящий конвейер без пуска (ревью Task 2.1, п.4).
    core_kwargs = {
        "job_ticks": _ms_to_ticks(args.job_ms),
        "accept_ticks": _ms_to_ticks(args.accept_ms),
    }
    if args.belt_mm_s is None:
        print(
            f"тайминг: pick-place {args.job_ms:.0f} мс, приём {args.accept_ms:.0f} мс, "
            f"лента — старое поведение (постоянная скорость, --belt-mm-s не задан)",
            flush=True,
        )
    else:
        core_kwargs["belt"] = BeltDrive(mm_s_at_max_freq=args.belt_mm_s, freq_max_hz=DEFAULT_BELT_FREQ_MAX_HZ)
        print(
            f"тайминг: pick-place {args.job_ms:.0f} мс, приём {args.accept_ms:.0f} мс, "
            f"лента до {args.belt_mm_s:.0f} мм/с (на {DEFAULT_BELT_FREQ_MAX_HZ:.0f} Гц) — "
            f"едет только по команде ПЧ",
            flush=True,
        )
    run_sim_robot(
        args.host,
        args.port,
        args.unit,
        core_kwargs=core_kwargs,
        gui=args.gui,
    )


if __name__ == "__main__":
    main()
