import cv2
import numpy as np
import os
import time
import random


class LayerImage:
    def __init__(self, image_path):
        # Загрузка изображения с альфа-каналом
        self.original = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if self.original is None:
            raise ValueError(f"Не удалось загрузить изображение: {image_path}")
        
        # Добавление альфа-канала если отсутствует
        if self.original.shape[2] == 3:
            self.original = cv2.cvtColor(self.original, cv2.COLOR_BGR2BGRA)
        
        # Исходные параметры
        self.original_size = (self.original.shape[1], self.original.shape[0])
        self.transformed = self.original.copy()
        self.position = (0, 0)
        self.angle = 0
        self.scale_factor = 1.0
        self.visible = True

        # Параметры контура
        self.draw_contour = False
        self.contour_color = (0, 255, 0)  # Зеленый цвет по умолчанию
        self.contour_thickness = 2  # Толщина контура по умолчанию
        
        # Параметры для эффекта наполнения
        self.fill_enabled = False
        self.fill_color = (0, 0, 255, 180)  # Синий цвет с прозрачностью по умолчанию
        self.fill_level = 0.0  # Уровень наполнения (0.0 - 1.0)
        self.fill_mask = None  # Маска для наполнения
        self.fill_rect = None  # Прямоугольник для наполнения

    def enable_fill_effect(self, enable=True, color=None, initial_level=0.0):
        """Активация эффекта наполнения"""
        self.fill_enabled = enable
        if color:
            self.fill_color = color
        self.fill_level = initial_level
        self._generate_fill_mask()
    
    def set_fill_level(self, level):
        """Установка уровня наполнения (0.0 - 1.0)"""
        self.fill_level = max(0.0, min(1.0, level))
    
    def set_fill_color(self, color):
        """Установка цвета наполнения (B, G, R, A)"""
        self.fill_color = color
    
    def _generate_fill_mask(self):
        """Генерация маски для эффекта наполнения"""
        if self.original is None:
            return
        
        # Создаем маску из альфа-канала оригинального изображения
        alpha = self.original[:, :, 3]
        _, mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)
        
        # Находим контур и заполняем его
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # Создаем заполненную маску
            filled_mask = np.zeros_like(mask)
            cv2.drawContours(filled_mask, contours, -1, 255, cv2.FILLED)
            
            # Находим ограничивающий прямоугольник
            x, y, w, h = cv2.boundingRect(filled_mask)
            
            # Обрезаем маску до области бутылки
            self.fill_mask = filled_mask[y:y+h, x:x+w]
            self.fill_rect = (x, y, w, h)
    
    def apply_fill_effect(self):
        """Применение эффекта наполнения к изображению"""
        if not self.fill_enabled or self.fill_mask is None or self.fill_rect is None:
            return self.transformed.copy()
        
        # Создаем копию изображения для работы
        img = self.transformed.copy()
        
        # Вычисляем область наполнения на основе текущего уровня
        x, y, w, h = self.fill_rect
        fill_height = int(h * (1.0 - self.fill_level))
        
        # Создаем изображение наполнения
        fill_img = np.zeros((h, w, 4), dtype=np.uint8)
        fill_img[fill_height:, :] = self.fill_color
        
        # Применяем маску
        fill_img[:, :, 3] = cv2.bitwise_and(fill_img[:, :, 3], self.fill_mask)
        
        # Создаем временный холст для смешивания
        temp_canvas = np.zeros_like(img)
        temp_canvas[y:y+h, x:x+w] = fill_img
        
        # Смешиваем с основным изображением
        alpha_fill = temp_canvas[:, :, 3] / 255.0
        alpha_img = 1.0 - alpha_fill
        
        for c in range(3):
            img[:, :, c] = (alpha_fill * temp_canvas[:, :, c] + 
                            alpha_img * img[:, :, c])
        
        # Комбинируем альфа-каналы
        img[:, :, 3] = np.maximum(img[:, :, 3], temp_canvas[:, :, 3])
        
        return img

 
    def resize(self, width=None, height=None):
        """Изменение размера изображения"""
        if width is None and height is None:
            return
        
        # Расчет новых размеров
        if width is None:
            ratio = height / self.original_size[1]
            width = int(self.original_size[0] * ratio)
        elif height is None:
            ratio = width / self.original_size[0]
            height = int(self.original_size[1] * ratio)
        
        self.scale_factor = width / self.original_size[0]
        self.transformed = cv2.resize(self.original, (width, height))
    
    def rotate(self, angle):
        """Поворот исходного изображения вокруг центра"""
        self.angle = angle
        temp = self.original.copy()
        h, w = self.original.shape[:2]
        center = (w // 2, h // 2)
        
        # Матрица поворота
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        # Новые размеры
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        
        # Корректировка матрицы
        M[0, 2] += (new_w - w) / 2
        M[1, 2] += (new_h - h) / 2
        
        # # Применение поворота
        # rotated = cv2.warpAffine(
        #     temp, M, (new_w, new_h),
        #     flags=cv2.INTER_LINEAR,
        #     borderMode=cv2.BORDER_TRANSPARENT
        # )

        rotated = cv2.warpAffine(
            temp, M, (new_w, new_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0)  # Прозрачный черный цвет
        )

        # Обновляем преобразованное изображение
        self.transformed = rotated
    
    def set_contour_properties(self, draw_contour, color=None, thickness=None):
        """Установка свойств контура"""
        self.draw_contour = draw_contour
        if color is not None:
            self.contour_color = color
        if thickness is not None:
            self.contour_thickness = thickness


    def set_position(self, x, y):
        self.position = (x, y)

    def get_transformed(self):
        # Применяем эффект наполнения, если активирован
        if self.fill_enabled:
            img = self.apply_fill_effect()
        else:
            img = self.transformed.copy()
        
        # Добавляем контур, если нужно
        if self.draw_contour and img.size > 0:
            height, width = img.shape[:2]
            offset = 0
            
            contour_mask = np.zeros((height, width), dtype=np.uint8)
            cv2.rectangle(
                contour_mask, 
                (offset, offset),
                (width - offset, height - offset),
                255,
                self.contour_thickness
            )
            
            bgra_color = (*self.contour_color[:3], 255)
            img[contour_mask > 0] = bgra_color

        return img

    def shift_horizontal(self, offset):
        """Циклический сдвиг видимой части изображения по горизонтали
        
        Args:
            offset (int): Пиксели для сдвига. 
                Положительное значение -> сдвиг вправо
                Отрицательное -> сдвиг влево
        """
        if self.transformed is None or not self.visible:
            return
            
        # 1. Находим bounding box видимой части (непрозрачной области)
        alpha = self.transformed[:, :, 3]
        coords = np.argwhere(alpha > 0)
        if coords.size == 0:  # Нет видимых пикселей
            return
            
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        
        # 2. Вырезаем только видимую часть
        visible_part = self.transformed[y_min:y_max+1, x_min:x_max+1]
        h_vis, w_vis = visible_part.shape[:2]
        
        # 3. Применяем циклический сдвиг ТОЛЬКО к видимой части
        # Создаем копию, чтобы избежать проблем с памятью
        shifted_visible = np.roll(visible_part.copy(), shift=-offset, axis=1)
        
        # 4. Вставляем обратно в оригинальное изображение
        self.transformed[y_min:y_max+1, x_min:x_max+1] = shifted_visible

          
class BottleGroup:
    def __init__(self, image_dir, parts_config, position=(0, 0)):
        self.position = position
        self.parts = {}
        self.angle = 0
        self.scale = 1.0
        self.combined_image = None
        self.dirty = True
        
        # Параметры контура для всей бутылки
        self.draw_contour = False
        self.contour_color = (0, 255, 0)  # Зеленый по умолчанию
        self.contour_thickness = 2
        
        # Создаем слои для каждой части
        for part_name, config in parts_config.items():
            img_path = os.path.join(image_dir, config["file"])
            layer = LayerImage(img_path)
            
            if "scale" in config:
                layer.resize(width=int(layer.original_size[0] * config["scale"]))
            
            if "angle" in config:
                layer.rotate(config["angle"])
            
            if "position" in config:
                layer.set_position(config["position"][0], config["position"][1])
                            
            if "offset" in config:
                layer.shift_horizontal(config["offset"]) 
                
            if "visible" in config:
                layer.visible = config["visible"]

            if all(key in config for key in ["filler_enable", "filler_level", "filler_color"]):
                # Активация эффекта наполнения
                layer.enable_fill_effect(
                    enable=config["filler_enable"],
                    color=config["filler_color"],  
                    initial_level = config["filler_level"]
                )


            self.parts[part_name] = layer
            self.parts_config = parts_config.copy()

    def set_contour_properties(self, draw_contour, color=None, thickness=None):
        """Установка свойств контура для всей бутылки"""
        self.draw_contour = draw_contour
        if color is not None:
            self.contour_color = color
        if thickness is not None:
            self.contour_thickness = thickness
        self.dirty = True

    def combine_parts(self):
        """Объединение частей с добавлением контура при необходимости"""
        if not self.dirty and self.combined_image is not None:
            return self.combined_image
            
        # Определение общего размера холста
        all_positions = []
        for part_name, layer in self.parts.items():
            if not layer.visible:
                continue
                
            _, _, w, h = self.get_part_rect(part_name)
            all_positions.append((layer.position[0], layer.position[1]))
            all_positions.append((layer.position[0] + w, layer.position[1] + h))
        
        if not all_positions:
            self.combined_image = None
            return None
            
        min_x = min(p[0] for p in all_positions)
        min_y = min(p[1] for p in all_positions)
        max_x = max(p[0] for p in all_positions)
        max_y = max(p[1] for p in all_positions)
        
        width = int(max_x - min_x)
        height = int(max_y - min_y)
        
        # Создание холста
        canvas = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Добавление всех частей
        for part_name, layer in self.parts.items():
            if not layer.visible:
                continue
                
            img = layer.get_transformed()
            if img is None or img.size == 0:
                continue
                
            x = int(layer.position[0] - min_x)
            y = int(layer.position[1] - min_y)
            
            h, w = img.shape[:2]
            if y + h > height or x + w > width or y < 0 or x < 0:
                continue
                
            canvas_region = canvas[y:y+h, x:x+w]
            src_region = img[0:h, 0:w]
            
            # Альфа-композитинг
            alpha_s = src_region[:, :, 3] / 255.0
            alpha_d = 1.0 - alpha_s
            
            for c in range(3):
                canvas_region[:, :, c] = (
                    alpha_s * src_region[:, :, c] + 
                    alpha_d * canvas_region[:, :, c]
                )
                
            canvas_region[:, :, 3] = np.maximum(
                src_region[:, :, 3], 
                canvas_region[:, :, 3]
            )
        
        # Применение групповых преобразований
        if self.angle != 0 or self.scale != 1.0:
            canvas = self.apply_group_transform(canvas)
            
        # Добавление контура если нужно
        if self.draw_contour and canvas.size > 0:
            canvas = self.add_contour_to_image(canvas)
            
        self.combined_image = canvas
        self.dirty = False

        return canvas

    def add_contour_to_image(self, image):
        """Добавление контура к изображению бутылки"""
        height, width = image.shape[:2]
        offset = self.contour_thickness
        
        # Создаем маску для контура
        contour_mask = np.zeros((height, width), dtype=np.uint8)
        
        # Рисуем контур на маске
        cv2.rectangle(
            contour_mask, 
            (offset, offset),
            (width - offset, height - offset),
            255,  # Белый цвет
            self.contour_thickness
        )
        
        # Преобразуем цвет контура в BGRA
        bgra_color = (*self.contour_color[:3], 255)
        
        # Создаем копию изображения для модификации
        result = image.copy()
        
        # Применяем контур
        result[contour_mask > 0] = bgra_color
        
        return result
        
    def apply_group_transform(self, image):
        """Применение преобразований ко всему изображению бутылки"""
        if self.angle != 0:
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, self.angle, self.scale)
            
            # Рассчитываем новые размеры
            cos = np.abs(M[0, 0])
            sin = np.abs(M[0, 1])
            new_w = int((h * sin) + (w * cos))
            new_h = int((h * cos) + (w * sin))
            
            M[0, 2] += (new_w - w) // 2
            M[1, 2] += (new_h - h) // 2
            
            # image = cv2.warpAffine(
            #     image, M, (new_w, new_h),
            #     flags=cv2.INTER_LINEAR,
            #     borderMode=cv2.BORDER_TRANSPARENT
            # )

            image = cv2.warpAffine(
                image, M, (new_w, new_h),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0)  # Прозрачный черный цвет
                )
            
        elif self.scale != 1.0:
            image = cv2.resize(
                image, 
                None, 
                fx=self.scale, 
                fy=self.scale, 
                interpolation=cv2.INTER_LINEAR
            )
            
        return image
        
    def get_part_rect(self, part_name):
        """Получение размеров и позиции части"""
        layer = self.parts[part_name]
        if not layer.visible:
            return 0, 0, 0, 0
            
        img = layer.get_transformed()
        if img is None:
            return 0, 0, 0, 0
            
        h, w = img.shape[:2]
        return layer.position[0], layer.position[1], w, h
        
    def set_group_position(self, x, y):
        self.position = (x, y)
        self.dirty = True
    
    def move_group(self, dx, dy):
        self.position = (self.position[0] + dx, self.position[1] + dy)
        self.dirty = True
    
    def update_part(self, part_name, param, value):
        if part_name not in self.parts:
            return
            
        layer = self.parts[part_name]
        self.parts_config[part_name][param] = value
        
        if param == "position":
            layer.set_position(value[0], value[1])
        elif param == "angle":
            layer.rotate(value)
        elif param == "scale":
            layer.resize(width=int(layer.original_size[0] * value))
        elif param == "visible":
            layer.visible = value
        elif param == "offset":
            layer.shift_horizontal(value)
            
        self.dirty = True
        
    def set_group_rotation(self, angle):
        self.angle = angle
        self.dirty = True
        
    def set_group_scale(self, scale):
        self.scale = scale
        self.dirty = True
        
    def get_layers(self):
        """Получение объединенного изображения бутылки"""
        self.combine_parts()
        if self.combined_image is None:
            return []
        
        self.combined_image = self.combined_image[:,:187]
            
        return [(self.combined_image, self.position)]

