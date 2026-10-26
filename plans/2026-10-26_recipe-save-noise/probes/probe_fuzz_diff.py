# ruff: noqa
"""Differential fuzz OLD (pre-1.1f) vs NEW yaml_io: outcome classes + ground truth (written => PyYAML(bytes)==after)."""

import json, sys, random, collections
from probe_fuzz_common import *
from hypothesis import given, settings, HealthCheck, strategies as st

WORDS = [
    "yes",
    "On",
    "off",
    "No",
    "12:30",
    "1:20:30",
    "1e-05",
    "010",
    "0b11",
    "1_000",
    "0x1F",
    "~",
    "null",
    "true",
    "y",
    "2020-01-01",
    "",
    " lead",
    "trail ",
    "a: b",
    "# x",
    "- y",
    "'q'",
    '"d"',
    "=",
    "<<",
    "@a",
    "!t",
    "&a",
    "*a",
    "a\nb",
    "é",
    "1,000",
    "0",
    "-0",
    ".5",
    "+1",
]
_KEY = st.from_regex(r"k[a-z]{0,3}", fullmatch=True)
_TEXT = st.one_of(st.from_regex(r"s[a-z0-9]{0,4}", fullmatch=True), st.sampled_from(WORDS))
_FLOAT = st.one_of(st.integers(-4000, 4000).map(lambda n: n / 8), st.sampled_from([1e-05, 1e22, 0.1, 1e5, -2.5e-07]))
_SCALAR = st.one_of(st.none(), st.booleans(), st.integers(-1000, 1000), _FLOAT, _TEXT)
_VALUE = st.recursive(
    _SCALAR, lambda ch: st.one_of(st.lists(ch, max_size=4), st.dictionaries(_KEY, ch, max_size=4)), max_leaves=10
)
_DOC = st.dictionaries(_KEY, _VALUE, max_size=4)


def mutate(node, rnd):
    if isinstance(node, dict):
        res = {}
        for key, child in node.items():
            r = rnd.random()
            if r < 0.15:
                continue
            if r > 0.85 and isinstance(child, (dict, list)):
                res[key] = type(child)()
            else:
                res[key] = mutate(child, rnd) if r < 0.6 else child
        if rnd.random() < 0.1:
            res["knew"] = 1
        return res
    if isinstance(node, list):
        res = [mutate(x, rnd) if rnd.random() < 0.5 else x for x in node if rnd.random() >= 0.2]
        if rnd.random() < 0.1:
            res.insert(rnd.randint(0, len(res)), "sins")
        if rnd.random() < 0.1:
            res = []
        return res
    return (
        node
        if rnd.random() < 0.7
        else rnd.choice([7, "schg", True, None, 2.5, "On", "12:30", "yes", 1e-05, False, "x y"])
    )


def dump_c(doc, rnd, flavor):
    out = []
    ctr = iter(range(10000))

    def eol():
        return f"  # e{next(ctr)}" if rnd.random() < 0.3 else ""

    def lead(ind):
        if rnd.random() < 0.3:
            col = 0 if (flavor == "col0" and rnd.random() < 0.5) else ind
            out.append(" " * col + f"# c{next(ctr)}")

    def scalar(v):
        if v is True and flavor in ("words", "col0"):
            return rnd.choice(["yes", "on", "True", "true"])
        if v is False and flavor in ("words", "col0"):
            return rnd.choice(["no", "off", "False", "false"])
        return json.dumps(v)

    def entry(head, v, ind):
        if isinstance(v, (dict, list)) and v:
            out.append(head + eol())
            block(v, ind + 2)
        else:
            if isinstance(v, (dict, list)):
                flow = "{}" if isinstance(v, dict) else "[]"
                out.append(f"{head} {flow}" + (eol() if flavor in ("flowc", "col0") else ""))
            else:
                out.append(f"{head} {scalar(v)}" + eol())

    def block(v, ind):
        pairs = v.items() if isinstance(v, dict) else (("-", x) for x in v)
        for k, c in pairs:
            lead(ind)
            entry(" " * ind + (f"{k}:" if isinstance(v, dict) else "-"), c, ind)

    if doc:
        block(doc, 0)
    else:
        out.append("{}")
    return "\n".join(out) + "\n"


def j(x):
    return json.dumps(x, sort_keys=True, default=repr)


stats = collections.Counter()
examples = collections.defaultdict(list)
FLAV = sys.argv[1]
N = int(sys.argv[2])


@settings(max_examples=N, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(before=_DOC, rnd=st.randoms(use_true_random=False))
def t(before, rnd):
    after = mutate(before, rnd)
    if FLAV == "plain":
        src = yaml.safe_dump(before, sort_keys=False, allow_unicode=True)
    else:
        src = dump_c(before, rnd, FLAV)
    try:
        if j(yaml.safe_load(src)) != j(before):
            stats["skip_src_mismatch"] += 1
            return
    except Exception:
        stats["skip_src_unreadable"] += 1
        return
    res = {}
    for label, mod in (("OLD", OLD), ("NEW", NEW)):
        r = run(mod, src, before, after)
        if r["outcome"] == "written":
            got = pyread(r["bytes"])
            cls = (
                "written-ok"
                if j(got) == j(after)
                else (
                    "WRITTEN-INVALID" if isinstance(got, str) and got.startswith("<<UNREADABLE") else "WRITTEN-MISMATCH"
                )
            )
        elif r["outcome"] == "noop":
            cls = "noop"
        else:
            cls = "refused:" + r["outcome"][8:] + ("" if r["same"] else "!FILECHANGED")
        res[label] = cls
    key = (res["OLD"], res["NEW"])
    stats[key] += 1
    if len(examples[key]) < 3 and (key[0] != key[1] or "WRITTEN" in key[0] + key[1]):
        examples[key].append({"src": src, "before": before, "after": after})


t()
print("flavor", FLAV, "N", N)
for k, v in sorted(stats.items(), key=lambda kv: str(kv[0])):
    print(" ", k, v)
json.dump(
    {str(k): v for k, v in examples.items()},
    open(f"fuzz_ex_{FLAV}.json", "w", encoding="utf-8"),
    ensure_ascii=False,
    indent=1,
    default=repr,
)
