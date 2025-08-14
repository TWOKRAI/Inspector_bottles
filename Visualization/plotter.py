import matplotlib
matplotlib.use('Agg')  # Устанавливаем до импорта plt
import matplotlib.pyplot as plt

import seaborn as sns
import numpy as np
from io import BytesIO
from PIL import Image
import contextlib


class AdvancedPlotter:
    def __init__(self, style='seaborn', figsize=(10, 6), dpi=100):
        """
        Инициализация плоттера
        :param style: 'seaborn', 'ggplot', 'dark_background', 'plotly'
        :param figsize: размер графика (ширина, высота)
        :param dpi: разрешение
        """
        self.style = style
        self.figsize = figsize
        self.dpi = dpi
        self.lines = []
        self.title = "График"
        self.xlabel = "X"
        self.ylabel = "Y"
        self.grid = True
        self.legend = True
        
    def add_line(self, x, y, label=None, color=None, linestyle='-', marker=None):
        """Добавить линию на график"""
        self.lines.append({
            'x': x,
            'y': y,
            'label': label,
            'color': color,
            'linestyle': linestyle,
            'marker': marker
        })
        return self  # Возвращаем self для цепочки вызовов
    
    def configure(self, title=None, xlabel=None, ylabel=None, grid=None, legend=None):
        """Конфигурация параметров графика"""
        if title: self.title = title
        if xlabel: self.xlabel = xlabel
        if ylabel: self.ylabel = ylabel
        if grid is not None: self.grid = grid
        if legend is not None: self.legend = legend
        return self  # Возвращаем self для цепочки вызовов
    
    @contextlib.contextmanager
    def _create_figure(self):
        """Контекстный менеджер для создания фигуры"""
        plt.style.use(self.style if self.style != 'seaborn' else 'seaborn-v0_8')
        fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
        
        try:
            # Рисуем все линии
            for line in self.lines:
                ax.plot(
                    line['x'], 
                    line['y'], 
                    label=line['label'],
                    color=line['color'],
                    linestyle=line['linestyle'],
                    marker=line['marker']
                )
            
            # Применяем настройки
            ax.set_title(self.title, fontsize=14)
            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            if self.grid: ax.grid(alpha=0.4)
            if self.legend and any(line['label'] for line in self.lines): 
                ax.legend()
            
            yield fig, ax
            
        finally:
            plt.close(fig)
    
    def plot(self, save_path=None):
        """Построить и показать/сохранить график"""
        if self.style == 'plotly':
            return self._plot_plotly(save_path)
        
        with self._create_figure() as (fig, ax):
            if save_path:
                fig.savefig(save_path, bbox_inches='tight')
                print(f"График сохранён в: {save_path}")
            else:
                plt.show()
    
    def plot_to_numpy(self):
        """
        Возвращает изображение графика как numpy array (RGB)
        :return: numpy.ndarray shape (height, width, 3)
        """
        with self._create_figure() as (fig, ax):
            buf = BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=self.dpi)
            buf.seek(0)
            img = Image.open(buf)
            img_array = np.array(img)
            
            # Убираем альфа-канал если он есть
            if img_array.shape[2] == 4:
                img_array = img_array[:, :, :3]
                
            return img_array
    
    def _plot_plotly(self, save_path=None):
        """Интерактивный график с помощью Plotly"""
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("Установите plotly: pip install plotly")
            return
        
        fig = go.Figure()
        
        for line in self.lines:
            fig.add_trace(go.Scatter(
                x=line['x'],
                y=line['y'],
                name=line['label'],
                line=dict(
                    color=line['color'],
                    dash=line['linestyle'] if line['linestyle'] in ['dash', 'dot'] else 'solid'
                ),
                mode='lines+markers' if line['marker'] else 'lines'
            ))
        
        fig.update_layout(
            title=self.title,
            xaxis_title=self.xlabel,
            yaxis_title=self.ylabel,
            template="plotly_dark" if self.style == 'dark_background' else "plotly_white",
            showlegend=self.legend
        )
        
        if save_path:
            fig.write_html(save_path)
            print(f"Интерактивный график сохранён в: {save_path}")
        else:
            fig.show()

# Пример использования
if __name__ == "__main__":
    # Генерация данных
    x = np.linspace(0, 10, 100)
    y1 = np.sin(x)
    y2 = np.cos(x)
    
    # Создание и настройка графика с использованием цепочки вызовов
    plotter = (
        AdvancedPlotter(style='ggplot', figsize=(10, 5))
        .add_line(x, y1, label="sin(x)", color='blue', linestyle='-')
        .add_line(x, y2, label="cos(x)", color='red', linestyle='--')
        .configure(title="Тригонометрические функции", xlabel="X", ylabel="Y")
    )

    plotter.plot()
    
    # Получение графика как numpy array
    plot_array = plotter.plot_to_numpy()
    
    # Отображение информации о массиве
    print("Размерность массива:", plot_array.shape)
    print("Тип данных:", plot_array.dtype)
    print("Значения RGB (пример):", plot_array[0, 0, :])
    
    # Сохранение для проверки
    Image.fromarray(plot_array).save("plot_numpy.png")
    
    # Создание интерактивного графика
    plotly_plotter = (
        AdvancedPlotter(style='plotly')
        .add_line(x, y1, label="sin(x)")
        .add_line(x, y2, label="cos(x)")
        .configure(title="Интерактивный график")
    )
    plotly_plotter.plot()