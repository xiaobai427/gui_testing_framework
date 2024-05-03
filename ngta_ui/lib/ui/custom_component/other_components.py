# 导入PySide6中的各种组件
from PySide6.QtWidgets import (
    QLabel, QSpinBox, QSizePolicy, QCheckBox, QComboBox, QSlider,
    QProgressBar, QDateTimeEdit, QTableView, QListView, QTreeView, QFrame,
    QTabWidget, QStatusBar, QMenuBar, QToolBar, QGroupBox, QLineEdit, QWidget
)
from PySide6.QtGui import QFont  # 导入字体支持
from PySide6.QtCore import Qt  # 导入Qt核心模块，包括常量等


# 自定义QLabel类，用于创建带有特定字体和样式的标签
class CustomQLabel(QLabel):
    def __init__(self, text):
        super().__init__(text)  # 调用父类构造函数
        font = QFont()  # 创建字体对象
        font.setPointSize(14)  # 设置字体大小为14点
        self.setFont(font)  # 应用字体设置
        # 设置标签的样式（颜色、背景、边框）
        self.setStyleSheet("color: white; background-color: transparent; border: none;")
        # 设置标签的大小策略为固定
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


# 自定义QSpinBox类，用于创建带有特定字体和样式的数字输入框
class CustomQSpinBox(QSpinBox):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        font = QFont()  # 创建字体对象
        font.setPointSize(14)  # 设置字体大小
        self.setFont(font)  # 应用字体设置
        # 设置数字输入框的样式
        self.setStyleSheet("color: white; background-color: rgba(0,0,0, 80%);")


# 自定义QCheckBox类，用于创建带有特定字体和样式的复选框
class CustomQCheckBox(QCheckBox):
    def __init__(self, text):
        super().__init__(text)  # 调用父类构造函数
        font = QFont()  # 创建字体对象
        font.setPointSize(14)  # 设置字体大小
        self.setFont(font)  # 应用字体设置
        # 设置复选框的样式
        self.setStyleSheet(
            "QCheckBox::indicator { color: white; } "
            "QCheckBox { color: white; background-color: transparent; }")


# 自定义QComboBox类，用于创建带有特定字体和样式的下拉列表框
class CustomQComboBox(QComboBox):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        font = QFont()  # 创建字体对象
        font.setPointSize(14)  # 设置字体大小
        self.setFont(font)  # 应用字体设置
        # 设置下拉列表框的样式
        self.setStyleSheet("""
            QComboBox {
                color: white;
                background-color: rgba(0,0,0, 80%);
                padding-left: 1px; 
                padding-right: 1px;
            }
            QComboBox QAbstractItemView {
                color: black;
                background: white;
            }
        """)


# 自定义QSlider类，用于创建带有特定样式的滑块控件
class CustomQSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Horizontal)  # 设置为水平滑动条
        self.setMinimum(0)  # 设置最小值为0
        self.setMaximum(100)  # 设置最大值为100
        self.setTickPosition(QSlider.TicksBelow)  # 设置刻度位置在滑块下方
        self.setTickInterval(10)  # 设置刻度间隔为10
        self.setStyleSheet("QSlider::handle { background-color: white; }")  # 设置滑块的样式


# 自定义QProgressBar类，用于创建带有特定样式的进度条
class CustomQProgressBar(QProgressBar):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setMinimum(0)  # 设置最小值为0
        self.setMaximum(100)  # 设置最大值为100
        self.setValue(0)  # 设置初始进度为0
        # 设置进度条的样式
        self.setStyleSheet(
            "QProgressBar { border: 2px solid grey; border-radius: 5px; text-align: center; } QProgressBar::chunk { background-color: #05B8CC; width: 20px; }")


# 自定义QDateTimeEdit类，用于创建带有日历弹出和特定样式的日期时间选择器
class CustomQDateTimeEdit(QDateTimeEdit):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setCalendarPopup(True)  # 启用日历弹出功能
        self.setStyleSheet("background-color: white; color: black;")  # 设置样式


# 自定义QTableView类，用于创建带有特定样式的表格视图
class CustomQTableView(QTableView):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setStyleSheet("QTableView { selection-background-color: lightblue; }")  # 设置选中行的背景色


# 自定义QListView类，用于创建带有特定样式的列表视图
class CustomQListView(QListView):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setStyleSheet("QListView { selection-background-color: lightblue; }")  # 设置选中项的背景色


# 自定义QTreeView类，用于创建带有特定样式的树状视图
class CustomQTreeView(QTreeView):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setStyleSheet("QTreeView { selection-background-color: lightblue; }")  # 设置选中项的背景色


# 自定义QTabWidget类，用于创建带有特定样式的标签页控件
class CustomQTabWidget(QTabWidget):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setStyleSheet(
            "QTabWidget::tab-bar { alignment: center; } QTabBar::tab { background: lightgray; margin: 2px; } QTabBar::tab:selected { background: lightblue; }")  # 设置标签页的样式


# 自定义QFrame类，用于创建带有特定样式的框架
class CustomQFrame(QFrame):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        self.setFrameShape(QFrame.StyledPanel)  # 设置框架形状为样式化面板
        self.setStyleSheet("QFrame { border: 1px solid black; }")  # 设置框架的样式


# QGroupBoxBase类，用于创建带有标题的组框，可以添加各种自定义控件
class QGroupBoxBase(QGroupBox):
    def __init__(self, title):
        super().__init__(title)  # 调用父类构造函数
        self.widgets = {}  # 初始化一个字典来存储内部控件

    def create_widget(self, widget_class, name, *args, **kwargs):
        widget = widget_class(*args, **kwargs)  # 根据传入的类和参数创建控件
        self.widgets[name] = widget  # 将控件存储在字典中
        return widget  # 返回创建的控件


# 自定义QLineEdit类，用于创建带有特定字体和样式的文本输入框
class CustomQLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()  # 调用父类构造函数
        font = QFont()  # 创建字体对象
        font.setPointSize(14)  # 设置字体大小为14点
        self.setFont(font)  # 应用字体设置
        # 设置文本输入框的样式
        self.setStyleSheet("color: white; background-color: rgba(0,0,0, 80%); border: 1px solid gray;")

    def set_placeholder_text(self, text):
        self.setPlaceholderText(text)  # 设置占位符文本

    def set_initial_value(self, value):
        self.setText(value)  # 设置初始文本值
