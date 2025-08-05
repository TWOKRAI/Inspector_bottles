from Multiproccesing.Processes_Manager import MultiProcessManager


if __name__ == '__main__':
    manager = MultiProcessManager()
    manager.initialize_processes()
    manager.start_processes()
    manager.stop_processes()    
    