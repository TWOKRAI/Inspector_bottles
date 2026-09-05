"""Приёмочные тесты E1-E4 (ленивый импорт SDK) — Task 0.2 шаг 2 плана otel-export.md.

НЕЗАВИСИМЫЙ тестер, ДО реализации. Источник критериев — акты приёмки Task 0.2
шаг 2 (см. также E1-E4 в брифе тестеру). Реализации ``Services/otel_export`` и
``Plugins/io/otel_export`` не существует на момент написания.

Импорт предмета — ВНУТРИ каждого теста, не на уровне модуля этого файла, ради
`pytest --collect-only`.

Ожидаемое красное состояние сейчас: E1 (AST-разбор) падает `AssertionError`
"файлов не найдено" (это НАМЕРЕННО — иначе тест на пустом каталоге проходит
вхолостую и неотличим от отсутствующего, см. docstring test_e1). E2-E4 падают
`ModuleNotFoundError` на `Services.otel_export.exporter`.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUBJECT_DIRS = [
    REPO_ROOT / "Services" / "otel_export",
    REPO_ROOT / "Plugins" / "io" / "otel_export",
]


def _module_level_opentelemetry_imports(py_file: Path) -> list[str]:
    """Имена opentelemetry-импортов на уровне МОДУЛЯ (прямые дети ast.Module.body).

    Разбор через AST, не через grep по строкам — grep ловит комментарии и
    строки внутри докстрок/функций как ложные срабатывания, AST — нет.
    Импорт внутри `if TYPE_CHECKING:` или внутри тела функции НЕ считается
    (это не ast.Module.body напрямую) — такой импорт не исполняется при
    загрузке модуля и не тянет пакет в sys.modules, что и требуется E1/E3.
    """
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    hits: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "opentelemetry" or alias.name.startswith("opentelemetry."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "opentelemetry" or node.module.startswith("opentelemetry.")):
                hits.append(node.module)
    return hits


class TestLazyImport:
    """E1, E3: opentelemetry не грузится на уровне модуля и не тянется в sys.modules при импорте пакета."""

    def test_e1_no_module_level_opentelemetry_import_anywhere_in_subject(self) -> None:
        """E1: ни одного `import opentelemetry`/`from opentelemetry ...` на уровне модуля
        ни в одном .py файле Services/otel_export/*.py и Plugins/io/otel_export/*.py
        (исключая tests/).

        Как краснеет СЕЙЧАС: каталогов ещё нет -> список файлов пуст.
        Это НАРОЧНО assert'ится как отдельная ошибка (`no_files`, ниже) —
        иначе пустой список файлов давал бы пустой список нарушений и тест
        проходил бы вхолостую и на несуществующем предмете, что неотличимо от
        "предмет существует и импортов действительно нет".
        Как краснеет ПОСЛЕ появления файлов, но с нарушением: сообщение
        покажет конкретный файл и имя модуля импорта.
        """
        py_files: list[Path] = []
        for d in SUBJECT_DIRS:
            if not d.exists():
                continue
            for f in d.rglob("*.py"):
                rel_parts = f.relative_to(d).parts
                if "tests" in rel_parts or f.name.startswith("test_"):
                    continue
                py_files.append(f)

        assert py_files, (
            f"Не найдено ни одного файла предмета в {SUBJECT_DIRS} — "
            "сервис/плагин ещё не созданы (ожидаемое красное состояние ДО реализации)"
        )

        violations: dict[str, list[str]] = {}
        for f in py_files:
            hits = _module_level_opentelemetry_imports(f)
            if hits:
                violations[str(f.relative_to(REPO_ROOT))] = hits

        assert not violations, f"Импорт opentelemetry на уровне модуля: {violations}"

    def test_e3_importing_the_package_does_not_pull_opentelemetry_into_sys_modules(self) -> None:
        """E3: `import Services.otel_export` не добавляет ключей 'opentelemetry*' в sys.modules.

        Проверка — в ПОДПРОЦЕССЕ (чистый sys.modules, не загрязнённый другими
        тестами этого файла, которые сами импортируют opentelemetry напрямую
        для E2/E4).

        Ловушка, найденная при первом прогоне этого же теста: `Services/otel_export`
        и `Plugins/io/otel_export` — сейчас пустые каталоги (только `tests/`
        внутри), и голый `import Services.otel_export` в них молча УСПЕВАЕТ —
        Python трактует их как namespace-пакет (PEP 420) без единой строки
        реализации, exit code = 0, тест был бы зелёным ДО всякого кода. Поэтому
        импортируются конкретные подмодули предмета (config/interfaces/exporter
        сервиса, registers плагина — все четыре уже названы критериями B/C/D/E
        этого же брифа), их отсутствие даёт настоящий ModuleNotFoundError.
        """
        code = (
            "import sys\n"
            "import Services.otel_export.config\n"
            "import Services.otel_export.interfaces\n"
            "import Services.otel_export.exporter\n"
            "import Plugins.io.otel_export.registers\n"
            "leaked = [m for m in sys.modules if m == 'opentelemetry' or m.startswith('opentelemetry.')]\n"
            "print('LEAKED=' + repr(leaked))\n"
            "sys.exit(1 if leaked else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Импорт пакета протёк opentelemetry в sys.modules или упал.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


class TestSdkAvailable:
    """E2, E4: Services.otel_export.exporter.sdk_available() -> tuple[bool, str]."""

    def test_e2_sdk_available_reports_true_and_version_when_installed(self) -> None:
        """E2: SDK установлен в этом venv (проверено: opentelemetry-sdk 1.44.0,
        opentelemetry-exporter-otlp-proto-http 1.44.0 — importlib.metadata,
        независимо от кода предмета) -> sdk_available() == (True, "1.44.0"-подобная строка).
        """
        from Services.otel_export.exporter import sdk_available

        available, info = sdk_available()
        assert available is True
        assert isinstance(info, str) and info, "вторая компонента должна быть непустой строкой"
        assert "1.44" in info, f"версия SDK не отражена в ответе: {info!r}"

    def test_e4_sdk_available_reports_false_with_install_command_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """E4 (парная к E2): при смоделированном отсутствии SDK sdk_available()
        возвращает (False, <текст с командой установки>), НЕ бросает ImportError наружу.

        Смоделировано подменой sys.modules: 'opentelemetry' и все его
        подпакеты -> None, так что любой `import opentelemetry...` внутри
        sdk_available() поднимет ImportError, который функция обязана
        поймать сама (а не даёт ему всплыть до теста).
        """
        import sys

        real_modules = {
            name: mod
            for name, mod in sys.modules.items()
            if name == "opentelemetry" or name.startswith("opentelemetry.")
        }
        for name in real_modules:
            monkeypatch.setitem(sys.modules, name, None)

        # На случай если sdk_available() импортирует подпакет, которого ещё
        # не было в sys.modules к этому моменту (ленивый импорт — это и есть
        # предмет проверки) — блокируем импорт целиком через meta-path хук.
        import importlib.abc

        class _BlockOtel(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
                    raise ImportError(f"смоделировано отсутствие пакета: {fullname}")
                return None

        blocker = _BlockOtel()
        sys.meta_path.insert(0, blocker)
        try:
            from Services.otel_export.exporter import sdk_available

            available, info = sdk_available()
        finally:
            sys.meta_path.remove(blocker)

        assert available is False
        assert isinstance(info, str)
        assert "uv pip install --inexact '.[otel]'" in info, f"в тексте нет точной команды установки: {info!r}"
        assert "otel" in info, f"в тексте не назван extra 'otel': {info!r}"
