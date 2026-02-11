"""
Главный файл запуска прототипа инспектора
"""
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
