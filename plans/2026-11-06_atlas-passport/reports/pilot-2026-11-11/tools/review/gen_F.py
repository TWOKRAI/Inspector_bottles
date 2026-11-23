"""Fixture F of 4.7-cases.md, built literally from the stated line numbers (reviewer scratch)."""
import subprocess, sys
from pathlib import Path

root = Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)

def lines(spec: dict[int, str], total: int) -> str:
    out = ["    pass" if False else "" for _ in range(total)]
    for n, t in spec.items():
        out[n - 1] = t
    return "\n".join(out) + "\n"

def fill(spec, total):
    # unspecified lines: body 'pass' with indentation of previous header +4 (just use '        pass' safe where needed)
    out = [None] * total
    for n, t in spec.items():
        out[n - 1] = t
    res = []
    for i, t in enumerate(out):
        res.append(t if t is not None else "")
    return "\n".join(res) + "\n"

a = {
 1: "class Driver:",
 2: "    def stop(self):",
 3: "        pass",
 4: "    def run(self):",
 5: "        pass",
 7: "def outer():",
 8: "    def _pick():",
 9: "        pass",
 10: "    return _pick",
 12: "class A:",
 13: "    def b(self):",
 14: "        def _pick():",
 15: "            pass",
 16: "        return _pick",
 17: "    class B:",
 18: "        def c(self):",
 19: "            def deep():",
 20: "                pass",
 21: "            return deep",
 23: "LIMIT = 3",
 24: "class Schema:",
 25: '    KIND = "k"',
 26: "def dup():",
 27: "    pass",
 28: "if LIMIT:",
 29: "    def twice():",
 30: "        pass",
 31: "else:",
 32: "    def twice():",
 33: "        pass",
 34: "MODE = 1",
 36: "class Schema2:",
 37: "    NOTE = 1",
}
files = {
 "pkg/a.py": fill(a, 37),
 "pkg/b.py": "def dup():\n    pass\n\ndef helper():\n    pass\n",
 "lib/c.py": "def dup():\n    pass\n\n\nclass Holder:\n    def MODE(self):\n        pass\n\ndef run():\n    pass\n    def NOTE(self):\n        pass\n",
 "z/m.py": "def zf():\n    pass\n",
 "pkg/tests/test_a.py": "def dup():\n    pass\n\nclass Driver:\n    def stop(self):\n        pass\n",
 "pkg/tests/test_b.py": "def only_test():\n    pass\n\n\n\ndef helper():\n    pass\n",
}
for rel, text in files.items():
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
rows = [("pkg","pkg/"),("lib","lib/"),("tools/z","z/"),("p2","o/"),("q","p2/"),("deep/a","deep/a/"),("deep/b","deep/b/")]
(root / "modules.yaml").write_text('version: 1\nroots: []\nmodules:\n' + "".join(
  f'  - id: {i}\n    paths: ["{p}"]\n    layer: framework\n    tier: null\n    docs: []\n    parent: null\n    purpose: "P {i}."\n' for i, p in rows))
for d in ("o","p2","deep/a","deep/b"):
    (root/d).mkdir(parents=True, exist_ok=True); (root/d/"x.py").write_text("def x():\n    pass\n")
def g(*a): subprocess.run(["git","-C",str(root),*a],check=True,capture_output=True)
g("init","-q"); g("config","user.email","r@r"); g("config","user.name","r"); g("config","core.autocrlf","false")
g("add","-A"); g("commit","-q","-m","F")
print("built", root)
