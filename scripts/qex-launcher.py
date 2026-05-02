#!/usr/bin/env python3
"""qex MCP launcher — определяет платформу и запускает qex с нужной моделью."""
import os
import sys
import platform
import shutil
import subprocess

_script_dir = os.path.dirname(os.path.abspath(__file__))
workspace = os.path.dirname(_script_dir)  # корень проекта

if platform.system() == "Windows":
    model = "qwen3-embedding:4b"
    dimensions = "2560"
    default_bin = os.path.join(os.path.expanduser("~"), ".cargo", "bin", "qex.exe")
else:
    model = "qwen3-embedding:8b"
    dimensions = "4096"
    default_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "qex")

qex_bin = os.environ.get("QEX_BIN") or shutil.which("qex") or default_bin

env = {
    **os.environ,
    "RUST_LOG": "info",
    "WORKSPACE_PATH": workspace,
    "QEX_EMBEDDING_PROVIDER": "openai",
    "QEX_OPENAI_BASE_URL": "http://localhost:11434/v1",
    "QEX_OPENAI_API_KEY": "ollama",
    "QEX_OPENAI_MODEL": model,
    "QEX_OPENAI_DIMENSIONS": dimensions,
}

result = subprocess.run([qex_bin] + sys.argv[1:], env=env)
sys.exit(result.returncode)
