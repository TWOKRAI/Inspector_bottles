import cv2
import numpy as np

class ColorDetector:
    def __init__(self, video_source=0):
        self.cap = cv2.VideoCapture(video_source)
        self.window_name = 'Trackbars'
        self.min_contour_area = 500
        
        # Инициализация значений HSV по умолчанию
        self.h_min = 35
        self.h_max = 85
        self.s_min = 50
        self.s_max = 255
        self.v_min = 50
        self.v_max = 255
        self.erode = 1
        self.dilate = 1
        
        self.create_trackbar_window()
    

    def create_trackbar_window(self):
        """Создает окно с трекбарами для настройки параметров"""
        cv2.namedWindow(self.window_name)
        cv2.resizeWindow(self.window_name, 900, 500)
        
        # Создание трекбаров с текущими значениями
        cv2.createTrackbar('H Min', self.window_name, self.h_min, 179, lambda x: None)
        cv2.createTrackbar('H Max', self.window_name, self.h_max, 179, lambda x: None)
        cv2.createTrackbar('S Min', self.window_name, self.s_min, 255, lambda x: None)
        cv2.createTrackbar('S Max', self.window_name, self.s_max, 255, lambda x: None)
        cv2.createTrackbar('V Min', self.window_name, self.v_min, 255, lambda x: None)
        cv2.createTrackbar('V Max', self.window_name, self.v_max, 255, lambda x: None)
        cv2.createTrackbar('Erode', self.window_name, self.erode, 10, lambda x: None)
        cv2.createTrackbar('Dilate', self.window_name, self.dilate, 10, lambda x: None)

        cv2.createTrackbar('fps', self.window_name, self.dilate, 100, lambda x: None)
        cv2.createTrackbar('delta', self.window_name, self.dilate, 100, lambda x: None)

        cv2.createTrackbar('min_x', self.window_name, 0, 100, lambda x: None)
        cv2.createTrackbar('max_x', self.window_name, 100, 500, lambda x: None)

    
    def get_trackbar_values(self):
        """Считывает текущие значения с трекбаров"""
        self.h_min = cv2.getTrackbarPos('H Min', self.window_name)
        self.h_max = cv2.getTrackbarPos('H Max', self.window_name)
        self.s_min = cv2.getTrackbarPos('S Min', self.window_name)
        self.s_max = cv2.getTrackbarPos('S Max', self.window_name)
        self.v_min = cv2.getTrackbarPos('V Min', self.window_name)
        self.v_max = cv2.getTrackbarPos('V Max', self.window_name)
        self.erode = cv2.getTrackbarPos('Erode', self.window_name)
        self.dilate = cv2.getTrackbarPos('Dilate', self.window_name)

        self.fps = cv2.getTrackbarPos('fps', self.window_name)
        self.delta = cv2.getTrackbarPos('delta', self.window_name)

        self.min_x = cv2.getTrackbarPos('min_x', self.window_name)
        self.max_x = cv2.getTrackbarPos('max_x', self.window_name)

    
    def process_frame(self, frame):
        """
        Обрабатывает кадр: определяет цвет по HSV, применяет морфологические операции,
        находит контуры и рисует bounding boxes
        """
        # Преобразование в HSV
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Создание маски
        lower = np.array([self.h_min, self.s_min, self.v_min])
        upper = np.array([self.h_max, self.s_max, self.v_max])
        mask = cv2.inRange(hsv, lower, upper)
        
        # Морфологические операции
        mask = cv2.erode(mask, None, iterations=self.erode)
        mask = cv2.dilate(mask, None, iterations=self.dilate)
        
        # Поиск контуров
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Отрисовка контуров и прямоугольников
        processed_frame = frame.copy()
        for contour in contours:
            if cv2.contourArea(contour) > self.min_contour_area:
                # Рисование контура
                cv2.drawContours(processed_frame, [contour], -1, (0, 255, 0), 2)
                
                # Рисование bounding box
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(processed_frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
        
        return processed_frame, mask