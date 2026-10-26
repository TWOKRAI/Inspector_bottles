# ruff: noqa: E501
"""Подсчёт стенда SPI по каталогу прогона `run-*` (его пишет run_stand.py): таблица S0-S3 и проверки device_io.

Критерии (SPI.injections.md, раздел «Стенд»; не хуже C-29):
  * SERVO + DO_SET после команды «Отключить» = 0 (журнал драйвера и журнал сима);
  * STOP_REQ SOFT ровно 1 при поднятой связи (S1-S3), 0 до связи (S0), на клиенте и на симе;
  * до `disconnected` не больше 1,23 с (C-29: 0,75-1,23 с), порог критерия 5,0 с;
  * S0: обмен сима после `CTL done up` - ТОЛЬКО до первой строки следующего сценария (`MARK S1`) в sim.log, ожидается 0
    (урок C-29: прежний count.py считал до конца журнала вместе с S1-S3 и дал ложный FAIL).

Запуск: python count.py <каталог run-*>      (код выхода 0 - всё PASS, 1 - есть FAIL/WARN-ФАЗА, 2 - нет входных файлов)
Читает только файлы каталога: sim.log, events.jsonl, journal.jsonl, status.jsonl, checks.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PARAM_SETS_FULL = 58
C29_MAX_S = 1.23
LIMIT_S = 5.0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def read_sim(path: Path) -> list[tuple[float, str, str]]:
    rows = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split(" ", 2)
        if len(parts) == 3:
            try:
                rows.append((float(parts[0]), parts[1], parts[2]))
            except ValueError:
                continue
    return rows


def opcount(lines: list[dict[str, Any]], *names: str) -> int:
    pat = re.compile(r"^W\*? CMD_OPCODE = \d+ \((" + "|".join(names) + r")\)")
    return sum(int(x.get("n", 1)) for x in lines if pat.match(x.get("text", "")))


def soft_client(lines: list[dict[str, Any]]) -> int:
    return sum(int(x.get("n", 1)) for x in lines if re.match(r"^W\*? STOP_REQ = 1$", x.get("text", "")))


def soft_sim(rows: list[tuple[float, str, str]], t0: float, t1: float) -> int:
    return sum(
        1 for t, k, x in rows if k == "IO" and t0 <= t < t1 and x.startswith("W STOP_REQ ") and x.endswith("[1]")
    )


def sim_ops(rows: list[tuple[float, str, str]], t0: float, t1: float, *ops: str) -> int:
    pat = re.compile(r"^\[v2\] CMD seq=\d+ op=(" + "|".join(ops) + r")\b")
    return sum(1 for t, k, x in rows if k == "EV" and t0 <= t < t1 and pat.match(x))


def phase_label(ph: dict[str, Any]) -> str:
    if not ph.get("connect_ok"):
        return "до связи"
    if ph["param_set_before"] == 0:
        return "probe"
    if ph["param_set_before"] < PARAM_SETS_FULL:
        return f"sync_params {ph['param_set_before']}/{PARAM_SETS_FULL}"
    return "после sync, до SERVO" if ph["servo_before"] == 0 else "после SERVO"


EXPECT_PHASE = {"S0": "до связи", "S1": "probe", "S3": "после sync, до SERVO"}


def phase_ok(name: str, label: str) -> bool:
    if name == "S2":
        return label.startswith("sync_params")
    return label == EXPECT_PHASE[name]


def reply_body(res: Any) -> Any:
    return res.get("result", res) if isinstance(res, dict) and set(res) >= {"result"} and "status" not in res else res


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1])
    need = [run / "sim.log", run / "events.jsonl", run / "journal.jsonl", run / "status.jsonl"]
    if missing := [p.name for p in need if not p.exists()]:
        print(f"нет входных файлов: {missing}")
        return 2
    sim = read_sim(run / "sim.log")
    events = read_jsonl(run / "events.jsonl")
    journal: dict[int, dict[str, Any]] = {}
    for row in read_jsonl(run / "journal.jsonl"):  # последняя версия строки по seq (склейка поднимает n)
        journal[int(row["seq"])] = row
    status = [(r["t"], r["conn"]) for r in read_jsonl(run / "status.jsonl")]
    marks = [(t, x) for t, k, x in sim if k == "MARK"]
    up_done = [t for t, k, x in sim if k == "CTL" and x.startswith("done up")]

    bad = False
    rows_out = []
    for name in ("S0", "S1", "S2", "S3"):
        starts = [e for e in events if e["ev"] == "scenario_start" and e["scen"] == name]
        if not starts:
            continue
        ev = {e["ev"]: e for e in events if e.get("scen") == name}
        t_start = starts[0]["t"]
        t_mark = next((t for t, x in marks if x == name), t_start)
        # Граница сценария в sim.log - ПЕРВАЯ строка MARK любого следующего сценария (урок C-29), иначе конец журнала.
        t_end = next((t for t, x in marks if t > t_mark), float("inf"))
        t_cmd = ev["disconnect_send"]["t"]
        seq_cmd = ev["disconnect_send"]["seq_at_cmd"]
        # Журнал сценария - строки после команды и до начала следующего сценария (журнал драйвера общий на весь прогон).
        nxt = [e for e in events if e["ev"] == "scenario_start" and e["t"] > t_start]
        seq_hi = nxt[0]["seq0"] if nxt else float("inf")
        after = [journal[s] for s in sorted(journal) if seq_cmd < s <= seq_hi]
        servo_do_cli = opcount(after, "SERVO", "DO_SET")
        servo_do_sim = sim_ops(sim, t_cmd, t_end, "SERVO", "DO_SET")
        soft_cli = soft_client(after)
        soft_s = soft_sim(sim, t_mark, t_end)
        disc = ev.get("disconnected_seen", {}).get("disc_s")
        t_disc = ev.get("disconnected_seen", {}).get("t_disc")
        seq = []
        for t, c in status:
            if t_start <= t <= (t_disc or t + 1) and (not seq or seq[-1] != c):
                seq.append(c)
        label = phase_label(ev["scenario_end"]["phase"]) if "scenario_end" in ev else "?"
        want_soft = 0 if name == "S0" else 1
        exch_after_up = None
        if name == "S0":
            t_up = next((t for t in up_done if t >= t_mark), None)
            exch_after_up = sum(1 for t, k, _ in sim if k == "IO" and t_up is not None and t_up <= t < t_end)
        problems = []
        if servo_do_cli or servo_do_sim:
            problems.append(f"SERVO+DO после команды: клиент {servo_do_cli}, сим {servo_do_sim}")
        if (soft_cli, soft_s) != (want_soft, want_soft):
            problems.append(f"SOFT клиент/сим {soft_cli}/{soft_s}, ожидалось {want_soft}/{want_soft}")
        if disc is None or disc > LIMIT_S:
            problems.append(f"до disconnected {disc} с > порога {LIMIT_S} с")
        if exch_after_up:
            problems.append(f"обмен сима после up до границы: {exch_after_up}, ожидалось 0")
        if name != "S0" and not ev["disconnect_send"].get("trigger_reached"):
            problems.append("триггер фазы не достигнут (отправлено по таймауту)")
        phase_mismatch = "scenario_end" in ev and not phase_ok(name, label)
        if problems:
            verdict = "FAIL"
        elif phase_mismatch:
            verdict = "ФАЗА?"
        elif disc is not None and disc > C29_MAX_S:
            verdict = f"PASS (>{C29_MAX_S} с)"
        else:
            verdict = "PASS"
        bad |= verdict not in ("PASS",) and not verdict.startswith("PASS")
        rows_out.append(
            f"| {name} | {label} | {servo_do_cli}+{servo_do_sim} | {soft_cli}/{soft_s} | "
            f"{'-' if disc is None else f'{disc:.2f}'} | {' -> '.join(seq) or '-'} | "
            f"{'' if exch_after_up is None else f'обмен после up: {exch_after_up}; '}{verdict}"
            f"{'; ' + '; '.join(problems) if problems else ''} |"
        )

    print(
        "| сценарий | фаза в момент команды (из журнала) | SERVO+DO после (клиент+сим) | SOFT клиент/сим | до disconnected, с | статусы (опрос 25 мс) | итог |"
    )
    print("|---|---|---|---|---|---|---|")
    print("\n".join(rows_out))
    print(
        f"\nС-29 для сравнения: S0 0,75; S1 1,22; S2 1,23; S3 0,91 с; порог {LIMIT_S} с. `disconnecting` в опросе 25 мс может не попасть.\n"
    )

    bad |= check_groups(run)
    print("\nSTAND:", "FAIL/ПРОВЕРИТЬ" if bad else "PASS")
    return 1 if bad else 0


def check_groups(run: Path) -> bool:
    """Группы D (до связи), G (подключённый робот) и итог уборки. True - есть красное."""
    path = run / "checks.json"
    if not path.exists():
        print("checks.json нет: группы D/G/finish не проверены (прогон прерван?)")
        return True
    c = json.loads(path.read_text(encoding="utf-8"))
    d, g, fin = c.get("D", {}), c.get("G", {}), c.get("finish", {})
    red = False

    def line(ok: bool, text: str, raw: Any = None) -> None:
        nonlocal red
        red |= not ok
        print(
            f"- {'OK  ' if ok else 'FAIL'} {text}"
            + (f"\n    ответ: {json.dumps(raw, ensure_ascii=False)[:400]}" if raw is not None else "")
        )

    print("Проверки device_io (D, до связи) и форм ответов:")
    ex = (d.get("executors") or {}).get("executors", {}).get("device_io") or {}
    alive = sum(1 for w in (ex.get("workers") or {}).values() if w.get("is_alive"))
    line(bool(ex) and ex.get("max_workers") == 4 and ex.get("max_pending") == 64 and alive == 4,
         f"introspect.executors: device_io есть, max_workers=4, max_pending=64, живых рабочих {alive} (рабочие: {sorted((ex.get('workers') or {}))})", d.get("executors"))  # fmt: skip
    line(
        len(d.get("workers_keyed") or []) >= 4,
        f"introspect.status: рабочие keyed-device_io-*: {d.get('workers_keyed')}",
    )
    pl = reply_body(d.get("point_list"))
    line(isinstance(pl, dict) and pl.get("status") == "ok" and "points" in pl and "rev" in pl,
         f"robot_point_list {{device_id}} -> status ok, points, rev (за {d.get('point_list_s')} с, ответ пришёл по IPC через исполнитель)", pl)  # fmt: skip
    nk = reply_body(d.get("point_list_no_id"))
    line(nk == {"success": False, "error": "key_missing", "command": "robot_point_list"},
         "robot_point_list без device_id -> key_missing (ответ CommandManager: так отвечает только команда, привязанная к исполнителю)", nk)  # fmt: skip
    rs = reply_body(d.get("robot_stop_no_id"))
    line(isinstance(rs, dict) and rs.get("status") == "error" and "device_id обязателен" in str(rs.get("message")),
         "robot_stop без device_id -> status error, «device_id обязателен» (не привязана к исполнителю: контраст с key_missing)", rs)  # fmt: skip
    if "vfd_get_status_offline" in d:
        v = reply_body(d["vfd_get_status_offline"])
        line(isinstance(v, dict) and "status" in v, "vfd_get_status до связи: словарь с ключом status (форму сверить с main по снимку d3)", v)  # fmt: skip

    print("Группа G (подключённый робот, сим без задержки):")
    line(bool(g.get("connected")), "device_connect -> conn connected")
    if g.get("connected"):
        r = reply_body(g.get("robot_stop"))
        line(
            isinstance(r, dict) and r.get("status") == "ok",
            "robot_stop {device_id, level: SOFT} -> status ok (форму сверить с main)",
            r,
        )
        if "vfd_get_status" in g:
            line(isinstance(g["vfd_get_status"], dict), "vfd_get_status при подключённом роботе - ответ получен (форму сверить с main)", reply_body(g["vfd_get_status"]))  # fmt: skip
        pl = reply_body(g.get("point_list"))
        line(
            isinstance(pl, dict) and pl.get("status") == "ok",
            "robot_point_list при подключённом роботе -> status ok",
            pl,
        )
        sim = read_sim(run / "sim.log")
        t_stop = next((t for t, k, x in sim if k == "MARK" and x == "G_STOP"), None)
        if t_stop is not None:
            n = soft_sim(sim, t_stop, float("inf"))
            line(n == 1, f"сим после метки G_STOP: записей STOP_REQ=1 (SOFT) = {n}, ожидалось 1")
    line(bool(g.get("disconnected")), "device_disconnect -> conn disconnected")

    print("Уборка:")
    line(
        all(fin.get("ports_free", {}).values()) and bool(fin.get("ports_free")),
        f"порты свободны: {fin.get('ports_free')}",
    )
    line(bool(fin.get("main_app_yaml_md5_same")), "md5 app.yaml главного дерева до = после")
    line(bool(fin.get("worktree_status_same")), "git status worktree до = после")
    sd = fin.get("shutdown") or {}
    line(
        bool(sd.get("pm_gone")) and not fin.get("backend_terminated"),
        f"backend: system_shutdown graceful, без terminate: {sd} exit={fin.get('backend_exit')}",
    )
    hits = fin.get("devices_log_executor_lines") or []
    line(
        not any("не найден" in h for h in hits),
        f"лог devices: строк «исполнитель ... не найден» нет (всего строк про исполнитель: {len(hits)})",
    )
    return red


if __name__ == "__main__":
    sys.exit(main())
