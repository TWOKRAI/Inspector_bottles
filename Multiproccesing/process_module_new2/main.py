from Process_manager_module.main_launcher import SystemLauncher

from Test_example.process_manager import ProcessManager2

def main():
    """Главная функция запуска"""
    process_manager2 = ProcessManager2()
    launcher = SystemLauncher(process_manager2)
    
    try:
        # Инициализация и запуск
        launcher.initialize_system()
        launcher.start()
        
        # Основной цикл ожидания
        launcher.wait()
        
    except Exception as e:
        print(f"❌ System error: {e}")
        launcher.stop()
        return 1
    
    return 0

if __name__ == "__main__":
    import sys

    exit_code = main()
    sys.exit(exit_code)