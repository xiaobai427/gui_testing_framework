# coding: utf-8

import uuid

from datetime import datetime, timezone
from typing import NoReturn, List
from abc import ABCMeta, abstractmethod
from coupling.pattern import observer

from .context import TestContext, TestContextManager
from .constants import IdType
from .result import TestResult
from .suite import TestSuite, TestSuiteModel, is_testsuite_model
from .events import TestRunnerStartedEvent, TestRunnerStoppedEvent


import logging
logger = logging.getLogger(__name__)


class TestRunner:
    """
    Class of test runner.

    Parameters
    ----------
    id: IdType, optional
        Test runner id

    result: TestResult, optional
        Test result instance.

    context: TestContext, optional
        Test context instance.
    """

    class State:
        INITIAL = 1
        RUNNING = 2
        PAUSED = 3
        ABORTED = 4
        UNEXPECTED = 5
        FINISHED = 6

    class Observable(observer.BaseObservable):
        def __init__(self, id: IdType = None, state: "TestRunner.State" = None):
            super().__init__()
            self.id = id
            self.state = state

    class BaseObserver(observer.BaseObserver, metaclass=ABCMeta):
        def update(self, observable: "TestRunner.Observable", *args, **kwargs) -> NoReturn:
            data = {
                "id": observable.id,
                "state": observable.state,
            }
            self.emit(data)

        @abstractmethod
        def emit(self, data: dict) -> NoReturn:
            pass

    def __init__(self, id: IdType = None, result: TestResult = None, context: TestContext = None):
        self.id = id or uuid.uuid1()
        self.result = result or TestResult()
        self.context = context or TestContext()
        self._testsuites = []

        self.observable = self.Observable(self.id)
        self.state = TestRunner.State.INITIAL

    @property
    def state(self) -> "TestRunner.State":
        return self.observable.state

    @state.setter
    def state(self, value: "TestRunner.State") -> NoReturn:
        self.observable.state = value
        self.observable.notify()

    def pause(self) -> NoReturn:
        self.result.pause()
        self.state = TestRunner.State.PAUSED

    def resume(self) -> NoReturn:
        self.result.resume()
        self.state = TestRunner.State.RUNNING

    def abort(self) -> NoReturn:
        self.result.abort()
        self.state = TestRunner.State.ABORTED

    def clear(self):
        self._testsuites.clear()
        self.result.clear()

    def add_testsuites(self, testsuites: List[TestSuiteModel | TestSuite]) -> NoReturn:
        for testsuite in testsuites:
            self.add_testsuite(testsuite)

    def add_testsuite(self, testsuite: TestSuiteModel | TestSuite) -> NoReturn:
        """
        Add testsuite into testrunner to run..

        Parameters
        ----------
        testsuite: testsuite instance or testsuite dict
        """
        if is_testsuite_model(testsuite):
            testsuite = testsuite.as_test()

        self._testsuites.append(testsuite)

        self.result.add_testsuite_record(testsuite.record)

    def is_stopped(self) -> bool:
        return self.state in (self.State.ABORTED, self.State.UNEXPECTED, self.State.FINISHED)

    def _run_tests(self):
        for testsuite in self._testsuites:      # type: TestSuite
            try:
                logger.debug("=== Start %s ===", testsuite)
                testsuite.run(self.result)
            finally:
                logger.debug("=== Finish %s ===", testsuite)

    def run(self) -> NoReturn:
        TestContextManager.register(self.context)   # register context with current thread ident
        try:
            if not self.result.started_at:
                self.result.started_at = datetime.now(timezone.utc).astimezone()
            self.context.dispatch_event(TestRunnerStartedEvent(self), reverse=False)
            self.state = TestRunner.State.RUNNING
            self._run_tests()
        except KeyboardInterrupt:
            self.abort()
            logger.warning("KeyboardInterrupt!!!")
            raise
        except:
            self.state = TestRunner.State.UNEXPECTED
            raise
        finally:
            self.result.stopped_at = datetime.now(timezone.utc).astimezone()
            if self.state not in (TestRunner.State.ABORTED, TestRunner.State.UNEXPECTED):
                self.state = TestRunner.State.FINISHED

            try:
                if self.context.testbench:
                    self.result.tb_records.append(self.context.testbench.as_record())
                self.context.dispatch_event(TestRunnerStoppedEvent(self), reverse=True)
            except:
                self.state = TestRunner.State.UNEXPECTED
                raise
            finally:
                self.context.event_observable.shutdown()
                TestContextManager.unregister()     # unregister context with current thread ident

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}(id:{self.id}, state:{self.state})>"
