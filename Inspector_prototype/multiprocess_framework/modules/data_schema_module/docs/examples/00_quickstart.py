# -*- coding: utf-8 -*-
"""
Quickstart: весь стек data_schema_module за 5 минут.

Показывает:
    1. Определение регистров через FieldMeta + FieldRouting + type aliases
    2. Работа с полями (plain values, model_dump, update_field)
    3. Метаданные (get_field_meta, get_field_metadata, маршрутизация)
    4. RegistersContainer (дандеры, diff, save/load через FileStorage)
    5. Конфиги процессов на той же базе (RegisterBase)
    6. Дата-модели (BaseModel, без метаданных)
"""
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterBase,
    RegistersContainer,
    FileStorage,
    # Готовые type aliases
    Percent,
    Pixels,
    HsvHue,
    HsvChannel,
    Seconds,
    NormalizedFloat,
)
from pydantic import BaseModel


# =============================================================================
# 1. Определение регистров
# =============================================================================

# FieldRouting: один объект вместо повторного {"channel": "control_draw"}
DRAW = FieldRouting(channel="control_draw")

class DrawRegisters(RegisterBase):
    """Параметры детектора кругов HoughCircles."""

    dp: Annotated[float, FieldMeta(
        "Разрешение аккумулятора",
        info="Обратное разрешение. Чем меньше — тем точнее.",
        min=0.1, max=20.0, transfer_k=0.1, round_k=1,
        routing=DRAW,
    )] = 1.4

    minDist: Annotated[float, FieldMeta(
        "Мин. расстояние между кругами", unit="px", min=0.0, max=1000.0,
        routing=DRAW,
    )] = 50.0

    enabled: bool = True


class ProcessingRegisters(RegisterBase):
    """Регистры обработки — используют type aliases."""

    # HsvHue / HsvChannel — готовые типы вместо повторного Annotated[int, FieldMeta(...)]
    hl: HsvHue = 0
    hm: HsvHue = 179
    sl: HsvChannel = 0
    sm: HsvChannel = 255

    # Pixels — аналогично
    crop_top: Pixels = 0
    crop_right: Pixels = 3840

    # Threshold как NormalizedFloat
    threshold: NormalizedFloat = 0.5


# =============================================================================
# 2. Работа с полями
# =============================================================================

def demo_fields():
    print("\n--- 2. Поля как plain-значения ---")
    r = DrawRegisters()

    print(f"r.dp = {r.dp}  (тип: {type(r.dp).__name__})")  # 1.4  float
    print(f"r.model_dump() = {r.model_dump()}")

    # update_field: валидация + присвоение
    ok, err = r.update_field("dp", 3.0)
    print(f"update_field(3.0) → ok={ok}")

    ok, err = r.update_field("dp", 999.0)
    print(f"update_field(999.0) → ok={ok}, err={err}")
    print(f"dp после ошибки = {r.dp}")  # → 3.0, не изменилось


# =============================================================================
# 3. Метаданные
# =============================================================================

def demo_metadata():
    print("\n--- 3. Метаданные ---")
    r = DrawRegisters()

    meta = DrawRegisters.get_field_meta("dp")
    print(f"meta.min={meta.min}, meta.max={meta.max}, meta.routing={meta.routing}")

    # Словарь для UI
    d = r.get_field_metadata("dp")
    print(f"get_field_metadata('dp') = {d}")

    # Маршрутизация
    print(f"Каналы: {r.get_routing_channels()}")
    print(f"Поля 'control_draw': {r.get_fields_for_channel('control_draw')}")

    # Type alias также содержит FieldMeta
    meta_hue = ProcessingRegisters.get_field_meta("hl")
    print(f"HsvHue meta: {meta_hue}")


# =============================================================================
# 4. RegistersContainer
# =============================================================================

def demo_container():
    print("\n--- 4. RegistersContainer ---")

    container = RegistersContainer({
        "draw": DrawRegisters,
        "processing": ProcessingRegisters,
    })

    # Атрибутный и индексный доступ
    print(f"container.draw.dp = {container.draw.dp}")
    print(f"container['draw'].dp = {container['draw'].dp}")

    # Дандеры
    print(f"'draw' in container = {'draw' in container}")
    print(f"len(container) = {len(container)}")
    print(f"Итерация: {[name for name, _ in container]}")

    # diff: только изменённые поля
    snap = container.snapshot()
    container.draw.update_field("dp", 5.0)
    changes = container.diff(snap)
    print(f"diff() = {changes}")  # {'draw': {'dp': 5.0}}


# =============================================================================
# 5. FileStorage
# =============================================================================

def demo_storage():
    print("\n--- 5. FileStorage ---")

    container = RegistersContainer({
        "draw": DrawRegisters,
        "processing": ProcessingRegisters,
    })
    container.draw.update_field("dp", 7.7)

    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(Path(tmp) / "registers")
        container.save(storage, "main_process")
        print(f"Сохранено: {storage.list_containers()}")

        container2 = RegistersContainer({
            "draw": DrawRegisters,
            "processing": ProcessingRegisters,
        })
        loaded = container2.load(storage, "main_process")
        print(f"Загружено: {loaded}, dp = {container2.draw.dp}")


# =============================================================================
# 6. RegisterBase как конфиг процесса (не только UI-регистры)
# =============================================================================

def demo_config():
    print("\n--- 6. Конфиг процесса ---")

    class ServerConfig(RegisterBase):
        host: Annotated[str, FieldMeta("Адрес сервера")] = "localhost"
        port: Annotated[int, FieldMeta("Порт", min=1, max=65535)] = 8080
        timeout: Seconds = 5.0  # type alias
        debug: bool = False

    cfg = ServerConfig(port=9090)
    print(f"ServerConfig: {cfg.model_dump()}")
    print(f"port meta: {ServerConfig.get_field_meta('port').max}")  # → 65535


# =============================================================================
# 7. Дата-модели (BaseModel, без метаданных)
# =============================================================================

def demo_data_models():
    print("\n--- 7. Дата-модели ---")

    class RegionData(BaseModel):
        x1: int = 0; y1: int = 0
        x2: int = 100; y2: int = 100
        enabled: bool = True

    class CameraData(BaseModel):
        name: str = "unknown"
        regions: dict[str, RegionData] = {}

    cam = CameraData(
        name="cam_01",
        regions={"roi_1": RegionData(x1=10, y1=20, x2=110, y2=120)},
    )
    print(f"CameraData: {cam.model_dump()}")


if __name__ == "__main__":
    print("=" * 60)
    print("data_schema_module — Quickstart")
    print("=" * 60)

    demo_fields()
    demo_metadata()
    demo_container()
    demo_storage()
    demo_config()
    demo_data_models()

    print("\n" + "=" * 60)
    print("Quickstart завершён.")
