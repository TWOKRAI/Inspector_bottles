from PIL import Image
import cv2
import threading
import time

from .process_module import ProcessModule
from Visualization.plotter import AdvancedPlotter
from Utils.timer import Timer


class GraphProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'max_points': 500,
                    'min_x': 0,
                    'max_x': 500,
                    }

        self.get_parameters()

        # Инициализация структур данных
        self.lock = threading.Lock()

        self.all_data_graph = {'fps': [[], []],
                               'time_cycle': [[], []],
                               'process_capture': [[], []],
                               'process_processing': [[], []],
                               'process_render': [[], []],
                               'process_graph': [[], []],
                               'process_comunnication': [[], []],
                               
                               'time_input_processing': [[], []],
                               'time_input_render': [[], []],}
        
        self.all_data_state = {'fps': [True, 'мс'],
                            'time_cycle': [True, 'мс'],
                            'process_capture': [True, 'мс'],
                            'process_processing': [True, 'мс'],
                            'process_render': [True, 'мс'],
                            'process_graph': [False, 'мс'],
                            'process_comunnication': [False, 'мс'],

                            'time_input_processing': [True, 'мс'],
                            'time_input_render': [True, 'мс'],}


        self.graph = 'fps'
        self.last_image = None
        self.data_changed = False

        self.register_thread(name="accept_data_thread", 
                            target=self._accept_data_threading)
        
        self.register_thread(name="accept_data_cycle_thread", 
                            target=self._accept_data_cycle_threading)
        
        self.real_time = time.time()
        self.timer = Timer('create_frame')
        self.timer_process = Timer('time_process')
        self.data_graph = [self.real_time, 1]
       
        
    def get_parameters(self):
        self.max_points = self.local_controls_parameters['max_points'] 
        self.min_x = self.local_controls_parameters['min_x']
        self.max_x = self.local_controls_parameters['max_x']

    
    def _draw_graph(self):
        """Создает изображение графика из текущих данных"""
        with self.lock:
            # Создаем объект для построения графиков
            plotter = AdvancedPlotter(style='ggplot', figsize=(10, 5))
            has_data = False
            
            # Перебираем все возможные графики
            for graph_name in self.all_data_state:
                graph_parametrs = self.all_data_state[graph_name]
                # Проверяем, активен ли график
                if graph_parametrs[0]:
                    # Получаем данные для этого графика
                    data_xy = self.all_data_graph.get(graph_name, [[], []])
                    if not data_xy[0] or not data_xy[1]:
                        continue
                        
                    # Применяем ограничения по диапазону
                    x = data_xy[0][max(0, self.min_x):min(len(data_xy[0]), self.max_x)]
                    y = data_xy[1][max(0, self.min_x):min(len(data_xy[0]), self.max_x)]
                    
                    # Добавляем линию графика
                    if x and y:
                        graph_name = f'{graph_name}, {graph_parametrs[1]}'
                        plotter.add_line(x, y, label=graph_name, linestyle='-')
                        has_data = True
            
            # Если нет активных данных, возвращаем None
            if not has_data:
                return None
                        
            # Настраиваем общий вид графика
            plotter.configure(
                title="Графики производительности",
                xlabel="Время",
                ylabel=f"Значение, {graph_parametrs[1]}",
                legend_position='bottom'
            )
            
            return plotter.plot_to_numpy()


    def main(self):
        self.real_time = time.time()

        while not self.should_stop():
            #self.timer.start()
            self.timer_process.start()
            
            if self.data_changed:
                image = self._draw_graph()
                if image is not None:
                    self.last_image = image
                    cv2.imshow('plot_array', image)
                self.data_changed = False
            else:
                time.sleep(0.001)

            self.data_graph = self.timer_process.get_data()
            
            # Получение графика как numpy array
            #plot_array = plotter.plot_to_numpy()
            
            # cv2.imshow('plot_array', plot_array)
            cv2.waitKey(1)  # Ждем нажатия любой клавиши

            # Сохранение для проверки
            # Image.fromarray(plot_array).save("plot_numpy.png")


    def _accept_data_threading(self):
        while not self.should_stop():
            data_graph = self.queue_manager.input_graph.get()
            self.put_data(data_graph)
            

    def _accept_data_cycle_threading(self):
        while not self.should_stop():
            data_graph = self.queue_manager.input_graph_cycle.get()
            self.put_data(data_graph)

            data = {'process_graph': self.data_graph}
            self.put_data(data)
                 

    def put_data(self, data_graph):
        with self.lock:
            for key, value in data_graph.items():
                if key in self.all_data_graph:
                    if value[1] == 0 and len(self.all_data_graph[key][0]) > 0:
                        value[1] = self.all_data_graph[key][1][-1]

                    # Добавляем данные с ограничением длины
                    self.all_data_graph[key][0].append(value[0] - self.real_time)
                    self.all_data_graph[key][1].append(value[1])
                    
                    # Сохраняем только последние max_points точек
                    if len(self.all_data_graph[key][0]) > self.max_points:
                        self.all_data_graph[key][0] = self.all_data_graph[key][0][-self.max_points:]
                        self.all_data_graph[key][1] = self.all_data_graph[key][1][-self.max_points:]
            
            self.data_changed = True


def main(queue_manager=None):
    process = GraphProcess(name='Graph_process', 
                                queue_manager=queue_manager, 
                                control_queue=queue_manager.control_graph)
    process.run()