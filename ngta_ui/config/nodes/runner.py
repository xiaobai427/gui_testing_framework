# coding: utf-8

import os
from typing import Optional, List
from functools import partial

import pydantic
from ..base import TestRunnerType
from ...constants import (
    IdType, FilePathType, DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT,
)
from ...bench import TestBench
from ...runner import TestRunner
from ...result import TestResult
from ...context import TestContext
from ...interceptor import TestCaseLogFileInterceptor, TestRunnerLogFileInterceptor
from ...concurrent import MultiProcessQueueTestConsumer, TestRunnerProcess
from ...events import EventObservable, TestEventHandler
from ...serialization import parse_dict
from ...errors import ConfigError

from .testsuite import TestSuiteNode

import logging
logger = logging.getLogger(__name__)


parse_dict_by_path = partial(parse_dict, key="path")


class TestBenchNode(pydantic.BaseModel, extra="allow"):
    path: str = pydantic.Field(alias="()")

    def as_bench(self) -> TestBench:
        return parse_dict_by_path(self.model_dump())


class TestResultNode(pydantic.BaseModel, extra="allow"):
    path: str = pydantic.Field(alias="()")
    failfast: bool = False

    def as_result(self) -> TestResult:
        return parse_dict_by_path(self.model_dump())


class EventObserverNode(pydantic.BaseModel, extra="allow"):
    path: str = pydantic.Field(alias="()")

    def as_event_handler(self) -> TestEventHandler:
        return parse_dict_by_path(self.model_dump())


class EventObservableNode(pydantic.BaseModel):
    default: bool = True
    observers: List[EventObserverNode] = pydantic.Field(default_factory=list)

    def as_event_subject(self, output_dir: FilePathType, runner_node: 'TestRunnerNode') -> EventObservable:
        event_observable = EventObservable()
        if self.default:
            if runner_node.process_count == 0:
                event_observable.attach(TestCaseLogFileInterceptor(output_dir))
            else:
                output_dir = os.path.join(output_dir, runner_node.id)
                event_observable.attach(TestCaseLogFileInterceptor(output_dir))
                event_observable.attach(TestRunnerLogFileInterceptor(output_dir))

        for observer_node in self.observers:
            event_observable.attach(observer_node.as_event_handler())
        return event_observable


class TestContextNode(pydantic.BaseModel):
    testbench: Optional[TestBenchNode] = None
    event_observable: Optional[EventObservableNode] = pydantic.Field(None, alias="event-observable")

    def as_context(self,
                   output_dir: FilePathType,
                   runner_node: 'TestRunnerNode',
                   enable_mock: bool = None,
                   strict: bool = None) -> TestContext:
        if self.event_observable:
            subject = self.event_observable.as_event_subject(output_dir, runner_node)
        else:
            subject = EventObservableNode().as_event_subject(output_dir, runner_node)

        testbench = self.testbench.as_bench() if self.testbench else None
        return TestContext(subject, testbench, enable_mock, strict)


class TestRunnerNode(pydantic.BaseModel):
    id: Optional[IdType] = None
    context: Optional[TestContextNode] = None
    testsuites: List[TestSuiteNode]

    # only for multiple process test runner
    process_count: int = pydantic.Field(0, alias="process-count")
    is_prerequisite: bool = pydantic.Field(False, alias="is-prerequisite")
    log_level: str = pydantic.Field(DEFAULT_LOG_LEVEL, alias="log-level")
    log_layout: str = pydantic.Field(DEFAULT_LOG_LAYOUT, alias="log-layout")

    def _update_ident_by_index(self, index, testbench_name: str = None):
        if self.process_count == 1:
            ident = f'Process-{index:02d}'
        else:
            ident = f'Runner-{index:02d}'

        if testbench_name:
            ident += f'-{testbench_name}'

        self.id = ident

    def as_runner(self,
                  output_dir: FilePathType,
                  cfg_yaml: FilePathType = None,
                  result: TestResult = None,
                  index: int = None,
                  enable_mock: bool = None,
                  strict: bool = None
                  ) -> TestRunnerType:
        if result is None:
            result = TestResult()

        if index is not None:
            if self.context and self.context.testbench:
                testbench_name = getattr(self.context.testbench, "name", None)
            else:
                testbench_name = None

            if self.id is None:
                self._update_ident_by_index(index, testbench_name)

        if self.context is None:
            context = TestContextNode().as_context(output_dir, self, enable_mock, strict)
        else:
            context = self.context.as_context(output_dir, self, enable_mock, strict)

        if self.process_count == 0:
            runner = TestRunner(id=self.id, result=result, context=context)
        elif self.process_count == 1:
            # clear main process test result before set it in sub process
            # otherwise it will cause duplicated tests display in report.
            runner = TestRunnerProcess(id=self.id, result=TestResult(failfast=result.failfast),
                                       context=context, log_level=self.log_level, log_layout=self.log_layout)
        else:
            if context.testbench is not None and context.testbench.exclusive:
                raise ConfigError("Can't perform multi-process when TestBench is exclusive.")
            runner = MultiProcessQueueTestConsumer(self.process_count, result, context, self.log_level, self.log_layout)
        runner.is_prerequisite = self.is_prerequisite

        for testsuite in self.testsuites:
            for model in testsuite.as_model_list(cfg_yaml):
                runner.add_testsuite(model)
        return runner


__all__ = (
    "parse_dict_by_path",
    "TestBenchNode",
    "TestResultNode",
    "EventObserverNode",
    "EventObservableNode",
    "TestContextNode",
    "TestRunnerNode"
)
