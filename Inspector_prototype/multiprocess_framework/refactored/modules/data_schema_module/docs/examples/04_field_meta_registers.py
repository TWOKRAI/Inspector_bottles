# -*- coding: utf-8 -*-
"""
Пример 4: Новый подход — FieldMeta + RegisterBase.

Демонстрирует:
    - определение регистров через Annotated[T, FieldMeta(...)]
    - доступ к полям как plain-значениям
    - методы RegisterMixin (метаданные, валидация, маршрутизация)
    - RegistersContainer с IO (to_json / from_json / to_yaml)
    - персистентность через FileStorage (IRegisterStorage)
    - конфиги процессов на той же базе (RegisterBase)
"""
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
    RegistersContainer,
    FileStorage,
    discover_registers_from_package,
)


# =============================================================================
# 1. Определение регистров
# =============================================================================

class AlgorithmRegisters(RegisterBase):
    """Параметры алгоритма детекции."""

    threshold: Annotated[
        float,
        FieldMeta(
            "Порог уверенности",
            info="Минимальный порог для принятия результата.",
            min=0.0, max=1.0,
            transfer_k=100.0, round_k=2,
            routing={"channel": "control_algorithm"},
        ),
    ] = 0.5

    iterations: Annotated[
        int,
        FieldMeta(
            "Итерации",
            info="Число итераций алгоритма.",
            min=1, max=100,
        ),
    ] = 10

    enabled: bool = True


class ServerConfig(RegisterBase):
    """Конфиг сервера — тот же RegisterBase, только для конфигурации."""

    host: Annotated[
        str,
        FieldMeta("Адрес сервера", info="IP или hostname сервера."),
    ] = "localhost"

    port: Annotated[
        int,
        FieldMeta("Порт", info="TCP-порт.", min=1, max=65535),
    ] = 8080

    workers: Annotated[
        int,
        FieldMeta("Кол-во воркеров", info="Потоков обработки.", min=1, max=32),
    ] = 4

    debug: bool = False


# =============================================================================
# 2. Работа с полями
# =============================================================================

def demo_field_access():
    print("\n=== 1. Доступ к полям ===")

    r = AlgorithmRegisters()

    # Поле — plain float, не объект-обёртка
    print(f"threshold = {r.threshold}")          # → 0.5
    print(f"type = {type(r.threshold).__name__}") # → float

    # model_dump() — плоский dict, без вложений
    print(f"model_dump() = {r.model_dump()}")


def demo_field_meta():
    print("\n=== 2. Метаданные FieldMeta ===")

    # Метаданные доступны на уровне класса
    meta = AlgorithmRegisters.get_field_meta("threshold")
    print(f"description: {meta.description}")
    print(f"min: {meta.min}, max: {meta.max}")
    print(f"transfer_k: {meta.transfer_k}")
    print(f"routing: {meta.routing}")

    # Нет метаданных для plain-поля
    no_meta = AlgorithmRegisters.get_field_meta("enabled")
    print(f"enabled meta: {no_meta}")  # → None

    # Словарь метаданных для UI
    r = AlgorithmRegisters()
    print(f"to_dict(): {r.get_field_metadata('threshold')}")


def demo_validation():
    print("\n=== 3. Валидация ===")

    r = AlgorithmRegisters()

    # Валидное значение
    ok, err = r.update_field("threshold", 0.8)
    print(f"0.8 → ok={ok}, err={err}")       # ok=True

    # За диапазоном
    ok, err = r.update_field("threshold", 2.0)
    print(f"2.0 → ok={ok}, err={err}")       # ok=False

    # Значение НЕ изменилось
    print(f"После ошибки threshold = {r.threshold}")  # → 0.8

    # @model_validator ловит нарушение при создании
    try:
        AlgorithmRegisters(threshold=5.0)
    except ValueError as e:
        print(f"Ошибка при создании: {e}")


def demo_routing():
    print("\n=== 4. Маршрутизация ===")

    r = AlgorithmRegisters()
    print(f"Каналы: {r.get_routing_channels()}")
    print(f"Поля control_algorithm: {r.get_fields_for_channel('control_algorithm')}")


def demo_container():
    print("\n=== 5. RegistersContainer ===")

    container = RegistersContainer({
        "algorithm": AlgorithmRegisters,
        "server": ServerConfig,
    })

    print(f"Регистры: {container.register_names()}")
    print(f"algorithm.threshold = {container.algorithm.threshold}")
    print(f"server.port = {container.server.port}")

    # Изменяем и сериализуем
    container.algorithm.update_field("threshold", 0.9)
    json_str = container.to_json()
    print(f"JSON: {json_str[:120]}...")

    # Десериализуем в новый контейнер
    container2 = RegistersContainer({
        "algorithm": AlgorithmRegisters,
        "server": ServerConfig,
    })
    container2.from_json(json_str)
    print(f"После from_json threshold = {container2.algorithm.threshold}")  # → 0.9


def demo_file_storage():
    print("\n=== 6. FileStorage (IRegisterStorage) ===")

    container = RegistersContainer({
        "algorithm": AlgorithmRegisters,
        "server": ServerConfig,
    })
    container.algorithm.update_field("threshold", 0.75)
    container.server.update_field("port", 9000)

    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(Path(tmp) / "registers")

        # Сохраняем
        container.save(storage, "my_process")
        print(f"Сохранено: {storage.list_containers()}")

        # Загружаем в новый контейнер
        container2 = RegistersContainer({
            "algorithm": AlgorithmRegisters,
            "server": ServerConfig,
        })
        loaded = container2.load(storage, "my_process")
        print(f"Загружено: {loaded}")
        print(f"threshold после загрузки: {container2.algorithm.threshold}")  # → 0.75
        print(f"port после загрузки: {container2.server.port}")               # → 9000


def demo_clamp():
    print("\n=== 7. FieldMeta.clamp() и process_numeric() ===")

    meta = AlgorithmRegisters.get_field_meta("threshold")
    print(f"clamp(1.5) = {meta.clamp(1.5)}")      # → 1.0
    print(f"clamp(-0.1) = {meta.clamp(-0.1)}")    # → 0.0

    # Округление через round_value
    meta2 = AlgorithmRegisters.get_field_meta("threshold")
    print(f"round_value(0.12345) = {meta2.round_value(0.12345)}")  # → 0.12


if __name__ == "__main__":
    print("=" * 60)
    print("Пример 4: FieldMeta + RegisterBase")
    print("=" * 60)

    demo_field_access()
    demo_field_meta()
    demo_validation()
    demo_routing()
    demo_container()
    demo_file_storage()
    demo_clamp()

    print("\n" + "=" * 60)
    print("Все примеры выполнены успешно!")
