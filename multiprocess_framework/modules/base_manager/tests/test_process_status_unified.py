# -*- coding: utf-8 -*-
"""
Тесты унификации ProcessStatus enum (ADR-117).

Проверяют:
- Все значения из всех трёх старых определений присутствуют в едином enum.
- Импорт из старых мест возвращает тот же Python-объект.
- Сравнение статусов из разных импортов работает корректно.
"""


class TestProcessStatusHasAllLegacyValues:
    """Единый ProcessStatus содержит все значения из всех прежних определений."""

    def test_has_process_module_values(self):
        """Все 9 значений из process_module присутствуют."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus

        # process_module определял: 9 значений
        process_module_values = {
            "initializing",
            "ready",
            "running",
            "stopping",
            "stopped",
            "error",
            "crashed",
            "unresponsive",
            "failed",
        }
        actual = {s.value for s in ProcessStatus}
        assert process_module_values.issubset(actual), (
            f"Отсутствуют значения process_module: {process_module_values - actual}"
        )

    def test_has_shared_resources_values(self):
        """Все 7 значений из shared_resources_module присутствуют."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus

        # shared_resources_module определял: 7 значений
        srm_values = {
            "initializing",
            "ready",
            "running",
            "stopping",
            "stopped",
            "error",
            "crashed",
        }
        actual = {s.value for s in ProcessStatus}
        assert srm_values.issubset(actual), f"Отсутствуют значения shared_resources: {srm_values - actual}"

    def test_total_count(self):
        """Всего 9 уникальных значений (суперсет)."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus

        assert len(ProcessStatus) == 9

    def test_is_str_enum(self):
        """ProcessStatus наследуется от str и Enum — для удобной сериализации."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus
        from enum import Enum

        assert issubclass(ProcessStatus, str)
        assert issubclass(ProcessStatus, Enum)
        # .value — всегда str
        assert isinstance(ProcessStatus.RUNNING.value, str)
        # Сравнение со строкой работает
        assert ProcessStatus.RUNNING == "running"


class TestLegacyImportsStillWork:
    """Старые пути импорта возвращают тот же объект ProcessStatus."""

    def test_process_module_import_is_same_object(self):
        """from process_module.types.types import ProcessStatus — тот же объект."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.process_module.types.types import ProcessStatus as PMS

        assert Canonical is PMS, "ProcessStatus из process_module должен быть тем же объектом что из base_manager"

    def test_shared_resources_import_is_same_object(self):
        """from shared_resources_module.types.types import ProcessStatus — тот же объект."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.shared_resources_module.types.types import (
            ProcessStatus as SRM,
        )

        assert Canonical is SRM, (
            "ProcessStatus из shared_resources_module должен быть тем же объектом что из base_manager"
        )

    def test_process_module_package_import(self):
        """from process_module.types import ProcessStatus — через __init__.py."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.process_module.types import ProcessStatus as PMS

        assert Canonical is PMS

    def test_shared_resources_package_import(self):
        """from shared_resources_module.types import ProcessStatus — через __init__.py."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.shared_resources_module.types import (
            ProcessStatus as SRM,
        )

        assert Canonical is SRM

    def test_process_module_top_level_import(self):
        """from process_module import ProcessStatus — через __init__.py модуля."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.process_module import ProcessStatus as PMS

        assert Canonical is PMS

    def test_shared_resources_top_level_import(self):
        """from shared_resources_module import ProcessStatus — через __init__.py модуля."""
        from multiprocess_framework.modules.base_manager.types import ProcessStatus as Canonical
        from multiprocess_framework.modules.shared_resources_module import (
            ProcessStatus as SRM,
        )

        assert Canonical is SRM

    def test_base_manager_top_level_import(self):
        """from base_manager import ProcessStatus — новый канонический путь."""
        from multiprocess_framework.modules.base_manager import ProcessStatus as BM
        from multiprocess_framework.modules.base_manager.types.process_status import (
            ProcessStatus as Source,
        )

        assert BM is Source


class TestStatusComparisonAcrossModules:
    """Сравнение ProcessStatus из разных модулей даёт True (один Python-объект)."""

    def test_running_is_identical_across_modules(self):
        """ProcessStatus.RUNNING из разных мест — один объект."""
        from multiprocess_framework.modules.process_module.types.types import (
            ProcessStatus as PMS,
        )
        from multiprocess_framework.modules.shared_resources_module.types.types import (
            ProcessStatus as SRM,
        )
        from multiprocess_framework.modules.base_manager.types import (
            ProcessStatus as BM,
        )

        assert PMS.RUNNING is BM.RUNNING
        assert SRM.RUNNING is BM.RUNNING
        assert PMS.RUNNING is SRM.RUNNING

    def test_all_common_values_identical(self):
        """Все 7 общих значений идентичны при импорте из разных мест."""
        from multiprocess_framework.modules.process_module.types.types import (
            ProcessStatus as PMS,
        )
        from multiprocess_framework.modules.shared_resources_module.types.types import (
            ProcessStatus as SRM,
        )

        common = ["INITIALIZING", "READY", "RUNNING", "STOPPING", "STOPPED", "ERROR", "CRASHED"]
        for name in common:
            assert getattr(PMS, name) is getattr(SRM, name), (
                f"ProcessStatus.{name} не идентичен между process_module и shared_resources"
            )

    def test_extended_values_available_from_shared_resources(self):
        """UNRESPONSIVE и FAILED доступны при импорте из shared_resources (т.к. это тот же enum)."""
        from multiprocess_framework.modules.shared_resources_module.types.types import (
            ProcessStatus as SRM,
        )

        # Раньше SRM не имел этих значений, теперь — имеет (единый enum)
        assert hasattr(SRM, "UNRESPONSIVE")
        assert hasattr(SRM, "FAILED")
        assert SRM.UNRESPONSIVE.value == "unresponsive"
        assert SRM.FAILED.value == "failed"

    def test_pickle_roundtrip(self):
        """Pickle round-trip работает для единого ProcessStatus."""
        import pickle
        from multiprocess_framework.modules.base_manager.types import ProcessStatus

        for status in ProcessStatus:
            assert pickle.loads(pickle.dumps(status)) == status
            assert pickle.loads(pickle.dumps(status)) is status
