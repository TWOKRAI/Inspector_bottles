# ruff: noqa: E501
"""Подсчёт стенда T5.3e по каталогу(ам) прогона `run-*` (их пишет run_stand.py).

Копия `SPI.stand/count.py` с правками T5.3e.3s: к таблице S0-S3 (регрессия `--regress`: S0, S1, G, пороги прежние)
добавлена таблица park P1-P3 (L1-L3 брифа T5.3e.3, «Общие правила»): строка на критерий PASS / FAIL с фактом, пороги
- литералы в коде. Несколько каталогов - отчёт по каждому и сводка `P<n>: k/N`; `STAND: PASS` и код 0 - только если все PASS.

Ниже - текст count.py SPI.stand (S0-S3, device_io). Таблица park: `count_park`.


Критерии (SPI.injections.md, раздел «Стенд»; не хуже C-29):
  * SERVO + DO_SET после команды «Отключить» = 0 (журнал драйвера и журнал сима);
  * STOP_REQ SOFT ровно 1 при поднятой связи (S1-S3), 0 до связи (S0), на клиенте и на симе;
  * до `disconnected` не больше 1,23 с (C-29: 0,75-1,23 с), порог критерия 5,0 с;
  * S0: обмен сима после `CTL done up` - ТОЛЬКО до первой строки следующего сценария (`MARK S1`) в sim.log, ожидается 0
    (урок C-29: прежний count.py считал до конца журнала вместе с S1-S3 и дал ложный FAIL).

Запуск: python count.py <каталог run-*> [<каталог run-*> ...]   (код выхода 0 - всё PASS, 1 - есть FAIL/WARN-ФАЗА, 2 - нет входных файлов)
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
    # STOP_REQ = stop_seq*4 + level (client_v2.py:113), SOFT = 1: значение & 3 == 1
    total = 0
    for x in lines:
        m = re.match(r"^W\*? STOP_REQ = (\d+)$", x.get("text", ""))
        if m and int(m.group(1)) & 3 == 1:
            total += int(x.get("n", 1))
    return total


def soft_sim(rows: list[tuple[float, str, str]], t0: float, t1: float) -> int:
    total = 0
    for t, k, x in rows:
        m = re.match(r"^W STOP_REQ fc=\d+ \[(\d+)\]$", x) if k == "IO" and t0 <= t < t1 else None
        if m and int(m.group(1)) & 3 == 1:
            total += 1
    return total


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


def find_key(res: Any, key: str, depth: int = 3) -> Any:
    if isinstance(res, dict):
        if key in res:
            return res[key]
        if depth:
            for v in res.values():
                got = find_key(v, key, depth - 1)
                if got is not None:
                    return got
    return None


def reply_body(res: Any) -> Any:
    return res.get("result", res) if isinstance(res, dict) and set(res) >= {"result"} and "status" not in res else res


def count_spi(run: Path) -> int:
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
        after = [journal[s] for s in sorted(journal) if seq_cmd < s <= seq_hi and journal[s].get("t_rx", 0) < t_end]
        servo_do_cli = opcount(after, "SERVO", "DO_SET")
        servo_do_sim = sim_ops(sim, t_cmd, t_end, "SERVO", "DO_SET")
        soft_cli = soft_client(after)
        soft_s = soft_sim(sim, t_mark, t_end)
        disc = ev.get("disconnected_seen", {}).get("disc_s")
        t_disc = ev.get("disconnected_seen", {}).get("t_disc")
        seq = []
        for t, c in status:
            if t_start <= t <= (t_disc + 0.01 if t_disc else t + 1) and (not seq or seq[-1] != c):
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
    race = run / "race.json"
    if race.exists():
        print("\nГонка introspect (от Popen бэкенда; пауза 0,1 с, вызов <= 2 с):")
        for cmd, v in json.loads(race.read_text(encoding="utf-8")).items():
            print(
                f"- {cmd}: ok={v['ok']}, попыток до успеха {v['attempts_to_first_ok']} (всего {v['attempts_total']}), первый успех на {v['t_first_ok_s']} с, ошибки {v['errors']}"
            )
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

    io = c.get("meta", {}).get("device_io_expected", True)

    def na(text: str, raw: Any = None) -> None:
        print(
            f"- n/a  {text} (дерево без device_io)"
            + (f"\n    ответ: {json.dumps(raw, ensure_ascii=False)[:400]}" if raw is not None else "")
        )

    print("Проверки device_io (D, до связи) и форм ответов:")
    ex = (find_key(d.get("executors"), "executors") or {}).get("device_io") or {}
    alive = sum(1 for w in (ex.get("workers") or {}).values() if w.get("is_alive"))
    if io:
        line(bool(ex) and ex.get("max_workers") == 4 and ex.get("max_pending") == 64 and alive == 4,
             f"introspect.executors: device_io есть, max_workers=4, max_pending=64, живых рабочих {alive} (рабочие: {sorted((ex.get('workers') or {}))})", d.get("executors"))  # fmt: skip
        line(
            len(d.get("workers_keyed") or []) >= 4,
            f"introspect.status: рабочие keyed-device_io-*: {d.get('workers_keyed')}",
        )
    else:
        na("introspect.executors / рабочие keyed-device_io-*", d.get("executors"))
    pl = reply_body(d.get("point_list"))
    line(isinstance(pl, dict) and pl.get("status") == "ok" and "points" in pl and "rev" in pl,
         f"robot_point_list {{device_id}} -> status ok, points, rev (за {d.get('point_list_s')} с, ответ пришёл по IPC; через исполнитель - только при device_io)", pl)  # fmt: skip
    nk = reply_body(d.get("point_list_no_id"))
    if io:
        line(nk == {"success": False, "error": "key_missing", "command": "robot_point_list"},
             "robot_point_list без device_id -> key_missing (ответ CommandManager: так отвечает только команда, привязанная к исполнителю)", nk)  # fmt: skip
    else:
        na("robot_point_list без device_id: ответ main записан, key_missing не ожидается", nk)
    rs = reply_body(d.get("robot_stop_no_id"))
    line(isinstance(rs, dict) and rs.get("status") == "error" and "device_id обязателен" in str(rs.get("message")),
         "robot_stop без device_id -> status error, «device_id обязателен» (не привязана к исполнителю: контраст с key_missing)", rs)  # fmt: skip
    if "vfd_get_status_offline" in d:
        v = reply_body(d["vfd_get_status_offline"])
        line(isinstance(v, dict) and "status" in v, "vfd_get_status до связи: словарь с ключом status (форму сверить с main по снимку d3)", v)  # fmt: skip

    if "G" in c:  # прогон park: группа G не гонялась
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
                t_dis = next(
                    (
                        e["t"]
                        for e in read_jsonl(run / "events.jsonl")
                        if e["ev"] == "disconnect_send" and e.get("scen") == "G"
                    ),
                    float("inf"),
                )
                n = soft_sim(sim, t_stop, t_dis)
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


# --------------------------------------------------------------------------- park P1-P3 (L1-L3 брифа T5.3e.3)

ROBOT_ID = "robot_main"
USER_PROGRAM = "p3"
LINE_L1 = f"робот '{ROBOT_ID}': jog остановлен поводком: окно удержания истекло"
LINE_A1 = f"робот '{ROBOT_ID}': jog остановлен поводком после начала остановки"
LINE_E1 = f"робот '{ROBOT_ID}': jog остановлен поводком: область закрывается"
LINE_INTERRUPTED = f"робот '{ROBOT_ID}': поводок jog прерван"
REPLY_MAX_S = 1.0  # P1: ответ robot_park
DONE_MAX_S = 30.0  # P1: итог от ответа
ALREADY_MAX_S = 1.5  # P2: итог второго park от ответа
TICK_S = 0.5  # период тика драйвера (число тиков до итога = elapsed_s / 0,5)


def sim_stop_writes(rows: list[tuple[float, str, str]], t0: float) -> list[int]:
    """Значения всех записей STOP_REQ (все уровни) в sim.log начиная с метки `t0` до конца прогона."""
    out = []
    for t, k, x in rows:
        m = re.match(r"^W STOP_REQ fc=\d+ \[(\d+)\]$", x) if k == "IO" and t >= t0 else None
        if m:
            out.append(int(m.group(1)))
    return out


def log_lines(run: Path, needle: str) -> int:
    """Строки со вхождением `needle` во всех `logs/**/*.log` прогона (обход файлов - как в run_stand.finish)."""
    total = 0
    for log in (run / "logs").rglob("*.log"):
        total += sum(1 for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if needle in ln)
    return total


def count_park(run: Path, events: list[dict[str, Any]], sim: list[tuple[float, str, str]]) -> tuple[bool, str]:
    """Таблица критериев park для одного прогона. Возвращает (есть красное, имя сценария)."""
    name = next(e["scen"] for e in events if e["ev"] == "scenario_start" and str(e.get("scen", "")).startswith("P"))
    t_mark = next(
        (t for t, k, x in sim if k == "MARK" and x == name), next(e["t"] for e in events if e["ev"] == "scenario_start")
    )
    replies = {e["label"]: e for e in events if e["ev"] == "park_reply"}
    finals = {e["label"]: e for e in events if e["ev"] == "park_final"}
    jog = read_jsonl(run / "jog.jsonl")
    program = read_jsonl(run / "program.jsonl")
    stops = sim_stop_writes(sim, t_mark)
    n = {"L1": log_lines(run, LINE_L1), "A1": log_lines(run, LINE_A1), "E1": log_lines(run, LINE_E1)}
    interrupted = log_lines(run, LINE_INTERRUPTED)
    stop_echo = log_lines(run, "stop_echo")
    rows: list[tuple[str, bool, str]] = []

    def row(criterion: str, ok: bool, fact: str) -> None:
        rows.append((criterion, ok, fact))

    def final_value(label: str) -> dict[str, Any]:
        v = (finals.get(label) or {}).get("value")
        return v if isinstance(v, dict) else {}

    def reply_of(label: str) -> dict[str, Any]:
        v = (replies.get(label) or {}).get("reply")
        return v if isinstance(v, dict) else {}

    def to_final_s(label: str) -> float | None:
        f = finals.get(label) or {}
        return round(f["t_final"] - f["t_reply"], 3) if f.get("t_final") and f.get("t_reply") else None

    abort = [e for e in events if e["ev"] in ("abort", "precondition_failed")]
    row(
        "прогон не прерван, предусловия сценария выполнены",
        not abort,
        "; ".join(str(e.get("error") or e.get("what")) for e in abort) or "да",
    )

    if name == "P1":
        r = reply_of("P1")
        el = (replies.get("P1") or {}).get("elapsed_s")
        row(
            "ответ robot_park: accepted is True, seq - число",
            r.get("accepted") is True and isinstance(r.get("seq"), int),
            str(r),
        )
        row(f"ответ <= {REPLY_MAX_S} с", el is not None and el <= 1.0, f"{el} с")
        fv, tf = final_value("P1"), to_final_s("P1")
        row('итог .park: state == "done"', fv.get("state") == "done", str(fv.get("state")))
        row('итог: home == "moved"', fv.get("home") == "moved", str(fv.get("home")))
        row(f"итог за <= {DONE_MAX_S} с от ответа", tf is not None and tf <= 30.0, f"{tf} с")
        t_rx = (replies.get("P1") or {}).get("t_rx")
        after = [j for j in jog if t_rx is not None and j["t"] >= t_rx]
        ok_after = [j for j in after if j.get("status") == "ok"]
        row("jog_hold после ответа >= 3", len(after) >= 3, str(len(after)))
        row("из них ok == 0", len(ok_after) == 0, str(len(ok_after)))
        row("L1 == 0", n["L1"] == 0, str(n["L1"]))
        row("A1 == 0", n["A1"] == 0, str(n["A1"]))
        row("E1 == 0", n["E1"] == 0, str(n["E1"]))
        row("d1 == 2 (SOFT release и SOFT выключения)", len(stops) == 2, f"{len(stops)} {stops}")
        row(
            "последняя запись STOP_REQ & 3 == 1 (SOFT)",
            bool(stops) and stops[-1] & 3 == 1,
            str(stops[-1] & 3 if stops else None),
        )
    elif name == "P2":
        r1, r2 = reply_of("P2.1"), reply_of("P2.2")
        f1, f2, tf2 = final_value("P2.1"), final_value("P2.2"), to_final_s("P2.2")
        row(
            "первый park принят, итог done",
            r1.get("accepted") is True and f1.get("state") == "done",
            f"{r1.get('accepted')} / {f1.get('state')}",
        )
        row(
            "второй park принят",
            r2.get("accepted") is True and isinstance(r2.get("seq"), int) and r2.get("seq") != r1.get("seq"),
            str(r2),
        )
        row(
            'итог второго: state == "done", home == "already"',
            f2.get("state") == "done" and f2.get("home") == "already",
            f"{f2.get('state')} / {f2.get('home')}",
        )
        row(f"итог второго за <= {ALREADY_MAX_S} с от ответа", tf2 is not None and tf2 <= 1.5, f"{tf2} с")
        row("d1 == 1 (только SOFT выключения)", len(stops) == 1, f"{len(stops)} {stops}")
        row("L1 == 0", n["L1"] == 0, str(n["L1"]))
    else:
        fv = final_value("P3")
        t_ab = next(
            (
                j["t"]
                for j in program
                if j["value"].get("name") == USER_PROGRAM and j["value"].get("state") == "aborted"
            ),
            None,
        )
        t_park = next((j["t"] for j in program if j["value"].get("name") == "park_home"), None)
        row(
            f".program {USER_PROGRAM}/aborted наблюдается раньше park_home",
            t_ab is not None and t_park is not None and t_ab < t_park,
            f"aborted t={t_ab}, park_home t={t_park}",
        )
        row('итог .park: state == "done"', fv.get("state") == "done", str(fv.get("state")))
        row('итог: home == "moved"', fv.get("home") == "moved", str(fv.get("home")))
        row("L1 == 0", n["L1"] == 0, str(n["L1"]))
        row("A1 == 0", n["A1"] == 0, str(n["A1"]))

    print(f"Сценарий {name} (каталог {run.name})")
    print("| критерий | итог | факт |\n|---|---|---|")
    for criterion, ok, fact in rows:
        print(f"| {criterion} | {'PASS' if ok else 'FAIL'} | {fact} |")
    sd_send = next((e["t"] for e in events if e["ev"] == "shutdown_send"), None)
    sd_reply = next((e["t"] for e in events if e["ev"] == "shutdown_reply"), None)
    last_final = [f for f in finals.values() if f.get("t_final")]
    t_last = max((f["t_final"] for f in last_final), default=None)
    fv_last = (list(finals.values())[-1:] or [{}])[0].get("value") or {}
    elapsed = fv_last.get("elapsed_s")
    ready = next((e.get("attempts") for e in events if e["ev"] == "ready"), None)
    print(
        "В отчёт: "
        f"ответ {(replies.get(next(iter(replies), ''), {}) or {}).get('elapsed_s')} с; elapsed_s {elapsed}; "
        f"тиков до итога {round(elapsed / TICK_S, 1) if isinstance(elapsed, (int, float)) else None}; "
        f"d1 {len(stops)}, L1 {n['L1']}, A1 {n['A1']}, E1 {n['E1']}; "
        f"итог -> process.stop {round(sd_send - t_last, 3) if sd_send and t_last else None} с; "
        f"process.stop (system_shutdown) {round(sd_reply - sd_send, 3) if sd_send and sd_reply else None} с; "
        f"health device_hub.stop_echo в логах: {'есть' if stop_echo else 'нет'} ({stop_echo} строк, по логам; сам health после выключения не опрашивается); "
        f"«поводок jog прерван»: {interrupted}; попыток готовности C-57: {ready}"
    )
    return any(not ok for _, ok, _ in rows), name


def count_run(run: Path) -> tuple[int, str | None]:
    """Один каталог: park-таблица (если в нём сценарий P*) + проверки D / уборки, иначе прежний отчёт SPI.stand."""
    events = read_jsonl(run / "events.jsonl")
    if not any(e["ev"] == "scenario_start" and str(e.get("scen", "")).startswith("P") for e in events):
        return count_spi(run), None
    need = [run / "sim.log", run / "events.jsonl"]
    if missing := [p.name for p in need if not p.exists()]:
        print(f"нет входных файлов: {missing}")
        return 2, None
    bad, name = count_park(run, events, read_sim(run / "sim.log"))
    bad |= check_groups(run)
    return (1 if bad else 0), name


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(sys.argv) > 1 else 2
    code, results = 0, {}
    for arg in sys.argv[1:]:
        print(f"== {arg}")
        run_code, name = count_run(Path(arg))
        code |= run_code
        if name:
            results.setdefault(name, []).append(run_code == 0)
    if len(sys.argv) > 2 or results:
        for name, oks in results.items():
            print(f"{name}: {sum(oks)}/{len(oks)}")
    print("\nSTAND:", "FAIL/ПРОВЕРИТЬ" if code else "PASS")
    return 1 if code else 0


if __name__ == "__main__":
    sys.exit(main())
