import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import List, Dict, Any, Callable, Optional, Type
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# 定义一个名为SingletonMeta的元类
class SingletonMeta(type):
    # 使用一个字典_instances来存储已经创建的单例对象
    _instances = {}

    # 当用户通过类名创建一个对象时，__call__方法会被调用
    def __call__(cls, *args, **kwargs):
        # 如果cls不在_instances字典中，说明还没有创建过该类的对象
        if cls not in cls._instances:
            # 调用父类的__call__方法创建一个新的实例并将其添加到_instances字典中
            cls._instances[cls] = super(SingletonMeta, cls).__call__(*args, **kwargs)
        # 如果cls已经在_instances字典中，直接返回已经创建的对象
        return cls._instances[cls]


# 数据存储
class AttrDict(defaultdict):
    def __getattr__(self, key):
        if key not in self:
            return None

        # 创建一个新的AttrDict实例并将其作为value返回
        value = self[key] = type(self)()
        return value


# 数据记录
class DataRecord(BaseModel, arbitrary_types_allowed=True):
    extras: AttrDict = AttrDict()


class Observer:
    def __init__(self, callback: Callable, event_type: str = None, priority: int = 0, data_type: Optional[Type] = None):
        """
        使用提供的回调函数、事件类型、优先级和数据类型创建一个观察者。
        :param callback:当事件发生时调用的函数。
        :param event_type: 要观察的事件类型
        :param priority: 观察者的优先级，优先级高的观察者会优先调用
        :param data_type: 事件的预期数据类型

        return: None
        """
        self.callback = callback
        self.event_type = event_type
        self.priority = priority
        self.data_type = data_type

    def __call__(self, *args, **kwargs):
        """
        该方法允许实例对象被调用，相当于调用了观察者的回调函数。
        1、检查是否指定了data_type,如果没有则跳过类型检查
        2、获取关键字参数中为"data"的值，如果不存在则设置为None
        3、如果指定了data_type,则检查提供的苏剧是否与预期类型匹配，如果不匹配则记录错误日志并返回，阻止后续的回调函数执行
        4、如果数据类型匹配或未指定数据类型，则调用实例对象保存的回调函数，并传入参数args和kwargs给该回调
        :param args
        :param args:
        :param kwargs:
        :return: 回到函数
        """
        if self.data_type is not None:
            data = kwargs.get("data", None)
            if not isinstance(data, self.data_type):
                logger.error(f"Observer {self.callback.__name__} expects data of type {self.data_type}, but got {type(data)}")
                return
        self.callback(*args, **kwargs)
