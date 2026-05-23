#!/usr/bin/env python3
"""qex MCP launcher — определяет платформу и запускает qex с нужной моделью.

Расположение: .claude/mcp/qex-launcher.py
Корень проекта вычисляется через realpath (работает и через симлинк).

Побочные эффекты (оба idempotent):
1) Копирует .claude/mcp/qex/templates/ignore.template → <workspace>/.ignore —
   whitelist для qex semantic index при первом запуске.
2) Проверяет что embedding-модель в ollama имеет правильный num_ctx (Win=2048,
   Mac=4096). Если нет — пишет в stderr подсказку запустить setup-скрипт:
       bash .claude/mcp/qex/setup-embedding-model.sh
   (или .ps1 на Win без Git Bash). Setup создаёт Modelfile-вариант с явным
   num_ctx + num_gpu=999 → embedding инференс идёт на 100% GPU.

Почему это важно: ollama по умолчанию читает num_ctx из OLLAMA_CONTEXT_LENGTH
env. Если переменная не установлена или слишком большая — embedding-модель
раздувается через KV cache, не помещается в VRAM ноутбучных GPU и CPU-offload
вызывает MCP-таймауты на индексации больших репо.
"""

import json
import os
import sys
import platform
import shutil
import subprocess
import urllib.error
import urllib.request

# realpath разрешает симлинк (scripts/qex-launcher.py -> .claude/mcp/qex-launcher.py)
_script_dir = os.path.dirname(os.path.realpath(__file__))
# .claude/mcp/qex-launcher.py → корень проекта = два уровня вверх
workspace = os.path.dirname(os.path.dirname(_script_dir))

# ── .ignore: создать из template при первом запуске qex (idempotent) ─────────
_ignore_target = os.path.join(workspace, ".ignore")
_ignore_template = os.path.join(_script_dir, "qex", "templates", "ignore.template")
if not os.path.exists(_ignore_target) and os.path.exists(_ignore_template):
    try:
        shutil.copy2(_ignore_template, _ignore_target)
        # stderr — чтобы Claude Code увидел в логах MCP-сервера, но не сломал JSON-RPC
        print(
            f"[qex-launcher] Created {_ignore_target} from template. "
            "Edit it to whitelist only active development directories.",
            file=sys.stderr,
        )
    except OSError as e:
        print(f"[qex-launcher] Failed to seed .ignore: {e}", file=sys.stderr)

if platform.system() == "Windows":
    base_url = "http://localhost:11434/v1"
    api_key = "ollama"
    model = "qwen3-embedding:4b"
    dimensions = "2560"
    expected_num_ctx = 2048  # см. setup-embedding-model.sh — Win 4b → 2048
    default_bin = os.path.join(os.path.expanduser("~"), ".cargo", "bin", "qex.exe")
else:
    # macOS: Ollama (qwen3-embedding:8b, dim=4096) на :11434 (GUI Ollama.app).
    # Эксперименты 2026-05-10:
    # - mlx-openai-server :1235 → 2.5× медленнее (single inference worker).
    # - OLLAMA_NUM_PARALLEL=4 на CLI Ollama → 0% эффекта (Metal не масштабируется
    #   по parallel calls на одну модель; Ollama embedding-runner грузится с Parallel:1
    #   независимо от env). См. handoff 2026-05-10.
    base_url = "http://localhost:11434/v1"
    api_key = "ollama"
    model = "qwen3-embedding:8b"
    dimensions = "4096"
    expected_num_ctx = 4096  # см. setup-embedding-model.sh — Mac 8b → 4096
    default_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "qex")


# ── health-check ollama embedding-модели (idempotent, non-blocking) ──────────
# Если модель загружена с раздутым контекстом (например 32768 по дефолту) — она
# не помещается в VRAM, идёт на CPU и MCP таймаутит при индексации. Не блокируем
# запуск qex, только подсказываем как починить.
def _check_embedding_model_health() -> None:
    ollama_base = base_url.rsplit("/v1", 1)[0]
    try:
        req = urllib.request.Request(
            f"{ollama_base}/api/show",
            method="POST",
            data=json.dumps({"name": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            info = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return  # ollama недоступна — qex сам напишет понятную ошибку при первом запросе
    actual_ctx = info.get("parameters", "")
    if isinstance(actual_ctx, str) and "num_ctx" in actual_ctx:
        try:
            actual = int(actual_ctx.split("num_ctx")[1].strip().split()[0])
        except (IndexError, ValueError):
            return
        if actual != expected_num_ctx:
            setup = os.path.join(_script_dir, "qex", "setup-embedding-model.sh")
            print(
                f"[qex-launcher] WARN: модель {model} имеет num_ctx={actual}, "
                f"ожидается {expected_num_ctx}. Это вызывает CPU-offload и MCP "
                f"таймауты. Запусти setup: bash '{setup}'  (или .ps1 на Win)",
                file=sys.stderr,
            )


_check_embedding_model_health()

qex_bin = os.environ.get("QEX_BIN") or shutil.which("qex") or default_bin

env = {
    **os.environ,
    "RUST_LOG": "info",
    "WORKSPACE_PATH": workspace,
    "QEX_EMBEDDING_PROVIDER": "openai",
    "QEX_OPENAI_BASE_URL": base_url,
    "QEX_OPENAI_API_KEY": api_key,
    "QEX_OPENAI_MODEL": model,
    "QEX_OPENAI_DIMENSIONS": dimensions,
}

result = subprocess.run([qex_bin] + sys.argv[1:], env=env)
sys.exit(result.returncode)
