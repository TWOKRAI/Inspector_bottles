import time
import cv2

from .process_module import ProcessModule
from Camera_module.socket_module import StreamServer
from Camera_module.frame_fps import FrameFPS
from Utils.timer import Timer


class Capture_process(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 120,
                    }

        self.connection_active = False

        self.resolution=(1920, 1080)

        self.fps_counter = FrameFPS(update_interval=1.0)
        self.fps = 0

        self.video_stream = 0

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

        self.timer = Timer('read_frame')


    def get_parameters(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        #print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
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
        self.timer.start()

        if self.video_stream == 0:
            ret, frame = self.cap.read()
        elif self.video_stream == 1:
            params, frame = self.server.receive()

            # Обработка подтверждения параметров
            if params and params[0] == "ACK":
                print("Клиент подтвердил получение параметров")
                return

        #self.timer.elapsed_time(print_log=True)

        # Обработка видеокадра
        if frame is not None:
            self._process_frame(frame)
        
        # Проверка активности соединения
        if self.video_stream == 1:
            if params is None and frame is None:
                raise ConnectionError("Соединение разорвано")


    def _process_frame(self, frame):
        """Обработка и сохранение кадра"""
        self.fps  = self.fps_counter.update()
        if self.fps  > 0:
            print(f"FPS: {self.fps :.2f}")
            pass
        
        if self.queue_manager:
            frames = [frame]
            id_memory = 0
            self.queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)
            
            data_frame = {'id_memory': id_memory, 'time': time.time()}
            self.queue_manager.input_processing.put(data_frame)
            #self.queue_manager.input_capture.get()


    def _reset_connection(self):
        """Сброс состояния соединения"""
        if self.video_stream == 1:
            self.server._close_connection()
        
        self.connection_active = False


def main(queue_manager=None):
    capture = Capture_process(name='Capture_process', 
                              queue_manager=queue_manager, 
                              control_queue=queue_manager.control_capture)
    capture.run()
    