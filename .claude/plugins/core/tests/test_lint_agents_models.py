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


def test_latest_generation_is_known_and_current():
    """Литералы, не константы линтера: ID нового поколения обязаны проходить гейт."""
    linter = _load_linter()
    for model in ("opus", "sonnet", "haiku", "fable", "claude-opus-5-5", "claude-sonnet-5-5",
                  "claude-fable-5-1", "claude-haiku-4-5"):
        assert model in linter.KNOWN_MODELS, f"{model} не известен линтеру"
        assert model in linter.CURRENT_MODELS, f"{model} не считается текущим"


def test_previous_generation_is_known_but_not_current():
    """Прошлое поколение — допустимый пин, но не «последняя модель яруса»."""
    linter = _load_linter()
    for model in ("claude-opus-4-8", "claude-sonnet-5"):
        assert model in linter.KNOWN_MODELS, f"{model} выпал из известных"
        assert model not in linter.CURRENT_MODELS, f"{model} застрял в текущих"


def _write_probe_agent(tmp_path: Path, model: str) -> Path:
    path = tmp_path / "probe.md"
    path.write_text(
        f"---\nname: probe\ndescription: probe agent\nmodel: {model}\n---\nBody.\n", encoding="utf-8"
    )
    return path


def test_lint_warns_on_previous_generation_model(tmp_path: Path):
    """Поведение, не данные: агент на прошлом поколении получает предупреждение «not latest-of-tier»."""
    linter = _load_linter()
    errors, warnings = linter.lint_file(_write_probe_agent(tmp_path, "claude-opus-4-8"))
    assert errors == [], errors
    assert any("latest-of-tier" in w for w in warnings), warnings


@pytest.mark.parametrize("model", ["opus", "claude-opus-5-5", "claude-sonnet-5-5"])
def test_lint_is_silent_on_latest_model(tmp_path: Path, model: str):
    """Обратная сторона: актуальная модель не даёт предупреждений про модель."""
    linter = _load_linter()
    errors, warnings = linter.lint_file(_write_probe_agent(tmp_path, model))
    assert errors == [], errors
    assert not [w for w in warnings if "model" in w], warnings


def _roster_fixture(tmp_path: Path, roster_tier: str):
    """Плагин `dev` с одним агентом (model: opus) и таблицей состава, где роль названа ярусом `roster_tier`."""
    agents = tmp_path / "dev" / "agents"
    agents.mkdir(parents=True)
    (tmp_path / "dev" / "modes").mkdir()
    agent = agents / "manager.md"
    agent.write_text("---\nname: manager\ndescription: m\nmodel: opus\n---\nBody.\n", encoding="utf-8")
    (tmp_path / "dev" / "modes" / "dev.md").write_text(
        "| Agent | Model | Skill | When |\n|---|---|---|---|\n"
        f"| **manager** | {roster_tier} | `/dev:plan` | plan |\n",
        encoding="utf-8",
    )
    return agents, {"manager": agent}


def test_roster_tier_drift_is_reported(tmp_path: Path):
    """Таблица состава говорит Sonnet, frontmatter — opus: линтер обязан назвать расхождение."""
    linter = _load_linter()
    agents, files = _roster_fixture(tmp_path, "Sonnet")
    errors = linter.cross_check_model_tiers(agents, files)
    assert len(errors) == 1 and "manager" in errors[0], errors


def test_roster_tier_match_is_silent(tmp_path: Path):
    """Ярус в таблице совпадает с frontmatter: тишина."""
    linter = _load_linter()
    agents, files = _roster_fixture(tmp_path, "Opus")
    assert linter.cross_check_model_tiers(agents, files) == []
