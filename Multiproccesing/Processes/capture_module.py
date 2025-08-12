import threading
import time
import cv2

from Camera_module.socket_module import StreamServer
from Camera_module.frame_fps import FrameFPS
from Utils.timer import Timer


class Capture_process:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

        self.stop_proccess = False

        self.connection_active = False

        self.resolution=(1920, 1080)

        self.fps_counter = FrameFPS(update_interval=1.0)

        self.video_stream = 0

        self.local_controls_parametrs = {
                    'fps': 50, 
                    'delta': 120,
                    }

        if self.video_stream == 0:
            self.cap = cv2.VideoCapture(0)
        elif self.video_stream == 1:
            host='0.0.0.0'
            port=5000
            quality=95,
            framerate=100
            self.params = (4, self.resolution[0], self.resolution[1], quality, framerate)

            self.server = StreamServer(host=host, port=port)
            self.server.start()

            print(f'Сервер запущен на {self.server.host}:{self.server.port}')


        self._init_threading()


    def _init_threading(self):
        self.control_thread = threading.Thread(target=self._control_threading)
        self.main_thread = threading.Thread(target=self._main_threading)


    def start_thread(self):
        self.main_thread.start()
        self.control_thread.start()


    def stop_thread(self):
        self.main_thread.join()
        self.control_thread.join()

        """Остановка сервера"""
        if self.video_stream == 1:  
            self.server.stop()
            print("Сервер остановлен")

        #self.camera.release()

        #print('Процесс RTSPStreamProcessor остановлен')


    def _control_threading(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            controls_parametrs = self.queue_manager.control_capture.get()

            self.update_parametrs(controls_parametrs)


    def update_parametrs(self, incoming_parametrs):
        for key in incoming_parametrs:
            if key in self.local_controls_parametrs:
                self.local_controls_parametrs[key] = incoming_parametrs[key]
        
        self.fps = self.local_controls_parametrs['fps']
        self.delta = self.local_controls_parametrs['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def _main_threading(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            if self.video_stream == 1:
                print("Ожидание подключения клиента...")
                self._accept_connection()
            else:
                self.connection_active = True

            try:
                while self.connection_active:
                    self._process_client()
            except ConnectionError:
                print("Соединение разорвано")
                self._reset_connection()
            except Exception as e:
                print(f"Критическая ошибка: {str(e)}")
                break


    def _accept_connection(self):
        """Принимаем и настраиваем новое подключение"""
        connected, addr = self.server.accept_connection()
        if connected:
            print(f"Клиент подключен: {addr}")
            self.connection_active = True
            self.server.send_params(self.params)
            print("Параметры камеры отправлены клиенту")
        else:
            self.connection_active = False


    def _process_client(self):
        """Обработка данных от клиента"""
        #start_frame = time.time()

        if self.video_stream == 0:
            ret, frame = self.cap.read()
        elif self.video_stream == 1:
            params, frame = self.server.receive()

            # Обработка подтверждения параметров
            if params and params[0] == "ACK":
                print("Клиент подтвердил получение параметров")
                return

        #elapsed = time.time() - start_frame
        #print(f"Время захвата кадра {elapsed * 1000} мс")
        
        # Обработка видеокадра
        if frame is not None:
            self._process_frame(frame)
        
        # Проверка активности соединения
        if self.video_stream == 1:
            if params is None and frame is None:
                raise ConnectionError("Соединение разорвано")


    def _process_frame(self, frame):
        """Обработка и сохранение кадра"""
        fps = self.fps_counter.update()
        if fps > 0:
            #print(f"FPS: {fps:.2f}")
            pass
        
        if self.queue_manager:
            frames = [frame]
            id_memory = 0
            self.queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)
            
            data_frame = {'id_memory': id_memory, 'time': time.time()}
            self.queue_manager.input_processing.put(data_frame)
            self.queue_manager.input_capture.get()


    def _reset_connection(self):
        """Сброс состояния соединения"""
        if self.video_stream == 1:
            self.server._close_connection()
        
        self.connection_active = False


def main(queue_manager=None):
    capture = Capture_process(queue_manager)
    
    try:
        capture.start_thread()
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop_thread()


if __name__ == "__main__":
    main()