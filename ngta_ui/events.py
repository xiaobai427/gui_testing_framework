# coding: utf-8

import inspect
from typing import NoReturn, Callable, Tuple
from enum import Enum, unique, auto
from concurrent.futures import ThreadPoolExecutor
from coupling.pattern.observer import BaseObservable, BaseObserver
from .errors import HookError

import logging
logger = logging.getLogger(__name__)


class EventNotifyError(HookError):
    pass


@unique
class EventType(Enum):
    ON_ANY_EVENT = 0

    ON_TESTRUNNER_STARTED = 11
    ON_TESTRUNNER_STOPPED = 12

    ON_TESTSUITE_STARTED = 21
    ON_TESTSUITE_STOPPED = 22

    ON_TESTCASE_STARTED = 31
    ON_SETUP_STARTED = 32
    ON_SETUP_STOPPED = 33
    ON_TESTMETHOD_STARTED = 34
    ON_TESTMETHOD_STOPPED = 35
    ON_TEARDOWN_STARTED = 36
    ON_TEARDOWN_STOPPED = 37
    ON_TESTCASE_STOPPED = 38

    ON_TESTCASE_FAILED = auto()

    ON_SETUP_MODULE_STARTED = 41
    ON_SETUP_MODULE_STOPPED = 42
    ON_TEARDOWN_MODULE_STARTED = 43
    ON_TEARDOWN_MODULE_STOPPED = 44

    ON_SETUP_CLASS_STARTED = 51
    ON_SETUP_CLASS_STOPPED = 52
    ON_TEARDOWN_CLASS_STARTED = 53
    ON_TEARDOWN_CLASS_STOPPED = 54


class Event:
    type = EventType.ON_ANY_EVENT

    def __init__(self, target):
        self.target = target

    def __str__(self):
        return f"<{self.__class__.__name__}(target:{self.target}, type:{self.__class__.type.name})>"

    def __eq__(self, other):
        return self.type == other.type and self.target is other.target


TestRunnerStartedEvent = type("TestRunnerStartedEvent", (Event, ), dict(type=EventType.ON_TESTRUNNER_STARTED))
TestRunnerStoppedEvent = type("TestRunnerStoppedEvent", (Event, ), dict(type=EventType.ON_TESTRUNNER_STOPPED))

TestSuiteStartedEvent = type("TestSuiteStartedEvent", (Event, ), dict(type=EventType.ON_TESTSUITE_STARTED))
TestSuiteStoppedEvent = type("TestSuiteStoppedEvent", (Event, ), dict(type=EventType.ON_TESTSUITE_STOPPED))

TestCaseStartedEvent = type("TestCaseStartedEvent", (Event, ), dict(type=EventType.ON_TESTCASE_STARTED))
TestCaseStoppedEvent = type("TestCaseStoppedEvent", (Event, ), dict(type=EventType.ON_TESTCASE_STOPPED))

TestMethodStartedEvent = type("TestMethodStartedEvent", (Event, ), dict(type=EventType.ON_TESTMETHOD_STARTED))
TestMethodStoppedEvent = type("TestMethodStoppedEvent", (Event, ), dict(type=EventType.ON_TESTMETHOD_STOPPED))

SetupModuleStartedEvent = type("SetupModuleStartedEvent", (Event, ), dict(type=EventType.ON_SETUP_MODULE_STARTED))
SetupModuleStoppedEvent = type("SetupModuleStoppedEvent", (Event, ), dict(type=EventType.ON_SETUP_MODULE_STOPPED))

TeardownModuleStartedEvent = type(
    "TeardownModuleStartedEvent",  (Event, ), dict(type=EventType.ON_TEARDOWN_MODULE_STARTED)
)
TeardownModuleStoppedEvent = type(
    "TeardownModuleStoppedEvent", (Event, ), dict(type=EventType.ON_TEARDOWN_MODULE_STOPPED)
)

SetupClassStartedEvent = type("SetupClassStartedEvent", (Event, ), dict(type=EventType.ON_SETUP_CLASS_STARTED))
SetupClassStoppedEvent = type("SetupClassStoppedEvent", (Event, ), dict(type=EventType.ON_SETUP_CLASS_STOPPED))

