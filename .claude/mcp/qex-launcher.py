#!/usr/bin/env python3
"""qex MCP launcher — определяет платформу и запускает qex с нужной моделью.

Расположение: .claude/mcp/qex-launcher.py
Корень проекта вычисляется через realpath (работает и через симлинк).
"""
import os
import sys
import platform
import shutil
import subprocess

# realpath разрешает симлинк (scripts/qex-launcher.py -> .claude/mcp/qex-launcher.py)
_script_dir = os.path.dirname(os.path.realpath(__file__))
# .claude/mcp/qex-launcher.py → корень проекта = два уровня вверх
workspace = os.path.dirname(os.path.dirname(_script_dir))

if platform.system() == "Windows":
    base_url = "http://localhost:11434/v1"
    api_key = "ollama"
    model = "qwen3-embedding:4b"
    dimensions = "2560"
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
    default_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "qex")

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
