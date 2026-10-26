# ruff: noqa
"""CTO probe: (1) six literals B1-B6 -> ValueError + bytes intact; (2) property generator, refusal rate per seed."""

import json, sys, tempfile, collections
from pathlib import Path
import yaml
from hypothesis import given, settings, seed, Phase, assume, HealthCheck
from hypothesis import strategies as st
from multiprocess_framework.modules.recipe import yaml_io
from multiprocess_framework.modules.recipe.tests import test_yaml_patch as T

# capture ruamel dump text that the safety net refuses
_captured = {}
_orig_verify = yaml_io._verify_dump


def _spy(text, data, path, expected=yaml_io._MISSING):
    _captured["text"] = text
    return _orig_verify(text, data, path, expected)


yaml_io._verify_dump = _spy

B = {
    "B1": (
        "# c0\nk: null  # e1\n# c2\nka:  # e3\n  # c4\n  - null  # e5\n  # c6\n  - null  # e7\n  # c8\n  -  # e9\n    # c10\n    k: null  # e11\n    # c12\n    ka: null  # e13\n    # c14\n    kb: null  # e15\n    # c16\n    kt: null  # e17\n",
        {"k": None, "ka": [None, None, {"k": None, "ka": None, "kb": None, "kt": None}]},
        {"ka": [{"kt": None, "knew": 1}], "knew": 1},
    ),
    "B2": (
        "# c0\nk: null  # e1\n# c2\nka:  # e3\n  # c4\n  -  # e5\n    # c6\n    k: null  # e7\n  # c8\n  - null  # e9\n  # c10\n  -  # e11\n    # c12\n    k: null  # e13\n    # c14\n    ka: null  # e15\n    # c16\n    kb: null  # e17\n    # c18\n    ki: null  # e19\n",
        {"k": None, "ka": [{"k": None}, None, {"k": None, "ka": None, "kb": None, "ki": None}]},
        {"ka": [{"knew": 1}, {"knew": 1}], "knew": 1},
    ),
    "B3": (
        "# c0\nk: []\n# c1\nka:  # e2\n  # c3\n  - []\n  # c4\n  -  # e5\n    # c6\n    k: null  # e7\n    # c8\n    ka: null  # e9\n  # c10\n  - null  # e11\n",
        {"k": [], "ka": [[], {"k": None, "ka": None}, None]},
        {"ka": [{"ka": None, "knew": 1}], "knew": 1},
    ),
    "B4": (
        "# c0\nkgv:  # e1\n  - {}\n  - {}\n  -\n    - null  # e2\n    # c3\n    - null\n  -\n    kggr: null  # e4\n    kcats: null\n    # c5\n    k: {}\n    kliyk: null  # e6\n",
        {"kgv": [{}, {}, [None, None], {"kggr": None, "kcats": None, "k": {}, "kliyk": None}]},
        {"kgv": [{}, {}, {"kcats": None}, "sins"]},
    ),
    "B5": (
        "# c0\nk:  # e1\n  # c2\n  - {}\n  # c3\n  - {}\n  # c4\n  - null  # e5\n  # c6\n  -  # e7\n    # c8\n    k: []\n    # c9\n    ka: null  # e10\n    kaa: null\n    # c11\n    kaaa: null  # e12\n",
        {"k": [{}, {}, None, {"k": [], "ka": None, "kaa": None, "kaaa": None}]},
        {"k": [{}, {"knew": 1}, {"kaaa": None, "knew": 1}, "sins"], "knew": 1},
    ),
    "B6": (
        "# c0\nk:  # e1\n  # c2\n  - {}\n  # c3\n  - {}\n  # c4\n  - null  # e5\n  # c6\n  -  # e7\n    # c8\n    k: []\n    # c9\n    ka: null  # e10\n    kaa: null\n    # c11\n    kaaa: null  # e12\n",
        {"k": [{}, {}, None, {"k": [], "ka": None, "kaa": None, "kaaa": None}]},
        {"k": [{}, "sins", {"knew": 1}, {"knew": 1}], "knew": 1},
    ),
}


def run_one(src: str, before, after):
    """-> (outcome, dump_fragment). outcome in {'written_ok','written_wrong','refused_intact','refused_changed','other'}"""
    _captured.clear()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "r.yaml"
        raw = src.encode("utf-8")
        p.write_bytes(raw)
        try:
            yaml_io.patch_yaml_preserving(p, before, after)
        except ValueError as exc:
            intact = p.read_bytes() == raw
            return (
                ("refused_intact" if intact else "refused_changed"),
                (_captured.get("text") or "")[:400],
                str(exc)[:80],
            )
        except Exception as exc:  # noqa
            return "other:" + type(exc).__name__, "", str(exc)[:80]
        out = p.read_text(encoding="utf-8")
        ok = json.dumps(yaml.safe_load(out), sort_keys=True) == json.dumps(after, sort_keys=True)
        comments = [l.split("#", 1)[1] for l in out.splitlines() if "#" in l]
        ok = ok and len(comments) == len(set(comments))
        return ("written_ok" if ok else "written_wrong"), out[:400], ""


print("=== literals B1..B6 ===")
for name, (src, before, after) in B.items():
    clean = T._ruamel_roundtrip_clean(src, before)
    outcome, dump, msg = run_one(src, before, after)
    bad = [
        l
        for l in dump.splitlines()
        if ":   -" in l or ": k" in l and ": {" not in l or l.rstrip().endswith("-") and "- " not in l.strip()[:2]
    ]
    print(f"{name}: clean_rt={clean} outcome={outcome} msg={msg!r}")
    for l in dump.splitlines():
        if ("knew: 1   -" in l) or (": knew:" in l) or (":   -" in l):
            print(f"    glue line: {l!r}")

print("=== property generator, per seed (300 examples, no db, no shrink) ===")
seeds = [int(s) for s in sys.argv[1:]] or [13]
for sd in seeds:
    cnt = collections.Counter()

    @seed(sd)
    @settings(
        max_examples=300,
        deadline=None,
        database=None,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(before=T._DOC, rnd=st.randoms(use_true_random=False))
    def body(before, rnd):
        after = T._mutate(before, rnd)
        src = T._dump_commented(before, rnd)
        assume(T._ruamel_roundtrip_clean(src, before))
        cnt["examples"] += 1
        outcome, _, _ = run_one(src, before, after)
        cnt[outcome] += 1

    body()
    print(f"seed {sd}: {dict(cnt)}")
