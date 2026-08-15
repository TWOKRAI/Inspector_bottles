#!/usr/bin/env python3
"""kos MCP launcher — находит движок KnowledgeOS и запускает его MCP-сервер.

Расположение (две байт-в-байт копии):
  - knowledge-apps/launcher/kos_mcp_launcher.py   — канон в репо движка
  - <plugin>/kos_mcp_launcher.py                  — user-level плагин knowledge

Зачем launcher, а не ${ENV} прямо в .mcp.json: переменные окружения в JSON-конфиге
MCP ненадёжны (GUI-приложение Claude Code не наследует shell-env; разные версии CC
по-разному раскрывают ${VAR}). Поэтому в .mcp.json — только надёжный
${CLAUDE_PLUGIN_ROOT}, а KOS_* резолвятся здесь, в Python, с явным fallback.

Связка cross-machine (Win <-> Mac) держится на ДВУХ путях:
  KOS_HOME            — корень репо движка (knowledge-apps): venv + src/apps/
  KOS_KNOWLEDGE_ROOT  — корень базы знаний (knowledge-base): куда читать/писать

Резолв каждого: переменная окружения -> ~/.kos/launcher.json -> внятная ошибка.
На новой машине достаточно ОДИН раз прописать env (setx на Win / export в profile
на Mac) ЛИБО положить ~/.kos/launcher.json — код не трогается. Платформа не важна:
`uv` сам поднимает нужный per-platform venv по universal uv.lock (CUDA на Win,
MPS/MLX на Mac).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Опциональные переменные, которые пробрасываем в окружение MCP-сервера, если заданы.
_OPTIONAL_VARS = ("KOS_KNOWLEDGE_ROOT", "KOS_MODELS_DIR")


def _load_launcher_json() -> dict[str, str]:
    """~/.kos/launcher.json — per-machine fallback для KOS_* (когда env не задан)."""
    cfg = Path.home() / ".kos" / "launcher.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (ValueError, OSError) as exc:
            print(f"[kos-launcher] WARN: не смог прочитать {cfg}: {exc}", file=sys.stderr)
    return {}


_FALLBACK = _load_launcher_json()


def _resolve(var: str) -> str | None:
    """env -> ~/.kos/launcher.json -> None. Раскрывает ~ в путях."""
    val = os.environ.get(var) or _FALLBACK.get(var)
    return os.path.expanduser(val) if val else None


def _resolve_kb_sibling(kos_home_dir: str | None) -> str | None:
    """Авто-резолв канона, если KOS_KNOWLEDGE_ROOT не задан явно.

    Пробуем соседний репозиторий `knowledge-base/` (рядом с движком KOS_HOME
    или с текущим проектом). Канон подтверждается наличием `wiki/` — та же
    логика, что в apps/core/config.py и apps/video_analyzer/organizer.py.
    """
    bases: list[Path] = []
    if kos_home_dir:
        bases.append(Path(kos_home_dir).parent)
    bases.extend((Path.cwd(), Path.cwd().parent))
    for base in bases:
        cand = base / "knowledge-base"
        if (cand / "wiki").is_dir():
            return str(cand)
    return None


def _fail(msg: str) -> "None":
    print(f"[kos-launcher] ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


# ── KOS_HOME (обязателен) ────────────────────────────────────────────────────
kos_home = _resolve("KOS_HOME")
if not kos_home:
    _fail(
        "KOS_HOME не задана. Укажи корень репо движка через env "
        "(setx KOS_HOME <путь> на Win / export KOS_HOME=<путь> в profile на Mac) "
        f"ЛИБО добавь в {Path.home() / '.kos' / 'launcher.json'}: "
        '{"KOS_HOME": "<путь к knowledge-apps>"}.'
    )
if not Path(kos_home).is_dir():
    _fail(f"KOS_HOME указывает на несуществующий каталог: {kos_home}")

# ── uv: env UV_BIN -> PATH -> платформенный дефолт ───────────────────────────
if sys.platform == "win32":
    _uv_default = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe")
else:
    _uv_default = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")
uv_bin = os.environ.get("UV_BIN") or shutil.which("uv") or _uv_default

# ── Окружение для сервера: пробрасываем заданные KOS_* (env > json) ───────────
env = {**os.environ}
for _var in _OPTIONAL_VARS:
    _val = _resolve(_var)
    if _val:
        env[_var] = _val

if "KOS_KNOWLEDGE_ROOT" not in env:
    _sibling = _resolve_kb_sibling(kos_home)
    if _sibling:
        env["KOS_KNOWLEDGE_ROOT"] = _sibling
        print(
            "[kos-launcher] KOS_KNOWLEDGE_ROOT не задана — авто-резолв соседнего "
            f"knowledge-base: {_sibling}",
            file=sys.stderr,
        )
    else:
        # Не фатально: config.py упадёт на file-relative knowledge/, но из чужого
        # проекта это почти наверняка не то, что нужно — предупреждаем явно.
        print(
            "[kos-launcher] WARN: KOS_KNOWLEDGE_ROOT не задана и соседний "
            "knowledge-base/ не найден — сервер будет искать базу относительно "
            "движка. Задай env или ~/.kos/launcher.json.",
            file=sys.stderr,
        )

# `uv run` сам синхронизирует/создаёт per-platform venv по uv.lock при первом запуске.
cmd = [uv_bin, "--directory", kos_home, "run", "python", "-m", "apps.mcp_server", *sys.argv[1:]]
result = subprocess.run(cmd, env=env)
sys.exit(result.returncode)
