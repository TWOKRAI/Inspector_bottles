import cv2
import numpy as np


def is_color_area_above_threshold(image, target_color, threshold_percentage):
    if not isinstance(image, np.ndarray):
        return False
    
        # Проверяем, что массив имеет три измерения (высота, ширина, каналы)
    if len(image.shape) != 3:
        return False

    # Проверяем, что тип данных массива - uint8
    if image.dtype != np.uint8:
        return False

    # Преобразование цвета из BGR в HSV
    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Определение диапазона цвета
    lower_bound = np.array(target_color['lower'])
    upper_bound = np.array(target_color['upper'])

    # Создание маски для выбранного цвета
    mask = cv2.inRange(hsv_image, lower_bound, upper_bound)

    # Вычисление площади выбранного цвета
    color_area = np.sum(mask == 255)

    # Вычисление общей площади изображения
    total_area = image.shape[0] * image.shape[1]

    # Вычисление процентной доли площади выбранного цвета
    color_percentage = (color_area / total_area) * 100

    #print('color_percentage', color_percentage)

    # Сравнение с заданным порогом
    return color_percentage > threshold_percentage
