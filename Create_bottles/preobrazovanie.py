import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict, Callable, Any
from enum import Enum


def detect_horizontal_lines(image_bw, 
                           canny_threshold1=30, 
                           canny_threshold2=90,
                           hough_threshold=50,
                           theta=np.pi/180,
                           min_line_length=50,
                           max_line_gap=20,
                           angle_tolerance=5,
                           morph_size=10):
    """
    Обнаруживает горизонтальные линии на черно-белом изображении
    
    Параметры:
        debug: если True, показывает промежуточные этапы обработки
    """

    all_image = {}
    
    # 3. Детектирование границ
    edges = cv2.Canny(image_bw, canny_threshold1, canny_threshold2)

    all_image['edges'] = edges
    
    if morph_size > 0:
        # 4. Морфологические операции для усиления линий
        kernel_horizontal = np.ones((1, morph_size), np.uint8)
        enhanced = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel_horizontal)
    else:
        enhanced = edges
    
    all_image['enhanced'] = enhanced
    
    # 5. Применяем преобразование Хафа
    lines = cv2.HoughLinesP(
        enhanced,
        rho=1,
        theta=theta,
        threshold=hough_threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap
    )
    
    horizontal_lines = []
    
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            
            # Фильтр горизонтальных линий (0° и 180° ± допуск)
            if (abs(angle) < angle_tolerance) or (abs(angle) > 180 - angle_tolerance):
                horizontal_lines.append((x1, y1, x2, y2))
    
    return horizontal_lines, all_image


class GrayConversionMethod(Enum):
    """Методы преобразования в оттенки серого"""
    DEFAULT = "default"
    WEIGHTED = "weighted"
    AVERAGE = "average"
    LUMINANCE = "luminance"
    DESATURATION = "desaturation"


class ThresholdMethod(Enum):
    """Методы бинаризации"""
    BINARY = "binary"
    ADAPTIVE_GAUSSIAN = "adaptive_gaussian"
    ADAPTIVE_MEAN = "adaptive_mean"
    OTSU = "otsu"


class MorphOperation(Enum):
    """Морфологические операции"""
    OPEN = "open"
    CLOSE = "close"
    DILATE = "dilate"
    ERODE = "erode"
    GRADIENT = "gradient"
    TOPHAT = "tophat"
    BLACKHAT = "blackhat"


class ContourFilterMethod(Enum):
    """Методы фильтрации контуров"""
    AREA = "area"
    WIDTH = "width"
    HEIGHT = "height"
    ASPECT_RATIO = "aspect_ratio"
    SOLIDITY = "solidity"
    EXTENT = "extent"


