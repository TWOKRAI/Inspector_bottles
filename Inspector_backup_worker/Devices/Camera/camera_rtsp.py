import cv2
import numpy as np
import os


#os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"
#os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

class Camera_rtsp:
    def __init__(self, rtsp_url):
        buffer_size = 655360
        self.rtsp_url = rtsp_url #+ f"/path?buffer_size={buffer_size}"
        self.cap = None

        self.create_cap()

        self.width = 1280
        self.height = 720

        self.fps = 20
        
        print("Камера запущена")


    def clear_cache(self, cadr):
        # Читаем несколько кадров без задержек для очистки кэша
        for _ in range(cadr):  
            self.cap.grab()


    def capture_frame(self):
        # Захватываем кадр без декодирования
        self.cap.grab()
        ret, frame = self.cap.retrieve()

        if not ret:
            return None

        return frame


    def create_cap(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(self.rtsp_url,
                                        cv2.CAP_FFMPEG)
            
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 


    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


    def start_recording(self, output_file, codec='XVID', fps=20.0, frame_size=(1280, 720)):
        fourcc = cv2.VideoWriter_fourcc(*codec)
        self.out = cv2.VideoWriter(output_file, fourcc, fps, frame_size)
        print(f"Запись видео начата в файл: {output_file}")


    def record_frame(self):
        # Захватываем кадр и записываем его в видеофайл
        ret, frame = self.cap.read()
        if not ret:
            return False
        self.out.write(frame)
        return frame 


    def stop_recording(self):
        # Освобождаем ресурсы VideoWriter
        self.out.release()
        print("Запись видео остановлена")


    def calculate_delay(self, fps):
        if fps <= 0:
            raise ValueError("FPS должно быть положительным числом")
        delay = 1.0 / fps
        
        return delay
    

    def create_image_with_text(self, background_color, text, text_color, font_size):
        # Создаем пустое изображение заданного размера и цвета
        image = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        image[:] = background_color

        # Определяем шрифт и его размер
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = font_size / 48.0  # Примерный масштаб шрифта

        # Определяем размер текста
        (text_width, text_height), _ = cv2.getTextSize(text, font, fontScale=font_scale, thickness=2)

        # Вычисляем координаты для центрирования текста
        text_x = (self.width - text_width) // 2
        text_y = (self.height + text_height) // 2

        # Рисуем текст на изображении
        cv2.putText(image, text, (text_x, text_y), font, font_scale, text_color, thickness=2)

        return image
