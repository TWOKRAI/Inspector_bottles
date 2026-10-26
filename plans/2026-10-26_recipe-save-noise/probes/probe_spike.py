# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import io
import difflib
import sys
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.tokens import CommentToken
from multiprocess_framework.modules.recipe.yaml_io import _make_yaml

y = _make_yaml()


def dump(d):
    b = io.StringIO()
    y.dump(d, b)
    return b.getvalue()


def _tail(node):
    """(container, key) holding the comment after node's deepest last leaf, or None."""
    while True:
        if isinstance(node, CommentedMap) and len(node):
            k = list(node)[-1]
            v = node[k]
            if isinstance(v, (CommentedMap, CommentedSeq)) and len(v):
                node = v
                continue
            return node, k, 2
        if isinstance(node, CommentedSeq) and len(node):
            i = len(node) - 1
            v = node[i]
            if isinstance(v, (CommentedMap, CommentedSeq)) and len(v):
                node = v
                continue
            return node, i, 0
        return None


def delete_keep_next_comment(container, key):
    """del container[key]; comment lines after the deleted item's last leaf (they head the NEXT sibling) move to the previous sibling's tail."""
    keys = list(container) if isinstance(container, CommentedMap) else list(range(len(container)))
    pos = keys.index(key)
    gone = (
        _tail(container[key])
        if isinstance(container[key], (CommentedMap, CommentedSeq))
        else (container, key, 2 if isinstance(container, CommentedMap) else 0)
    )
    tok = None
    if gone:
        c, k, slot = gone
        t = c.ca.items.get(k)
        tok = t[slot] if t else None
    # keep only full-line comments (drop the deleted leaf's own EOL comment)
    text = tok.value if tok is not None else ""
    keep = text[text.index("\n") :] if text.startswith("#") and "\n" in text else ("" if text.startswith("#") else text)
    del container[key]
    if not keep.strip() or pos == 0:
        return bool(keep.strip())  # nothing to move / no previous sibling (first item: needs parent-comment handling)
    prev = container[keys[pos - 1]] if isinstance(container, CommentedMap) else container[pos - 1]
    tgt = (
        _tail(prev)
        if isinstance(prev, (CommentedMap, CommentedSeq))
        else (container, keys[pos - 1], 2 if isinstance(container, CommentedMap) else 0)
    )
    c, k, slot = tgt
    slots = c.ca.items.setdefault(k, [None, None, None, None])
    old = slots[slot]
    slots[slot] = (
        CommentToken((old.value if old is not None else "") + keep, tok.start_mark, None)
        if old is not None or tok is not None
        else None
    )
    return True


SYN = open(sys.argv[1], encoding="utf-8").read()
for i in (1, 2):
    doc = y.load(SYN)
    delete_keep_next_comment(doc["procs"], i)
    out = dump(doc)
    print(f"--- delete procs[{i}] with transfer ---")
    print(
        "\n".join(
            l
            for l in difflib.unified_diff(SYN.splitlines(), out.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))
        )
    )
FX = open(sys.argv[2], encoding="utf-8").read()
doc = y.load(FX)
delete_keep_next_comment(doc["blueprint"]["processes"][2], "protected")
out = dump(doc)
print("--- delete camera_0.protected with transfer ---")
print(
    "\n".join(
        l
        for l in difflib.unified_diff(FX.splitlines(), out.splitlines(), lineterm="", n=0)
        if l[:1] in "+-" and not l.startswith(("+++", "---"))
    )
)