class ObjectDetector:
    """
    Универсальный класс для обнаружения объектов на изображении с настраиваемыми методами обработки.
    """
    
    GRAY_CONVERSION_METHODS = {
        GrayConversionMethod.DEFAULT: {
            "function": lambda img: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
            "description": "Стандартное преобразование BGR в GRAY"
        },
        GrayConversionMethod.WEIGHTED: {
            "function": lambda img: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
            "description": "Взвешенное преобразование (использует стандартный метод OpenCV)"
        },
        GrayConversionMethod.AVERAGE: {
            "function": lambda img: np.mean(img, axis=2).astype(np.uint8),
            "description": "Усреднение каналов"
        },
        GrayConversionMethod.LUMINANCE: {
            "function": lambda img: (0.299 * img[:,:,2] + 0.587 * img[:,:,1] + 0.114 * img[:,:,0]).astype(np.uint8),
            "description": "Преобразование по яркости (ITU-R BT.601)"
        },
        GrayConversionMethod.DESATURATION: {
            "function": lambda img: ((np.max(img, axis=2) + np.min(img, axis=2)) / 2).astype(np.uint8),
            "description": "Десатурация (усреднение мин и макс)"
        }
    }
    
    THRESHOLD_METHODS = {
        ThresholdMethod.BINARY: {
            "function": cv2.threshold,
            "description": "Простая бинаризация с фиксированным порогом",
            "params": ["thresh", "maxval", "type"]
        },
        ThresholdMethod.ADAPTIVE_GAUSSIAN: {
            "function": cv2.adaptiveThreshold,
            "description": "Адаптивная бинаризация с гауссовым окном",
            "params": ["maxValue", "adaptiveMethod", "thresholdType", "blockSize", "C"]
        },
        ThresholdMethod.ADAPTIVE_MEAN: {
            "function": cv2.adaptiveThreshold,
            "description": "Адаптивная бинаризация по среднему значению",
            "params": ["maxValue", "adaptiveMethod", "thresholdType", "blockSize", "C"]
        },
        ThresholdMethod.OTSU: {
            "function": cv2.threshold,
            "description": "Бинаризация с методом Оцу",
            "params": ["thresh", "maxval", "type"]
        }
    }
    
    MORPH_OPERATIONS = {
        MorphOperation.OPEN: {
            "function": cv2.morphologyEx,
            "description": "Открытие (эрозия с последующей дилатацией)",
            "default_params": {"op": cv2.MORPH_OPEN, "kernel_size": 5, "iterations": 1}
        },
        MorphOperation.CLOSE: {
            "function": cv2.morphologyEx,
            "description": "Закрытие (дилатация с последующей эрозией)",
            "default_params": {"op": cv2.MORPH_CLOSE, "kernel_size": 5, "iterations": 1}
        },
        MorphOperation.DILATE: {
            "function": cv2.dilate,
            "description": "Дилатация (расширение объектов)",
            "default_params": {"kernel_size": 5, "iterations": 1}
        },
        MorphOperation.ERODE: {
            "function": cv2.erode,
            "description": "Эрозия (сужение объектов)",
            "default_params": {"kernel_size": 5, "iterations": 1}
        },
        MorphOperation.GRADIENT: {
            "function": cv2.morphologyEx,
            "description": "Морфологический градиент (разница между дилатацией и эрозией)",
            "default_params": {"op": cv2.MORPH_GRADIENT, "kernel_size": 5, "iterations": 1}
        },
        MorphOperation.TOPHAT: {
            "function": cv2.morphologyEx,
            "description": "Top-hat преобразование (разница между исходным и открытым изображением)",
            "default_params": {"op": cv2.MORPH_TOPHAT, "kernel_size": 5, "iterations": 1}
        },
        MorphOperation.BLACKHAT: {
            "function": cv2.morphologyEx,
            "description": "Black-hat преобразование (разница между закрытым и исходным изображением)",
            "default_params": {"op": cv2.MORPH_BLACKHAT, "kernel_size": 5, "iterations": 1}
        }
    }
    
    CONTOUR_FILTER_METHODS = {
        ContourFilterMethod.AREA: {
            "function": lambda cnt, params: cv2.contourArea(cnt) > params.get("min_area", 1000),
            "description": "Фильтрация по минимальной площади контура",
            "default_params": {"min_area": 1000}
        },
        ContourFilterMethod.WIDTH: {
            "function": lambda cnt, params: cv2.boundingRect(cnt)[2] > params.get("min_width", 10),
            "description": "Фильтрация по минимальной ширине",
            "default_params": {"min_width": 10}
        },
        ContourFilterMethod.HEIGHT: {
            "function": lambda cnt, params: cv2.boundingRect(cnt)[3] > params.get("min_height", 10),
            "description": "Фильтрация по минимальной высоте",
            "default_params": {"min_height": 10}
        },
        ContourFilterMethod.ASPECT_RATIO: {
            "function": lambda cnt, params: (
                lambda w, h: (w / max(h, 1)) > params.get("min_ratio", 0.1) and 
                (w / max(h, 1)) < params.get("max_ratio", 10.0)
            )(cv2.boundingRect(cnt)[2], cv2.boundingRect(cnt)[3]),
            "description": "Фильтрация по соотношению сторон",
            "default_params": {"min_ratio": 0.1, "max_ratio": 10.0}
        },
        ContourFilterMethod.SOLIDITY: {
            "function": lambda cnt, params: (
                lambda area, hull_area: hull_area > 0 and area / hull_area > params.get("min_solidity", 0.5)
            )(cv2.contourArea(cnt), cv2.contourArea(cv2.convexHull(cnt))),
            "description": "Фильтрация по солидности (отношение площади к площади выпуклой оболочки)",
            "default_params": {"min_solidity": 0.5}
        },
        ContourFilterMethod.EXTENT: {
            "function": lambda cnt, params: (
                lambda area, w, h: area / (w * h) > params.get("min_extent", 0.5)
            )(cv2.contourArea(cnt), *cv2.boundingRect(cnt)[2:]),
            "description": "Фильтрация по экстенту (отношение площади к площади ограничивающего прямоугольника)",
            "default_params": {"min_extent": 0.5}
        }
    }
    
    def __init__(
        self,
        gray_conversion_method: GrayConversionMethod = GrayConversionMethod.DEFAULT,
        threshold_method: ThresholdMethod = ThresholdMethod.BINARY,
        morph_operations: Optional[List[Dict]] = None,
        contour_filter_method: ContourFilterMethod = ContourFilterMethod.AREA,
        threshold_params: Optional[Dict] = None,
        morph_params: Optional[Dict] = None,
        filter_params: Optional[Dict] = None
    ):
        self.gray_conversion_method = gray_conversion_method
        self.threshold_method = threshold_method
        self.morph_operations = morph_operations or []
        self.contour_filter_method = contour_filter_method
        
        # Устанавливаем параметры по умолчанию если не предоставлены
        self.threshold_params = threshold_params or self._get_default_threshold_params()
        self.morph_params = morph_params or {"kernel_size": 5}
        self.filter_params = filter_params or self.CONTOUR_FILTER_METHODS[contour_filter_method].get("default_params", {}).copy()
    
    def _get_default_threshold_params(self) -> Dict:
        """Возвращает параметры по умолчанию для выбранного метода бинаризации"""
        if self.threshold_method == ThresholdMethod.BINARY:
            return {"thresh": 190, "maxval": 255, "type": cv2.THRESH_BINARY_INV}
        elif self.threshold_method == ThresholdMethod.OTSU:
            return {"thresh": 0, "maxval": 255, "type": cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU}
        elif self.threshold_method == ThresholdMethod.ADAPTIVE_GAUSSIAN:
            return {"maxValue": 255, "adaptiveMethod": cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                    "thresholdType": cv2.THRESH_BINARY_INV, "blockSize": 51, "C": 2}
        elif self.threshold_method == ThresholdMethod.ADAPTIVE_MEAN:
            return {"maxValue": 255, "adaptiveMethod": cv2.ADAPTIVE_THRESH_MEAN_C, 
                    "thresholdType": cv2.THRESH_BINARY_INV, "blockSize": 51, "C": 2}
        return {}
    
    def convert_to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """Преобразует изображение в оттенки серого выбранным методом"""
        if len(image.shape) == 2:
            return image.copy()
        
        method_info = self.GRAY_CONVERSION_METHODS.get(self.gray_conversion_method)
        if method_info:
            return method_info["function"](image)
        
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    def apply_threshold(self, image: np.ndarray) -> np.ndarray:
        """Применяет выбранный метод бинаризации"""
        method_info = self.THRESHOLD_METHODS.get(self.threshold_method)
        if not method_info:
            raise ValueError(f"Unknown threshold method: {self.threshold_method}")
        
        function = method_info["function"]
        params = self.threshold_params.copy()
        
        if self.threshold_method in [ThresholdMethod.BINARY, ThresholdMethod.OTSU]:
            _, result = function(image, **params)
            return result
        else:
            # Для адаптивных методов
            return function(image, **params)
    
    def apply_morphological_operations(self, image: np.ndarray) -> np.ndarray:
        """Применяет последовательность морфологических операций"""
        result = image.copy()
        
        for op_config in self.morph_operations:
            operation = op_config.get("operation", MorphOperation.OPEN)
            kernel_size = op_config.get("kernel_size", self.morph_params.get("kernel_size", 5))
            iterations = op_config.get("iterations", 1)
            
            method_info = self.MORPH_OPERATIONS.get(operation)
            if not method_info:
                continue
            
            kernel = np.ones((kernel_size, kernel_size), np.uint8)
            function = method_info["function"]
            params = {k: v for k, v in op_config.items() if k not in ["operation", "kernel_size", "iterations"]}
            
            if "op" in method_info.get("default_params", {}):
                result = function(result, method_info["default_params"]["op"], kernel, iterations=iterations)
            else:
                result = function(result, kernel, iterations=iterations)
        
        return result
    
    def filter_contours(self, contours: List[np.ndarray]) -> List[np.ndarray]:
        """Фильтрует контуры выбранным методом"""
        method_info = self.CONTOUR_FILTER_METHODS.get(self.contour_filter_method)
        if not method_info:
            return contours
        
        filter_function = method_info["function"]
        return [cnt for cnt in contours if filter_function(cnt, self.filter_params)]
    
    def detect(
        self,
        image: np.ndarray,
        return_contours: bool = False
    ) -> List[Tuple[int, int]]:
        """
        Обнаруживает объекты на изображении с использованием настроенных методов обработки.
        """
        # Преобразование в оттенки серого
        gray = self.convert_to_grayscale(image)
        
        # Бинаризация
        binary = self.apply_threshold(gray)
        
        # Морфологические операции
        processed = self.apply_morphological_operations(binary)
        
        # Поиск контуров
        contours, _ = cv2.findContours(processed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Фильтрация контуров
        filtered_contours = self.filter_contours(contours)
        
        # Вычисление центров масс
        centers = []
        for contour in filtered_contours:
            M = cv2.moments(contour)
            if M["m00"] != 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                centers.append((cX, cY))
        
        # Сортировка по x-координате
        centers.sort(key=lambda x: x[0])
        
        if return_contours:
            return centers, filtered_contours
        return centers
    
    def visualize_detection(
        self,
        image: np.ndarray,
        centers: List[Tuple[int, int]],
        contours: Optional[List[np.ndarray]] = None
    ) -> np.ndarray:
        """
        Визуализирует результаты обнаружения на изображении.
        """
        result_image = image.copy()
        if len(result_image.shape) == 2:
            result_image = cv2.cvtColor(result_image, cv2.COLOR_GRAY2BGR)
        
        # Рисуем контуры если предоставлены
        if contours is not None:
            cv2.drawContours(result_image, contours, -1, (255, 0, 0), 2)
        
        # Рисуем центры
        for center in centers:
            cv2.circle(result_image, center, 10, (0, 255, 0), -1)
            cv2.putText(result_image, f"({center[0]}, {center[1]})", 
                       (center[0] + 15, center[1]), cv2.FONT_HERSHEY_SIMPLEX, 
                       0.5, (0, 255, 0), 1)
        
        return result_image


# Пример использования с правильными параметрами
if __name__ == "__main__":
    from my_timer import Timer

    frame_rgb = cv2.imread("Create_bottles\image.jpg")

    my_timer = Timer('timer')
    my_timer.start()

    # Способ 1: Простая бинаризация (как в вашем примере)
    detector1 = ObjectDetector(
        gray_conversion_method=GrayConversionMethod.LUMINANCE,
        threshold_method=ThresholdMethod.BINARY,
        morph_operations=[
            {"operation": MorphOperation.CLOSE, "kernel_size": 5},
            {"operation": MorphOperation.OPEN, "kernel_size": 5}
        ],
        contour_filter_method=ContourFilterMethod.AREA,
        threshold_params={"thresh": 190, 
                          "maxval": 255, 
                          "type": cv2.THRESH_BINARY_INV},
        filter_params={"min_area": 1000}
    )
    
    # # Способ 2: Адаптивная бинаризация
    # detector2 = ObjectDetector(
    #     gray_conversion_method=GrayConversionMethod.LUMINANCE,
    #     threshold_method=ThresholdMethod.ADAPTIVE_GAUSSIAN,
    #     morph_operations=[
    #         {"operation": MorphOperation.CLOSE, "kernel_size": 5},
    #         {"operation": MorphOperation.OPEN, "kernel_size": 5}
    #     ],
    #     contour_filter_method=ContourFilterMethod.AREA,
    #     threshold_params={
    #         "maxValue": 255,
    #         "adaptiveMethod": cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    #         "thresholdType": cv2.THRESH_BINARY_INV,
    #         "blockSize": 51,
    #         "C": 5
    #     },
    #     filter_params={"min_area": 1000}
    # )
    
    # Загружаем изображение (пример)
    
    frame_gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
    image_frame = frame_gray[:300, :]
    
    # Обнаруживаем объекты
    centers, contours = detector1.detect(image_frame, return_contours=True)
    
    my_timer.elapsed_time(print_log=True)

    print(f"Найдено объектов: {len(centers)}")
    for i, center in enumerate(centers):
        print(f"Объект {i+1}: x={center[0]}, y={center[1]}")

    #my_timer.elapsed_time(print_log=True)

    
    # Визуализируем результат
    result_image = detector1.visualize_detection(image_frame, centers, contours)
    
    # Показываем результат
    cv2.imshow("Detection Result", result_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()