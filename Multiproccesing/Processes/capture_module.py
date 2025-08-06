import time
from Camera_module.socket_module import StreamServer
from Camera_module.frame_fps import FrameFPS
from Utils.timer import Timer


class VideoServer:
    def __init__(self, host='0.0.0.0', port=5000, 
                 resolution=(1920, 1080), quality=95, framerate=100):
        
        self.server = StreamServer(host=host, port=port)
        self.params = (4, resolution[0], resolution[1], quality, framerate)
        self.fps_counter = FrameFPS(update_interval=1.0)
        self.connection_active = False

        self.server.start()


    def run(self, queue_manager=None):
        print(f'Сервер запущен на {self.server.host}:{self.server.port}')
        
        while True:
            print("Ожидание подключения клиента...")
            self._accept_connection()
            
            try:
                while self.connection_active:
                    self._process_client(queue_manager)
            except ConnectionError:
                print("Соединение разорвано")
                self._reset_connection()
            except Exception as e:
                print(f"Критическая ошибка: {str(e)}")
                self.stop()
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


    def _process_client(self, queue_manager):
        """Обработка данных от клиента"""
        #start_frame = time.time()
        params, frame = self.server.receive()

        #elapsed = time.time() - start_frame
        #print(f"Время захвата кадра {elapsed * 1000} мс")
        
        # Обработка подтверждения параметров
        if params and params[0] == "ACK":
            print("Клиент подтвердил получение параметров")
            return
        
        # Обработка видеокадра
        if frame is not None:
            self._process_frame(frame, queue_manager)
        
        # Проверка активности соединения
        if params is None and frame is None:
            raise ConnectionError("Соединение разорвано")


    def _process_frame(self, frame, queue_manager):
        """Обработка и сохранение кадра"""
        fps = self.fps_counter.update()
        if fps > 0:
            print(f"FPS: {fps:.2f}")
        
        if queue_manager:
            frames = [frame]
            id_memory = 0
            queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)
            
            data_frame = {'id_memory': id_memory, 'time': time.time()}
            queue_manager.input_processing.put(data_frame)
            queue_manager.input_capture.get()


    def _reset_connection(self):
        """Сброс состояния соединения"""
        self.server._close_connection()
        self.connection_active = False


    def stop(self):
        """Остановка сервера"""
        self.server.stop()
        print("Сервер остановлен")


def main(queue_manager=None):
    server = VideoServer(
        host='192.168.1.10', 
        port=5000,
        resolution=(1920, 1080),
        #resolution=(640, 480),
        quality=95,
        framerate=100
    )
    
    try:
        server.run(queue_manager)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()