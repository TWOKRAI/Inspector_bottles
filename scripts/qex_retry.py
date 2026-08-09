"""Повторяет инкрементальную индексацию qex, пока она не пройдёт целиком.

Батч эмбеддингов у qex стоит 8-10 с при зашитом таймауте ~10 с — попадание
впритык, поэтому один прогон почти всегда падает на каком-то батче. Прогресс
между прогонами сохраняется (проверено: chunk_count 86918 -> 89404 после
упавшего прогона), поэтому повтор двигает дело вперёд.
"""

import json
import os
import subprocess
import sys
import time

PROJECT = r"d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles"
MAX_ATTEMPTS = 12


def rpc(proc, method, params, req_id):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == req_id:
            return msg


#: Куда складывать stderr бинаря qex (RUST_LOG его наполняет). Раньше здесь стоял
#: DEVNULL — и 15 отказов подряд 2026-08-03 показали только вердикт обёртки
#: «timeout» без единой подробности, тогда как причина называется именно тут.
#: Свой файл на попытку: иначе следующая затрёт лог упавшей.
LOG_DIR = os.path.join(PROJECT, "logs", "qex_reindex")


def attempt(n):
    os.makedirs(LOG_DIR, exist_ok=True)
    err = open(os.path.join(LOG_DIR, f"attempt_{n:02d}.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        ["uv", "run", "--no-sync", "--", "python", ".claude/plugins/mcp-qex/qex-launcher.py"],
        cwd=PROJECT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        rpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "qex-retry", "version": "1"},
            },
            1,
        )
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        reply = rpc(
            proc,
            "tools/call",
            {
                "name": "index_codebase",
                "arguments": {"path": PROJECT},
            },
            2,
        )
        return reply
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=30)
        err.close()


for i in range(1, MAX_ATTEMPTS + 1):
    started = time.time()
    reply = attempt(i)
    took = time.time() - started
    if reply is None:
        print(f"[{i}] сервер закрылся молча за {took:.0f} с", flush=True)
        continue
    if "error" in reply:
        print(f"[{i}] {took:.0f} с — {reply['error'].get('message')}", flush=True)
        continue
    text = json.dumps(reply.get("result", {}), ensure_ascii=False)[:400]
    print(f"[{i}] УСПЕХ за {took:.0f} с: {text}", flush=True)
    sys.exit(0)

print("исчерпаны попытки", flush=True)
sys.exit(1)
