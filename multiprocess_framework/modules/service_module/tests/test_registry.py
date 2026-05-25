"""Тесты для ServiceRegistry, ServiceEntry и декоратора @register_service.

Покрытие: singleton, регистрация/дубликаты, get/list/filter,
unregister/clear, декоратор, thread-safety.

Фикстура `_clean_registry` (autouse) очищает singleton после каждого теста.
"""

from __future__ import annotations

import concurrent.futures
import threading

import pytest

from multiprocess_framework.modules.service_module.interfaces import (
    ServiceLifecycle,
)
from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
    register_service,
)


# ------------------------------------------------------------------
# Хелперы: классы-заглушки, совместимые с IService Protocol
# ------------------------------------------------------------------


class _DummyService:
    """Минимальный класс, структурно совместимый с IService."""

    name: str = "dummy"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "ok"}


class _AnotherService:
    """Второй сервис для тестов множественной регистрации."""

    name: str = "another"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "ok"}


class _ThirdService:
    """Третий сервис для тестов list()."""

    name: str = "third"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "ok"}


class _NoNameService:
    """Класс без атрибута name — для теста ошибки декоратора."""

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {}


# ------------------------------------------------------------------
# Фикстура: изоляция singleton между тестами
# ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищает реестр перед и после каждого теста."""
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


# ------------------------------------------------------------------
# 1. Singleton
# ------------------------------------------------------------------


class TestSingleton:
    """ServiceRegistry() всегда возвращает один и тот же экземпляр."""

    def test_singleton_same_instance(self):
        """ServiceRegistry() is ServiceRegistry() -> True."""
        r1 = ServiceRegistry()
        r2 = ServiceRegistry()
        assert r1 is r2

    def test_singleton_preserves_state(self):
        """Данные, добавленные через один ref, видны через другой."""
        r1 = ServiceRegistry()
        r2 = ServiceRegistry()
        entry = ServiceEntry(name="svc", cls=_DummyService)
        r1.register(entry)
        assert r2.get("svc") is entry


# ------------------------------------------------------------------
# 2. register / get
# ------------------------------------------------------------------


class TestRegisterGet:
    """Тесты на register() и get()."""

    def test_register_adds_entry(self):
        """После register(entry), get(name) возвращает её."""
        registry = ServiceRegistry()
        entry = ServiceEntry(
            name="dummy",
            cls=_DummyService,
            lifecycle=ServiceLifecycle.READY,
        )
        registry.register(entry)
        result = registry.get("dummy")
        assert result is entry
        assert result.name == "dummy"
        assert result.cls is _DummyService
        assert result.lifecycle == ServiceLifecycle.READY

    def test_register_duplicate_raises(self):
        """Повторная регистрация того же name -> ValueError."""
        registry = ServiceRegistry()
        entry1 = ServiceEntry(name="dup", cls=_DummyService)
        entry2 = ServiceEntry(name="dup", cls=_AnotherService)
        registry.register(entry1)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            registry.register(entry2)

    def test_get_missing_returns_none(self):
        """get('nonexistent') -> None."""
        assert ServiceRegistry().get("nonexistent") is None


# ------------------------------------------------------------------
# 3. list
# ------------------------------------------------------------------


class TestList:
    """Тесты на list()."""

    def test_list_empty(self):
        """Пустой реестр -> []."""
        assert ServiceRegistry().list() == []

    def test_list_returns_all(self):
        """После 3 регистраций list() содержит все 3."""
        registry = ServiceRegistry()
        classes = [_DummyService, _AnotherService, _ThirdService]
        for cls in classes:
            registry.register(ServiceEntry(name=cls.name, cls=cls))
        result = registry.list()
        assert len(result) == 3
        names = {e.name for e in result}
        assert names == {"dummy", "another", "third"}

    def test_list_returns_copy(self):
        """list() возвращает копию — мутация не влияет на реестр."""
        registry = ServiceRegistry()
        registry.register(ServiceEntry(name="x", cls=_DummyService))
        lst = registry.list()
        lst.clear()
        assert len(registry.list()) == 1


# ------------------------------------------------------------------
# 4. filter
# ------------------------------------------------------------------


