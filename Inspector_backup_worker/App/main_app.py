import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QCursor
import qdarkstyle


from App.Windows.main_window import MainWindow
from App.Widget.Loading_widjet.window_loading import LoadingWindow
from App.Windows.neuroun_window import NeurounWindow
from App.Windows.message_window import MessageWindow


# from App.Widget.Loading_widjet.Threads.thread_loading import Loading
# from App.Threads.thread_image_update import UpdateImage
from App.Threads.thread_bot_message import BotThread


class WindowManager:
    def __init__(self, queue_manager, name):
        self.process_name = str(name)
        self.queue_manager = queue_manager
        #self.stop_event = stop_event

        self.app = QApplication(sys.argv)
        self.app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

        self.loading_window = None
        self.main_window = None
        self.neuroun_window = None
        self.message_window = None
        self.header = None

        self.fullscreen = False

        self.access_level = 2

        self.create_all_windows()
        self.create_thread()
        self.toggle_cursor_visibility(True)
        self.set_fullscreen(self.fullscreen)

        self.admin_function(self.access_level)


    def create_all_windows(self):
        self.main_window = MainWindow(window_manager = self)
        self.main_window.hide() 

        self.loading_window = LoadingWindow(window_manager = self) 
        
        # self.main_window.hide()
        # self.loading_window.hide()


    def create_thread(self):
        self.bot_thread = BotThread(window_manager = self)
        self.bot_thread.message.connect(self.show_message)
        self.bot_thread.start()


    def set_fullscreen(self, fullscreen):
        self.fullscreen = fullscreen

        if self.main_window:
            if fullscreen:
                self.main_window.showFullScreen()
            else:
                self.main_window.showNormal()
                
        if hasattr(self, 'loading_window') and self.loading_window is not None:
            try:
                if fullscreen:
                    self.loading_window.showFullScreen()
                else:
                    self.loading_window.showNormal()
            except RuntimeError:
                self.loading_window = None


    def toggle_cursor_visibility(self, visible):
        cursor = QCursor(Qt.ArrowCursor) if visible else QCursor(Qt.BlankCursor)

        if self.main_window:
            self.main_window.setCursor(cursor)

        if self.loading_window:
            self.loading_window.setCursor(cursor)


    def change_language(self, language):
        # Реализация смены языка
        pass

    def admin_function(self, access_level):
        self.access_level = access_level
        self.main_window.update_access_level(access_level)


    def close_program(self):
        # if self.loading_window:
        #     self.loading_window.close()

        if hasattr(self, 'loading_window') and self.loading_window is not None:
            try:
                self.main_window.close()
            except RuntimeError:
                self.loading_window = None

        if self.main_window:
            self.main_window.close()

        self.queue_manager.stop_event.set()
        self.queue_manager.memory_manager.close_all()


    def run(self):
        self.loading_window.show()
        sys.exit(self.app.exec_())


    def show_message(self, message):
        if isinstance(self.message_window, MessageWindow):
            self.message_window.close()
            self.message_window.deleteLater()
            self.message_window = None

        if message[0] != '.':
            print(message)
            self.message_window = MessageWindow(self.queue_manager, message)
            self.message_window.show()


    def close_loading_winodw(self):
        if self.loading_window:
            self.loading_window.close()
            self.loading_window.deleteLater()
            self.loading_window = None


    # def close_main_winodw(self):
    #     if self.main_window:
    #         self.main_window.close()    


    # def show_main_winodw(self):
    #     if not self.main_window:
    #         self.main_window = MainWindow(window_manager = self)
    #         self.main_window.show()
    #     else:
    #         self.main_window.show()
        
    #     self.close_neuroun_winodw()

    #     print('ПОказал окно майн')



    
    # def show_neuroun_winodw(self):
    #     if not self.neuroun_window:
    #         self.neuroun_window = NeurounWindow(window_manager = self)
    #         self.neuroun_window.header.main_show.connect(self.show_main_winodw)
    #         self.neuroun_window.header.neuroun_show.connect(self.show_neuroun_winodw)
    #         self.neuroun_window.show()
    #     else:
    #         self.neuroun_window.show()
        
    #     self.close_main_winodw()

    #     print('ПОказал окно нейрон')

    # def close_neuroun_winodw(self):
    #     if self.neuroun_window:
    #         self.neuroun_window.hide()


def create_app(queue_manager, name):
    window_manager = WindowManager(queue_manager, name)
    window_manager.run()

