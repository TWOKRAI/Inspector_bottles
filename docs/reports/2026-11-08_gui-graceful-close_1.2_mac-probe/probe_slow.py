"""Проба 1.2 (различающая): ребёнок с shutdown 4 с; ответы supervision_status ПОСЛЕ system.shutdown.

Копия пробы 1.1a (docs/reports/2026-11-07_gui-graceful-close_1.1a_mac-probe/probe_slow.py) + чтение
r["result"]["processes"]: stop_outcome, stop_deadline_at, stop_wave, alive по каждой записи (Task 1.2, ADR-PMM-042).

Запуск (R — корень worktree, D — этот каталог):
  PYTHONPATH=$R:$D/slowapp <python venv> $D/probe_slow.py <N прогонов> <порт> [пауза опроса, с]

Сводка по прогону — пункты (а)–(д) из задания Task 1.2-probe.
"""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from backend_ctl.harness import BackendHarness

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8799
# Пауза между опросами, с (по умолчанию 0.05, как в 1.1a); меньше — больше шанс поймать ответ у самого конца стопа.
POLL_SLEEP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
SCRATCH = Path(__file__).resolve().parent
APP_YAML = SCRATCH / "slowapp" / "app.yaml"

# Дети slowapp (pipeline.yaml): ticker — обычный, console_sink — shutdown 4 с (SlowConsumerPlugin).
NEIGHBOR = "ticker"
SLOW = "console_sink"
CHILDREN = (NEIGHBOR, SLOW)
# Окно стопа имени g и infra_s. app.yaml не задаёт shutdown_timeout и stop_window_s ни у одного процесса,
# значит g = DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0 (stop_budget.py:46, process_registry._system_window_s),
# infra_s = min(INFRA_STOP_S=1.0, 0.8*5.0/4=1.0) = 1.0 (stop_budget.py:95). Здесь литералы, не импорт из кода.
WINDOW_S = 5.0
INFRA_S = 1.0
STOPPED = ("exited", "terminated", "killed")


def build():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(APP_YAML)


def _processes(r):
    """processes из ответа supervision_status или None, если ответ не того вида."""
    if not (isinstance(r, dict) and r.get("type") == "response" and not r.get("error")):
        return None, None
    res = r.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("processes"), dict):
        return None, None
    stop = res.get("system_stop")
    return res["processes"], (stop.get("phase") if isinstance(stop, dict) else None)


def _fmt(rec, t_cmd):
    if not isinstance(rec, dict):
        return "-"
    dl = rec.get("stop_deadline_at")
    dl_s = "None" if dl is None else f"{dl - t_cmd:+.2f}"
    return f"alive={rec.get('alive')} out={rec.get('stop_outcome')} wave={rec.get('stop_wave')} dl={dl_s}"


def summarize(samples, t_cmd, post):
    """Сводка (а)–(д) по ответам одного прогона; samples — [(t0, t1, processes, phase)] в порядке получения."""
    all_names = sorted({n for (_, _, procs, _) in samples for n in procs})
    pm_names = [n for n in all_names if n not in CHILDREN]
    after = [s for s in samples if s[0] > t_cmd]
    out = {}
    out["names"] = all_names
    out["n_total"] = len(samples)
    out["n_after"] = len(after)

    # (а) соседи остановлены ("exited") пока медленный жив
    out["a"] = sum(
        1
        for (_, _, procs, _) in after
        if procs.get(NEIGHBOR, {}).get("stop_outcome") == "exited" and procs.get(SLOW, {}).get("alive") is True
    )

    # (б) stop_outcome у PM — None в каждом ответе
    pm_seen = pm_bad = 0
    for _, _, procs, _ in samples:
        for n in pm_names:
            if n in procs:
                pm_seen += 1
                if procs[n].get("stop_outcome") is not None:
                    pm_bad += 1
    out["b_pm_records"] = pm_seen
    out["b_violations"] = pm_bad

    # (в) stop_wave == "main" у всех записей
    waves = [rec.get("stop_wave") for (_, _, procs, _) in samples for rec in procs.values()]
    out["c_records"] = len(waves)
    out["c_violations"] = sum(1 for w in waves if w != "main")

    # (г) stop_deadline_at: живой ребёнок с сигналом — в [t_cmd; t_cmd + окно + infra_s]; PM и до сигнала — None
    lo, hi = t_cmd, t_cmd + WINDOW_S + INFRA_S
    live_with_deadline = []
    viol = []
    dead_with_deadline = 0
    for t0, t1, procs, _ in samples:
        for n, rec in procs.items():
            dl = rec.get("stop_deadline_at")
            if n in pm_names:
                if dl is not None:
                    viol.append(f"PM {n} dl={dl - t_cmd:+.3f}")
                continue
            if dl is None:
                continue
            if t1 < t_cmd:
                viol.append(f"до команды {n} dl={dl - t_cmd:+.3f}")
                continue
            if rec.get("alive") is True:
                live_with_deadline.append(dl - t_cmd)
                if not (lo <= dl <= hi):
                    viol.append(f"живой {n} вне [0;{WINDOW_S + INFRA_S:g}] dl={dl - t_cmd:+.3f}")
            else:
                dead_with_deadline += 1
    out["g_live_with_deadline"] = len(live_with_deadline)
    out["g_live_min"] = min(live_with_deadline) if live_with_deadline else None
    out["g_live_max"] = max(live_with_deadline) if live_with_deadline else None
    out["g_dead_with_deadline"] = dead_with_deadline
    out["g_violations"] = len(viol)
    out["g_violation_list"] = viol[:10]

    # (д) финальные stop_outcome детей: последний ответ (после shutdown, если он пришёл)
    last = post if post is not None else (samples[-1] if samples else None)
    out["d_source"] = "post-запрос после system_shutdown" if post is not None else "последний ответ опроса"
    out["d_phase"] = last[3] if last else None
    out["d_final"] = {n: (last[2].get(n, {}).get("stop_outcome") if last else None) for n in CHILDREN}
    done_resp = [s for s in samples if s[3] == "done"]
    out["d_done_responses"] = len(done_resp)
    out["d_final_in_done"] = (
        {n: done_resp[-1][2].get(n, {}).get("stop_outcome") for n in CHILDREN} if done_resp else None
    )
    return out


