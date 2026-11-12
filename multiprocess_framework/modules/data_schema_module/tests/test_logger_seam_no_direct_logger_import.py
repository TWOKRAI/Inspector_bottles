"""Шов data_schema_module -> logger_module: только через дверь ``_fallback.FallbackLogger``.

``core/field_meta.py`` и ``core/metrics.py`` грузятся из ``core/__init__.py`` на
LAYER 0 пакета. Прямой импорт ``logger_module`` из них — даже ленивый, в теле
функции — замыкал файловую SCC framework (logger_module -> channel_routing_module
-> data_schema_module -> logger_module). Дверь ``FallbackLogger`` конструируется
без импортов и подтягивает вид при первой записи.

Проверки:

* статическая (AST): ни одного ``import``/``from ... import`` с ``logger_module``
  на любой вложенности, включая ``if TYPE_CHECKING`` и тела функций, и ни одного
  строкового обхода через ``importlib.import_module`` / ``__import__``;
* наблюдаемый эффект: предупреждение ``FieldMeta.from_dict`` о неизвестном
  правиле приходит в stdlib-логгер с ТОЧНЫМ именем модуля и прежним текстом —
  в этом процессе (caplog) и в чистом ``python -I`` с пакетом ПЕРВЫМ (зелёный
  pytest не доказывает отсутствие цикла: соседи грузят пакеты раньше).
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[1] / "core"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIELD_META_LOGGER = "multiprocess_framework.modules.data_schema_module.core.field_meta"
_UNKNOWN_RULES_TEXT = "отброшены неизвестные правила"


def _logger_module_imports(path: Path) -> list[str]:
    """Строки ``<lineno>: <что>`` для каждого импорта logger_module в файле."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        elif isinstance(node, ast.Call):
            func = node.func
            func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if func_name not in ("import_module", "__import__"):
                continue
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        else:
            continue
        if any("logger_module" in n for n in names):
            hits.append(f"{node.lineno}: {ast.unparse(node)}")
    return hits


def test_field_meta_has_no_direct_logger_module_import() -> None:
    hits = _logger_module_imports(_CORE / "field_meta.py")
    assert hits == [], f"core/field_meta.py импортирует logger_module мимо двери _fallback: {hits}"


def test_metrics_has_no_direct_logger_module_import() -> None:
    hits = _logger_module_imports(_CORE / "metrics.py")
    assert hits == [], f"core/metrics.py импортирует logger_module мимо двери _fallback: {hits}"


def test_unknown_rule_warning_reaches_the_exact_stdlib_logger(caplog: pytest.LogCaptureFixture) -> None:
    from ..core.field_meta import FieldMeta

    caplog.set_level(logging.WARNING, logger=_FIELD_META_LOGGER)
    meta = FieldMeta.from_dict({"rules": {"zz_unknown_rule_seam_probe": 1}})

    assert meta.rules == {}, f"неизвестное правило не отброшено: {meta.rules!r}"
    hits = [
        r
        for r in caplog.records
        if r.name == _FIELD_META_LOGGER and r.levelno == logging.WARNING and _UNKNOWN_RULES_TEXT in r.getMessage()
    ]
    assert len(hits) == 1, (
        f"ожидалась одна WARNING-запись «{_UNKNOWN_RULES_TEXT}» в логгере {_FIELD_META_LOGGER}, получено: "
        f"{[(r.name, r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    assert "zz_unknown_rule_seam_probe" in hits[0].getMessage()


# Корневой ``multiprocess_framework/__init__.py`` грузит ``base_manager`` и половину
# framework раньше всех — с ним «пакет первым» не выполнялось бы никогда. Подмена
# корня пустым пакетом с настоящим ``__path__`` оставляет порядок за пробой.
_ROOT_STUB = """
import sys, types
_root = types.ModuleType("multiprocess_framework")
_root.__path__ = [sys.argv[1] + "/multiprocess_framework"]
sys.modules["multiprocess_framework"] = _root
"""

_CLEAN_PROBE = (
    _ROOT_STUB
    + """
import logging
logging.basicConfig(stream=sys.stdout, level=logging.WARNING, format="%(name)s|%(levelname)s|%(message)s")
import multiprocess_framework.modules.data_schema_module as ds
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
FieldMeta.from_dict({"rules": {"zz_clean_probe": 1}})
print("SCHEMA_BASE_OK", ds.SchemaBase.__name__)
"""
)

_LOGGER_FIRST_PROBE = (
    _ROOT_STUB
    + """
import multiprocess_framework.modules.logger_module
print("LOGGER_FIRST_OK")
"""
)


def _run_clean(probe: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", probe, str(_REPO_ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_unknown_rule_warning_in_a_clean_process_with_the_package_first() -> None:
    proc = _run_clean(_CLEAN_PROBE)
    assert proc.returncode == 0, f"чистый импорт пакета упал (rc={proc.returncode}):\n{proc.stderr[-3000:]}"
    expected = f"{_FIELD_META_LOGGER}|WARNING|FieldMeta.from_dict: {_UNKNOWN_RULES_TEXT} ['zz_clean_probe']"
    assert expected in proc.stdout.splitlines(), f"нет строки {expected!r} в выводе:\n{proc.stdout[-3000:]}"
    assert "SCHEMA_BASE_OK SchemaBase" in proc.stdout


def test_logger_module_first_survives_the_voice_ring() -> None:
    """Hazard: ``logger_module`` ПЕРВЫМ в чистом процессе — голос ``metrics`` попадает в кольцо.

    ``logger_module/__init__`` -> ``channel_routing_module`` -> ``data_schema_module``:
    пакет данных собирается ВНУТРИ частично инициализированного ``logger_module``, и
    голос ``MetricsCollector`` на импорте зовёт ``_std_logger()``. Резолв двери под
    ``try`` в ``_std_logger`` откладывает голос; без него первая запись бросает
    ``ImportError: cannot import name 'ChannelRoutingManager' from partially initialized
    module`` (инъекция b ревью Opus 2026-11-12, rc=1).
    """
    proc = _run_clean(_LOGGER_FIRST_PROBE)
    assert proc.returncode == 0, f"logger_module первым упал (rc={proc.returncode}):\n{proc.stderr[-3000:]}"
    assert proc.stderr == "", f"stderr не пуст:\n{proc.stderr[-3000:]}"
    assert "LOGGER_FIRST_OK" in proc.stdout