class ImageComposer:
    def __init__(self, width, height, bg_color=(0, 0, 0, 0)):
        self.width = width
        self.height = height
        self.bg_color = bg_color
        self.layers = []
    
    def add_layer(self, image, position=(0, 0)):
        if image is not None:
            self.layers.append((image, position))
    
    def compose(self):
        # Создаем холст с указанным цветом фона
        result = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        result[:] = self.bg_color
        
        # Обрабатываем каждый слой
        for img, (x, y) in self.layers:
            if img is None or img.size == 0:
                continue
                
            h, w = img.shape[:2]
            
            # Определяем область наложения
            y1 = max(y, 0)
            x1 = max(x, 0)
            y2 = min(y + h, self.height)
            x2 = min(x + w, self.width)
            
            # Пропускаем невидимые слои
            if x1 >= x2 or y1 >= y2:
                continue
                
            # Вычисляем область изображения для наложения
            img_x1 = x1 - x
            img_y1 = y1 - y
            img_x2 = img_x1 + (x2 - x1)
            img_y2 = img_y1 + (y2 - y1)
            img_region = img[img_y1:img_y2, img_x1:img_x2]
            
            # Получаем область холста для наложения
            canvas_region = result[y1:y2, x1:x2]
            
            # Альфа-композитинг
            self._alpha_blend(img_region, canvas_region)
            
        return result
    
    def _alpha_blend(self, src, dst):
        # Разделяем каналы
        src_bgr = src[:, :, :3]
        src_alpha = src[:, :, 3] / 255.0
        dst_bgr = dst[:, :, :3]
        dst_alpha = dst[:, :, 3] / 255.0
        
        # Рассчитываем результирующую прозрачность
        out_alpha = src_alpha + dst_alpha * (1 - src_alpha)
        
        # Избегаем деления на ноль
        out_alpha[out_alpha == 0] = 1e-5
        
        # Рассчитываем результирующий цвет
        out_bgr = (
            src_bgr * src_alpha[:, :, np.newaxis] + 
            dst_bgr * dst_alpha[:, :, np.newaxis] * (1 - src_alpha[:, :, np.newaxis])
        ) / out_alpha[:, :, np.newaxis]
        
        # Объединяем результаты
        dst[:, :, :3] = out_bgr.astype(np.uint8)
        dst[:, :, 3] = (out_alpha * 255).astype(np.uint8)



