"""Тесты для ServiceScanner — discover(*dirs) + DiscoveryResult.

Покрытие: пустая директория, нет service.py, успешная регистрация,
множество директорий, broken-файл не прерывает обход, дубликат имени,
вызов без аргументов.

Фикстура ``_clean_registry`` (autouse) очищает singleton ServiceRegistry
перед каждым тестом, обеспечивая изоляцию.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from multiprocess_framework.modules.service_module.registry import ServiceRegistry
from multiprocess_framework.modules.service_module.scanner import (
    DiscoveryResult,
    discover,
)


# ------------------------------------------------------------------
# Autouse-фикстура: изоляция singleton между тестами
# ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищать ServiceRegistry до и после каждого теста."""
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


# ------------------------------------------------------------------
# Вспомогательные функции
# ------------------------------------------------------------------


def _write_service(directory: Path, name: str) -> Path:
    """Создать минимальный service.py с @register_service в директории."""
    service_dir = directory / name
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / "service.py"
    service_file.write_text(
        textwrap.dedent(f"""\
            from multiprocess_framework.modules.service_module import register_service

            @register_service(name={name!r})
            class _Service_{name}:
                name: str = {name!r}

                def start(self, config: dict) -> bool:
                    return True

                def stop(self) -> bool:
                    return True

                def get_status(self) -> dict:
                    return {{"state": "ready", "service": self.name}}
        """),
        encoding="utf-8",
    )
    return service_file


def _write_broken_service(directory: Path, name: str) -> Path:
    """Создать service.py с синтаксической ошибкой."""
    service_dir = directory / name
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / "service.py"
    service_file.write_text(
        "this is NOT valid python @@@@\n",
        encoding="utf-8",
    )
    return service_file


# ------------------------------------------------------------------
# Тесты
# ------------------------------------------------------------------


class TestDiscoverEmptyDir:
    """Сканирование пустой директории."""

    def test_discover_empty_dir(self, tmp_path: Path):
        """discover(пустая_директория) → loaded=[], failed=[], total=0."""
        result = discover(tmp_path)

        assert isinstance(result, DiscoveryResult)
        assert result.loaded == []
        assert result.failed == []
        assert result.total == 0


class TestDiscoverNoServicePy:
    """Директория есть, service.py нет."""

    def test_discover_no_service_py(self, tmp_path: Path):
        """Файлы __init__.py не вызывают регистрацию — результат пустой."""
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "some_module.py").write_text("x = 1\n", encoding="utf-8")

        result = discover(tmp_path)

        assert result.loaded == []
        assert result.failed == []
        assert result.total == 0


class TestDiscoverOneService:
    """Один service.py успешно регистрируется."""

    def test_discover_one_service_registers(self, tmp_path: Path):
        """После discover ServiceRegistry содержит зарегистрированный сервис."""
        _write_service(tmp_path, "foo_test")

        result = discover(tmp_path)

        assert len(result.loaded) == 1
        assert result.failed == []
        entry = ServiceRegistry().get("foo_test")
        assert entry is not None
        assert entry.name == "foo_test"

    def test_discover_loaded_contains_relative_path(self, tmp_path: Path):
        """loaded содержит относительный путь к service.py (slash-separated)."""
        _write_service(tmp_path, "bar_test")

        result = discover(tmp_path)

        assert len(result.loaded) == 1
        # путь содержит имя папки и файла
        assert "service.py" in result.loaded[0]
        assert "bar_test" in result.loaded[0]