TeardownClassStartedEvent = type(
    "TeardownClassStartedEvent",  (Event, ), dict(type=EventType.ON_TEARDOWN_CLASS_STARTED)
)
TeardownClassStoppedEvent = type(
    "TeardownClassStoppedEvent", (Event, ), dict(type=EventType.ON_TEARDOWN_CLASS_STOPPED)
)

SetupStartedEvent = type("SetupStartedEvent", (Event, ), dict(type=EventType.ON_SETUP_STARTED))
SetupStoppedEvent = type("SetupStoppedEvent", (Event, ), dict(type=EventType.ON_SETUP_STOPPED))
TeardownStartedEvent = type("TeardownStartedEvent", (Event, ), dict(type=EventType.ON_TEARDOWN_STARTED))
TeardownStoppedEvent = type("TeardownStoppedEvent", (Event, ), dict(type=EventType.ON_TEARDOWN_STOPPED))


TestCaseFailedEvent = type("TestCaseFailedEvent", (Event, ), dict(type=EventType.ON_TESTCASE_FAILED))


class TestEventHandler(BaseObserver):
    """
    Base class for handling test event.

    Parameters
    ----------
    priority : int, optional
        called priority which used by :class:`EventObservable <EventObservable>`

    ignore_errors : bool, optional
        ignore exceptions when each hook method has been invoking.

    is_async : bool, optional
        whether calling the hook method in async.
    """

    def __init__(self, priority: int = 1, ignore_errors: bool = False, is_async: bool = False):
        self.priority = priority
        self.ignore_errors = ignore_errors
        self.is_async = is_async

    def on_testrunner_started(self, event: TestRunnerStartedEvent):
        pass

    def on_testrunner_stopped(self, event: TestRunnerStoppedEvent):
        pass

    def on_testsuite_started(self, event: TestSuiteStartedEvent):
        pass

    def on_testsuite_stopped(self, event: TestSuiteStoppedEvent):
        pass

    def on_testcase_started(self, event: TestCaseStartedEvent):
        pass

    def on_testcase_stopped(self, event: TestCaseStoppedEvent):
        pass

    def on_testmethod_started(self, event: TestMethodStartedEvent):
        pass

    def on_testmethod_stopped(self, event: TestMethodStoppedEvent):
        pass

    def on_setup_module_started(self, event: SetupModuleStartedEvent):
        pass

    def on_setup_module_stopped(self, event: SetupModuleStoppedEvent):
        pass

    def on_teardown_module_started(self, event: TeardownModuleStartedEvent):
        pass

    def on_teardown_module_stopped(self, event: TeardownModuleStoppedEvent):
        pass

    def on_setup_class_started(self, event: SetupClassStartedEvent):
        pass

    def on_setup_class_stopped(self, event: SetupClassStoppedEvent):
        pass

    def on_teardown_class_started(self, event: TeardownClassStartedEvent):
        pass

    def on_teardown_class_stopped(self, event: TeardownClassStartedEvent):
        pass

    def on_setup_started(self, event: SetupStartedEvent):
        pass

    def on_setup_stopped(self, event: SetupStoppedEvent):
        pass

    def on_teardown_started(self, event: TeardownStartedEvent):
        pass

    def on_teardown_stopped(self, event: TeardownStoppedEvent):
        pass

    def on_testcase_failed(self, event: TestCaseFailedEvent):
        pass

    def on_any_event(self, event: Event):
        pass

    def dispatch(self, event: Event):
        self.on_any_event(event)
        method = getattr(self, event.type.name.lower())
        method(event)

    def update(self, observable: "EventObservable", event: Event):
        if self.is_async:
            future = observable.executor.submit(self.dispatch, event)
            future.add_done_callback(self._on_future_done)
        else:
            try:
                self.dispatch(event)
            except Exception as err:
                if self.ignore_errors:
                    logger.exception("event handler ignore errors:")
                else:
                    logger.exception("event handler ignore_errors is False, re-raise exception: %s", err)
                    raise

    def _on_future_done(self, future):
        try:
            future.result()
        except Exception as err:
            if self.ignore_errors:
                logger.exception("ignore errors from future: %s", future)
            else:
                logger.exception("ignore_errors is False, re-raise exception from future: %s", future)
                raise

    def __str__(self):
        return f"<{self.__class__.__name__}(priority:{self.priority}, ignore_errors:{self.ignore_errors})>"