if __name__ == "__main__":
    # Параметры анимации
    CANVAS_WIDTH = 1200
    CANVAS_HEIGHT = 800
    CONVEYOR_HEIGHT = 600
    SPEED = 100
    GREEN_BG = (210, 210, 210, 255)  # Зеленый фон (B, G, R, A)

    # Задаем координаты вертикальных линий
    LINE_LEFT = 400
    LINE_RIGHT = 800

    # Фиксированные координаты горизонтальных линий
    TOP_LINE_Y1 = 50
    TOP_LINE_Y2 = 170
    BOTTOM_LINE_Y1 = 430
    BOTTOM_LINE_Y2 = 580

    # Добавляем внутренние линии для детекции центра объекта
    LINE_LEFT_INNER = 530
    LINE_RIGHT_INNER = 650

    BOTTLE_WIDTH = 188
    BOTTLE_HEIGHT = 665
        

    bottle_spacing = 160  # Текущее расстояние между бутылками
    last_bottle_pos = CANVAS_WIDTH  # Позиция последней созданной бутылки
    
    # Создаем компоновщик
    composer = ImageComposer(CANVAS_WIDTH, CANVAS_HEIGHT, (0, 0, 0, 0))

    # Загрузка изображений
    image_dir = "Test_bottle/Images"
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
        print(f"Создана папка {image_dir}. Пожалуйста, добавьте в нее изображения.")
        exit()

    # Конфигурация частей бутылки
    bottle_config = {
        "bottle": {
            "file": "bottle2.png",
            "position": (0, 130),
            "angle": 0,
            "scale": 1.0,
            "visible": True,
            "offset": 0,
            "filler_enable": True,
            "filler_level": 0.8,
            "filler_color": (100, 200, 200, 180),
        },

        "cap": {
            "file": "cap2.png",
            "position": (51, 122),
            "angle": 0,
            "scale": 1.0,
            "visible": True,
            "offset": 0
        },
        "ring": {
            "file": "ring2.png",
            "position": (51, 155),
            "angle": 0,
            "scale": 1.0,
            "visible": True,
            "offset": 0
        },
        "label": {
            "file": "eticet2.png",
            "position": (0, 490),
            "angle": 0,
            "scale": 1.0,
            "visible": True, 
            "offset": 0
        }
    }
    
    # Создаем группу бутылок
    bottles = []
    
    # Создаем холст (фон конвейера)
    conveyor = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 4), dtype=np.uint8)
    conveyor[:] = GREEN_BG
    
    # Главный цикл анимации
    frame_count = 0
    bottle_count = 0
    all_bottle_count = 0

    # Создаем окно для трекбаров
    cv2.namedWindow("Mask Controls")
    cv2.resizeWindow("Mask Controls", 1200, 1200) 

    # Создаем трекбары для нижнего и верхнего порогов
    cv2.createTrackbar("Lower H", "Mask Controls", 0, 255, lambda x: None)
    cv2.createTrackbar("Lower S", "Mask Controls", 0, 255, lambda x: None)
    cv2.createTrackbar("Lower V", "Mask Controls", 0, 255, lambda x: None)
    cv2.createTrackbar("Upper H", "Mask Controls", 255, 255, lambda x: None)
    cv2.createTrackbar("Upper S", "Mask Controls", 255, 255, lambda x: None)
    cv2.createTrackbar("Upper V", "Mask Controls", 255, 255, lambda x: None)

    cv2.createTrackbar("Level", "Mask Controls", 0, 100, lambda x: None)
    cv2.createTrackbar("Bottle Spacing", "Mask Controls", 0, 500, lambda x: None)
    cv2.createTrackbar("Speed", "Mask Controls", 0, 400, lambda x: None)
    cv2.createTrackbar("Direction", "Mask Controls", 0, 1, lambda x: None)

    # Устанавливаем начальные значения для серого фона
    cv2.setTrackbarPos("Lower H", "Mask Controls", 0)
    cv2.setTrackbarPos("Lower S", "Mask Controls", 0)
    cv2.setTrackbarPos("Lower V", "Mask Controls", 200)
    cv2.setTrackbarPos("Upper H", "Mask Controls", 255)
    cv2.setTrackbarPos("Upper S", "Mask Controls", 50)
    cv2.setTrackbarPos("Upper V", "Mask Controls", 255)

    cv2.setTrackbarPos("Level", "Mask Controls", 70)
    cv2.setTrackbarPos("Bottle Spacing", "Mask Controls", bottle_spacing)

    cv2.setTrackbarPos("Speed", "Mask Controls", 100)
    cv2.setTrackbarPos("Direction", "Mask Controls", 0)

    while True:
        # Получаем текущие значения трекбаров
        l_h = cv2.getTrackbarPos("Lower H", "Mask Controls")
        l_s = cv2.getTrackbarPos("Lower S", "Mask Controls")
        l_v = cv2.getTrackbarPos("Lower V", "Mask Controls")
        u_h = cv2.getTrackbarPos("Upper H", "Mask Controls")
        u_s = cv2.getTrackbarPos("Upper S", "Mask Controls")
        u_v = cv2.getTrackbarPos("Upper V", "Mask Controls")

        level = cv2.getTrackbarPos("Level", "Mask Controls")
        bottle_spacing = cv2.getTrackbarPos("Bottle Spacing", "Mask Controls")
        speed = cv2.getTrackbarPos("Speed", "Mask Controls")
        direction = cv2.getTrackbarPos("Direction", "Mask Controls")
        
        level = level / 100 

        # Очищаем компоновщик
        composer = ImageComposer(CANVAS_WIDTH, CANVAS_HEIGHT, (0, 0, 0, 0))
        
        # Добавляем фон конвейера
        composer.add_layer(conveyor, (0, 0))

        create_new = True


        
        # # Рассчитываем случайное отклонение для интервала между бутылками
        # random_delta = random.randint(0, 100)
        # speed_delta = speed // 5

        # # Добавляем новые бутылки с учетом расстояния
        # if not bottles:
        #     # Если нет бутылок, создаем первую
        #     create_new = True
        # else:
        #     # Определяем позицию последней бутылки
        #     last_bottle = bottles[-1]
        #     last_bottle_right_edge = last_bottle.position[0] + BOTTLE_WIDTH 
            
        #     # Проверяем, достаточно ли места для новой бутылки
        #     create_new = last_bottle_right_edge < CANVAS_WIDTH - bottle_spacing + random_delta 

        if create_new:
            # Создаем копию конфигурации для этой бутылки
            current_config = {k: v.copy() for k, v in bottle_config.items()}
            
            random_level_on = random.randint(0, 10)
            if random_level_on == 5:
                random_level = random.randint(-10, 10) 
                delta_level = (random_level / 100)
                current_config["bottle"]["filler_level"] = level + delta_level
            else:
                current_config["bottle"]["filler_level"] = level 
                
            # Случайным образом определяем, будет ли видна крышка
            random_visual_cap = random.randint(4, 8) 

            if bottle_count > 0 and random_visual_cap == 4:
                current_config["cap"]["visible"] = False
            else:
                current_config["cap"]["visible"] = True

            random_visual_ring = random.randint(7, 12) 

            if bottle_count > 0 and random_visual_ring == 9:
                current_config["ring"]["visible"] = False
            else:
                current_config["ring"]["visible"] = True

            random_visual_label = random.randint(7, 12) 

            random_offset_horizontal = random.randint(0, 30) 
            current_config["label"]["offset"] = random_offset_horizontal

            random_angel_on = random.randint(0, 10) 
            if random_angel_on == 5:
                random_angel = random.randint(0, 10) 
                current_config["label"]["angle"] = random_angel

            if bottle_count > 0 and random_visual_label == 9:
                current_config["label"]["visible"] = False
            else:
                current_config["label"]["visible"] = True

            random_position_label = random.randint(0, 10) 
            if random_position_label == 1:
                random_position_label = random.randint(-20, 20) 
                current_config["label"]["position"] = (current_config["label"]["position"][0], current_config["label"]["position"][1] + random_position_label)

            bottle = BottleGroup(
                image_dir, 
                current_config,
                position=(CANVAS_WIDTH//2, 79))
            
            
            # Включение контура с настройками
            bottle.set_contour_properties(
                draw_contour=False,
                color=(255, 0, 255),  # Красный контур
                thickness=1       # Толщина 3 пикселя
            )
            
            #bottles.append(new_bottle)
            bottle_count += 1  # Увеличиваем счетчик бутылок
        

        srtting = bottle.get_layers()
        img, pos = srtting[0]
        composer.add_layer(img, pos)

        # if direction == 0:
        #     direction = -1
        # else:
        #     direction = 1

        # for bottle in bottles:
        #     bottle.move_group(speed * direction, 0)
            
        # # Удаляем бутылки, которые ушли за левый край
        # bottles = [b for b in bottles if b.position[0] + 500 > 0]
        
        # # Добавляем все бутылки в компоновщик
        # for bottle in bottles:
        #     for img, pos in bottle.get_layers():
        #         composer.add_layer(img, pos)

        # Компоновка изображения
        result = composer.compose()
        

        # # Создаем копию изображения для обработки
        # processed_img = result.copy()

        # # 1. Создаем маску для области между линиями
        # mask = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), dtype=np.uint8)
        # mask[:, LINE_LEFT:LINE_RIGHT] = 255

        # # 2. Выделяем не-зеленые объекты
        # hsv = cv2.cvtColor(processed_img, cv2.COLOR_BGRA2BGR)
        # hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)


        # # Создаем массивы для нижнего и верхнего порогов
        # lower_green = np.array([l_h, l_s, l_v])
        # upper_green = np.array([u_h, u_s, u_v])
        
        # green_mask = cv2.inRange(hsv, lower_green, upper_green)
        # non_green_mask = cv2.bitwise_not(green_mask)

        # # 3. Объединяем с маской области между линиями
        # final_mask = cv2.bitwise_and(non_green_mask, non_green_mask, mask=mask)

        # # Рисуем вертикальные линии
        # cv2.line(processed_img, (LINE_LEFT, 0), (LINE_LEFT, CANVAS_HEIGHT), (120, 120, 100), 2)
        # cv2.line(processed_img, (LINE_RIGHT, 0), (LINE_RIGHT, CANVAS_HEIGHT), (120, 120, 100), 2)
        # cv2.line(processed_img, (LINE_LEFT_INNER, 0), (LINE_LEFT_INNER, CANVAS_HEIGHT), (255, 0, 0), 2)
        # cv2.line(processed_img, (LINE_RIGHT_INNER, 0), (LINE_RIGHT_INNER, CANVAS_HEIGHT), (255, 0, 0), 2)

        # # Рисуем горизонтальные линии
        # cv2.line(processed_img, (0, TOP_LINE_Y1), (CANVAS_WIDTH, TOP_LINE_Y1), (255, 255, 0), 2)
        # cv2.line(processed_img, (0, TOP_LINE_Y2), (CANVAS_WIDTH, TOP_LINE_Y2), (0, 255, 255), 2)
        # cv2.line(processed_img, (0, BOTTOM_LINE_Y1), (CANVAS_WIDTH, BOTTOM_LINE_Y1), (255, 0, 255), 2)
        # cv2.line(processed_img, (0, BOTTOM_LINE_Y2), (CANVAS_WIDTH, BOTTOM_LINE_Y2), (255, 0, 255), 2)

        # final_mask = final_mask[:TOP_LINE_Y2]
        # contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # # Создаем копию без аннотаций для вырезки
        # clean_img = result.copy()  # Используем оригинальное изображение без рисованных элементов

        # # Список для сохранения вырезанных областей
        # cropped_regions = []

        # for contour in contours:
        #     if cv2.contourArea(contour) > 100:
        #         x, y, w, h = cv2.boundingRect(contour)
        #         center_x = x + w // 2
                
        #         # Отрисовка объекта в зависимости от положения
        #         if LINE_LEFT_INNER <= center_x <= LINE_RIGHT_INNER:
        #             cv2.drawContours(processed_img, [contour], -1, (0, 255, 0), 2)
        #             cv2.putText(processed_img, "Bottle", (x, y-10), 
        #                         cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        #             # Координаты прямоугольника
        #             x1 = center_x - BOTTLE_WIDTH // 2
        #             y1 = y
        #             x2 = x1 + BOTTLE_WIDTH
        #             y2 = y1 + BOTTLE_HEIGHT

        #             # Вырезаем область
        #             cropp_bottle = clean_img[y1:y2, x1:x2]

        #             all_bottle_count += 1 

        #             if cropp_bottle.shape[0] > 20 and cropp_bottle.shape[1] > 20:
        #                 # ВЫРЕЗАЕМ ДВЕ ОБЛАСТИ ИЗ ОРИГИНАЛЬНОГО ИЗОБРАЖЕНИЯ

        #                 # 1. Верхняя область (между TOP_LINE_Y1 и TOP_LINE_Y2)
        #                 top_region = clean_img[TOP_LINE_Y1:TOP_LINE_Y2, center_x-70:center_x+70]
                        
        #                 # 2. Нижняя область (между BOTTOM_LINE_Y1 и BOTTOM_LINE_Y2)
        #                 bottom_region = clean_img[BOTTOM_LINE_Y1:BOTTOM_LINE_Y2, center_x - BOTTLE_WIDTH // 2 - 10:center_x + BOTTLE_WIDTH // 2 + 10]

                        
        #                 # Сохраняем вырезанные области
        #                 cropped_regions.append(top_region)
        #                 cropped_regions.append(bottom_region)
                        
        #                 # Показываем вырезанные области
        #                 if top_region.size > 0:
        #                     cv2.imshow("Top Region", top_region)
        #                 if bottom_region.size > 0:
        #                     cv2.imshow("Bottom Region", bottom_region)

        #             # Рисуем прямоугольник
        #             cv2.rectangle(processed_img, (x1, y1), (x2, y2), (0, 0, 255), 2)


        # cv2.putText(processed_img, f"All bottle: {all_bottle_count}", (30, 30), 
        #                         cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 3)
        # cv2.putText(processed_img, f"Speed: {speed} | Spacing: {bottle_spacing}", (30, 70), 
        #                         cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 3)
                    
        # Отображаем результат
        cv2.imshow("Bottle Conveyor", result)
        cv2.imshow("Mask Controls", np.zeros((100, 500, 3), dtype=np.uint8))  # Пустое окно для трекбаров

        # Управление скоростью (ESC для выхода)
        key = cv2.waitKey(1)
        # if key == 27:  # ESC
        #     break
        # elif key == ord('+'):
        #     SPEED += 1
        # elif key == ord('-') and SPEED > 1:
        #     SPEED -= 1
        # elif key == ord('v'):
        #     # Переключаем видимость этикетки для всех бутылок
        #     for bottle in bottles:
        #         current = bottle.parts["label"]["layer"].visible
        #         bottle.update_part("label", "visible", not current)
        # elif key == ord('l'):  # Переместить левую линию
        #     LINE_LEFT = max(0, LINE_LEFT - 10)
        # elif key == ord('L'):  # Переместить левую линию
        #     LINE_LEFT = min(LINE_RIGHT - 50, LINE_LEFT + 10)
        # elif key == ord('r'):  # Переместить правую линию
        #     LINE_RIGHT = max(LINE_LEFT + 50, LINE_RIGHT - 10)
        # elif key == ord('R'):  # Переместить правую линию
        #     LINE_RIGHT = min(CANVAS_WIDTH, LINE_RIGHT + 10)
        # elif key == ord('s'):  # Уменьшить интервал между бутылками
        #     bottle_spacing = max(0, bottle_spacing - 10)
        #     cv2.setTrackbarPos("Bottle Spacing", "Mask Controls", bottle_spacing)
        # elif key == ord('S'):  # Увеличить интервал между бутылками
        #     bottle_spacing += 10
        #     cv2.setTrackbarPos("Bottle Spacing", "Mask Controls", bottle_spacing)

        frame_count += 1

    cv2.destroyAllWindows()