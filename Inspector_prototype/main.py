"""
Главный файл запуска прототипа инспектора
"""
import sys
from pathlib import Path

# Добавляем корень прототипа в путь (для multiprocess_framework, App и т.д.)
_proto = Path(__file__).resolve().parent
if str(_proto) not in sys.path:
    sys.path.insert(0, str(_proto))

from Multiproccesing.Processes_Manager import MultiProcessManager


if __name__ == '__main__':
    print("="*60)
    print("Inspector Prototype - Starting...")
    print("="*60)
    
    try:
        manager = MultiProcessManager()
        manager.initialize_processes()
        manager.start_processes()
        manager.join_processes()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        if 'manager' in locals():
            manager.stop_processes()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        if 'manager' in locals():
            manager.stop_processes()
    
    print("="*60)
    print("Inspector Prototype - Finished")
    print("="*60)