class TestDiscoverMultipleDirs:
    """Несколько директорий — оба сервиса регистрируются."""

    def test_discover_multiple_dirs(self, tmp_path: Path):
        """discover(dir_a, dir_b) загружает сервисы из обеих директорий."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        _write_service(dir_a, "svc_alpha")
        _write_service(dir_b, "svc_beta")

        result = discover(dir_a, dir_b)

        assert len(result.loaded) == 2
        assert result.failed == []
        assert ServiceRegistry().get("svc_alpha") is not None
        assert ServiceRegistry().get("svc_beta") is not None

    def test_discover_multiple_services_in_one_dir(self, tmp_path: Path):
        """Несколько service.py в поддиректориях одной корневой директории."""
        _write_service(tmp_path, "svc_one")
        _write_service(tmp_path, "svc_two")
        _write_service(tmp_path, "svc_three")

        result = discover(tmp_path)

        assert len(result.loaded) == 3
        assert result.failed == []
        assert len(ServiceRegistry().list()) == 3


class TestDiscoverBrokenService:
    """Ошибка в одном файле не прерывает обход."""

    def test_discover_broken_service_continues(self, tmp_path: Path):
        """Файл с синтаксической ошибкой → failed, остальной файл регистрируется."""
        _write_broken_service(tmp_path, "broken_svc")
        _write_service(tmp_path, "good_svc")

        result = discover(tmp_path)

        assert len(result.loaded) == 1
        assert len(result.failed) == 1

        # Хороший сервис зарегистрирован
        assert ServiceRegistry().get("good_svc") is not None

        # В failed есть пояснение
        failed_path, failed_reason = result.failed[0]
        assert "broken_svc" in failed_path
        assert len(failed_reason) > 0

    def test_discover_failed_reason_mentions_error_type(self, tmp_path: Path):
        """Описание ошибки содержит тип исключения."""
        _write_broken_service(tmp_path, "err_svc")

        result = discover(tmp_path)

        assert len(result.failed) == 1
        _, reason = result.failed[0]
        # SyntaxError или другое — имя типа должно присутствовать
        assert "Error" in reason or "error" in reason


class TestDiscoverDuplicateName:
    """Дублирующиеся имена сервисов."""

    def test_discover_duplicate_name(self, tmp_path: Path):
        """Два service.py с одинаковым name: второй в failed, обход не падает."""
        # Первый сервис с именем "dup_svc"
        dir_a = tmp_path / "plugin_a"
        dir_a.mkdir()
        (dir_a / "service.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.service_module import register_service

                @register_service(name="dup_svc")
                class _SvcA:
                    name: str = "dup_svc"
                    def start(self, config: dict) -> bool: return True
                    def stop(self) -> bool: return True
                    def get_status(self) -> dict: return {}
            """),
            encoding="utf-8",
        )

        # Второй сервис с тем же именем
        dir_b = tmp_path / "plugin_b"
        dir_b.mkdir()
        (dir_b / "service.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.service_module import register_service

                @register_service(name="dup_svc")
                class _SvcB:
                    name: str = "dup_svc"
                    def start(self, config: dict) -> bool: return True
                    def stop(self) -> bool: return True
                    def get_status(self) -> dict: return {}
            """),
            encoding="utf-8",
        )

        result = discover(tmp_path)

        # Один загружен успешно, второй упал с ValueError (дубликат)
        assert result.total == 2
        assert len(result.loaded) == 1
        assert len(result.failed) == 1

        _, reason = result.failed[0]
        assert "dup_svc" in reason

    def test_discover_duplicate_registry_has_only_one_entry(self, tmp_path: Path):
        """При дубликате в реестре только одна запись с этим именем."""
        dir_a = tmp_path / "svc_x"
        dir_a.mkdir()
        (dir_a / "service.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.service_module import register_service

                @register_service(name="unique_dup")
                class _SvcX:
                    name: str = "unique_dup"
                    def start(self, config: dict) -> bool: return True
                    def stop(self) -> bool: return True
                    def get_status(self) -> dict: return {}
            """),
            encoding="utf-8",
        )

        dir_b = tmp_path / "svc_y"
        dir_b.mkdir()
        (dir_b / "service.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.service_module import register_service

                @register_service(name="unique_dup")
                class _SvcY:
                    name: str = "unique_dup"
                    def start(self, config: dict) -> bool: return True
                    def stop(self) -> bool: return True
                    def get_status(self) -> dict: return {}
            """),
            encoding="utf-8",
        )

        discover(tmp_path)

        entries = ServiceRegistry().list()
        names = [e.name for e in entries]
        assert names.count("unique_dup") == 1


class TestDiscoverNoArgs:
    """discover() без аргументов."""

    def test_discover_no_args_returns_empty(self):
        """discover() без аргументов → DiscoveryResult(loaded=[], failed=[])."""
        result = discover()

        assert isinstance(result, DiscoveryResult)
        assert result.loaded == []
        assert result.failed == []
        assert result.total == 0

    def test_discover_no_args_registry_unchanged(self):
        """discover() без аргументов не изменяет состояние реестра."""
        # Предположим, что в реестре уже что-то есть (autouse сделал clear)
        # Просто убеждаемся, что discover() не добавляет мусор
        assert len(ServiceRegistry().list()) == 0
        discover()
        assert len(ServiceRegistry().list()) == 0


class TestDiscoverResult:
    """Свойства DiscoveryResult."""

    def test_total_is_sum_of_loaded_and_failed(self, tmp_path: Path):
        """total == len(loaded) + len(failed)."""
        _write_service(tmp_path, "ok_svc")
        _write_broken_service(tmp_path, "fail_svc")

        result = discover(tmp_path)

        assert result.total == len(result.loaded) + len(result.failed)
        assert result.total == 2

    def test_empty_result_total_is_zero(self):
        """DiscoveryResult() по умолчанию: total == 0."""
        result = DiscoveryResult()
        assert result.total == 0

    def test_nonexistent_dir_skipped(self, tmp_path: Path):
        """Несуществующая директория молча пропускается."""
        nonexistent = tmp_path / "does_not_exist"
        result = discover(nonexistent)

        assert result.loaded == []
        assert result.failed == []
