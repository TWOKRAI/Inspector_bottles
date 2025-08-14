from PIL import Image
import cv2

from .process_module import ProcessModule
from Visualization.plotter import AdvancedPlotter
from Utils.timer import Timer


class GraphProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 10,
                    }
        
        self.timer = Timer('create_frame')

        self.get_parameters()

        self.all_data_graph = {'fps': [[], [], 1000]}
        self.graph = 'fps'

        self.register_thread(name="accept_data_thread", 
                            target=self._accept_data_threading)

        
    def get_parameters(self):
        self.delta = self.local_controls_parameters['delta']
        
        #print('self.delta', self.delta)


    def main(self):
        while not self.should_stop():
            self.timer.start()

            data_xy = self.all_data_graph.get(self.graph, [[],[]])

            x = data_xy[0]
            y = data_xy[1]

            # Создание и настройка графика с использованием цепочки вызовов
            plotter = (
                AdvancedPlotter(style='ggplot', figsize=(10, 5))
                .add_line(x, y, label=f"{self.graph}", color='blue', linestyle='-')
                #.add_line(x, y2, label="cos(x)", color='red', linestyle='--')
                .configure(title=f"График {self.graph}", xlabel="time", ylabel=f"{self.graph}")
            )
            
            # Получение графика как numpy array
            plot_array = plotter.plot_to_numpy()
            
            cv2.imshow('plot_array', plot_array)
            cv2.waitKey(1)  # Ждем нажатия любой клавиши

            # Сохранение для проверки
            Image.fromarray(plot_array).save("plot_numpy.png")

            #self.accept_data()


    def _accept_data_threading(self):
        while not self.should_stop():
            data_graph = self.queue_manager.input_graph.get()

            for key, value in data_graph.items():
                if key in self.all_data_graph:
                    self.all_data_graph[key][0].append(value[0])
                    self.all_data_graph[key][1].append(value[1])


def main(queue_manager=None):
    process = GraphProcess(name='Graph_process', 
                                queue_manager=queue_manager, 
                                control_queue=queue_manager.control_graph)
    process.run()