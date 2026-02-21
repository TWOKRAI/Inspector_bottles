# -*- coding: utf-8 -*-
"""
Регистры отрисовки.
"""
from pydantic import BaseModel, Field


class DrawRegisters(BaseModel):
    """Регистры отрисовки"""
    
    dp: float = Field(
        default=1.4,
        description='Обратное разрешение аккумулятора',
        json_schema_extra={
            'info': 'Обратное разрешение аккумулятора для детектора кругов. Меньшие значения дают более точное обнаружение, но требуют больше вычислений.',
            'info_i18n': {
                'ru': 'Обратное разрешение аккумулятора для детектора кругов. Меньшие значения дают более точное обнаружение, но требуют больше вычислений.',
                'en': 'Inverse accumulator resolution for circle detector. Smaller values provide more accurate detection but require more computation.',
                'de': 'Inverse Akkumulatorauflösung für Kreiserkennung. Kleinere Werte ermöglichen genauere Erkennung, erfordern aber mehr Berechnung.'
            },
            'description_i18n': {
                'ru': 'Обратное разрешение аккумулятора',
                'en': 'Inverse accumulator resolution',
                'de': 'Inverse Akkumulatorauflösung'
            },
            'unit': '',
            'min': 0.1,
            'max': 20.0,
            'transfer_k': 0.1,
            'round_k': 1,
            'range': '0.1-20.0',
            'access_level': 1,
            'examples': [1.0, 1.4, 2.0]

        }
    )
    
    minDist: int = Field(
        default=51,
        description='Минимальное расстояние между центрами кругов',
        json_schema_extra={
            'info': 'Минимальное расстояние между центрами обнаруженных кругов в пикселях. Если круги находятся ближе этого расстояния, выбирается только один.',
            'info_i18n': {
                'ru': 'Минимальное расстояние между центрами обнаруженных кругов в пикселях. Если круги находятся ближе этого расстояния, выбирается только один.',
                'en': 'Minimum distance between centers of detected circles in pixels. If circles are closer than this distance, only one is selected.',
                'de': 'Mindestabstand zwischen den Mittelpunkten erkannte Kreise in Pixeln. Wenn Kreise näher als dieser Abstand sind, wird nur einer ausgewählt.'
            },
            'description_i18n': {
                'ru': 'Минимальное расстояние между центрами кругов',
                'en': 'Minimum distance between circle centers',
                'de': 'Mindestabstand zwischen Kreismittelpunkten'
            },
            'unit': 'px',
            'min': 0,
            'max': 1000,
            'range': '0-1000',
            'access_level': 1,
            'examples': [50, 100, 200]
        }
    )
    
    param1: int = Field(
        default=47,
        description='Верхний порог для детектора',
        json_schema_extra={
            'info': 'Верхний порог для внутреннего детектора краёв. Используется в алгоритме детекции кругов.',
            'unit': '',
            'min': 0,
            'max': 200,
            'range': '0-200',
            'access_level': 1,
            'examples': [30, 50, 100]
        }
    )
    
    param2: int = Field(
        default=31,
        description='Порог накопления для центра круга',
        json_schema_extra={
            'info': 'Порог накопления для центра круга. Меньшие значения дают больше обнаруженных кругов, но могут быть ложные срабатывания.',
            'unit': '',
            'min': 0,
            'max': 200,
            'range': '0-200',
            'access_level': 1,
            'examples': [20, 30, 50]
        }
    )
    
    minRadius: int = Field(
        default=22,
        description='Минимальный радиус круга',
        json_schema_extra={
            'info': 'Минимальный радиус круга для обнаружения в пикселях. Круги с меньшим радиусом игнорируются.',
            'unit': 'px',
            'min': 0,
            'max': 1000,
            'range': '0-1000',
            'access_level': 1,
            'examples': [10, 20, 50]
        }
    )
    
    maxRadius: int = Field(
        default=41,
        description='Максимальный радиус круга',
        json_schema_extra={
            'info': 'Максимальный радиус круга для обнаружения в пикселях. Круги с большим радиусом игнорируются.',
            'unit': 'px',
            'min': 0,
            'max': 1000,
            'range': '0-1000',
            'access_level': 1,
            'examples': [50, 100, 200]
        }
    )
