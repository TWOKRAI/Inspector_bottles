# -*- coding: utf-8 -*-
"""
Тесты для RegistersScanner.

Тестируемые сценарии:
    - scan_directory: корректно находит *Registers-подклассы
    - scan_package_path: эквивалент scan_directory от __init__.py
    - Имена ключей: CamelCase → snake_case
    - Исключение базового класса и классов без суффикса
    - Пустая директория → {}
    - Несуществующая директория → {} с предупреждением
    - custom suffix (например "Config")
    - name_from_class кастомная функция
    - list_files: только перечисление без импорта
    - exclude_files: файлы из исключений
    - Дублирующиеся ключи: предупреждение + последний побеждает
"""

import sys
import types

# Заглушка для multiprocess_framework (для запуска вне общего окружения)
if "multiprocess_framework" not in sys.modules:
    _mock_fw = types.ModuleType("multiprocess_framework")
    _mock_fw.__path__ = []
    sys.modules["multiprocess_framework"] = _mock_fw

import logging
import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

from multiprocess_framework.modules.data_schema_module.registry.discovery import (
    RegistersScanner,
    _class_name_to_snake,
)
from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase


# =============================================================================
# Вспомогательная фикстура: временная директория с .py файлами
# =============================================================================


@pytest.fixture()
def reg_dir(tmp_path: Path) -> Path:
    """Создаём временную директорию с тремя файлами регистров."""
    (tmp_path / "alpha.py").write_text(
        textwrap.dedent("""\
            from typing import Annotated
            from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase
            from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta

            class AlphaRegisters(RegisterBase):
                value: Annotated[int, FieldMeta("Значение")] = 0
        """),
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        textwrap.dedent("""\
            from typing import Annotated
            from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase
            from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta

            class BetaRegisters(RegisterBase):
                flag: Annotated[bool, FieldMeta("Флаг")] = True
        """),
        encoding="utf-8",
    )
    # Файл без подходящих классов — должен быть проигнорирован
    (tmp_path / "utils.py").write_text(
        "def helper(): return 42\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def multi_word_dir(tmp_path: Path) -> Path:
    """Директория с многословным именем класса."""
    (tmp_path / "frame_process.py").write_text(
        textwrap.dedent("""\
            from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase

            class FrameProcessRegisters(RegisterBase):
                timeout: int = 100
        """),
        encoding="utf-8",
    )
    return tmp_path


# =============================================================================
# Тесты _class_name_to_snake
# =============================================================================


class TestClassNameToSnake:
    def test_simple(self) -> None:
        assert _class_name_to_snake("DrawRegisters", "Registers") == "draw"

    def test_multi_word(self) -> None:
        assert _class_name_to_snake("FrameProcessRegisters", "Registers") == "frame_process"

    def test_no_suffix(self) -> None:
        result = _class_name_to_snake("DrawRegisters", "Config")
        assert result == "drawregisters"

    def test_empty_suffix(self) -> None:
        assert _class_name_to_snake("SomeClass", "") == "someclass"

    def test_three_words(self) -> None:
        assert _class_name_to_snake("PostProcessingRegisters", "Registers") == "post_processing"


# =============================================================================
# Тесты scan_directory
# =============================================================================


class TestScanDirectory:
    def test_finds_registers(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        assert "alpha" in result
        assert "beta" in result

    def test_classes_are_register_base(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        for cls in result.values():
            assert issubclass(cls, RegisterBase)

    def test_ignores_file_without_registers(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        assert "utils" not in result

    def test_ignores_base_class_itself(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        assert RegisterBase not in result.values()

    def test_nonexistent_dir_returns_empty(self) -> None:
        result = RegistersScanner.scan_directory("/no/such/path")
        assert result == {}

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        result = RegistersScanner.scan_directory(tmp_path)
        assert result == {}

    def test_multi_word_class_name(self, multi_word_dir: Path) -> None:
        result = RegistersScanner.scan_directory(multi_word_dir)
        assert "frame_process" in result

    def test_custom_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "system.py").write_text(
            textwrap.dedent("""\
                from pydantic import BaseModel
                class SystemConfig(BaseModel):
                    debug: bool = False
            """),
            encoding="utf-8",
        )
        result = RegistersScanner.scan_directory(tmp_path, base_class=BaseModel, suffix="Config")
        assert "system" in result

    def test_custom_name_from_class(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir, name_from_class=lambda cls: cls.__name__.lower())
        assert "alpharegisters" in result
        assert "betaregisters" in result

    def test_exclude_files(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir, exclude_files=["alpha"])
        assert "alpha" not in result
        assert "beta" in result

    def test_instantiate_found_class(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        alpha_cls = result["alpha"]
        instance = alpha_cls()
        assert hasattr(instance, "value")
        assert instance.value == 0

    def test_field_meta_accessible(self, reg_dir: Path) -> None:
        result = RegistersScanner.scan_directory(reg_dir)
        alpha_cls = result["alpha"]
        meta = alpha_cls.get_field_meta("value")
        assert meta is not None
        assert meta.description == "Значение"

    def test_duplicate_key_warning(self, tmp_path: Path, caplog) -> None:
        """Два файла с одинаковым именем класса → предупреждение в логе."""
        (tmp_path / "first.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase
                class DupeRegisters(RegisterBase):
                    x: int = 1
            """),
            encoding="utf-8",
        )
        (tmp_path / "second.py").write_text(
            textwrap.dedent("""\
                from multiprocess_framework.modules.data_schema_module.core.schema_base import RegisterBase
                class DupeRegisters(RegisterBase):
                    x: int = 2
            """),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="data_schema_module.registry.discovery"):
            result = RegistersScanner.scan_directory(tmp_path)
        assert "dupe" in result
        assert any("дублирующийся" in rec.message for rec in caplog.records)


# =============================================================================
# Тесты scan_package_path
# =============================================================================


class TestScanPackagePath:
    def test_equivalent_to_scan_directory(self, reg_dir: Path) -> None:
        init_file = reg_dir / "__init__.py"
        init_file.write_text("", encoding="utf-8")

        from_dir = RegistersScanner.scan_directory(reg_dir)
        from_pkg = RegistersScanner.scan_package_path(init_file)
        assert set(from_dir.keys()) == set(from_pkg.keys())

    def test_using_dunder_file(self, reg_dir: Path) -> None:
        """Типичный use-case: передаём __file__ из __init__.py."""
        fake_init = reg_dir / "__init__.py"
        fake_init.write_text("", encoding="utf-8")
        result = RegistersScanner.scan_package_path(str(fake_init))
        assert "alpha" in result


# =============================================================================
# Тесты list_files
# =============================================================================


class TestListFiles:
    def test_lists_py_files(self, reg_dir: Path) -> None:
        files = RegistersScanner.list_files(reg_dir)
        names = [f.stem for f in files]
        assert "alpha" in names
        assert "beta" in names
        assert "utils" in names

    def test_excludes_init(self, reg_dir: Path) -> None:
        (reg_dir / "__init__.py").write_text("", encoding="utf-8")
        files = RegistersScanner.list_files(reg_dir)
        names = [f.stem for f in files]
        assert "__init__" not in names

    def test_nonexistent_returns_empty(self) -> None:
        assert RegistersScanner.list_files("/no/such/path") == []

    def test_recursive(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("x = 1", encoding="utf-8")
        files = RegistersScanner.list_files(tmp_path, recursive=True)
        assert any(f.name == "nested.py" for f in files)

    def test_non_recursive_misses_nested(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("x = 1", encoding="utf-8")
        files = RegistersScanner.list_files(tmp_path, recursive=False)
        assert not any(f.name == "nested.py" for f in files)
