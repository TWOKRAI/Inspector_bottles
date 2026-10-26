# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import difflib
import json


def plan_ops(b, a):
    """design.md 2.2.2: common prefix/suffix + index-wise middle."""
    p = 0
    while p < min(len(b), len(a)) and b[p] == a[p]:
        p += 1
    s = 0
    while s < min(len(b), len(a)) - p and b[-1 - s] == a[-1 - s]:
        s += 1
    mb, ma = b[p : len(b) - s], a[p : len(a) - s]
    ops = []
    for i in range(min(len(mb), len(ma))):
        ops.append(("EDIT idx", p + i, mb[i], "->", ma[i]))
    for i in range(len(ma), len(mb)):
        ops.append(("DELETE idx", p + i, mb[i]))  # (real impl: descending)
    for i in range(len(mb), len(ma)):
        ops.append(("INSERT idx", p + i, ma[i]))
    return ops


def lcs_ops(b, a):
    sm = difflib.SequenceMatcher(
        None, [json.dumps(x, sort_keys=True) for x in b], [json.dumps(x, sort_keys=True) for x in a], autojunk=False
    )
    return [(t, i1, i2, b[i1:i2], a[j1:j2]) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != "equal"]


bind = lambda n, d: {"node_id": n, "display_id": d}
before = [
    bind("vision.circle_detector.frame", "main"),
    bind("vision.hsv_mask.mask", "phone"),
    bind("recog.ml_inference.out", "recog"),
    bind("line.line_filter.frame", "phone"),
]
after = [before[0], before[2]]  # unregister("phone"): two NON-contiguous bindings removed
print("plan rule :")
[print("  ", o) for o in plan_ops(before, after)]
print("LCS opcodes:")
[print("  ", o) for o in lcs_ops(before, after)]
# duplicates: [A,B,A,B] delete idx1
A, B = {"k": "A"}, {"k": "B"}
print("dup [A,B,A,B]->[A,A,B] plan:", plan_ops([A, B, A, B], [A, A, B]))
