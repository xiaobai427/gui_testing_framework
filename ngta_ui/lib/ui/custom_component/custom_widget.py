from abc import abstractmethod

from PySide6.QtWidgets import QWidget

from ngta_ui.lib.ui.base import ObserverObject


class CustomWidget(QWidget, ObserverObject):

    def __init__(self):
        super().__init__()
        self.setup()
        # UI设置
        self.setup_ui()
        # 属性设置
        self.setup_properties()
        # 信号连接
        self.connect_signals()
        # # Connect resize event to a custom slot
        # self.resizeEvent = self.on_resize

    def setup(self):
        # 类变量的相关定义
        pass

    # 定义抽象方法，子类必须实现
    @abstractmethod
    def setup_ui(self):
        pass

    @abstractmethod
    def setup_properties(self):
        pass

    @abstractmethod
    def connect_signals(self):
        pass
