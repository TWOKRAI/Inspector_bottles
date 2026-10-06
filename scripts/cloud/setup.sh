#!/usr/bin/env bash
# Подготовка облачного окружения Claude Code (claude.ai/code) для Inspector_bottles.
# Образ облака — Ubuntu 24.04; шаги повторяют job CI `tests` (.github/workflows/ci.yml), который зелёный на Linux.
# Вызов: setup script окружения в UI — `bash scripts/cloud/setup.sh` (из корня клона).
# Переменная QT_QPA_PLATFORM=offscreen задаётся в настройках окружения UI: export отсюда в сессию не доходит.
# План и правила облака: plans/2026-10-04_atlas/CLOUD.md.
set -euo pipefail

SUDO="$(command -v sudo || true)"

# Qt offscreen: те же системные библиотеки, что в CI.
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq --no-install-recommends libegl1 libgl1 libxkbcommon0 libdbus-1-3

# uv: в образе не гарантирован; системный pip Ubuntu 24.04 закрыт PEP 668.
if ! command -v uv >/dev/null 2>&1; then
    python3 -m pip install --user --quiet --break-system-packages uv
    export PATH="$HOME/.local/bin:$PATH"
fi

# Окружение проекта по uv.lock — как `uv sync` в CI (Python 3.12, без extras).
uv sync

# Инструменты пилота P1.1: граф кода (mcp вшит, см. docs/claude/memory/project_graphify_mcp_setup.md).
uv tool install graphifyy --with mcp --quiet || echo "graphify: install failed (P1.1 записывает это как результат)"

uv run python --version
echo "cloud setup: ok"
