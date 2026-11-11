import importlib.util, sys, json
S="/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/rev_r1/"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
old = load("score_old_r1", S+"score_old_r1.py")
new = load("score_new_r1", "/Users/twokrai/Project_code/Inspector_bottles/scripts/nav_bench/score.py")
inputs = [
 "a.py:12-", "a:1:b:2", "see a.py:12 and b.py:30", "a.py:12, b.py", "a.py:12:5,20-25", "path with space/a b.py:12",
 "./a.py:5", "a.py:5.", "a.py:5)", "`a.py:5`", "[x](a.py#L5)", "a.py#L5-L9", "a.py#L5", "C:\\x\\a.py:12:3", "C:\\x\\a.py:12",
 "файл/модуль.py:7", "a.py:12-15,20", "a.py:12–15", "a.py:52,289-327,411-496", "a.py:10-5", "a.py (line 5)", "a.py:5 (func)",
 "a.py line 5", "a.py:L5", "a.py:5-L9", "a.py, line 12", "a.py:5,", "a.py:5;", "a.py:5, b.py:6", "a.py:5/b.py:6",
 "a.py:5-9:3", "src/a.py:12 (class Foo)", "a.py:12-15 and a.py:30-31", "a.py:12 / a.py:40", "a.py:1234567890123", "a.py:0",
 "https://x.com/a.py:12", "a.py:12:3:4", "pkg.mod.func:12", "a.py:5\u00a0", "a.py:５", "a.py::12", "a.py:12::", "foo::bar:12",
 "a.py:5:", "a.py:5:x", "a.py: 5", "a.py :5", "a.py:5 - 9", "a.py:5 -9", "a.py:5~9", "a.py:5..9", "a.py:5…9", "a.py:5 to 9", "a.py:5-9,",
 "a.py:5,\n6", "a.py:5, 6, 7", "a.py:5 6 7", "a.py:5 ,6", "a.py:5;6", "a.py:5 b.py:7", "a.py#L5-L9", "a.py:(5)", "a.py:[5]", "(a.py:5)", "'a.py':5",
 "a.py:5-", "a.py:-5", "a.py:5--9", "a.py:5-9-12", "a.py:5-9-", "a.py:5,-9", "a.py:5,,9", "dir/a.py:5,dir/b.py:7",
 "a.py:5, dir/b.py:7", "a.py:5, 7 dir/b.py:8",
]
def show(m, t):
    try:
        if hasattr(m, "parse_claims"):
            return m.parse_claims(t)
        return [m.parse_location_range(t)]
    except Exception as e:
        return f"EXC {e!r}"
for t in inputs:
    o = [old.parse_location_range(t)]
    n = show(new, t)
    mark = "" if (len(n)==1 and tuple(n[0])==o[0]) else "  <<< DIFF"
    print(f"{t!r:45} old={o[0]}  new={n}{mark}")
