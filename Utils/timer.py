import time


class Timer:
    def __init__(self, name):
        self.name = name
        self.start_time = None


    def start(self):
        """Начинает отсчет времени и сохраняет текущее время в атрибут start_time."""
        self.start_time = time.time()
        #print(f"Таймер {self.name} запущен")


    def elapsed_time(self, print_log=False):
        """Возвращает количество секунд, прошедших с момента запуска таймера."""
        if self.start_time is None:
            #print(f"Таймер {self.name} не был запущен.")
            return 0
        
        elapsed = time.time() - self.start_time

        if print_log:
            print(f"Таймер {self.name} {elapsed * 1000} мс")
        
        return elapsed