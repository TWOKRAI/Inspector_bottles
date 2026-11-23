"""Проба: находит ли pyright-langserver ссылки, которые паспорт пропускает. Только чтение."""
import json, os, subprocess, sys, time, threading, queue, pathlib
root = pathlib.Path.cwd()
p = subprocess.Popen([str(root/".venv/bin/pyright-langserver"), "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
q = queue.Queue()
def reader():
    while True:
        h = b""
        while not h.endswith(b"\r\n\r\n"):
            c = p.stdout.read(1)
            if not c: q.put(None); return
            h += c
        n = int([l for l in h.decode().split("\r\n") if l.lower().startswith("content-length")][0].split(":")[1])
        q.put(json.loads(p.stdout.read(n)))
threading.Thread(target=reader, daemon=True).start()
def send(o):
    b = json.dumps(o).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush()
_id = 0
def request(method, params, deadline=150):
    global _id; _id += 1; mid = _id
    send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
    t0 = time.time()
    while time.time() - t0 < deadline:
        try: m = q.get(timeout=1)
        except queue.Empty: continue
        if m is None: raise RuntimeError("сервер закрылся")
        if "method" in m and "id" in m:   # запрос сервера к клиенту
            res = [None] * len(m["params"].get("items", [])) if m["method"] == "workspace/configuration" else None
            send({"jsonrpc": "2.0", "id": m["id"], "result": res}); continue
        if m.get("id") == mid: return m.get("result"), time.time() - t0
    raise TimeoutError(method)
uri = lambda path: (root/path).as_uri()
request("initialize", {"processId": os.getpid(), "rootUri": root.as_uri(), "capabilities": {}, "workspaceFolders": [{"uri": root.as_uri(), "name": "repo"}]})
send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
# ждём, пока сервер найдёт файлы проекта; печатаем его журнал
t0 = time.time(); ready = False
while time.time() - t0 < 120 and not ready:
    try: m = q.get(timeout=1)
    except queue.Empty: continue
    if m is None: break
    if "method" in m and "id" in m:
        res = [None] * len(m["params"].get("items", [])) if m["method"] == "workspace/configuration" else None
        send({"jsonrpc": "2.0", "id": m["id"], "result": res}); continue
    if m.get("method") == "window/logMessage":
        msg = m["params"]["message"]; print("  [server]", msg[:150])
        if "source file" in msg.lower() and "found" in msg.lower(): ready = True
print(f"готовность сервера: {ready}, {time.time()-t0:.1f} с")
def refs(path, name, label, want):
    lines = open(path, encoding="utf-8").read().splitlines()
    ln = next(i for i, l in enumerate(lines) if l.lstrip().startswith(("class " + name, "def " + name)))
    col = lines[ln].find(name)
    send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri(path), "languageId": "python", "version": 1, "text": "\n".join(lines) + "\n"}}})
    try:
        res, dt = request("textDocument/references", {"textDocument": {"uri": uri(path)}, "position": {"line": ln, "character": col + 1}, "context": {"includeDeclaration": False}})
    except Exception as e:
        print(f"{label}: {type(e).__name__} {e}"); return
    got = sorted({(r["uri"].replace(root.as_uri() + "/", ""), r["range"]["start"]["line"] + 1) for r in (res or [])})
    prod = [g for g in got if "/tests/" not in g[0] and not g[0].split("/")[-1].startswith("test_")]
    print(f"{label}: {len(got)} ссылок за {dt:.1f} с; из продукта {len(prod)}")
    for w in want:
        print(f"   {w[0].split('/')[-1]}:{w[1]} найдено: {'ДА' if any(g[0].endswith(w[0]) and abs(g[1]-w[1])<=1 for g in got) else 'нет'}")
    return prod
refs("multiprocess_framework/modules/router_module/core/router_manager.py", "RouterManager", "pyright RouterManager", [("process_module/managers/process_managers.py", 356)])
refs("multiprocess_framework/modules/process_module/core/process_module.py", "ProcessModule", "pyright ProcessModule", [("process_manager_module/process/process_manager_process.py", 105)])
refs("multiprocess_framework/modules/chain_module/interfaces.py", "execute_remote", "pyright IRemoteExecutable.execute_remote", [("chain_module/core/chain.py", 72), ("chain_module/core/dag.py", 99), ("chain_module/core/parallel.py", 113)])
refs("multiprocess_framework/modules/config_module/tools/watcher.py", "start", "pyright ConfigFileWatcher.start (паспорт: unresolved 1612)", [])
p.kill()
