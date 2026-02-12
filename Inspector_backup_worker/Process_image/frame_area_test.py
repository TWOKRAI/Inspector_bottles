import os
import cv2
import numpy as np

class ImageProcessor:
    def __init__(self, image_folder):
        self.image_folder = image_folder
        self.images = [f for f in os.listdir(image_folder) if f.endswith(('.png', '.jpg', '.jpeg'))]
        self.current_image_index = 0
        self.hsv_bounds = [0, 0, 0, 255, 255, 255]  # Начальные границы HSV
        self.area_threshold = 1000  # Пример порога площади

    def filter_color_and_check_area(self, image, hsv_bounds, area_threshold, width=25, height=25):
        """
        Обрезка изображения по центру, фильтрация по заданному цвету и проверка площади фильтрованного изображения.

        :param image: Исходное изображение.
        :param hsv_bounds: Кортеж с границами HSV (hl, sl, vl, hm, sm, vm).
        :param area_threshold: Порог по площади.
        :param width: Ширина области обрезки.
        :param height: Высота области обрезки.
        :return: False, если площадь фильтрованного изображения больше порога, иначе True.
        """
        # Вычисляем координаты для обрезки по центру
        center_x = image.shape[1] // 2
        center_y = image.shape[0] // 2
        x = center_x - width // 2
        y = center_y - height // 2

        # Обрезка изображения
        cropped_image = image[y:y+height, x:x+width]

        hl, sl, vl, hm, sm, vm = hsv_bounds

        # Преобразуем изображение в HSV
        hsv_image = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2HSV)

        # Определяем диапазон цвета
        lower_bound = np.array([hl, sl, vl])
        upper_bound = np.array([hm, sm, vm])

        # Создаем маску для фильтрации цвета
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)

        # Находим контуры на маске
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Вычисляем площадь всех контуров
        total_area = sum(cv2.contourArea(contour) for contour in contours)

        # Добавляем текст с площадью на маску
        mask_with_text = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        cv2.putText(mask_with_text, f'{total_area}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Проверяем площадь
        return total_area <= area_threshold, mask_with_text, total_area

    def process_images(self):
        cv2.namedWindow('Original Image', cv2.WINDOW_NORMAL)
        cv2.namedWindow('Processed Mask', cv2.WINDOW_NORMAL)

        # Устанавливаем фиксированный размер окон
        cv2.resizeWindow('Original Image', 100, 100)
        cv2.resizeWindow('Processed Mask', 300, 100)

        # Создаем трекбары для границ HSV
        cv2.createTrackbar('H Low', 'Processed Mask', 0, 255, lambda x: None)
        cv2.createTrackbar('S Low', 'Processed Mask', 0, 255, lambda x: None)
        cv2.createTrackbar('V Low', 'Processed Mask', 150, 255, lambda x: None)
        cv2.createTrackbar('H High', 'Processed Mask', 255, 255, lambda x: None)
        cv2.createTrackbar('S High', 'Processed Mask', 255, 255, lambda x: None)
        cv2.createTrackbar('V High', 'Processed Mask', 255, 255, lambda x: None)

        # Создаем трекбар для индекса изображения
        cv2.createTrackbar('Image Index', 'Processed Mask', 0, len(self.images) - 1, lambda x: None)

        while True:
            # Обновляем границы HSV и индекс изображения
            self.update_hsv_bounds()
            self.update_image_index()

            # Читаем текущее изображение
            image_path = os.path.join(self.image_folder, self.images[self.current_image_index])
            image = cv2.imread(image_path)

            # Обрабатываем изображение
            result, mask_with_text, total_area = self.filter_color_and_check_area(image, self.hsv_bounds, self.area_threshold)
            print(total_area)
            # Отображаем оригинальное и обработанное изображения
            cv2.imshow('Original Image', image)
            cv2.imshow('Processed Mask', mask_with_text)

            # Выход по нажатию клавиши 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cv2.destroyAllWindows()

    def update_hsv_bounds(self):
        self.hsv_bounds = [
            cv2.getTrackbarPos('H Low', 'Processed Mask'),
            cv2.getTrackbarPos('S Low', 'Processed Mask'),
            cv2.getTrackbarPos('V Low', 'Processed Mask'),
            cv2.getTrackbarPos('H High', 'Processed Mask'),
            cv2.getTrackbarPos('S High', 'Processed Mask'),
            cv2.getTrackbarPos('V High', 'Processed Mask')
        ]

    def update_image_index(self):
        self.current_image_index = cv2.getTrackbarPos('Image Index', 'Processed Mask')


# Example usage
image_folder = r'C:\dev\TechVision_Inspector2\Data_Image\test'  # Replace with your image folder path
processor = ImageProcessor(image_folder)
processor.process_images()
