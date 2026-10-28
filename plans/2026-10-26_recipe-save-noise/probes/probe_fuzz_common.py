# ruff: noqa
import importlib.util, sys, os, tempfile, json
from pathlib import Path

WT = r"D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\lane-d-c30"
S = os.path.dirname(os.path.abspath(__file__))
if WT not in sys.path:
    sys.path.insert(0, WT)
from multiprocess_framework.modules.recipe import yaml_io as NEW


def _load_old():
    """Движок до задачи: пакет `oldrecipe` из make_oldpkg.py; каталог — env C30_OLDPKG."""
    oldpkg = os.environ["C30_OLDPKG"]
    if oldpkg not in sys.path:
        sys.path.insert(0, oldpkg)
    import oldrecipe.yaml_io as mod

    return mod


OLD = _load_old()
import yaml


def run(mod, text, before, after, raw=None, capture_dump=False):
    """Run patch_yaml_preserving of `mod` on a temp copy. Returns dict(outcome, msg, bytes, dump)."""
    dumps = []
    orig_verify = mod._verify_dump
    if capture_dump:

        def spy(text_, *a, **k):
            dumps.append(text_)
            return orig_verify(text_, *a, **k)

        mod._verify_dump = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.yaml"
            src = raw if raw is not None else text.encode("utf-8")
            p.write_bytes(src)
            try:
                r = mod.patch_yaml_preserving(p, before, after)
                out = "written" if r else "noop"
                msg = ""
            except BaseException as exc:
                out = "REFUSED:" + type(exc).__name__
                msg = str(exc).splitlines()[0][:110] if str(exc) else ""
            res = p.read_bytes()
            return {"outcome": out, "msg": msg, "bytes": res, "same": res == src, "dump": dumps[0] if dumps else None}
    finally:
        mod._verify_dump = orig_verify


def pyread(b):
    try:
        return yaml.safe_load(b.decode("utf-8"))
    except Exception as e:
        return "<<UNREADABLE %s>>" % type(e).__name__
