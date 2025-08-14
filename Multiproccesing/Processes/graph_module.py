from PIL import Image
import cv2
import threading

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
        
        self.timer = Timer('create_frame')

        self.get_parameters()

        # Инициализация структур данных
        self.lock = threading.Lock()
        self.all_data_graph = {'fps': [[], [], 1000]}
        self.graph = 'fps'
        self.last_image = None
        self.data_changed = False

        self.register_thread(name="accept_data_thread", 
                            target=self._accept_data_threading)

        
    def get_parameters(self):
        self.max_points = self.local_controls_parameters['max_points'] 
        self.min_x = self.local_controls_parameters['min_x']
        self.max_x = self.local_controls_parameters['max_x'] 
        
        #print('self.delta', self.delta)


    def _draw_graph(self):
        """Создает изображение графика из текущих данных"""
        with self.lock:
            data_xy = self.all_data_graph.get(self.graph, [[], []])
            x = data_xy[0][max(0, self.min_x):min(len(data_xy[0]), self.max_x)]
            y = data_xy[1][max(0, self.min_x):min(len(data_xy[0]), self.max_x)]
                    
        if not x or not y:
            return None
            
        return (
            AdvancedPlotter(style='ggplot', figsize=(10, 5))
            .add_line(x, y, label=self.graph, color='blue', linestyle='-')
            .configure(title=f"График {self.graph}", xlabel="time", ylabel=self.graph)
            .plot_to_numpy()
        )


    def main(self):
        while not self.should_stop():
            self.timer.start()
            
            if self.data_changed:
                image = self._draw_graph()
                if image is not None:
                    self.last_image = image
                    cv2.imshow('plot_array', image)
                self.data_changed = False
            
            # Получение графика как numpy array
            #plot_array = plotter.plot_to_numpy()
            
            # cv2.imshow('plot_array', plot_array)
            cv2.waitKey(1)  # Ждем нажатия любой клавиши

            # Сохранение для проверки
            # Image.fromarray(plot_array).save("plot_numpy.png")


    def _accept_data_threading(self):
        while not self.should_stop():
            data_graph = self.queue_manager.input_graph.get()
            
            with self.lock:
                for key, value in data_graph.items():
                    if key in self.all_data_graph:
                        # Добавляем данные с ограничением длины
                        self.all_data_graph[key][0].append(value[0])
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