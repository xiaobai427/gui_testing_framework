# coding: utf-8

from typing import Union, List, Tuple, Sequence
from .base import BaseConfig, TestRunnerType
from .nodes.testsuite import ObjLoaderNode


from ..constants import (
    DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT,
)
from ..bench import TestBench
from ..result import TestResult
from ..context import TestContext
from ..events import EventObservable
from ..util import locate


class CommandArgsConfig(BaseConfig):
    def __init__(self,
                 paths: Sequence | str,
                 includes: Sequence[str] = None,
                 excludes: Sequence[str] = None,
                 tags: Sequence[str] = None,
                 pattern: str = "test*.py",
                 repeat_number: int = 1,
                 repeat_foreach: bool = False,
                 process_count: int = 1,
                 failfast: bool = False,
                 enable_mock: bool = False,
                 log_level: str = None,
                 log_layout: str = None,
                 testbench: TestBench = None,
                 event_observable: str | EventObservable = None,
                 ):
        self.loaders = []
        if isinstance(paths, str):
            path = paths
            loader = ObjLoaderNode(
                path=path, includes=includes, excludes=excludes, tags=tags,
                repeat_number=repeat_number, repeat_foreach=repeat_foreach,
                as_testsuite=path
            )
            self.loaders.append(loader)
        else:
            for path in paths:
                loader = ObjLoaderNode(
                    path=path, includes=includes, excludes=excludes, tags=tags,
                    repeat_number=repeat_number, repeat_foreach=repeat_foreach,
                    as_testsuite=path
                )
                self.loaders.append(loader)
        self.process_count = process_count
        self.failfast = failfast
        self.enable_mock = enable_mock
        self.log_level = log_level or DEFAULT_LOG_LEVEL
        self.log_layout = log_layout or DEFAULT_LOG_LAYOUT
        self.observable = locate(event_observable) if isinstance(event_observable, str) else event_observable
        self.testbench = testbench

    def get_log_level_and_layout(self) -> Tuple[str, str]:
        return self.log_level, self.log_layout

    def get_result(self):
        return TestResult()

    def get_runners(self, result: TestResult = None) -> List[TestRunnerType]:
        context = TestContext(event_observable=self.observable, testbench=self.testbench)
        runner = new_runner(self.process_count, None, result, context, self.log_level, self.log_layout)
        for loader in self.loaders:
            runner.add_testsuite(loader.as_model_data())
        return [runner]
