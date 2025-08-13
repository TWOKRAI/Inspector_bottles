import time
import numpy as np
from PIL import Image

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
        
        self.timer = Timer('read_frame')

        self.get_parameters()

        
    def get_parameters(self):
        self.delta = self.local_controls_parameters['delta']
        
        print('self.delta', self.delta)


    def main(self):
        while not self.should_stop():
            x = np.linspace(0, 10, 100)
            y1 = np.sin(x) + self.delta
            y2 = np.cos(x)
            
            # Создание и настройка графика с использованием цепочки вызовов
            plotter = (
                AdvancedPlotter(style='ggplot', figsize=(10, 5))
                .add_line(x, y1, label="sin(x)", color='blue', linestyle='-')
                .add_line(x, y2, label="cos(x)", color='red', linestyle='--')
                .configure(title="Тригонометрические функции", xlabel="X", ylabel="Y")
            )

            #plotter.plot()

              # Получение графика как numpy array
            plot_array = plotter.plot_to_numpy()
            
            # Сохранение для проверки
            Image.fromarray(plot_array).save("plot_numpy.png")


def main(queue_manager=None):
    process = GraphProcess(name='Graph_process', 
                                queue_manager=queue_manager, 
                                control_queue=queue_manager.control_graph)
    process.run()