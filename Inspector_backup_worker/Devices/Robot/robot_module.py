import socket
import time
import math


class RobotModule:
    def __init__(self, host, port, stop_event):
        self.stop_event = stop_event

        self.server_ready= False
        self.socket = None
        self.host = host
        self.port = port
        
        self.connected = False
        self.conn = None
        self.addr = None    

        self.ready_on = False
        self.state_on = False
        self.servo_state = False
        self.read_recv = False

        self.hand = 1

        self.x0 = 0
        self.y0 = 0

        self.speed_arm = 1800

        self.radius_min = 150
        self.radius_max = 550

        self.y_max = 480

        self.position_real_x = 300
        self.position_real_y = -300

        self.position_camera_x = 310
        self.position_camera_y = -860

        self.home_postion = (300, -300)

        self.max_vis_x = 700
        self.min_vis_x = 120
        self.max_rob_x = 525
        self.min_rob_x = 87

        self.max_vis_y = 31
        self.min_vis_y = -31
        self.max_rob_y = 23
        self.min_rob_y = -23

        self.iterator = 0

        #self.speed_conveyor = 21.8  # mm/s


    def start_server(self):
        """Запускает сервер и слушает входящие подключения."""
        if not self.server_ready:
            print('Попытка запустить сервер')
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.bind((self.host, self.port))
                self.socket.listen()
                self.server_ready = True

                print(f"Сервер запущен и слушает на {self.host}:{self.port}")
                
            except Exception as e:
                self.close_server()
                print(f"Произошла ошибка при запуске сервера: {e}")
        

    def close_server(self):
        if self.socket:
            self.socket.close()
            self.server_ready = False


    def create_connected(self):      
        if not self.connected:
            print('Попытка создать подключение')
            try:
                self.conn, self.addr = self.socket.accept()
                self.conn.settimeout(21000) #5
                self.connected = True
                print(f"Подключено к клиенту с адреса {self.addr}")
      
            except Exception as e:
                print(f"Произошла ошибка: {e}. Перезапуск подключения..")
                self.close_robot()


    def close_robot(self):
        if self.conn:
            self.conn.close()
        
        self.connected = False
        print(f'Соединение закрыто с {self.addr}')


    def send_data(self, data):
        data = self.format_data_for_tcp(data)

        if self.connected:
            try:
                #print(f'Сервер отправил {data}')
                self.conn.sendall(data.encode('utf-8'))
            except Exception as e:
                print(f"Произошла ошибка при отправке данных: {e}. Закрытие соединения...")
                self.close_robot()


    def receive_data(self):
        if self.connected:
            try:
                data = self.conn.recv(1024)
                #print(f'Сервер получил {data}')

                data = self.split_message(data.decode('utf-8'))

                return data
            except Exception as e:
                print(f"Произошла ошибка при получении подтверждения: {e}. Закрытие соединения...")
                self.close_robot()
                
                return None
        else:
            return None


    @staticmethod
    def format_data_for_tcp(data_list, delimiter=',', end_of_line='\r\n'):
        """
        Преобразует список данных в строку, готовую для отправки по TCP.

        :param data_list: Список данных для отправки.
        :param delimiter: Знак разделения элементов списка.
        :param end_of_line: Символ конца строки.
        :return: Строка, готовая для отправки по TCP.
        """
        formatted_data = delimiter.join(map(str, data_list)) + end_of_line
        #print('formatted_data:', repr(formatted_data), 'time', time.time())
        return formatted_data


    @staticmethod
    def split_message(message, delimiter=',', end_of_line='\r\n'):
        """
        Убирает символы конца строки и разбивает сообщение на список строк на основе указанного разделителя.

        :param message: Сообщение для разбиения.
        :param delimiter: Разделитель для разбиения сообщения.
        :param end_of_line: Символы конца строки для удаления.
        :return: Список строк, полученных из сообщения.
        """
        # Убираем символы конца строки
        cleaned_message = message.strip(end_of_line)
        # Разбиваем сообщение на список
        return cleaned_message.split(delimiter)


    @staticmethod
    def hertz_to_mm_per_sec(frequency_hz: float, per_cycle=0.727) -> float:
        """
        Переводит частоту в герцах в скорость в миллиметрах в секунду.

        :param frequency_hz: Частота в герцах.
        :param per_cycle: коэффициент соотношения.
        :return: Скорость в миллиметрах в секунду.
        """
        speed_mm_per_sec = frequency_hz * per_cycle
        return speed_mm_per_sec
    

    def calculate_radius(self, x, y):
        """
        Вычисляет радиус круга, зная координаты точки и центра круга.

        :param x: Координата x точки.
        :param y: Координата y точки.
        :return: Радиус круга.
        """
        radius = math.sqrt((x - self.x0)**2 + (y - self.y0)**2)
        return radius


    @staticmethod
    def calculate_distance(start_timestamp: float, speed_mm_per_sec: float) -> float:
        """
        Вычисляет расстояние, которое конвейер проехал с момента заданной временной метки до текущего времени.

        :param start_timestamp: Временная метка начала движения конвейера в секундах.
        :param speed_mm_per_sec: Скорость конвейера в мм/с.
        :return: Расстояние в миллиметрах.
        """
        current_timestamp = time.time()
        time_difference = current_timestamp - start_timestamp
        distance = speed_mm_per_sec * time_difference

        return distance
    

    @staticmethod
    def calculate_distance_radius(y_point, radius):
        # Проверка, находится ли точка в пределах окружности
        if y_point > radius:
            return None

        # Вычисление x-координаты точки пересечения
        x_intersection = math.sqrt(radius**2 - y_point**2)

        return x_intersection


    def scale_image_to_real_distance_x(self, coordinate: float, min_diff: float = 10) -> float:
        """
        Преобразует координату из визуального диапазона (пиксели) в реальный диапазон (размеры).

        :param coordinate: Координата в визуального диапазона (пиксели), которую нужно преобразовать.
        :param min_diff: Минимальная разница между максимальными и минимальными значениями диапазонов.
        :return: Координата в реальном диапазоне (размеры).
        """
        # Корректировка значений, если разница меньше min_diff
        if self.max_vis_x - self.min_vis_x < min_diff:
            self.max_vis_x = self.min_vis_x + min_diff
        if self.max_rob_x - self.min_rob_x < min_diff:
            self.max_rob_x = self.min_rob_x + min_diff

        # Ограничение координаты в пределах визуального диапазона
        coordinate = max(self.min_vis_x, min(coordinate, self.max_vis_x))

        # Преобразование координаты
        scaled_coordinate = (self.max_rob_x - self.min_rob_x) * (coordinate - self.min_vis_x) / (self.max_vis_x - self.min_vis_x) + self.min_rob_x
        return scaled_coordinate


    def scale_image_to_real_distance_y(self, coordinate: float, min_diff: float = 10) -> float:
        """
        Преобразует координату из визуального диапазона (пиксели) в реальный диапазон (размеры).

        :param coordinate: Координата в визуального диапазона (пиксели), которую нужно преобразовать.
        :param min_diff: Минимальная разница между максимальными и минимальными значениями диапазонов.
        :return: Координата в реальном диапазоне (размеры).
        """
        # Корректировка значений, если разница меньше min_diff
        if self.max_vis_y - self.min_vis_y < min_diff:
            self.max_vis_y = self.min_vis_y + min_diff
        if self.max_rob_y - self.min_rob_y < min_diff:
            self.max_rob_y = self.min_rob_y + min_diff

        # Ограничение координаты в пределах визуального диапазона
        coordinate = max(self.min_vis_y, min(coordinate, self.max_vis_y))

        # Преобразование координаты
        scaled_coordinate = (self.max_rob_y - self.min_rob_y) * (coordinate - self.min_vis_y) / (self.max_vis_y - self.min_vis_y) + self.min_rob_y
        return scaled_coordinate


    def distance_to_point(self, point):
        x1, y1 = self.position_real_x, self.position_real_y
        x2, y2 = point

        distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

        return distance


    def check_point_to_x_intersection(self, point, direction='positive'):
        center_x = 0
        center_y = 0
        radius = self.radius_max

        point_x, point_y = point

        # Вычисляем расстояние от точки до центра окружности
        distance_to_center = math.sqrt((point_x - center_x) ** 2 + (point_y - center_y) ** 2)

        # Проверяем, находится ли точка внутри окружности
        if distance_to_center > radius:
            return None

        # Вычисляем расстояние до края окружности при движении по оси y
        if direction == 'positive':
            # Находим y-координату точки пересечения с окружностью
            delta_y = math.sqrt(radius**2 - (point_x - center_x)**2)
            y_intersection = center_y + delta_y
            distance_to_edge = y_intersection - point_y
        elif direction == 'negative':
            # Находим y-координату точки пересечения с окружностью
            delta_y = math.sqrt(radius**2 - (point_x - center_x)**2)
            y_intersection = center_y - delta_y
            distance_to_edge = point_y - y_intersection
        else:
            raise ValueError("Direction must be 'positive' or 'negative'")

        return distance_to_edge