class TestFilter:
    """Тесты на filter()."""

    def test_filter_by_lifecycle(self):
        """filter(RUNNING) возвращает только RUNNING."""
        registry = ServiceRegistry()
        registry.register(
            ServiceEntry(
                name="running1",
                cls=_DummyService,
                lifecycle=ServiceLifecycle.RUNNING,
            )
        )
        registry.register(
            ServiceEntry(
                name="stopped1",
                cls=_AnotherService,
                lifecycle=ServiceLifecycle.STOPPED,
            )
        )
        registry.register(
            ServiceEntry(
                name="running2",
                cls=_ThirdService,
                lifecycle=ServiceLifecycle.RUNNING,
            )
        )
        result = registry.filter(ServiceLifecycle.RUNNING)
        assert len(result) == 2
        names = {e.name for e in result}
        assert names == {"running1", "running2"}

    def test_filter_empty_match(self):
        """filter(STOPPED) при пустом реестре -> []."""
        assert ServiceRegistry().filter(ServiceLifecycle.STOPPED) == []

    def test_filter_returns_copy(self):
        """filter() возвращает копию — безопасна для итерации."""
        registry = ServiceRegistry()
        registry.register(
            ServiceEntry(
                name="r",
                cls=_DummyService,
                lifecycle=ServiceLifecycle.READY,
            )
        )
        filtered = registry.filter(ServiceLifecycle.READY)
        filtered.clear()
        assert len(registry.filter(ServiceLifecycle.READY)) == 1


# ------------------------------------------------------------------
# 5. unregister
# ------------------------------------------------------------------


class TestUnregister:
    """Тесты на unregister()."""

    def test_unregister_removes(self):
        """После unregister(name), get(name) -> None."""
        registry = ServiceRegistry()
        registry.register(ServiceEntry(name="rem", cls=_DummyService))
        assert registry.unregister("rem") is True
        assert registry.get("rem") is None

    def test_unregister_missing_returns_false(self):
        """unregister('nonexistent') -> False."""
        assert ServiceRegistry().unregister("nonexistent") is False


# ------------------------------------------------------------------
# 6. clear
# ------------------------------------------------------------------


class TestClear:
    """Тесты на clear()."""

    def test_clear_empties_registry(self):
        """После clear(), list() -> []."""
        registry = ServiceRegistry()
        registry.register(ServiceEntry(name="a", cls=_DummyService))
        registry.register(ServiceEntry(name="b", cls=_AnotherService))
        assert len(registry.list()) == 2
        registry.clear()
        assert registry.list() == []


# ------------------------------------------------------------------
# 7. Декоратор @register_service
# ------------------------------------------------------------------


class TestDecorator:
    """Тесты на декоратор @register_service."""

    def test_decorator_registers_class(self):
        """@register_service с явным name='foo' регистрирует класс."""

        @register_service(name="foo")
        class FooService:
            name: str = "foo"

            def start(self, config: dict) -> bool:
                return True

            def stop(self) -> bool:
                return True

            def get_status(self) -> dict:
                return {}

        entry = ServiceRegistry().get("foo")
        assert entry is not None
        assert entry.cls is FooService
        assert entry.lifecycle == ServiceLifecycle.READY

    def test_decorator_uses_class_name_attr(self):
        """@register_service() без аргументов читает cls.name."""

        @register_service()
        class BarService:
            name: str = "bar_svc"

            def start(self, config: dict) -> bool:
                return True

            def stop(self) -> bool:
                return True

            def get_status(self) -> dict:
                return {}

        entry = ServiceRegistry().get("bar_svc")
        assert entry is not None
        assert entry.cls is BarService

    def test_decorator_no_name_raises(self):
        """@register_service() без name и без cls.name -> ValueError."""
        with pytest.raises(ValueError, match="не имеет атрибута 'name'"):

            @register_service()
            class _BadService:
                def start(self, config: dict) -> bool:
                    return True

                def stop(self) -> bool:
                    return True

                def get_status(self) -> dict:
                    return {}

    def test_decorator_with_meta(self):
        """@register_service(meta={...}) сохраняет meta в entry."""
        meta_data = {"vendor": "opencv", "version": "4.13"}

        @register_service(name="meta_svc", meta=meta_data)
        class MetaService:
            name: str = "meta_svc"

            def start(self, config: dict) -> bool:
                return True

            def stop(self) -> bool:
                return True

            def get_status(self) -> dict:
                return {}

        entry = ServiceRegistry().get("meta_svc")
        assert entry is not None
        assert entry.meta == {"vendor": "opencv", "version": "4.13"}

    def test_decorator_duplicate_raises(self):
        """Два класса с одним name через декоратор -> ValueError на втором."""

        @register_service(name="conflict")
        class ServiceA:
            name: str = "conflict"

            def start(self, config: dict) -> bool:
                return True

            def stop(self) -> bool:
                return True

            def get_status(self) -> dict:
                return {}

        with pytest.raises(ValueError, match="уже зарегистрирован"):

            @register_service(name="conflict")
            class ServiceB:
                name: str = "conflict"

                def start(self, config: dict) -> bool:
                    return True

                def stop(self) -> bool:
                    return True

                def get_status(self) -> dict:
                    return {}

    def test_decorator_returns_original_class(self):
        """Декоратор возвращает оригинальный класс (не обёртку)."""

        @register_service(name="orig")
        class OrigService:
            name: str = "orig"

            def start(self, config: dict) -> bool:
                return True

            def stop(self) -> bool:
                return True

            def get_status(self) -> dict:
                return {}

        assert OrigService.__name__ == "OrigService"
        assert OrigService.name == "orig"


