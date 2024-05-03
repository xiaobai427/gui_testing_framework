from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox


class MessageBoxThread(QThread):
    request_message_box = Signal(str)

    def __init__(self, message):
        super().__init__()
        self.message = message

    def run(self):
        self.request_message_box.emit(self.message)


class CustomMessageBox(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None

    def show_message(self, message):
        if self.thread is not None and self.thread.isRunning():
            return
        self.thread = MessageBoxThread(message)
        self.thread.request_message_box.connect(self.showMessage)
        self.thread.start()

    def showMessage(self, message):
        self.information(self, "Message", message)