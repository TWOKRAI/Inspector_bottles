"""Гейт «последние модели всегда» для определений агентов.

Почему тест, а не только линтер: `lint_agents.py` про модель-не-последнюю выдаёт
WARNING (exit 2), а гейт `make gate` смотрит на exit 0/1 — предупреждение молча
проезжает. Здесь тот же признак поднят до жёсткого падения.

Историческая справка: докстринг `lint_agents.py` ссылался на
`tests/test_lint_agents_models.py` как на существующий «HARD gate» — файла не было
нигде в репозитории (проверено 2026-08-05). Это тот самый класс «уверенное неверное
объяснение живёт дольше бага»: ссылка читалась как доказательство, доказательства не
было. Файл создан здесь, ссылка стала правдой.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
LINTER = REPO_ROOT / ".claude" / "plugins" / "core" / "scripts" / "lint_agents.py"


def _load_linter():
    spec = importlib.util.spec_from_file_location("lint_agents", LINTER)
    assert spec and spec.loader, f"не загрузился линтер: {LINTER}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_agents"] = module
    spec.loader.exec_module(module)
    return module


def _agent_files() -> list[Path]:
    """Все определения агентов: проектные + плагинные. Шаблоны исключены."""
    roots = [REPO_ROOT / ".claude" / "agents", *sorted((REPO_ROOT / ".claude" / "plugins").glob("*/agents"))]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(p for p in root.rglob("*.md") if not p.stem.startswith("_"))
    return sorted(files)


def test_agent_files_found():
    """Оракул самого гейта: пустой список файлов согласится с любым ответом."""
    files = _agent_files()
    assert len(files) >= 12, f"найдено всего {len(files)} агентов — гейт смотрит не туда"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_agent_model_is_current(path: Path):
    """Каждый агент — на актуальной модели своего яруса (или на алиасе поколения)."""
    linter = _load_linter()
    fm = linter.parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fm is not None, f"{path}: нет YAML frontmatter"
    model = fm.get("model", "")
    if not model:
        return  # model опущено → наследование от родителя, это законно
    assert model in linter.CURRENT_MODELS, (
        f"{path.relative_to(REPO_ROOT)}: model={model!r} не из CURRENT_MODELS "
        f"({sorted(linter.CURRENT_MODELS)}). Предпочтительна форма-алиас: opus/sonnet/haiku/fable — "
        "она не устаревает при выходе нового поколения."
    )
