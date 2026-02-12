import cv2
import numpy as np
import time
import os
from datetime import datetime


class FrameDetection:
    def __init__(self):
        self.frame_id = 0

        self.top = 150
        self.bottom = 550
        self.left = 180
        self.right = 1075

        self.frame_crop = (self.top, self.bottom, self.left, self.right)

        self.dp = 1.2
        self.minDist = 20
        self.param1 = 50
        self.param2 = 30
        self.minRadius = 27
        self.maxRadius = 40

        self.last_height = 90


    def save_image_with_incremental_number(self, image, folder_path, prefix='image', extension='.jpg'):
        """
        Сохраняет изображение в папку с инкрементальным номером.

        :param image: Исходное изображение.
        :param folder_path: Путь к папке для сохранения изображения.
        :param prefix: Префикс для имени файла.
        :param extension: Расширение файла.
        """
        
        # Проверяем, существует ли папка, и создаем её, если нет
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        # Получаем список всех файлов в папке
        files = os.listdir(folder_path)

        # Находим последний номер изображения
        max_number = 0
        for file in files:
            if file.startswith(prefix) and file.endswith(extension):
                try:
                    number = int(file[len(prefix):-len(extension)])
                    if number > max_number:
                        max_number = number
                except ValueError:
                    continue
        
        # Определяем имя нового файла
        new_file_name = f"{prefix}{max_number + 1}{extension}"
        new_file_path = os.path.join(folder_path, new_file_name)
        
        # Сохраняем изображение
        cv2.imwrite(new_file_path, image)


    def add_border(self, image, border_width, border_color):
        """
        Добавляет контур вокруг изображения заданного цвета и ширины линии.

        :param image: Исходное изображение.
        :param border_width: Ширина контура.
        :param border_color: Цвет контура в формате (B, G, R).
        :return: Изображение с контуром.
        """

        # Создаем новое изображение с контуром
        bordered_image = cv2.rectangle(image, (0, 0), (image.shape[1], image.shape[0]), border_color, border_width)
        
        return bordered_image

        
    # def create_combined_image(self, main_image, images_info):
    #     """
    #     Формирует изображение из списков и запоминает высоту.

    #     :param main_image: Основное изображение.
    #     :param images_info: Список информации об изображениях.
    #     :return: Объединенное изображение и высота.
    #     """
    #     main_width = main_image.shape[1]

    #     if not images_info:
    #         return np.zeros((self.last_height, main_width, 3), dtype=np.uint8)

    #     groups = []
    #     current_group = []
    #     current_width = 0
    #     max_height = 0

    #     for frame_id, img, img_cnn, x, y, r, label, color in images_info:

    #         img = cv2.resize(img, (90, 90))

    #         image = self.add_border(img, 3, color)

    #         if image.shape[0] > max_height:
    #             max_height = image.shape[0]

    #         image_width = image.shape[1]

    #         # Пропускаем изображение, если его ширина превышает ширину основного изображения
    #         if image_width > main_width:
    #             continue

    #         if current_width + image_width > main_width:
    #             groups.append(current_group)
    #             current_group = []
    #             current_width = 0

    #         current_group.append(image)
    #         current_width += image_width

    #     if current_group:
    #         groups.append(current_group)

    #     # Объединяем все группы по горизонтали
    #     combined_rows = [np.hstack(group) for group in groups]

    #     # Определяем максимальную ширину объединенных строк
    #     max_combined_width = max(row.shape[1] for row in combined_rows)

    #     # Создаем новое изображение, добавляя объединенные строки изображений
    #     combined_image = np.zeros((len(combined_rows) * max_height, max_combined_width, 3), dtype=np.uint8)

    #     # Копируем объединенные строки изображений в новое изображение
    #     for i, row in enumerate(combined_rows):
    #         combined_image[i * max_height:(i + 1) * max_height, :row.shape[1]] = row

    #     self.last_height = max_height

    #     return combined_image
    
    
    def create_combined_image(self, main_image, batch_images, batch_metadata):
        """
        Формирует изображение из списков и запоминает высоту.

        :param main_image: Основное изображение.
        :param batch_metadata: Список информации об изображениях.
        :return: Объединенное изображение и высота.
        """
        
        main_width = main_image.shape[1]

        if not batch_metadata:
            return np.zeros((self.last_height, main_width, 3), dtype=np.uint8)

        groups = []
        current_group = []
        current_width = 0
        max_height = 0

        for i, input_item in enumerate(batch_metadata):
            if len(batch_images) > 0:
                img = batch_images[i]
            else:
                img = np.zeros((72, 72, 3), dtype=np.uint8)

            category = input_item.get('category', 'Good')
            total_area = input_item.get('total_area', 0)

            match category:
                case 'Good':
                    color = (0, 255, 0)
                case 'Bad':
                    color = (0, 0, 255)
                case 'Neutral':
                    color = (0, 255, 255)
                case _:
                    color = (255, 255, 255)
            
            try:
                img = cv2.resize(img, (90, 90))
            except:
                continue

            image = self.add_border(img, 3, color)
            
            #cv2.putText(img, str(round(total_area, 2)) , (27, 27 ), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

            if image.shape[0] > max_height:
                max_height = image.shape[0]

            image_width = image.shape[1]

            # Пропускаем изображение, если его ширина превышает ширину основного изображения
            if image_width > main_width:
                continue

            # Проверяем, выходит ли текущая ширина за пределы ширины основного изображения
            if current_width + image_width > main_width:
                break

            current_group.append(image)
            current_width += image_width

        if current_group:
            groups.append(current_group)

        # Объединяем все группы по горизонтали
        combined_rows = [np.hstack(group) for group in groups]

        # Определяем максимальную ширину объединенных строк
        max_combined_width = max(row.shape[1] for row in combined_rows)

        # Создаем новое изображение, добавляя объединенные строки изображений
        combined_image = np.zeros((len(combined_rows) * max_height, max_combined_width, 3), dtype=np.uint8)

        # Копируем объединенные строки изображений в новое изображение
        for i, row in enumerate(combined_rows):
            combined_image[i * max_height:(i + 1) * max_height, :row.shape[1]] = row

        self.last_height = max_height

        return combined_image

        
    def combine_images_vertically(self, main_image, combined_image):
        """
        Объединяет две картинки вертикально.

        :param main_image: Основное изображение.
        :param combined_image: Объединенное изображение.
        :return: Объединенное изображение.
        """
        main_height = main_image.shape[0]
        combined_height = combined_image.shape[0]
        main_width = main_image.shape[1]
        combined_width = combined_image.shape[1]

        # Создаем новое изображение, добавляя объединенные строки изображений ниже основного изображения
        final_image = np.zeros((main_height + combined_height, max(main_width, combined_width), 3), dtype=np.uint8)

        # Копируем основное изображение в новое изображение
        final_image[:main_height, :main_width] = main_image

        # Копируем объединенные строки изображений в новое изображение
        final_image[main_height:, :combined_width] = combined_image

        return final_image
    
    def blend_images(self, img1, img2, alpha=0.5):
        """
        Наложение двух изображений с заданной прозрачностью.

        :param img1: Первое изображение.
        :param img2: Второе изображение.
        :param alpha: Коэффициент прозрачности (0.0 - 1.0).
        :return: Наложенное изображение.
        """
    
        target_height, target_width = img1.shape[:2]

        # Изменение размера исходного изображения под размеры целевого изображения
        img2 = cv2.resize(img2, (target_width, target_height))
        

        return cv2.addWeighted(img1, alpha, img2, 1 - alpha, 0)


    def change_color_in_range(self, image, lower_bound, upper_bound, new_color):
        """
        Изменение цвета в заданном диапазоне на другой цвет в изображении.

        :param image: Входное изображение.
        :param lower_bound: Нижняя граница диапазона цветов (B, G, R).
        :param upper_bound: Верхняя граница диапазона цветов (B, G, R).
        :param new_color: Новый цвет в формате (B, G, R).
        :return: Измененное изображение.
        """
        # Создаем маску для заданного диапазона цветов
        mask = cv2.inRange(image, lower_bound, upper_bound)

        # Заменяем цвет в заданном диапазоне на новый цвет
        image[mask > 0] = new_color

        return image


    # def filter_color_and_check_area(self, image, hsv_bounds, area_threshold):
    #     """
    #     Фильтрует изображение по заданному цвету и проверяет площадь фильтрованного изображения.

    #     :param image: Исходное изображение.
    #     :param hsv_bounds: Кортеж с границами HSV (hl, sl, vl, hm, sm, vm).
    #     :param area_threshold: Порог по площади.
    #     :return: False, если площадь фильтрованного изображения больше порога, иначе True.
    #     """
         
    #     hl, sl, vl, hm, sm, vm = hsv_bounds
        
    #     # Преобразуем изображение в HSV
    #     hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        
    #     # Определяем диапазон цвета
    #     lower_bound = np.array([hl, sl, vl])
    #     upper_bound = np.array([hm, sm, vm])

    #     # Создаем маску для фильтрации цвета
    #     mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
        
    #     # Находим контуры на маске
    #     contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
    #     # Вычисляем площадь всех контуров
    #     total_area = sum(cv2.contourArea(contour) for contour in contours)
        
    #     # Добавляем текст с площадью на маску
    #     mask_with_text = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    #     cv2.putText(mask_with_text, f'{total_area}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
    #     # Проверяем площадь
    #     return total_area <= area_threshold, mask_with_text, total_area


    def filter_color_and_check_area(self, image, hsv_bounds, area_threshold, width = 25, height = 25):
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
        return total_area < area_threshold, mask_with_text, total_area


    def draw_on_frame(self, data_frame, control_data):
        frame = data_frame['frame_draw'] 
        batch_metadata = data_frame['batch_metadata']
        timestamp = data_frame['current_time']
        total = len(batch_metadata)

        total_good = data_frame.get('total_good', 0)
        total_bad = data_frame.get('total_bad', 0)
        
        #frame_crop = control_data['frame_crop']
        snap_y = control_data['snap_y']
        y_delta = control_data['y_delta']
        #frame_id = control_data['frame_id']
        #total = control_data['total']
        #total_all = control_data['total_all']
        x_min = control_data['x_min']
        x_max = control_data['x_max']
        fps = control_data['fps']
        draw = control_data['draw']
        circles = control_data['circles']
        rectangles = control_data['rectangles']
        record_video = control_data['record_video']
        save_image_all = control_data.get('save_image_all', False)
        calibration_line = control_data.get('calibration_line', False)
        calibration_circle = control_data.get('calibration_circle', False)
        resize_delta = control_data.get('resize_delta', 0)

        size_image_cnn = 72
        size_image_cnn_2 = int(size_image_cnn / 2) + 4

        if draw:
            for info_batch in batch_metadata:
                #(frame_id_circle, img, x, y, r, label, color, predict)
                frame_id_circle = info_batch['frame_id']
                x = info_batch['x']
                y = info_batch['y']
                r = info_batch['r']
                #color = info_batch['color']
                category = info_batch.get('category', 'Good')
                predict = info_batch.get('predict_value', 1)

                match category:
                    case 'Good':
                        color = (0, 255, 0)
                    case 'Bad':
                        color = (0, 0, 255)
                    case 'Neutral':
                        color = (0, 255, 255)
                    case _:
                        color = (255, 255, 255)

                #if frame_id_circle == frame_id:
                if circles:
                    cv2.circle(frame, (x + 1, y + 1), r, (0, 0, 0), 3)
                    cv2.circle(frame, (x, y), r, color, 3)

                if rectangles:
                    shadow_delta = 2
                    cv2.rectangle(frame, (x - size_image_cnn_2 + shadow_delta, y - size_image_cnn_2 + shadow_delta),
                                (x + size_image_cnn_2 + shadow_delta, y + size_image_cnn_2 + shadow_delta), (30, 30, 30), 1)
                    cv2.rectangle(frame, (x - size_image_cnn_2, y - size_image_cnn_2),
                                (x + size_image_cnn_2, y + size_image_cnn_2), (255, 0, 0), 2)

                if circles or rectangles:
                    cv2.putText(frame, category, (x - 15 + 1, y - r - 10 + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                    cv2.putText(frame, category, (x - 15, y - r - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

                    #cv2.putText(frame, str(round(r, 2)) , (x - 15 + 2, y ), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

                    cv2.putText(frame, str(round(predict, 2)) , (x - 15 + 2, y + 2 * r + 7 + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
                    cv2.putText(frame, str(round(predict, 2)) , (x - 15, y + 2 * r + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            
            if circles or rectangles:
                cv2.putText(frame, f'{total}', (x_max + 22, snap_y - 18), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 6)
                cv2.putText(frame, f'{total}', (x_max + 20, snap_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 6)
            
            processing_time = (time.time() - timestamp) * 1000

            cv2.putText(frame, f'Processing Time: {processing_time:.2f} ms', (22, 52), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            cv2.putText(frame, f'Processing Time: {processing_time:.2f} ms', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            cv2.putText(frame, f'fps: {fps}', (22, 82), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            cv2.putText(frame, f'fps: {fps}', (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            cv2.putText(frame, f'Total_all: {total_good + total_bad}', (502, 52), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            cv2.putText(frame, f'Total_all: {total_good + total_bad}', (500, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            cv2.putText(frame, f'Total_bad: {total_bad}', (502, 82), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            cv2.putText(frame, f'Total_bad: {total_bad}', (500, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)


            if not record_video:
                cv2.line(frame, (0, snap_y), (frame.shape[1], snap_y), (255, 0, 0), 2)

                cv2.line(frame, (x_min, snap_y - y_delta + 1), (x_max, snap_y - y_delta + 1), (0, 0, 0), 2)
                cv2.line(frame, (x_min, snap_y - y_delta), (x_max, snap_y - y_delta), (255, 255, 0), 2)

                cv2.line(frame, (x_min, snap_y + y_delta + 1), (x_max, snap_y + y_delta + 1), (0, 0, 0), 2)
                cv2.line(frame, (x_min, snap_y + y_delta), (x_max, snap_y + y_delta), (255, 255, 0), 2)

                cv2.line(frame, (x_min + 1, 0), (x_min + 1, frame.shape[0] - 98), (0, 0, 0), 2)
                cv2.line(frame, (x_min, 0), (x_min, frame.shape[0] - 98), (0, 255, 0), 2)

                cv2.line(frame, (x_max + 1, 0), (x_max + 1, frame.shape[0] - 98), (0, 0, 0), 2)
                cv2.line(frame, (x_max, 0), (x_max, frame.shape[0] - 98), (0, 255, 0), 2)

                cv2.line(frame, (41, snap_y - 30), (41, snap_y + 30), (0, 0, 255), 2)
                cv2.line(frame, (frame.shape[1] - 41, snap_y - 30), (frame.shape[1] - 41, snap_y + 30), (0, 0, 255), 2)


        color = (255, 0, 255)
        delta_bottom = 98
        center = (frame.shape[0]- delta_bottom) //2 + 6

        point_1 = (120, center)
        point_2 = (407, center)
        point_3 = (712, center)
        

        if calibration_line:
            cv2.line(frame, (point_1[0], 0), (point_1[0], frame.shape[0] - delta_bottom), (100, 255, 0), 2)

            cv2.line(frame, (point_2[0], 0), (point_2[0], frame.shape[0] - delta_bottom), (100, 255, 0), 2)

            cv2.line(frame, (point_3[0], 0), (point_3[0],  frame.shape[0] - delta_bottom), (100, 255, 0), 2)

            cv2.line(frame, (0, center), (frame.shape[1], center), (100, 255, 0), 2)

        if calibration_circle:
            radius = max(6, 33 + resize_delta)

            cv2.circle(frame, point_1, 3, color, -1)
            cv2.circle(frame, point_1, radius - 2, color, 3)
        
            cv2.circle(frame, point_2, 3, color, -1)
            cv2.circle(frame, point_2, radius, color, 3)
        
            cv2.circle(frame, point_3, 3, color, -1)
            cv2.circle(frame, point_3, radius - 2, color, 3)


        time_real = self.get_current_time()
        cv2.putText(frame, f'{time_real}', (700, 455), cv2.FONT_HERSHEY_PLAIN, 3, (255, 255, 255), 3)

        if record_video:
            cv2.putText(frame, 'Record video', (51, 81), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        if save_image_all:
            cv2.putText(frame, 'Save images', (51, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        return frame


    def add_black_space_below(self, frame, black_space_height):
        # Получаем размеры изображения
        height, width, channels = frame.shape

        # Создаем новое изображение с черной пустотой внизу
        new_image = np.zeros((height + black_space_height, width, channels), dtype=np.uint8)

        # Вставляем исходное изображение в верхнюю часть нового изображения
        new_image[:height, :] = frame

        return new_image
    

    def get_current_time(self):
        # Получаем текущее время
        now = datetime.now()
        # Форматируем строку в формат HH:MM
        current_time = now.strftime('%H:%M')
        return current_time
    
        
    def overlay_image(self, background, overlay, coordinates):
        bg_height, bg_width = background.shape[:2]
        result = background.copy()

        for (x, y, w, h) in coordinates:
            # Создаем overlay для текущей координаты
            if isinstance(overlay, np.ndarray):
                current_overlay = overlay
                oh, ow = current_overlay.shape[:2]
            else:
                # Создаем прямоугольник цвета с учетом текущих (w, h)
                current_overlay = np.full((h, w, 3), overlay, dtype=np.uint8)
                oh, ow = h, w

            # Рассчитываем обрезку overlay
            sx = max(0, -x)
            sy = max(0, -y)
            ex = min(ow, bg_width - x)
            ey = min(oh, bg_height - y)

            # Проверяем валидность области
            if ex <= sx or ey <= sy:
                continue

            # Рассчитываем позицию вставки
            dx = max(0, x)
            dy = max(0, y)
            overlay_cropped = current_overlay[sy:ey, sx:ex]

            # Вставляем в фон
            result[dy:dy + (ey - sy), dx:dx + (ex - sx)] = overlay_cropped

        return result
    

    def draw_circles(self, background, color, coordinates):
        """
        Рисует круги на изображении с центром в указанных координатах
        :param background: Исходное изображение (BGR)
        :param color: Цвет в формате (B, G, R)
        :param coordinates: Список координат [(x, y, radius), ...]
        :return: Изображение с кругами
        """
        result = background.copy()
        h, w = result.shape[:2]
        
        for (x, y, radius, _) in coordinates:
            # Проверка валидности радиуса
            if radius <= 0:
                continue
                
            # Определяем границы для безопасного рисования
            x_min = max(0, x - radius)
            x_max = min(w, x + radius + 1)
            y_min = max(0, y - radius)
            y_max = min(h, y + radius + 1)
            
            # Если круг полностью за пределами изображения
            if x_max <= x_min or y_max <= y_min:
                continue
                
            # Рисуем круг на копии изображения
            cv2.circle(
                img=result,
                center=(int(x), int(y)),
                radius=int(radius - 8),
                color=color,
                thickness=-1  # Заливка
            )
        
        return result
    

    # def find_counters(self, mask, area_trheshold_min, area_trheshold_max):
    #     #mask = cv2.cvtColor(mask, cv2.COLOR_RGB2GRAY)

    #     #mask = mask[:, :, 2]

    #     # Нахождение контуров
    #     contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    #     # Список для хранения результатов
    #     results = []

    #     # Обработка каждого контура
    #     for contour in contours:
    #         # Вычисление площади
    #         area = cv2.contourArea(contour)

    #         if area_trheshold_min <= area <= area_trheshold_max:
    #             # Вычисление ограничивающего прямоугольника
    #             x, y, w, h = cv2.boundingRect(contour)

    #             if h / w < 3.3 and w / h < 3.3:
    #                 # Вычисление центра 
    #                 center_x = x + w // 2
    #                 center_y = y + h // 2

    #                 # Добавление результатов в список
    #                 results.append({
    #                     'center': (center_x, center_y),
    #                     'counter': contour,
    #                     'area': area,
    #                     'width': w,
    #                     'height': h
    #                 })

    #     return results, contours

    def find_counters(self, mask, 
                        area_threshold_min, 
                        area_threshold_max, 
                        image_center_y=None, 
                        vertical_tolerance=100, 
                        height_min=None,  # Минимальная допустимая высота
                        height_max=None   # Максимальная допустимая высота
                        ):

        # Нахождение контуров
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Если image_center_y не задан, используем центр изображения по вертикали
        if image_center_y is None:
            image_center_y = mask.shape[0] // 2

        # Список для хранения результатов
        results = []

        # Обработка каждого контура
        for contour in contours:
            # Вычисление площади
            area = cv2.contourArea(contour)

            if area_threshold_min <= area <= area_threshold_max:
                # Вычисление ограничивающего прямоугольника
                x, y, w, h = cv2.boundingRect(contour)

                # Проверка высоты (если заданы ограничения)
                height_valid = True
                if height_min is not None and h < height_min:
                    height_valid = False
                if height_max is not None and h > height_max:
                    height_valid = False

                # Вычисление центра 
                center_x = x + w // 2
                center_y = y + h // 2

                # Проверка что центр по вертикали близок к центру изображения
                if height_valid and abs(center_y - image_center_y) <= vertical_tolerance:
                    # Добавление результатов в список
                    results.append({
                        'center': (center_x, center_y),
                        'counter': contour,
                        'area': area,
                        'width': w,
                        'height': h
                    })

        return results, contours

    def image_mask(self, image, hsv_bounds, blur=0):
        hl, sl, vl, hm, sm, vm = hsv_bounds

        # Преобразование изображения в HSV
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Определение границ цвета
        lower_bound = np.array([max(0, hl),
                                max(0, sl),
                                max(0, vl)])
        
        upper_bound = np.array([min(179, hm),
                                min(255, sm),
                                min(255, vm)])

        # Создание маски
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
        
        # Применение морфологических операций для удаления шумов
        kernel = np.ones((3, 3), np.uint8)
        mask_without_noise = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # Применение фильтра Гаусса для сглаживания
        mask_blurred = cv2.GaussianBlur(mask_without_noise, (7, 7), blur)

        # Создание белого изображения того же размера
        white_image = np.full_like(image, 255)

        # Применение маски для выделения нужных областей
        #extracted_image = np.where(mask[:, :, np.newaxis] == 255, image, white_image)
        extracted_image = np.where(mask_blurred[:, :, np.newaxis] == 255, image, white_image)
        
        
        return extracted_image, mask, mask_blurred
    

    def update_list_with_max_size(self, main_list, replacement_list, max_size):
        """Обновляет main_list, добавляя элементы из replacement_list, с учетом максимального размера max_size."""
        if len(replacement_list) > max_size:
            raise ValueError("Список замены не может быть длиннее максимального размера.")

        # Если основной список меньше максимального размера, добавляем элементы в конец
        if len(main_list) < max_size:
            main_list.extend(replacement_list[:max_size - len(main_list)])
        else:
            # Если основной список равен или больше максимального размера, заменяем последние элементы
            main_list[-len(replacement_list):] = replacement_list

        return main_list
    
    @staticmethod
    def create_image_with_text(width, height, background_color, text, text_color, font_size):

        # Создаем пустое изображение заданного размера и цвета
        image = np.zeros((height, width, 3), dtype=np.uint8)
        image[:] = background_color

        # Определяем шрифт и его размер
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = font_size / 48.0  # Примерный масштаб шрифта

        # Определяем размер текста
        (text_width, text_height), _ = cv2.getTextSize(text, font, fontScale=font_scale, thickness=2)

        # Вычисляем координаты для центрирования текста
        text_x = (width - text_width) // 2
        text_y = (height + text_height) // 2

        # Рисуем текст на изображении
        cv2.putText(image, text, (text_x, text_y), font, font_scale, text_color, thickness=2)

        return image