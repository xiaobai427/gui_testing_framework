# coding: utf-8

import types
from typing import List, Tuple, Union
from abc import ABCMeta, abstractmethod
from ..concurrent import MultiProcessQueueTestConsumer
from ..result import TestResult
from ..runner import TestRunner
from ..case import TestCase

TestRunnerType = Union[TestRunner, MultiProcessQueueTestConsumer]
ObjLoaderPathType = Union[str, types.ModuleType, TestCase, types.MethodType, types.FunctionType]


class BaseConfig(metaclass=ABCMeta):
    @abstractmethod
    def get_log_level_and_layout(self) -> Tuple[str, str]:
        pass

    @abstractmethod
    def get_result(self) -> TestResult:
        pass

    @abstractmethod
    def get_runners(self, result: TestResult = None) -> List[TestRunnerType]:
        pass
