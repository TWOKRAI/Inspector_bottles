import shutil, subprocess, sys, pathlib, re
S = pathlib.Path("/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/e2edcaee-7aad-4901-9110-64aff4d27ddb/scratchpad")
BASE = S / "inj_base"
REL = "multiprocess_framework/modules/process_manager_module/process/process_manager_process.py"
PY = "/Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python"
TESTS = [
    "multiprocess_framework/modules/process_manager_module/tests/test_supervision_status_system_stop.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_supervision_status_system_stop_hazards.py",
]
INJ = {
 "a_begin_before_args": (
   '        args = _merge_cmd_args(data, kwargs)\n        mode = args.get("mode", "graceful")\n        if mode not in ("graceful", "force"):\n            return {"error": "mode: graceful|force"}\n        # Task 1.2a:',
   '        args = _merge_cmd_args(data, kwargs)\n        self._begin_system_stop("graceful", "unknown", None)\n        mode = args.get("mode", "graceful")\n        if mode not in ("graceful", "force"):\n            return {"error": "mode: graceful|force"}\n        # Task 1.2a:'),
 "b_no_publish_lock": ("        with self._system_stop_publish_lock:\n            info = self._system_stop_snapshot()", "        if True:\n            info = self._system_stop_snapshot()"),
 "c_no_lazy_begin": ("        if system_stop is None and self._pm_stopping():", "        if False:"),
 "d_sender_from_data": ('inner_msg["data"][_SHUTDOWN_SENDER_KEY] = msg.get("sender")', 'inner_msg["data"].setdefault(_SHUTDOWN_SENDER_KEY, msg.get("sender"))'),
 "e_snapshot_no_copy": ("            return dict(info) if info is not None else None", "            return info"),
 "f_done_on_any_join": ("        if stopped:\n            # Task 1.2a: дети ушли", "        if True:\n            # Task 1.2a: дети ушли"),
 "g_value_from_arg_publish_nolock": ("        with self._system_stop_publish_lock:\n            info = self._system_stop_snapshot()", "        info = self._system_stop_snapshot()\n        if True:"),
}
which = sys.argv[1:] or list(INJ)
for name in which:
    d = S / f"inj_{name}"
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(BASE, d)
    p = d / REL
    src = p.read_text()
    old, new = INJ[name]
    assert src.count(old) == 1, (name, src.count(old))
    p.write_text(src.replace(old, new))
    r = subprocess.run([PY, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", "-x" if False else "-q", *TESTS], cwd=d, env={"PYTHONPATH": str(d), "PYTHONUTF8": "1", "PATH": "/usr/bin:/bin", "HOME": "/Users/twokrai"}, capture_output=True, text=True, timeout=600)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")]
    print(f"== {name}: rc={r.returncode}; {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]}")
    for l in fails: print("   ", l[:200])
