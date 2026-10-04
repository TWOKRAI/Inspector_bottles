"""5.0(г): каждый рецепт backend/topology — старт, 30 с, grep логов на read-only. cwd = PYTHONPATH = дерево."""

import json
import re
import sys
import tempfile
import time
from pathlib import Path
from backend_ctl.harness import BackendHarness

PAT = re.compile(r"assignment destination is read-only", re.I)
ERR = re.compile(r"Traceback|\[ERROR\]|\[CRITICAL\]")


def main():
    out = {}
    names = sys.argv[2:]
    for rp in sorted(Path("multiprocess_prototype/backend/topology").glob("*.yaml")):
        if names and rp.stem not in names:
            continue
        if rp.name == "TEMPLATE.yaml":
            continue
        case = Path(tempfile.mkdtemp(prefix=f"sw50_{rp.stem}_"))
        logs = case / "logs"
        logs.mkdir()
        rec = {"started": False}
        t = time.perf_counter()
        try:
            h = BackendHarness(recipe=rp, port=8775, ready_timeout=90, log_dir=logs)
            drv = h.start()
            rec["started"] = True
            rec["start_s"] = round(time.perf_counter() - t, 1)
            try:
                ov = drv.system_overview(timeout=5)
                rec["procs"] = {p: v.get("hz") for p, v in (ov.get("processes") or {}).items()}
                time.sleep(30)
                ov = drv.system_overview(timeout=5)
                rec["procs_30s"] = {p: v.get("hz") for p, v in (ov.get("processes") or {}).items()}
            finally:
                h.stop()
        except BaseException as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        ro, errs, sample = 0, 0, []
        for f in logs.rglob("*"):
            if f.is_file():
                txt = f.read_text(encoding="utf-8", errors="replace")
                ro += len(PAT.findall(txt))
                for line in txt.splitlines():
                    if ERR.search(line):
                        errs += 1
                        if len(sample) < 4 and f.suffix != ".db":
                            sample.append(f"{f.name}: {line[:220]}")
        rec.update(read_only=ro, error_lines=errs, error_sample=sample, logs=str(logs))
        out[rp.name] = rec
        Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(
            rp.name,
            json.dumps(
                {k: rec.get(k) for k in ("started", "start_s", "read_only", "error_lines", "error")}, ensure_ascii=False
            ),
            flush=True,
        )
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
