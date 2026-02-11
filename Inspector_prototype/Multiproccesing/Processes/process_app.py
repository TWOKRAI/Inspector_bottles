from App.main_app import create_app


def app_processing(queue_manager, stop_event):
    """Процесс App для отображения"""
    create_app(queue_manager, stop_event)


def main(queue_manager, stop_event):
    """Главная функция процесса App"""
    app_processing(queue_manager, stop_event)
