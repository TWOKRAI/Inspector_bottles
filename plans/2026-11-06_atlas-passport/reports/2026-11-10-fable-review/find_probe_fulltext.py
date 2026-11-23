"""Проба «найти файл по описанию задачи»: SQLite FTS5 (BM25) по пути, именам верхнего уровня и первым строкам.
Без модели и без эмбеддингов. Набор r1, дерево на repo_sha набора (git show), пути exclude набора не индексируются."""
import ast, json, re, sqlite3, subprocess, sys, time
qs = json.load(open("scripts/nav_bench/questions/r1.json")); sha = qs["repo_sha"]; excl = tuple(qs["exclude"])
t0 = time.time()
paths = subprocess.run(["git", "ls-tree", "-r", "--name-only", sha], capture_output=True, text=True).stdout.split("\n")
TEXT = (".py", ".md", ".toml", ".yaml", ".yml", ".sh", ".cfg", ".ini", ".txt", ".json", ".gitmessage")
paths = [p for p in paths if p and not p.startswith(excl) and (p.endswith(TEXT) or "/" not in p and p.startswith("."))]
split = lambda s: " ".join(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).replace("_", " ").replace("/", " ").replace(".", " ").replace("-", " ").split())
proc = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
def blob(p):
    proc.stdin.write(f"{sha}:{p}\n".encode()); proc.stdin.flush()
    head = proc.stdout.readline().split()
    if len(head) < 3: return ""
    data = proc.stdout.read(int(head[2])); proc.stdout.read(1)
    return data.decode("utf-8", "replace") if int(head[2]) < 600_000 else ""
con = sqlite3.connect(":memory:")
con.execute("create virtual table f using fts5(path, words, names, doc, tokenize='porter unicode61')")
n = 0
for p in paths:
    src = blob(p); names = doc = ""
    if p.endswith(".py"):
        try:
            tree = ast.parse(src)
            doc = (ast.get_docstring(tree) or "")[:400]
            top = []
            for b in tree.body:
                if isinstance(b, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)): top.append(b.name)
                elif isinstance(b, (ast.Assign, ast.AnnAssign)):
                    for tg in (b.targets if isinstance(b, ast.Assign) else [b.target]):
                        if isinstance(tg, ast.Name): top.append(tg.id)
            names = split(" ".join(top))
        except SyntaxError: pass
    else:
        lines = src.splitlines()
        heads = [l for l in lines if l.startswith("#") or (p.endswith(".toml") and l.startswith("["))][:40]
        doc = src[:30000]; names = split(" ".join(heads))[:1500]
    con.execute("insert into f values (?,?,?,?)", (p, split(p), names, doc)); n += 1
build = time.time() - t0
STOP = set("the a an of to in is are be and or for that which what where when must with by on at as it its this into from not no does do how each one two three all also should currently instead their they them there than then both between about only such so if any can will has have new old own out over under more most other some same would could per up down who whom whose while after before these those been being was were may might via".split())
hits = 0; rows = []
for q in qs["questions"]:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", q["question"].lower()) if w not in STOP]
    query = " OR ".join(dict.fromkeys(words))
    t1 = time.time()
    res = [r[0] for r in con.execute("select path from f where f match ? order by bm25(f, 4.0, 4.0, 3.0, 1.0) limit 50", (query,))]
    dt = time.time() - t1
    want = list(dict.fromkeys(e["path"] for e in q["expected"]))
    ranks = [(res.index(w) + 1 if w in res else None) for w in want]
    ok5 = all(r is not None and r <= 5 for r in ranks); ok10 = all(r is not None and r <= 10 for r in ranks); hits += ok5
    rows.append((q["id"], ranks, ok5, ok10, res[:3], dt))
print(f"индекс: {n} файлов за {build:.1f} с")
for qid, ranks, ok5, ok10, top3, dt in rows:
    print(f"{qid}: места нужных файлов {ranks}  все в первых 5: {'да' if ok5 else 'нет'}; в первых 10: {'да' if ok10 else 'нет'}  ({dt*1000:.0f} мс)")
    print("     первые 3:", [t.split('/')[-1] if len(t) > 48 else t for t in top3])
print(f"вопросов, где ВСЕ нужные файлы в первых 5: {hits} из {len(rows)}")
