#!/usr/bin/env python3
"""Bootstrap MCP-инфраструктуры для нового проекта.

Кросс-платформенный — работает на macOS, Linux, Windows.

Запуск:
    python3 .claude/mcp/bootstrap.py        # macOS / Linux
    python .claude/mcp/bootstrap.py         # Windows

Что делает:
    1. Проверяет sentrux (если нет — ставит на macOS через brew, на Linux/Windows подсказывает install-команду)
    2. Проверяет ollama + наличие нужной embedding-модели под платформу
    3. Проверяет node/npx + Context7 (user-level)
    4. Копирует mcp.template.json -> ./.mcp.json в корне проекта
    5. Копирует sentrux/rules.template.toml -> .sentrux/rules.toml (с защитой от перезаписи)

Что НЕ делает:
    - Не индексирует проект в qex (запусти `/qex-reindex` в Claude Code)
    - Не качает Ollama-модели автоматически (только подсказывает команду)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# ── ANSI-цвета (с поддержкой Windows 10+ через VT mode) ─────────────────────
class C:
    R = "\033[0;31m"  # red
    G = "\033[0;32m"  # green
    Y = "\033[1;33m"  # yellow
    B = "\033[0;34m"  # blue
    N = "\033[0m"     # reset


def _enable_vt_on_windows():
    """Включает ANSI/VT escape sequences в cmd.exe / PowerShell на Windows 10+."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        for attr in ("R", "G", "Y", "B", "N"):
            setattr(C, attr, "")


IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

if IS_WIN:
    _enable_vt_on_windows()


# ── Пути ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
TEMPLATE = SCRIPT_DIR / "mcp.template.json"
TARGET = PROJECT_ROOT / ".mcp.json"
RULES_TEMPLATE = SCRIPT_DIR / "sentrux" / "rules.template.toml"
RULES_TARGET = PROJECT_ROOT / ".sentrux" / "rules.toml"


