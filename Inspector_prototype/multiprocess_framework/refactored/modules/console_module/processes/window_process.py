"""
Процесс окна консоли для отображения вывода.

Используется для отдельного процесса консоли (отладка).
"""
import sys
import queue
from typing import List
from multiprocessing import Queue

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32


class ConsoleWindowProcess:
    """
    Процесс консольного окна, читает из queue и отображает в консоли.
    
    Используется для отдельного процесса консоли (отладка).
    """
    
    def __init__(self, title: str, process_names: List[str], output_queue: Queue):
        """
        Args:
            title: Заголовок окна консоли
            process_names: Список имен процессов
            output_queue: Queue для получения данных
        """
        self.title = title
        self.process_names = process_names
        self.output_queue = output_queue
        self.console_handle = None
        self._running = False
    
    def run(self):
        """Запуск процесса консоли"""
        if sys.platform != 'win32':
            self._run_unix_console()
            return
        
        try:
            if not kernel32.AllocConsole():
                self._run_fallback()
                return
            
            self.console_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            kernel32.SetConsoleTitleW(self.title)
            
            user32 = ctypes.windll.user32
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
            
            self._running = True
            self._read_and_display()
            
        except Exception:
            self._run_fallback()
        finally:
            if self.console_handle:
                kernel32.FreeConsole()
    
    def _run_unix_console(self):
        """Запуск на Unix-системах"""
        print(f"\n{'='*60}")
        print(f"Console: {self.title}")
        print(f"Processes: {', '.join(self.process_names)}")
        print(f"{'='*60}\n")
        self._running = True
        self._read_and_display()
    
    def _run_fallback(self):
        """Резервный режим"""
        print(f"Console Window: {self.title}")
        self._running = True
        self._read_and_display()
    
    def _read_and_display(self):
        """Чтение из queue и отображение"""
        try:
            while self._running:
                try:
                    stream_type, data = self.output_queue.get(timeout=0.1)
                    
                    if stream_type == 'close':
                        break
                    elif stream_type == 'flush':
                        sys.stdout.flush()
                        sys.stderr.flush()
                    elif stream_type in ('stdout', 'stderr'):
                        if sys.platform == 'win32' and self.console_handle:
                            if isinstance(data, str):
                                data_bytes = data.encode('utf-8')
                            else:
                                data_bytes = data
                            
                            kernel32.WriteFile(
                                self.console_handle,
                                data_bytes,
                                len(data_bytes),
                                ctypes.byref(wintypes.DWORD()),
                                None
                            )
                        else:
                            if stream_type == 'stdout':
                                sys.stdout.write(data)
                                sys.stdout.flush()
                            else:
                                sys.stderr.write(data)
                                sys.stderr.flush()
                except queue.Empty:
                    continue
                except Exception:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