# ------------------------------------------------------------------
# 8. IService-совместимый класс
# ------------------------------------------------------------------


class TestIServiceCompatibility:
    """Проверка что структурный класс с start/stop/get_status/name регистрируется."""

    def test_register_with_iservice_class_ok(self):
        """Класс с полным IService-контрактом регистрируется без ошибок."""
        registry = ServiceRegistry()
        entry = ServiceEntry(
            name="iservice_ok",
            cls=_DummyService,
            lifecycle=ServiceLifecycle.READY,
            meta={"test": True},
        )
        registry.register(entry)
        result = registry.get("iservice_ok")
        assert result is not None
        assert result.cls is _DummyService
        assert result.meta == {"test": True}


# ------------------------------------------------------------------
# 9. Thread-safety
# ------------------------------------------------------------------


class TestThreadSafety:
    """Конкурентный доступ к реестру."""

    def test_thread_safety_concurrent_register(self):
        """10 потоков регистрируют 10 разных имён -> все попадают в реестр."""
        registry = ServiceRegistry()
        barrier = threading.Barrier(10)
        errors: list[str] = []

        def _register_one(idx: int) -> None:
            # Создаём уникальный класс для каждого потока
            svc_cls = type(
                f"Svc{idx}",
                (),
                {
                    "name": f"svc_{idx}",
                    "start": lambda self, config: True,
                    "stop": lambda self: True,
                    "get_status": lambda self: {},
                },
            )
            entry = ServiceEntry(
                name=f"svc_{idx}",
                cls=svc_cls,
                lifecycle=ServiceLifecycle.READY,
            )
            barrier.wait()  # все потоки стартуют одновременно
            try:
                registry.register(entry)
            except Exception as exc:
                errors.append(f"svc_{idx}: {exc}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_register_one, i) for i in range(10)]
            concurrent.futures.wait(futures)

        assert not errors, f"Ошибки при конкурентной регистрации: {errors}"
        assert len(registry.list()) == 10

    def test_thread_safety_concurrent_read_write(self):
        """Параллельные чтения и записи не вызывают RuntimeError."""
        registry = ServiceRegistry()
        stop_event = threading.Event()
        read_errors: list[str] = []

        # Заполним стартовыми данными
        for i in range(5):
            svc_cls = type(
                f"Pre{i}",
                (),
                {
                    "name": f"pre_{i}",
                    "start": lambda self, config: True,
                    "stop": lambda self: True,
                    "get_status": lambda self: {},
                },
            )
            registry.register(ServiceEntry(name=f"pre_{i}", cls=svc_cls))

        def _reader() -> None:
            """Читает list() и filter() в цикле."""
            while not stop_event.is_set():
                try:
                    registry.list()
                    registry.filter(ServiceLifecycle.READY)
                    registry.get("pre_0")
                except RuntimeError as exc:
                    read_errors.append(str(exc))

        def _writer() -> None:
            """Регистрирует и удаляет записи."""
            for j in range(20):
                svc_cls = type(
                    f"W{j}",
                    (),
                    {
                        "name": f"w_{j}",
                        "start": lambda self, config: True,
                        "stop": lambda self: True,
                        "get_status": lambda self: {},
                    },
                )
                try:
                    registry.register(ServiceEntry(name=f"w_{j}", cls=svc_cls))
                except ValueError:
                    pass  # дубликат — ок в этом тесте
                registry.unregister(f"w_{j}")
            stop_event.set()

        reader = threading.Thread(target=_reader)
        writer = threading.Thread(target=_writer)
        reader.start()
        writer.start()
        writer.join(timeout=5)
        stop_event.set()
        reader.join(timeout=5)

        assert not read_errors, f"RuntimeError при параллельном чтении: {read_errors}"


# ------------------------------------------------------------------
# 10. Dunder-методы
# ------------------------------------------------------------------


class TestDunderMethods:
    """__len__, __contains__, __repr__."""

    def test_len(self):
        """len(registry) == количество записей."""
        registry = ServiceRegistry()
        assert len(registry) == 0
        registry.register(ServiceEntry(name="x", cls=_DummyService))
        assert len(registry) == 1

    def test_contains(self):
        """'name' in registry -> True/False."""
        registry = ServiceRegistry()
        registry.register(ServiceEntry(name="c", cls=_DummyService))
        assert "c" in registry
        assert "z" not in registry

    def test_repr(self):
        """repr содержит количество сервисов."""
        registry = ServiceRegistry()
        assert "services=0" in repr(registry)
        registry.register(ServiceEntry(name="r", cls=_DummyService))
        assert "services=1" in repr(registry)