# ── Утилиты ─────────────────────────────────────────────────────────────────
def has_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run_capture(args: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "command not found"


def step(num: int, total: int, title: str) -> None:
    print(f"\n{C.B}[{num}/{total}]{C.N} {title}")


def ok(msg: str) -> None:
    print(f"  {C.G}OK{C.N} {msg}")


def warn(msg: str) -> None:
    print(f"  {C.Y}!{C.N}  {msg}")


def err(msg: str) -> None:
    print(f"  {C.R}X{C.N}  {msg}")


def hint(cmd: str) -> None:
    print(f"    {C.Y}{cmd}{C.N}")


# ── Header ──────────────────────────────────────────────────────────────────
print(f"{C.B}=== MCP Bootstrap для {PROJECT_ROOT.name} ==={C.N}")
print(f"Platform: {platform.system()} {platform.machine()}  |  Python: {sys.version.split()[0]}")


# ── 1. sentrux ──────────────────────────────────────────────────────────────
step(1, 5, "sentrux (архитектурный анализ)...")
if has_cmd("sentrux"):
    code, out, _ = run_capture(["sentrux", "--version"])
    version = out.strip().split("\n")[0] if out else "?"
    ok(f"sentrux установлен ({version})")
else:
    if IS_MAC and has_cmd("brew"):
        warn("sentrux не найден, ставим через Homebrew...")
        try:
            subprocess.check_call(["brew", "install", "sentrux/tap/sentrux"])
            ok("sentrux установлен")
        except subprocess.CalledProcessError:
            err("brew install не удался — попробуй вручную:")
            hint("brew install sentrux/tap/sentrux")
    elif IS_LINUX:
        err("sentrux не найден. Установка:")
        hint("curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh | sh")
    elif IS_WIN:
        err("sentrux не найден. Установка для Windows:")
        hint("Скачай sentrux-windows-x86_64.exe с https://github.com/sentrux/sentrux/releases/latest")
        hint("Положи в %USERPROFILE%\\bin или PATH-директорию, переименовав в sentrux.exe")
        hint("Или через winget: winget install sentrux (если доступно)")
    else:
        err("sentrux не найден. См. https://github.com/sentrux/sentrux")


# ── 2. ollama (для qex dense search) ────────────────────────────────────────
step(2, 5, "Ollama (qex embeddings)...")
if has_cmd("ollama"):
    ok("ollama установлен")
    qex_model = "qwen3-embedding:4b" if IS_WIN else "qwen3-embedding:8b"
    code, out, _ = run_capture(["ollama", "list"])
    if code == 0 and qex_model in out:
        ok(f"модель {qex_model} загружена")
    else:
        warn(f"модель {qex_model} не найдена. Запусти:")
        hint(f"ollama pull {qex_model}")
else:
    err("ollama не найден. Установи:")
    if IS_MAC:
        hint("brew install ollama")
    elif IS_LINUX:
        hint("curl -fsSL https://ollama.com/install.sh | sh")
    elif IS_WIN:
        hint("Скачай с https://ollama.com/download")
        hint("Или через winget: winget install Ollama.Ollama")


# ── 3. node + Context7 (user-level) ─────────────────────────────────────────
step(3, 5, "Context7 (актуальные доки библиотек)...")
if has_cmd("npx"):
    code, out, _ = run_capture(["node", "--version"])
    node_v = out.strip() if code == 0 else "?"
    ok(f"npx доступен (node {node_v})")

    user_claude = Path.home() / ".claude.json"
    if user_claude.exists():
        try:
            content = user_claude.read_text(encoding="utf-8")
            if '"context7"' in content:
                ok("Context7 уже настроен (user-level в ~/.claude.json)")
            else:
                warn("Context7 не настроен. Запусти:")
                hint("npx -y ctx7 setup --claude")
                print("    (откроется браузер для OAuth, free tier без карты)")
        except Exception as e:
            warn(f"Не смог прочитать ~/.claude.json: {e}")
    else:
        warn("Context7 не настроен. Запусти:")
        hint("npx -y ctx7 setup --claude")
        print("    (откроется браузер для OAuth, free tier без карты)")
else:
    err("node/npx не найден — нужен для Context7. Установи:")
    if IS_MAC:
        hint("brew install node")
    elif IS_LINUX:
        hint("через nvm или пакетный менеджер дистрибутива")
    elif IS_WIN:
        hint("https://nodejs.org/en/download")
        hint("Или: winget install OpenJS.NodeJS")


# ── 4. .mcp.json в корне проекта ────────────────────────────────────────────
step(4, 5, "Конфиг .mcp.json в корне проекта...")
if not TEMPLATE.exists():
    err(f"Template не найден: {TEMPLATE}")
    sys.exit(1)

def _normalized(path: Path) -> dict:
    """Грузит JSON и убирает поля-метаданные (`_*`), чтобы сравнить только сервера."""
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


if TARGET.exists():
    if _normalized(TARGET) == _normalized(TEMPLATE):
        ok(".mcp.json совпадает с template (по конфигурации серверов)")
    else:
        warn(".mcp.json существует и отличается от template по конфигурации серверов.")
        print(f"    Текущий:  {TARGET}")
        print(f"    Эталон:   {TEMPLATE}")
        print(f"    Перезаписать вручную, если нужно:")
        if IS_WIN:
            hint(f'copy "{TEMPLATE}" "{TARGET}"')
        else:
            hint(f"cp {TEMPLATE.relative_to(PROJECT_ROOT)} {TARGET.relative_to(PROJECT_ROOT)}")
else:
    shutil.copy2(TEMPLATE, TARGET)
    ok(".mcp.json создан из template")


# ── 5. .sentrux/rules.toml ──────────────────────────────────────────────────
step(5, 5, ".sentrux/rules.toml (архитектурные правила)...")
if not RULES_TEMPLATE.exists():
    warn(f"Template не найден: {RULES_TEMPLATE}")
    warn("Пропускаю — создай .sentrux/rules.toml вручную")
elif RULES_TARGET.exists():
    ok(".sentrux/rules.toml уже существует (пропускаю)")
else:
    RULES_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RULES_TEMPLATE, RULES_TARGET)
    ok(".sentrux/rules.toml создан из template")
    warn("Отредактируй слои и границы под свой проект!")


# ── Итог ────────────────────────────────────────────────────────────────────
print(f"\n{C.B}=== Готово ==={C.N}")
print("Дальше:")
print("  1. Перезапусти Claude Code, чтобы поднять MCP-серверы")
print("  2. В Claude Code: /mcp — проверь что qex и sentrux зелёные")
print("  3. /qex-reindex — индексация кодовой базы (разовая, 1-5 мин)")
print("  4. Отредактируй .sentrux/rules.toml под свой проект (слои и границы)")