def main():
    rows = []
    for i in range(N):
        log_dir = tempfile.mkdtemp(prefix="probe_slow_")
        os.environ["MULTIPROCESS_LOG_DIR"] = log_dir
        h = BackendHarness(launcher_factory=build, port=PORT)
        drv = h.start()
        samples = []  # (t0_wall, t1_wall, processes, phase)
        durations = []  # (t_start_monotonic, duration) как в 1.1a
        unparsed = [0]
        stop_flag = threading.Event()

        def poll():
            while not stop_flag.is_set():
                t0m = time.monotonic()
                t0 = time.time()
                try:
                    r = drv.supervision_status(timeout=1.0)
                    procs, phase = _processes(r)
                    ok = isinstance(r, dict) and r.get("type") == "response" and not r.get("error")
                except Exception:
                    ok, procs, phase = False, None, None
                t1 = time.time()
                if ok:
                    durations.append((t0m, time.monotonic() - t0m))
                    if procs is None:
                        unparsed[0] += 1
                    else:
                        samples.append((t0, t1, procs, phase))
                time.sleep(POLL_SLEEP)

        th = threading.Thread(target=poll, daemon=True)
        th.start()
        time.sleep(1.0)
        t_sd = time.monotonic()
        t_cmd = time.time()
        res = drv.system_shutdown(wait_timeout=30.0)
        dt = time.monotonic() - t_sd
        stop_flag.set()
        th.join(2)
        # Один запрос после возврата system_shutdown (корень может быть уже закрыт — тогда ответа нет).
        post = None
        try:
            t0 = time.time()
            r = drv.supervision_status(timeout=1.0)
            procs, phase = _processes(r)
            if procs is not None:
                post = (t0, time.time(), procs, phase)
        except Exception as exc:  # noqa: BLE001 — проба: фиксируем, не падаем
            print(f"  post-запрос после shutdown не дал ответа: {type(exc).__name__}: {exc}", flush=True)
        h.stop()
        after = [d for (t, d) in durations if t > t_sd]
        dns = 0
        for p in Path(log_dir).rglob("*.log"):
            try:
                dns += p.read_text(errors="ignore").count("did not stop in")
            except OSError:
                pass
        rows.append((dt, len(after), max(after) if after else 0.0, dns))
        print(
            f"run {i + 1}: shutdown={dt:.2f}s answers_after={len(after)} max={rows[-1][2]:.3f}s "
            f"did_not_stop={dns} accepted={res.get('accepted')}",
            flush=True,
        )

        # --- 1.2: построчно ответы после команды, потом сводка (а)–(д)
        print(
            f"  t_cmd(wall)={t_cmd:.3f}; окно g={WINDOW_S:g}s infra_s={INFRA_S:g}s; "
            f"ответы без processes: {unparsed[0]}",
            flush=True,
        )
        names = sorted({n for (_, _, p, _) in samples for n in p})
        pm_names = [n for n in names if n not in CHILDREN]
        for t0, t1, procs, phase in samples:
            if t0 <= t_cmd:
                continue
            cells = " | ".join(f"{n}: {_fmt(procs.get(n), t_cmd)}" for n in list(CHILDREN) + pm_names)
            print(f"  t={t0 - t_cmd:+.2f}s phase={phase} | {cells}", flush=True)
        if post is not None:
            cells = " | ".join(f"{n}: {_fmt(post[2].get(n), t_cmd)}" for n in list(CHILDREN) + pm_names)
            print(f"  POST t={post[0] - t_cmd:+.2f}s phase={post[3]} | {cells}", flush=True)
        s = summarize(samples, t_cmd, post)
        print(f"  --- сводка прогона {i + 1}", flush=True)
        print(
            f"  имена в processes: {s['names']}; ответов всего={s['n_total']}, после команды={s['n_after']}", flush=True
        )
        print(
            f"  (а) ответов, где {NEIGHBOR}.stop_outcome=='exited' при {SLOW}.alive==True: {s['a']} (порог >= 5)",
            flush=True,
        )
        print(
            f"  (б) записей PM={s['b_pm_records']}, из них stop_outcome != None: {s['b_violations']} (ожидается 0)",
            flush=True,
        )
        print(f"  (в) записей={s['c_records']}, stop_wave != 'main': {s['c_violations']} (ожидается 0)", flush=True)
        print(
            f"  (г) живых записей с deadline={s['g_live_with_deadline']} (min={s['g_live_min']} max={s['g_live_max']} "
            f"относительно t_cmd; допустимо [0; {WINDOW_S + INFRA_S:g}]); "
            f"мёртвых с deadline={s['g_dead_with_deadline']}; "
            f"нарушений={s['g_violations']} {s['g_violation_list']}",
            flush=True,
        )
        print(
            f"  (д) финал ({s['d_source']}, phase={s['d_phase']}): {s['d_final']}; "
            f"ответов с phase=='done': {s['d_done_responses']}, последний из них: {s['d_final_in_done']}",
            flush=True,
        )
    print("min answers_after:", min(r[1] for r in rows), "max shutdown:", f"{max(r[0] for r in rows):.2f}s")


if __name__ == "__main__":
    main()
