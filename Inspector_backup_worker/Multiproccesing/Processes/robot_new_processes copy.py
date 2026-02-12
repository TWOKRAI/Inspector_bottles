import threading
import logging
from queue import Empty
import time
import math

from Devices.Robot.robot_module import RobotModule
from Devices.Conveyer import Conveyor

from Utils.timer import Timer

with open('robot_communication.log', 'w'):
    pass

# Настройка логирования
logging.basicConfig(filename='robot_communication.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s, ', encoding='utf-8')


class RobotCommunicator:
    def __init__(self, queue_manager, stop_event, host='127.0.0.1', port=12345):
        self.queue_manager = queue_manager
        self.stop_event = stop_event

        self.robot_event = threading.Event()
        self.send_event = threading.Event()

        self.list_lock = threading.Lock()

        self.robot = RobotModule(host, port, stop_event)
        self.conveyor = Conveyor(port='COM7', baudrate=9600)

        self.servo_on = 0
        self.func = 0
        self.position = 0
        self.shift = 0
        self.lengh = 0
        self.drop = 2
        self.back = 0
        self.pr = 1
        self.tracking = 0
        self.DO1 = 0
        self.DO2 = 0

        self.server = False

        self.snap_y = 0

        self.x_new = 0
        self.y_new = 0

        self.current_id = 0
        self.filter_dict = {}
        self.coordinate_list = []
        self.sort_list = []

    
    def start(self):
        server_thread = threading.Thread(target=self.start_server)
        server_thread.start()

        conveyor_thread = threading.Thread(target=self.control_conveyor_thread)
        robot_thread = threading.Thread(target=self.control_robot_thread)
        process_queue_thread = threading.Thread(target=self.process_queue_thread)
        process_coordinates_thread = threading.Thread(target=self.process_coordinates_thread)
        data_sender_thread = threading.Thread(target=self.data_sender_thread)

        conveyor_thread.start()
        robot_thread.start()
        process_queue_thread.start()
        process_coordinates_thread.start()
        data_sender_thread.start()

        self.queue_manager.download.put(('communicate_with_robot', True))

        conveyor_thread.join()
        robot_thread.join()
        process_queue_thread.join()
        process_coordinates_thread.join()
        data_sender_thread.join()
        server_thread.join()

        print('Завершение процесса communicate_with_robot')
        self.robot.cleanup()


    def start_server(self):
        #self.robot_event.set()
        self.send_event.set()

        first = False

        while not self.queue_manager.stop_event.is_set():
            if self.server == False and self.robot.server_ready:
                self.queue_manager.robot_on.clear()
                self.robot.close_server() 
                self.robot.close_robot()
                first = False

            if self.server == True and not self.robot.server_ready:
                self.robot.start_server()

            if self.robot.server_ready and not self.robot.connected: 
                self.robot.create_connected()

            if self.robot.connected and not first:
                self.queue_manager.robot_on.set()

                logging.info(f'Первый опрос')
                self.send_event.set()
                first = True
            
            time.sleep(1)
                
        self.robot.close_server()
        self.robot.close_robot()


    def control_conveyor_thread(self):
        freq_real = self.conveyor.get_freq()
        self.conveyor.hertz_to_mm_per_sec(freq_real, self.conveyor.k)

        while not self.queue_manager.stop_event.is_set():
            try:
                #control_conveyor = self.queue_manager.control_conveyor.get(timeout=1)
                control_conveyor = self.queue_manager.control_conveyor.get_nowait()
            except Empty:
                time.sleep(0.1)
                continue

            self.queue_manager.control_conveyor_event.wait()
            control_conveyor = self.queue_manager.control_conveyor.get()
            self.queue_manager.control_conveyor_event.clear()

            if isinstance(control_conveyor, dict):
                conveyor_freq = control_conveyor['conveyor_freq']
                if conveyor_freq != self.conveyor.freq:
                    self.conveyor.change_freq(conveyor_freq)
                    freq_real = self.conveyor.get_freq()
                    #
                    print('freq_real', freq_real)
                    self.conveyor.hertz_to_mm_per_sec(freq_real, self.conveyor.k)



    def control_robot_thread(self):
        while not self.queue_manager.stop_event.is_set():
            self.queue_manager.control_robot_event.wait()
            control_robot = self.queue_manager.control_robot.get()
            self.queue_manager.control_robot_event.clear()

            self.robot_on = control_robot.get('robot_on', False)
            self.snap_y = control_robot.get('snap_y', 200)
            self.servo_on = control_robot.get('servo_on', False)
            self.position = control_robot.get('position', 0)
            self.shift = control_robot.get('shift', 0)
            self.shift_time = control_robot.get('shift_time', 1100)
            self.lengh = control_robot.get('lenght', 0)
            self.back = control_robot.get('back', 0)
            self.pr = control_robot.get('pr', 1)
            self.tracking = control_robot.get('tracking', 0)
            self.DO1 = control_robot.get('do1', False)
            self.DO2 = control_robot.get('do2', False)

            self.server = control_robot.get('server', False)

            self.min_rob_x = control_robot.get('min_rob_x', self.robot.min_rob_x)
            self.max_rob_x = control_robot.get('max_rob_x', self.robot.max_rob_x)

            self.robot.min_rob_x = self.min_rob_x
            self.robot.max_rob_x = self.max_rob_x 

            self.robot.state_on = self.robot_on

            logging.info(f'робот включен {self.robot_on}')

            if not self.robot_on:
                self.robot.ready_on = False
                # self.coordinate_list = []
                # self.sort_list = []
                self.func = 1
                # self.queue_manager.clear_queue(self.queue_manager.robot_queue, 0)
                self.clear_all()
            else:
                self.func = 2
   
            self.send_event.set()


    def process_queue_thread(self):
        prev_list = []

        while not self.queue_manager.stop_event.is_set():
            if self.servo_on and not self.robot.servo_state:
                self.robot.servo_state = True
                #self.queue_manager.clear_queue(self.queue_manager.robot_queue, 0)
                self.clear_all()

            if not self.servo_on and self.robot.servo_state:
                self.robot.servo_state = False
         
            if not self.robot.ready_on:
                #logging.info(f'self.robot.ready_on {self.robot.ready_on}')
                continue

            # try: 
            #     input_batch = self.queue_manager.robot_queue.get_nowait()
            #     #logging.info('input_batch', input_batch)
            # except Empty:
            #     time.sleep(0.05)
            #     continue
            
            input_batch = self.queue_manager.robot_queue.get()
            
            for input_item in input_batch:
                frame_id = input_item['frame_id']
                #img = input_item['img']
                x = input_item['x'] 
                y = input_item['y'] 
                #r  = input_item['r'] 
                timestamp = input_item['timestamp'] 
                # category = input_item['category']
     
                seconds_to_sub = self.shift_time / 1000.0
                new_timestramp = timestamp - seconds_to_sub

                x_new = self.robot.scale_image_to_real_distance_x(x)

                y_snap = -(y - self.snap_y)
                y_delta = self.robot.scale_image_to_real_distance_y((y_snap))

                if self.current_id >= 99:
                    self.current_id = 0 
                
                self.current_id += 1

                unique_id = self.current_id
                state = False

                delta_prev = True

                for prev_coord in prev_list:
                    if abs(x - prev_coord['x']) <= 8:
                        #logging.info(f'Не пропустил {unique_id, x, y_delta, new_timestramp, frame_id, state}')
                        #logging.info(f'Из за {prev_coord}')
                        delta_prev = False
                        break
                
                if not delta_prev:
                    continue

                with self.list_lock:
                    #logging.info(f'Добавил в список self.coordinate_list из очереди {unique_id, x_new, y_delta, new_timestramp, frame_id, state}')
                    self.coordinate_list.append([unique_id, x_new, y_delta, new_timestramp, frame_id, state])

            prev_list = input_batch


    def process_coordinates_thread(self):
        while not  self.queue_manager.stop_event.is_set():
            if not self.coordinate_list:
                time.sleep(0.01)
                #continue

            time.sleep(0.01)

            #self.timer_1.start()

            sort_list = []
            delete_list = []

            with self.list_lock:
                for replay in self.coordinate_list:
                    unique_id, x_new, y_delta, new_timestramp, frame_id, state = replay

                    current_timestamp = time.time()
                    y_new = self.robot.position_camera_y + self.calculate_distance(new_timestramp, self.conveyor.speed, current_timestamp) + y_delta
                    
                    distance_to_point = self.robot.distance_to_point((x_new, y_new)) / self.robot.speed_arm * self.conveyor.speed
                    
                    #logging.info(f'Replafy {replay, self.robot.y_max - distance_to_point}')
                    
                    if y_new <= self.robot.y_max - distance_to_point:
                        yx_radius = math.sqrt(x_new**2 + y_new**2)
                        if yx_radius <= self.robot.radius_max:
                            if state == False:
                                distance_intersection = self.robot.check_point_to_x_intersection((x_new, y_new))
                                sort_list.append((distance_intersection, x_new, y_new, unique_id, y_delta, new_timestramp))
                        #logging.info(f'sort_list {replay, self.robot.y_max - distance_to_point}')
                    else:
                        delete_list.append(unique_id)
                        #logging.info(f'Вышел из зоны на сервере {replay}')


            # if self.timer_wait.elapsed_time() > 12 and not self.robot_event.is_set():
            #     self.robot_event.set()
            #     self.timer_wait.start()


            if self.robot_event.is_set() and not self.send_event.set() and self.robot.ready_on:
                #logging.info(f'sort_list2 {sort_list}')
                if len(sort_list) > 0:
                    sort_list.sort(key=lambda item: item[0])

                    x_new = sort_list[0][1]
                    y_new = sort_list[0][2]
                    unique_id = sort_list[0][3]
                    y_delta = sort_list[0][4]
                    new_timestramp = sort_list[0][5]

                    if len(sort_list) > 1:
                        if sort_list[1][2] >= 250:
                            self.drop = 0
                        elif sort_list[1][2] <= -250:
                            self.drop = 1
                        else:
                            self.drop = 2
                    else:
                        self.drop = 2
                    
                    self.x_new = round(x_new, 1)

                    if self.robot.state_on:
                        self.func = 3

                    current_timestamp = time.time()
                    y_new = self.robot.position_camera_y + self.calculate_distance(new_timestramp, self.conveyor.speed, current_timestamp) + y_delta
                    self.y_new = round(y_new, 1)

                    if self.y_new < 0 and self.robot.hand == 0:
                        logging.info('Перестраивает плечо, через сброс')
                        self.func = 4 
                    
                    self.robot_event.clear()
                    #self.timer_wait.start()

                    #print(f'такое ожидание {self.timer_1.elapsed_time()}')
                    self.send_event.set()
                    
                    if self.func == 3:
                        self.state_by_id(unique_id, self.coordinate_list, True)

                    logging.info(f'-------------')
                    logging.info(f'Вычислена новая позиция: unique_id = {unique_id} x_new={x_new},  y_new={y_new}, y_delta ={y_delta}  время {new_timestramp}')
                else:
                    # if self.timer_wait.elapsed_time() > 12:
                    #     self.robot_event.set()
                    #     self.timer_wait.start()

                    if (abs(self.robot.position_real_x - self.robot.home_postion[0]) > 5 and abs(self.robot.position_real_y - self.robot.home_postion[1]) > 5) or self.robot.iterator >= 1:
                        if self.robot.state_on:
                            self.func = 4
                        
                            self.send_event.set()

                    # if self.robot.iterator >= 1:
                    #     self.func = 4
                    #     self.send_event.set()
                        
            for unique_id in delete_list:
                self.remove_entry_by_id(unique_id, self.coordinate_list)


    def data_sender_thread(self):
        while not self.queue_manager.stop_event.is_set():
            if self.send_event.wait(3):
                result_data = (self.servo_on,
                               self.func,
                               self.position,
                               self.shift,
                               self.conveyor.speed,
                               self.x_new,
                               self.y_new,
                               self.drop,
                               self.back,
                               self.pr,
                               self.tracking,
                               self.DO1,
                               self.DO2
                               )

                self.robot.send_data(result_data)
                logging.info(f"Отправка данных: {result_data} время {time.time()}")

                self.func = 0
                self.x_new = 0
                self.y_new = 0

                data = self.robot.receive_data()

                time.sleep(0.2)
                self.send_event.clear()

                if isinstance(data, list):
                    if data[0] == '0' or data[0] == '1' or data[0] == '2':
                        self.robot_event.set()
                        #self.timer_wait.start()

                    if data[0] == '21':
                        self.robot.ready_on = True

                    self.robot.position_real_x = float(data[1])
                    self.robot.position_real_y = float(data[2])
                    self.robot.iterator = int(data[3])
                    self.robot.hand = int(data[4])

                    if data[0] == '2':
                        logging.info('Вышел из зоны на роботе')

                logging.info(f"Получение данных: {data} время {time.time()}")
                logging.info(f'-------------')

                data = None
            else:
                self.send_event.set()


    def calculate_distance(self, start_timestamp: float, speed_mm_per_sec: float, current_timestamp: float) -> float:
        """
        Вычисляет расстояние, которое конвейер проехал с момента заданной временной метки до текущего времени.

        :param start_timestamp: Временная метка начала движения конвейера в секундах.
        :param speed_mm_per_sec: Скорость конвейера в мм/с.
        :param current_timestamp: Текущая временная метка в секундах.
        :return: Расстояние в миллиметрах.
        """
        time_difference = current_timestamp - start_timestamp
        distance = speed_mm_per_sec * time_difference

        return distance
    

    def filter_and_sort_coordinates(self, coordinate_list, border_1, border_2):
        """
        Фильтрует и сортирует список координат.

        :param coordinate_list: Список кортежей с координатами (x_new, y_delta, new_timestramp, frame_id).
        :return: Отфильтрованный и отсортированный список координат.
        """
        # Фильтрация координат по y_delta в диапазоне от -120 до 120
        filtered_list = [
            (x_new, y_delta, new_timestramp, frame_id)
            for x_new, y_delta, new_timestramp, frame_id in coordinate_list
            if border_1 <= y_delta <= border_2
        ]

        # Сортировка отфильтрованного списка по x_new в убывающем порядке
        filtered_list.sort(key=lambda item: item[0], reverse=True)

        return filtered_list
    

    def remove_entry_by_id(self, unique_id, coordinate_list):
        """
        Удаляет элемент из списка по уникальному ID.

        :param unique_id: Уникальный идентификатор элемента для удаления.
        :param coordinate_list: Список, из которого нужно удалить элемент.
        """
        
        with self.list_lock:
            index = 0
            while len(coordinate_list) > index:
                if coordinate_list[index][0] == unique_id:
                    coordinate_list.pop(index)
                    break
                index += 1

    def state_by_id(self, unique_id, coordinate_list, state):
        """
        Удаляет элемент из списка по уникальному ID.

        :param unique_id: Уникальный идентификатор элемента для удаления.
        :param coordinate_list: Список, из которого нужно удалить элемент.
        """
        
        with self.list_lock:
            index = 0
            while len(coordinate_list) > index:
                if coordinate_list[index][0] == unique_id:
                    coordinate_list[index][5] = state
                    break
                index += 1



    def add_coordinate(self, dictionary, id, coordinate):
        if id in dictionary:
            dictionary[id].append(coordinate)
        else:
            dictionary[id] = [coordinate]

        if len(dictionary) > 2:
            min_key = min(dictionary, key=lambda k: min(dictionary[k]))
            del dictionary[min_key]

        keys_to_remove = [key for key in dictionary if abs(key - id) > 2]
        for key in keys_to_remove:
            del dictionary[key]

    def check_coordinate_difference(self, dictionary, coordinate, difference):
        for key, coord_list in dictionary.items():
            for coord in coord_list:
                if abs(coord - coordinate) <= difference:
                    return True

        return False
    

    def clear_all(self):
        self.coordinate_list = []
        self.sort_list = []
        self.queue_manager.clear_queue(self.queue_manager.robot_queue, 0)


def communicate_with_robot(queue_manager, stop_event):
    host = '192.168.1.90'
    port = 502

    robot_communicator = RobotCommunicator(queue_manager, stop_event, host, port)
    robot_communicator.start()
