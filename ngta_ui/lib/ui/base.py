from typing import List, Callable, Optional, Type, Any

from ngta_ui.lib.ui.util import SingletonMeta, Observer, DataRecord
import logging

logger = logging.getLogger(__name__)


class BaseDataObservatory(metaclass=SingletonMeta):
    def __init__(self):
        """
        初始化BaseDataObservatory类的实例。此构造函数确保单例模式，即此类的实例在整个程序中只被创建一次。
        """
        # 检查实例是否已经初始化
        if hasattr(self, 'initialized'):
            # 如果已经初始化，则直接返回
            return
        # 初始化实例变量
        self._data = None  # 私有变量，用于存储数据
        self.observers: List[Observer] = []  # 存储观察者的列表
        self.data: DataRecord = DataRecord()  # 存储数据记录的实例
        self.initialized = True  # 设置初始化标志为True

    def register_observer(self, observer: Callable, event_type: str = None, priority: int = 0,
                          data_type: Optional[Type] = None):
        """
        注册一个新的观察者到观察者列表
        :param observer: 当事件发送时被调用的函数
        :param event_type: 观察者想要监听的事件类型
        :param priority: 观察者的优先级，优先级高的观察者先被通知
        :param data_type: 观察者期望接收的数据类型
        :return: None
        """
        # 创建一个观察者对象，包含回调函数、事件类型、优先级和数据类型
        wrapped_observer = Observer(observer, event_type, priority, data_type)
        # 将观察者对象添加到观察者列表
        self.observers.append(wrapped_observer)
        # 按优先级对观察者列表进行降序排序
        self.observers.sort(key=lambda x: x.priority, reverse=True)

    def unregister_observer(self, observer: Callable):
        """
        从观察者列表中移除一个观察者
        :param observer: 要移除的观察者的回调函数
        :return: None
        """
        # 遍历观察者列表，找到要移除的观察者对象并移除
        self.observers = [obs for obs in self.observers if obs.callback != observer]

    def notify_observers(self, event_type: str, *args, **kwargs):
        """
        通知所有相关的观察者一个特定的事件
        :param event_type: 发生的事件类型
        :param args: 传递给观察者的位置参数
        :param kwargs: 传递给观察者的关键字参数
        :return: None
        """
        # 遍历观察者列表
        for observer in self.observers:
            # 检查事件类型是否匹配或观察者监听所有事件
            if observer.event_type is None or observer.event_type == event_type:
                try:
                    # 调用观察者的回到函数，传递任何额外参数
                    observer.callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error occurred while calling observer {observer.callback.__name__}: {e}")

    def set_data(self, event_type: str, data: Any):
        """
        设置数据并通知所有相关的观察者
        :param event_type: 数据变化相关的事件类型
        :param data: 新的数据
        :return: None
        """
        # 检查新数据是否玉当前数据不同
        if self.data != self._data:
            self.data = data
            # 通知所有相关的观察者
            self.notify_observers(event_type=event_type, data=data)

    def clear_observers(self):
        """
        清空观察者列表
        :return: None
        """
        self.observers.clear()

    def clear_data(self):
        """
        清空数据
        :return: None
        """
        self._data = None


class ObserverObject:

    def __init__(self):
        self.observer = BaseDataObservatory()