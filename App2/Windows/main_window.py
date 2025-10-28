from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QWidget)
from PyQt5.QtWidgets import QWidget, QStackedWidget

from App2.Components.header import HeaderWidget
from App2.Widget.Frame_process_widjet.Frame_process import FrameProcessWindow
from App2.Widget.Image_sorting_widjet.Image_sorting import ImageSortingWidget


class MainWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            #self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen
        
        self.header = HeaderWidget(window_manager=self.window_manager)
        self.stacked_widget = QStackedWidget()

        self.frame_process = FrameProcessWindow(window_manager=self.window_manager)
        self.image_process = ImageSortingWidget(window_manager=self.window_manager)

        self.window_show = 'frame_process'

        self.init_ui()

        if self.fullscreen: self.showFullScreen()

        self.header.check_show.connect(self.check_show)
      

    def init_ui(self):
        # Создание главного окна
        self.setWindowTitle("Image Processing App")
        self.setGeometry(100, 100, 1200, 800)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        main_layout.addWidget(self.header)
        #main_layout.addSpacing(0)
        
        self.stacked_widget.addWidget(self.frame_process)
        self.stacked_widget.addWidget(self.image_process)
        main_layout.addWidget(self.stacked_widget) 

        self.stacked_widget.setCurrentWidget(self.frame_process)
        self.stacked_widget.setContentsMargins(0, 0, 0, 0)

        main_layout.addStretch()


    def show(self):
        super().show()

    
    def close(self):
        super().close()


    def update_access_level(self, level):
        self.frame_process.update_access_level(level)


    def check_show(self, window_show):
        match window_show:
            case 'frame_process':
                self.stacked_widget.setCurrentWidget(self.frame_process)
            case 'image_process':
                self.stacked_widget.setCurrentWidget(self.image_process)


