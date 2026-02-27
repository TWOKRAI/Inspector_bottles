# -*- coding: utf-8 -*-
"""
Регистры отрисовки.
Поля заданы через схему: переопределяем только нужное, остальное по умолчанию.
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema.field_schema import DEFAULT_FIELD_SCHEMA
from App.Registers.models.field_registers.data_schema.metadata_helper import RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class DrawRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры отрисовки"""

    dp: float = field_from_schema(
        1.4,
        description='Обратное разрешение аккумулятора',
        min=0.1,
        max=20.0,
        transfer_k=0.1,
        round_k=1,
        info='Обратное разрешение аккумулятора для детектора кругов. Меньшие значения дают более точное обнаружение, но требуют больше вычислений.',
        info_i18n={
            'ru': 'Обратное разрешение аккумулятора для детектора кругов. Меньшие значения дают более точное обнаружение, но требуют больше вычислений.',
            'en': 'Inverse accumulator resolution for circle detector. Smaller values provide more accurate detection but require more computation.',
            'de': 'Inverse Akkumulatorauflösung für Kreiserkennung. Kleinere Werte ermöglichen genauere Erkennung, erfordern aber mehr Berechnung.',
        },
        description_i18n={
            'ru': 'Обратное разрешение аккумулятора',
            'en': 'Inverse accumulator resolution',
            'de': 'Inverse Akkumulatorauflösung',
        },
        examples=[1.0, 1.4, 2.0],
        routing={'channel': 'control_draw'},
    )

    minDist: int = field_from_schema(
        51,
        description='Минимальное расстояние между центрами кругов',
        info='Минимальное расстояние между центрами обнаруженных кругов в пикселях. Если круги находятся ближе этого расстояния, выбирается только один.',
        min=0,
        max=1000,
        unit='px',
        info_i18n={
            'ru': 'Минимальное расстояние между центрами обнаруженных кругов в пикселях. Если круги находятся ближе этого расстояния, выбирается только один.',
            'en': 'Minimum distance between centers of detected circles in pixels. If circles are closer than this distance, only one is selected.',
            'de': 'Mindestabstand zwischen den Mittelpunkten erkannte Kreise in Pixeln. Wenn Kreise näher als dieser Abstand sind, wird nur einer ausgewählt.',
        },
        description_i18n={
            'ru': 'Минимальное расстояние между центрами кругов',
            'en': 'Minimum distance between circle centers',
            'de': 'Mindestabstand zwischen Kreismittelpunkten',
        },
        examples=[50, 100, 200],
        routing={'channel': 'control_draw'},
    )

    param1: int = field_from_schema(
        47,
        description='Верхний порог для детектора',
        min=0,
        max=200,
        info='Верхний порог для внутреннего детектора краёв. Используется в алгоритме детекции кругов.',
        examples=[30, 50, 100],
        routing={'channel': 'control_draw'},
    )

    param2: int = field_from_schema(
        31,
        description='Порог накопления для центра круга',
        min=0,
        max=200,
        info='Порог накопления для центра круга. Меньшие значения дают больше обнаруженных кругов, но могут быть ложные срабатывания.',
        examples=[20, 30, 50],
        routing={'channel': 'control_draw'},
    )

    minRadius: int = field_from_schema(
        22,
        description='Минимальный радиус круга',
        min=0,
        max=1000,
        unit='px',
        info='Минимальный радиус круга для обнаружения в пикселях. Круги с меньшим радиусом игнорируются.',
        examples=[10, 20, 50],
        routing={'channel': 'control_draw'},
    )

    maxRadius: int = field_from_schema(
        41,
        description='Максимальный радиус круга',
        min=0,
        max=1000,
        unit='px',
        info='Максимальный радиус круга для обнаружения в пикселях. Круги с большим радиусом игнорируются.',
        examples=[50, 100, 200],
        routing={'channel': 'control_draw'},
    )
