# coding: utf-8

import sys
import threading
from typing import Tuple, NoReturn, Optional
from .events import EventObservable, TestEventHandler, observable
from .bench import TestBench

import logging
logger = logging.getLogger(__name__)


class TestContext:
    """
    Test context bind with thread, each thread can only have one context.
    It used to notify observers when dispatching event.
    It can be got easily by calling current_context().
    """
    event_observable: EventObservable
    testbench: TestBench
    enable_mock: Optional[bool]
    strict: Optional[bool]

    def __init__(self, event_observable=EventObservable(), testbench=None, enable_mock=None, strict=None):
        self.event_observable = event_observable
        self.testbench = testbench
        self.enable_mock = enable_mock
        self.strict = strict

    def _make_sure_testbench_in_event_observable(self):
        if self.testbench is not None:
            self.testbench.priority = sys.maxsize
            self.event_observable.attach(self.testbench)

    def get_event_handlers(self, reverse=False) -> Tuple[TestEventHandler, ...]:
        self._make_sure_testbench_in_event_observable()
        return self.event_observable.get_observers(reverse)

    def dispatch_event(self, *args, **kwargs) -> NoReturn:
        self._make_sure_testbench_in_event_observable()
        self.event_observable.notify(*args, **kwargs)
        observable.notify(*args, **kwargs)


class TestContextManager:
    """
    Manage context which bind with thread.
    """

    _contexts = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, context: TestContext) -> NoReturn:
        ident = threading.current_thread().ident
        with cls._lock:
            cls._contexts[ident] = context

    @classmethod
    def unregister(cls) -> NoReturn:
        ident = threading.current_thread().ident
        with cls._lock:
            cls._contexts.pop(ident, None)

    @classmethod
    def current_context(cls) -> TestContext:
        """
        Get context in current thread.
        """
        ident = threading.current_thread().ident
        with cls._lock:
            try:
                return cls._contexts[ident]
            except KeyError:
                # for situation run testcase or testsuite without testrunner.
                msg = "Can't get context with thread ident %s, register a default TestContext object for it."
                logger.warning(msg, ident)
                context = TestContext()
                cls._contexts[ident] = context
                return context
    getCurrentContext = current_context


current_context = TestContextManager.current_context
register_context = TestContextManager.register
unregister_context = TestContextManager.unregister
