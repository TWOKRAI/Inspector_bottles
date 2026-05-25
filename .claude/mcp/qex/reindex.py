#!/usr/bin/env python3
"""Переиндексация qex с увеличенным timeout.

MCP-вызов index_codebase таймаутит на больших проектах (2000+ файлов,
30-60 мин на embedding). Этот скрипт запускает qex как subprocess,
отправляет JSON-RPC запрос на индексацию и ждёт без лимита.

Запуск:
    python .claude/mcp/qex/reindex.py                # инкрементальная
    python .claude/mcp/qex/reindex.py --force         # полная (30-60 мин)
    python .claude/mcp/qex/reindex.py --clear --force  # очистка + полная
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Пути (аналогично qex-launcher.py) ──────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent  # .claude/mcp/qex
MCP_DIR = SCRIPT_DIR.parent  # .claude/mcp
PROJECT_ROOT = MCP_DIR.parent.parent  # корень проекта

IS_WIN = platform.system() == "Windows"

if IS_WIN:
    model = "qwen3-embedding:4b"
    dimensions = "2560"
    default_bin = Path.home() / ".cargo" / "bin" / "qex.exe"
else:
    model = "qwen3-embedding:8b"
    dimensions = "4096"
    default_bin = Path.home() / ".local" / "bin" / "qex"

qex_bin = os.environ.get("QEX_BIN") or shutil.which("qex") or str(default_bin)

env = {
    **os.environ,
    "RUST_LOG": "info",
    "WORKSPACE_PATH": str(PROJECT_ROOT),
    "QEX_EMBEDDING_PROVIDER": "openai",
    "QEX_OPENAI_BASE_URL": "http://localhost:11434/v1",
    "QEX_OPENAI_API_KEY": "ollama",
    "QEX_OPENAI_MODEL": model,
    "QEX_OPENAI_DIMENSIONS": dimensions,
}


def jsonrpc_request(method: str, params: dict, req_id: int = 1) -> str:
    """Формирует JSON-RPC 2.0 запрос."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": method,
                "arguments": params,
            },
        }
    )


def run_qex_rpc(method: str, params: dict) -> dict | None:
    """Запускает qex как stdio MCP-сервер, отправляет запрос, ждёт ответ.

    Важно: stdin остаётся открытым пока не получим ответ на tool call,
    иначе qex MCP-сервер увидит EOF и завершится до окончания индексации.
    """
    import threading

    init_request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "qex-reindex-script", "version": "1.0.0"},
            },
        }
    )
    init_notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
    )
    tool_call = jsonrpc_request(method, params, req_id=1)

    print(f"Запуск: {qex_bin}")
    print(f"Проект: {PROJECT_ROOT}")
    print(f"Метод: {method}")
    print(f"Параметры: {json.dumps(params, ensure_ascii=False)}")
    print(f"Модель: {model} ({dimensions}-dim)")
    print("Ожидание ответа (может занять 30-60 мин)...\n")

    proc = subprocess.Popen(
        [str(qex_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )

    # Стримим stderr в реальном времени (логи qex)
    def stream_stderr():
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                print(f"  [qex] {line}", flush=True)

    stderr_thread = threading.Thread(target=stream_stderr, daemon=True)
    stderr_thread.start()

    # Отправляем сообщения по одному, держим stdin открытым
    proc.stdin.write(init_request + "\n")
    proc.stdin.flush()
    proc.stdin.write(init_notification + "\n")
    proc.stdin.flush()
    proc.stdin.write(tool_call + "\n")
    proc.stdin.flush()

    # Читаем stdout построчно — ждём ответ на id=1
    result = None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("id") == 1:
                if "error" in msg:
                    print(f"\nОшибка: {msg['error']}")
                    result = None
                else:
                    result = msg.get("result")
                break
            # id=0 — ответ на initialize, пропускаем
        except json.JSONDecodeError:
            continue

    # Получили ответ — закрываем stdin, ждём завершения
    proc.stdin.close()
    proc.wait()
    stderr_thread.join(timeout=2)

    if result is None and proc.returncode != 0:
        print(f"\nНе получен ответ. Exit code: {proc.returncode}")

    return result


def check_ollama() -> bool:
    """Проверяет что Ollama работает."""
    try:
        import urllib.request

        resp = urllib.request.urlopen("http://localhost:11434/", timeout=3)
        return b"running" in resp.read().lower() or resp.status == 200
    except Exception:
        return False


def main():
    force = "--force" in sys.argv
    clear = "--clear" in sys.argv
    project_path = str(PROJECT_ROOT)

    # Проверяем Ollama
    if not check_ollama():
        print("ОШИБКА: Ollama не запущен!")
        print("Запусти: ollama serve")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"qex reindex — {'полная' if force else 'инкрементальная'}")
    print(f"{'=' * 60}\n")

    # Очистка индекса
    if clear:
        print("Очистка индекса...")
        result = run_qex_rpc("clear_index", {"path": project_path})
        if result:
            print("Индекс очищен.\n")
        else:
            print("Не удалось очистить (возможно уже чист).\n")

    # Индексация
    params = {"path": project_path}
    if force:
        params["force"] = True

    result = run_qex_rpc("index_codebase", params)

    if result:
        print("\nГотово!")
        # Попробуем вытащить текст результата
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and "text" in item:
                print(item["text"])
    else:
        print("\nИндексация не удалась. Проверь логи выше.")
        sys.exit(1)

    # Статус
    print("\nПроверка статуса...")
    status = run_qex_rpc("get_indexing_status", {"path": project_path})
    if status:
        content = status.get("content", [])
        for item in content:
            if isinstance(item, dict) and "text" in item:
                print(item["text"])


if __name__ == "__main__":
    main()
