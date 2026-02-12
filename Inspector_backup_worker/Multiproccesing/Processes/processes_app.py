from App.main_app import create_app


def app_processing(queue_manager, name):
    create_app(queue_manager, name)