"""CLI-smoke robot_comm — проверка связи с роботом (или sim_robot) без GUI.

Примеры::

    python -m Services.robot_comm pos                      # 192.168.1.7:502
    python -m Services.robot_comm --host 127.0.0.1 --port 5021 pos   # sim
    python -m Services.robot_comm cal                      # подбор word order
    python -m Services.robot_comm job 150.5 -200.3         # тест-задание
    python -m Services.robot_comm state | params | enc | echo
    python -m Services.robot_comm mode draw

Команда ``cal`` — первое, что проверяют при «мусорном» энкодере: читает сырые
слова и показывает значение в обоих порядках; правильный — тот, что совпадает
с энкодером на пульте робота.
"""

from __future__ import annotations

import argparse
import struct
import sys

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig


def _cmd_pos(bot: RobotClient, _args: argparse.Namespace) -> None:
    p = bot.read_position()
    print(f"X={p.x_mm:.1f} Y={p.y_mm:.1f} Z={p.z_mm:.1f} RZ={p.rz_deg:.1f}")


def _cmd_enc(bot: RobotClient, _args: argparse.Namespace) -> None:
    print(f"enc={bot.read_encoder()}  free={bot.is_free()}")


def _cmd_cal(bot: RobotClient, _args: argparse.Namespace) -> None:
    raw = bot.read_enc_raw()
    big = struct.unpack(">i", struct.pack(">HH", raw[0], raw[1]))[0]
    little = struct.unpack(">i", struct.pack(">HH", raw[1], raw[0]))[0]
    print(f"сырые слова: {raw}")
    print(f"  word_order='big'    -> {big}")
    print(f"  word_order='little' -> {little}")
    print(f"сейчас в конфиге: '{bot.config.word_order}'. Верный — совпадающий с пультом робота.")


def _cmd_state(bot: RobotClient, _args: argparse.Namespace) -> None:
    t = bot.read_telemetry()
    busy = "ЗАНЯТ" if t.moving else "СВОБОДЕН"
    servo = "ON" if t.servo else "OFF"
    print(
        f"[{busy}] X={t.x_mm:.1f} Y={t.y_mm:.1f} Z={t.z_mm:.1f} RZ={t.rz_deg:.1f}  "
        f"серво={servo} спд={t.spd_pct}% лента={t.belt_mm_s}мм/с miss={t.miss_count} hb={t.heartbeat}"
    )


def _cmd_params(bot: RobotClient, _args: argparse.Namespace) -> None:
    print("  ".join(f"{k}={v}" for k, v in bot.get_config().items()))


def _cmd_echo(bot: RobotClient, _args: argparse.Namespace) -> None:
    e = bot.read_echo()
    print(f"принял X={e.job_x:.1f} Y={e.job_y:.1f} | trav={e.trav:.1f} -> px={e.px:.1f} py={e.py:.1f}")


def _cmd_job(bot: RobotClient, args: argparse.Namespace) -> None:
    enc = bot.read_encoder()
    ok = bot.send_job(args.x, args.y, enc)
    print(f"job X={args.x} Y={args.y} E_cap={enc}: {'отправлено' if ok else 'ОШИБКА'}")


def _cmd_mode(bot: RobotClient, args: argparse.Namespace) -> None:
    ok = bot.set_mode(args.value)
    print(f"режим {args.value.upper()}: {'ок' if ok else 'ОШИБКА'}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    defaults = RobotConfig()  # slots-dataclass: дефолты только у экземпляра
    parser = argparse.ArgumentParser(description="CLI-smoke робота Delta (robot_comm)")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--unit", type=int, default=defaults.unit_id)
    parser.add_argument("--word-order", choices=("big", "little"), default=defaults.word_order)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pos", help="позиция X/Y/Z/RZ").set_defaults(func=_cmd_pos)
    sub.add_parser("enc", help="энкодер + free").set_defaults(func=_cmd_enc)
    sub.add_parser("cal", help="подбор word order по сырому энкодеру").set_defaults(func=_cmd_cal)
    sub.add_parser("state", help="полная телеметрия").set_defaults(func=_cmd_state)
    sub.add_parser("params", help="конфиг-блок робота").set_defaults(func=_cmd_params)
    sub.add_parser("echo", help="эхо последнего задания").set_defaults(func=_cmd_echo)
    p_job = sub.add_parser("job", help="тестовое CVT-задание")
    p_job.add_argument("x", type=float)
    p_job.add_argument("y", type=float)
    p_job.set_defaults(func=_cmd_job)
    p_mode = sub.add_parser("mode", help="переключить режим")
    p_mode.add_argument("value", choices=("cvt", "draw"))
    p_mode.set_defaults(func=_cmd_mode)
    args = parser.parse_args(argv)

    cfg = RobotConfig(host=args.host, port=args.port, unit_id=args.unit, word_order=args.word_order)
    bot = RobotClient(cfg)
    if not bot.connect():
        print(f"Нет связи с роботом {cfg.describe()}", file=sys.stderr)
        return 1
    try:
        args.func(bot, args)
    finally:
        bot.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