class CallbackTestEventHandler(TestEventHandler):
    """
    A event handler for specified test event.

    Parameters
    ----------
    callback : typing.Callable
        This callback would be called when receiving specified event type.

    event_type : bool
        Specified the event type, when receiving event with this type, the callback will be called.

    *args, **kwargs: bool
        Refer to :class:`TestEventHandler <TestEventHandler>`
    """

    def __init__(self,
                 callback: Callable[[Event], None],
                 event_type: EventType,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callback = callback
        self.event_type = event_type

    def dispatch(self, event: Event):
        if self.event_type == event.type or self.event_type == EventType.ON_ANY_EVENT:
            self.callback(event)


class EventObservable(BaseObservable):
    """
    Event observable which used to dispatch test event to all attached handlers.

    Parameters
    ----------
    max_workers : int, optional
        Thread pool max workers. Used for calling :class:`TestEventHandler <TestEventHandler>` async.
    """

    def __init__(self, max_workers: int = None, ignore_notify_errors: bool = False):
        super().__init__()
        self.max_workers = max_workers
        self.ignore_notify_errors = ignore_notify_errors
        self.executor = ThreadPoolExecutor(self.max_workers)

    def __getstate__(self):
        excludes = ("executor", "_lock")
        return {k: v for k, v in self.__dict__.items() if k not in excludes}

    def __setstate__(self, state):
        super().__setstate__(state)
        self.max_workers = state["max_workers"]
        self.ignore_notify_errors = state["ignore_notify_errors"]
        self.executor = ThreadPoolExecutor(self.max_workers)

    def shutdown(self):
        self.executor.shutdown()

    def get_observers(self, reverse=False) -> Tuple[TestEventHandler, ...]:
        """
        Get all attached :class:`TestEventHandler <TestEventHandler>`.

        Parameters
        ----------
        reverse: bool, optional
            whether reverse instances of :class:`TestEventHandler <TestEventHandler>` in return tuple.

        Returns
        -------
        tuple
            A tuple contains instances of :class:`TestEventHandler <TestEventHandler>`.
        """

        observers = []
        with self._lock:
            observers.extend(self._observers)

        if reverse:
            observers.reverse()
        return tuple(observers)

    def listen(self, event_type: EventType, callback: Callable | TestEventHandler, *args, **kwargs):
        """
        Parameters
        ----------
        event_type: EventType
            Specify event type for listening.

        callback: typing.Callable or TestEventHandler
            if the type is function or method, construct a CallbackTestEventHandler and attach it.
            if the type is instance of TestEventHandler, attach it directly.
            if the type is subclass of TestEventHandler, construct and attach it.

        *args, **kwargs:
            used for construct an instance of TestEventHandler
        """

        if inspect.isfunction(callback) or inspect.ismethod(callback):
            listener = CallbackTestEventHandler(callback, event_type, *args, **kwargs)
        elif isinstance(callback, TestEventHandler):
            listener = callback
        elif inspect.isclass(callback):
            listener = callback(*args, **kwargs)
        else:
            raise ValueError("Unsupported callback: %s" % callback)
        self.attach(listener)

    def listen_for(self, event_type: EventType = EventType.ON_ANY_EVENT, *args, **kwargs):
        """
        A decorator which can be marked on function, instance of TestEventHandler or TestEventHandler class.
        when marked on TestEventHandler class, use *args and **kwargs to provide constructor arguments.

        Parameters
        ----------
        event_type: EventType
            Specify event type for listening.
        """
        def wrapper_outer(callback):
            self.listen(event_type, callback, *args, **kwargs)
            return callback
        return wrapper_outer

    def attach(self, observer: TestEventHandler) -> NoReturn:
        """
        Add TestEventHandler into maintenance list.
        """
        super().attach(observer)
        self._observers.sort(key=lambda x: x.priority)

    def notify(self, event: Event, reverse: bool = False):
        """
        Notify all attached TestEventHandler when receiving event.
        """
        # logger.debug('Notify: %s', event)
        errors = []
        for observer in self.get_observers(reverse):
            try:
                observer.update(self, event)
            except Exception as err:
                logger.error("error when updating observer %s: %s", observer, err)
                errors.append(err)

        if errors and not self.ignore_notify_errors:
            raise EventNotifyError(errors)

    def __str__(self):
        return f'<{self.__class__.__name__}(max_workers={self.max_workers})>'


observable = EventObservable()
