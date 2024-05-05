from abc import abstractmethod

from PySide6.QtWidgets import QWidget

from ngta_ui.lib.ui.base import ObserverObject


def auto_props(props):
    def class_decorator(cls):
        class Wrapped(cls):
            def __init__(self, *args, **kwargs):
                # 调用父类构造函数
                super().__init__(*args, **kwargs)
                # 为每个属性和其对应的初始值设定
                for prop, value in props.items():
                    setattr(self, prop, value)

        return Wrapped

    return class_decorator


class CustomWidget(QWidget, ObserverObject):
    def __init__(self):
        super().__init__()
        self.post_init()

    def post_init(self):
        self.setup_properties()
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        # 设置背景颜色
        self.setStyleSheet("background-color: #2d2d2d;")

    @abstractmethod
    def setup_properties(self):
        pass

    @abstractmethod
    def connect_signals(self):
        pass


