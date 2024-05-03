# coding: utf-8

from __future__ import annotations

import sys
import uuid
import enum
import inspect
import contextlib
from pathlib import Path
from datetime import datetime, timezone
from typing import NoReturn, Optional, List, Literal, Callable, ClassVar, Dict, Any
from types import MethodType, FunctionType
import pydantic

from .assertions import (
    pass_, fail_, warn_, skip_, assert_that, assert_warn, soft_assertions, assert_raises,
    AssertionBuilder
)
from .bench import TestBench
from .constants import IdType, FilePathType
from .context import current_context, TestContext
from .errors import Error, SkippedError, ErrorInfo, ArgumentError
from .mark import MarkHelper, RerunDecorator, TestDecorator
from .checkpoint import CheckPoint
from .events import (
    TestCaseStartedEvent, TestCaseStoppedEvent, TestMethodStartedEvent, TestMethodStoppedEvent,
    SetupStartedEvent, SetupStoppedEvent, TeardownStartedEvent, TeardownStoppedEvent, TestCaseFailedEvent
)
from .util import (
    get_source_code, remove_path_illegal_chars, locate, get_current_process_name, get_class_that_defined_method
)
from .serialization import BaseModel, parse_dict, AttrDict

import logging

logger = logging.getLogger(__name__)


class Parameters(AttrDict):
    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        for k, v in state.items():
            self[k] = v


class TestCaseResultStatus(enum.IntEnum):
    NOT_RUN = 0
    PASSED = 1
    WARNING = 2
    FAILED = 3
    SKIPPED = 4
    ERRONEOUS = 5
    REJECTED = 6
    CANCELED = 7


class PreAction(BaseModel):
    name: str
    status: int


class TestCaseResultRecord(BaseModel, arbitrary_types_allowed=True):
    """Used to save result of test case."""

    Status: ClassVar[TestCaseResultStatus] = TestCaseResultStatus

    id: IdType
    name: Optional[str] = None
    path: Optional[str] = None
    index: Optional[int] = None
    is_prerequisite: Optional[bool] = None
    parameters: Parameters = pydantic.Field(default_factory=Parameters)
    status: TestCaseResultStatus = TestCaseResultStatus.NOT_RUN
    error: Optional[ErrorInfo] = None
    checkpoints: List[CheckPoint] = pydantic.Field(default_factory=list)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    rerun_causes: List[str] = pydantic.Field(default_factory=list)
    enable_mock: Optional[bool] = None
    log_path: Optional[Path] = None
    testbench_node: Optional[str] = None
    testbench_name: Optional[str] = None
    testbench_type: Optional[str] = None
    is_manual: Optional[bool] = None
    extras: AttrDict = pydantic.Field(default_factory=AttrDict)
    pre_actions: List[PreAction] = pydantic.Field(default_factory=list)
    record_type: Literal['TestCaseResultRecord'] = pydantic.Field('TestCaseResultRecord')

    def get_status_name(self) -> str:
        if isinstance(self.status, int):
            self.status = TestCaseResultStatus(self.status)
        return self.status.name.lower()

    @property
    def rerun_counts(self) -> int:
        return len(self.rerun_causes)

    @property
    def duration(self) -> Optional[float]:
        if self.stopped_at is None or self.started_at is None:
            return None
        return (self.stopped_at - self.started_at).total_seconds()

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}(id:{self.id}, name:{self.name}, path:{self.path}, status:{self.status.name})>"

    def update(self, other, includes=None):
        for field in self.model_fields:
            if includes is None:
                setattr(self, field, getattr(other, field))
            else:
                if field in includes:
                    setattr(self, field, getattr(other, field))

    def as_test_model(self, **kwargs) -> 'TestCaseModel':
        model = TestCaseModel(
            id=self.id, name=self.name, path=self.path, index=self.index,
            is_prerequisite=self.is_prerequisite, enable_mock=self.enable_mock,
            parameters=self.parameters
        )
        for k, v in kwargs.items():
            setattr(model, k, v)
        return model


class _Outcome:
    def __init__(self, testcase: 'TestCase', event_on: bool = True):
        self.testcase = testcase
        self.event_on = event_on
        self.success = True
        self.expecting_failure = False
        self.expected_error = None

    @contextlib.contextmanager
    def execute(self, target, started_event_cls, stopped_event_cls) -> NoReturn:
        """
        A context method used to execute method and get the result.

        Parameters
        ----------
        target: method
            the target to be executed, it would be setup, teardown or test method

        started_event_cls:
            class of started event

        stopped_event_cls:
            class of stopped event
        """
        context = self.testcase.context
        record = self.testcase.record
        old_success = self.success
        self.success = True

        if self.event_on:
            context.dispatch_event(started_event_cls(target), reverse=False)
        try:
            yield
        except KeyboardInterrupt:
            self.success = False
            record.status = record.Status.ERRONEOUS
            exc_info = sys.exc_info()
            error = ErrorInfo.from_exception(exc_info)
            record.error = error
            raise
        except self.testcase.CheckPoint.FailureError:
            self.success = False
            record.status = TestCaseResultRecord.Status.FAILED
            error = self.testcase.record.checkpoints[-1].error
            if self.event_on:
                context.dispatch_event(TestCaseFailedEvent(self.testcase))
        except AssertionError as err:
            self.success = False
            record.status = TestCaseResultRecord.Status.FAILED
            info = ErrorInfo.from_exception(err)
            logger.error(info.trace)
            self.testcase.add_checkpoint(
                self.testcase.CheckPoint(name=str(err), status=self.testcase.CheckPoint.Status.FAILED, error=info)
            )
            if self.event_on:
                context.dispatch_event(TestCaseFailedEvent(self.testcase))
        except SkippedError as err:
            reason = str(err)
            self.success = False
            record.status = record.Status.SKIPPED
            record.error = ErrorInfo.from_exception(err)
            record.error.value = reason
            record.error.trace = reason
            logger.warning("Skip %s, Reason: %s", self.testcase, reason)
        except:
            exc_info = sys.exc_info()
            error = ErrorInfo.from_exception(exc_info)
            logger.error(error.trace)
            record.status = TestCaseResultRecord.Status.ERRONEOUS
            record.error = error

            if self.expecting_failure:
                self.expected_error = error
            else:
                self.success = False
        finally:
            self.success = self.success and old_success
            if self.success:
                if self.expecting_failure:
                    if self.expected_error:
                        record.status = record.Status.PASSED
                        record.error = self.expected_error
                    else:
                        record.status = record.Status.FAILED
                else:
                    record.status = record.Status.PASSED

            if self.event_on:
                context.dispatch_event(stopped_event_cls(target), reverse=True)


class TestCase:
    """
    Base class of test case.

    Parameters
    ----------
    method_name: str
        Method name to be run.

    id: IdType, optional
        Test case id

    name: str, optional
        Test case name

    index: int, optional
        Index in current test suite.

    is_prerequisite: bool, optional
        If is True, when current test case failed, the subsequent test cases in same test suite will not run.

    parameters: dict, optional
        Test parameters for test method.

    enable_mock: bool, optional
        Enable mock or not.

    strict: bool, optional
        Check whether check testcase lack of assert.
    """
    CheckPoint = CheckPoint
    Record = TestCaseResultRecord

    CLASS_SETUP_ERROR = None  # this error will be set when fail to call setup_class in suite.py.

    def __init__(self,
                 method_name,
                 id: IdType = None,
                 name: str = None,
                 index: int = None,
                 is_prerequisite: bool = False,
                 parameters: dict = None,
                 enable_mock: bool = None,
                 strict: bool = None,
                 ):
        self._method_name = method_name
        self.record = self.Record(id=(id or uuid.uuid1()))
        self.record.path = f"{self.__module__}.{self.__class__.__name__}.{self._method_name}"
        self.name = name
        self.index = index
        self.is_prerequisite = is_prerequisite  # determine whether following tests still running in current TestSuite.
        if parameters:
            self.parameters.update(parameters)

        self.enable_mock = enable_mock
        self.strict = strict

        method = self.get_test_method()
        self.is_manual = MarkHelper.is_manual(method)
        self.tags = MarkHelper.get_tags(method, self.__class__)
        self.route = MarkHelper.get_route(method, self.__class__)
        self.soft_errors = None

    def setup(self):
        # Hook method before calling test method
        pass

    def teardown(self):
        # Hook method after calling test method
        pass

    @classmethod
    def setup_class(cls):
        """
        Hook method before calling any test method in this class
        Note: This method will be called only once if there are multi test method in same class to be called sequent.

        For example:
        There are two methods: test_1, test_2
        When run test_1 and test_2 sequent, the calling sequence should be:
        1. setup_class
        2. setup -> test_1 -> teardown
        3. setup -> test_2 -> teardown
        4. teardown_class
        """
        pass

    @classmethod
    def teardown_class(cls):
        """
        Hook method after calling any test method in this class
        Note: This method will be called only once if there are multi test method in same class to be called sequent.

        For example:
        There are two methods: test_1, test_2
        When run test_1 and test_2 sequent, the calling sequence should be:
        1. setup_class
        2. setup -> test_1 -> teardown
        3. setup -> test_2 -> teardown
        4. teardown_class
        """
        pass

    def add_checkpoint(self, checkpoint: CheckPoint) -> NoReturn:
        logger.info(checkpoint)
        self.record.checkpoints.append(checkpoint)

    def pass_(self, message: str, **kwargs) -> NoReturn:
        pass_(message, self, **kwargs)

    def fail_(self, message: str, **kwargs) -> NoReturn:
        fail_(message, self, **kwargs)

    def warn_(self, message: str, **kwargs) -> NoReturn:
        warn_(message, self, **kwargs)

    def skip_(self, reason):
        skip_(reason)

    def skip_test(self, reason, event_on=True):
        """skip test without invoke TestCase.run()"""
        try:
            self._on_started(event_on)
            self.record.status = self.record.Status.SKIPPED
            self.record.error = ErrorInfo(type=SkippedError, value=reason, trace=reason)
            logger.warning("Skip %s, Reason: %s", self, reason)
        finally:
            self._on_stopped(event_on)

    def assert_that(self, value, message: str = '', is_warning: bool = False, verbose: int = AssertionBuilder.VERBOSE,
                    **checkpoint_kwargs):
        return assert_that(value, message, self, is_warning, verbose, **checkpoint_kwargs)

    def assert_warn(self, value, message: str = '', verbose: int = AssertionBuilder.VERBOSE, **checkpoint_kwargs):
        return assert_warn(value, message, self, verbose, **checkpoint_kwargs)

    def assert_raises(self, expected_exception, message: str = '', match_expr=None):
        """
        Assert the context should raise exception.

        Sample:
            with assert_raises(NotImplementedError, "should raise NotImplementedError") as error_info:
                pass
        """
        return assert_raises(expected_exception, message, match_expr, self)

    def soft_assertions(self):
        """
        Run all assertions in context, and then raise exception if failed.
        It is useful if you don't want to break the test steps.

        Sample:
            with self.soft_assertions():
                self.assert_that(1, "checkpoint1").is_equal_to(1)
                self.assert_that(1, "checkpoint2").is_equal_to(2)
                self.assert_that(1, "checkpoint3").is_equal_to(1)
        """
        return soft_assertions(self)

    def __eq__(self, other):
        if type(self) is not type(other):
            return False
        return self._method_name == other._method_name

    def __hash__(self):
        return hash((type(self), self._method_name))

    def __str__(self):
        return f"<{self.__class__.__name__}(id:{self.id}, name:{self.name}, path:{self.path}, index: {self.index})>"

    def __call__(self, *args, **kwds):
        return self.run(*args, **kwds)

    @property
    def id(self) -> IdType:
        return self.record.id

    @id.setter
    def id(self, id: IdType) -> NoReturn:
        self.record.id = id

    @property
    def name(self) -> str:
        return self.record.name

    @name.setter
    def name(self, name: str) -> NoReturn:
        self.record.name = name

    @property
    def index(self) -> int:
        return self.record.index

    @index.setter
    def index(self, index: int) -> NoReturn:
        self.record.index = index

    @property
    def path(self) -> str:
        return self.record.path

    @property
    def is_prerequisite(self) -> bool:
        return self.record.is_prerequisite

    @is_prerequisite.setter
    def is_prerequisite(self, is_prerequisite: bool) -> NoReturn:
        self.record.is_prerequisite = is_prerequisite

    @property
    def is_manual(self) -> bool:
        return self.record.is_manual

    @is_manual.setter
    def is_manual(self, is_manual: bool) -> NoReturn:
        self.record.is_manual = is_manual

    @property
    def enable_mock(self) -> bool:
        return self.record.enable_mock

    @enable_mock.setter
    def enable_mock(self, enable_mock: bool) -> NoReturn:
        self.record.enable_mock = enable_mock

    @property
    def parameters(self):
        return self.record.parameters

    @property
    def context(self) -> TestContext:
        return current_context()

    @property
    def testbench(self) -> TestBench:
        return self.context.testbench

    @property
    def log_path(self) -> Optional[Path]:
        return self.record.log_path

    @log_path.setter
    def log_path(self, log_path: FilePathType) -> NoReturn:
        self.record.log_path = Path(log_path)

    def get_default_name(self) -> str:
        return self.__class__.__name__ + "." + self._method_name

    def get_test_method(self, default=None) -> MethodType:
        return getattr(self, self._method_name, default)

    def description(self) -> str:
        method = self.get_test_method()
        return method.__doc__

    def run(self, event_on: bool = True):
        # FIXME: if one testcase call another, when running another testcase, it will also dispatch event.
        context = self.context
        record = self.record

        if self.enable_mock is None:
            self.enable_mock = context.enable_mock

        if self.strict is None:
            self.strict = context.strict

        try:
            self._on_started(event_on)

            if self.is_manual:
                return record

            self._exec(event_on)
            self._handle_rerun(event_on)
        except:
            logger.exception("")
            raise
        else:
            return record
        finally:
            if len(record.checkpoints) == 0:
                if self.strict and record.status == record.Status.PASSED:
                    record.status = record.Status.ERRONEOUS
                    msg = "There are no checkpoints, it means this testcase lack of assert."
                    record.error = ErrorInfo(type=Error, value=msg, trace=msg)
            else:
                if record.status == record.Status.PASSED:
                    warning_pre_actions = [pre_action for pre_action in record.pre_actions if pre_action.status != 0]
                    warning_checkpoints = [cp for cp in record.checkpoints if cp.status == cp.Status.WARNING]

                    if warning_pre_actions or warning_checkpoints:
                        record.status = record.Status.WARNING

            self._on_stopped(event_on)

    def _exec(self, event_on):
        outcome = _Outcome(self, event_on)
        with outcome.execute(self.setup, SetupStartedEvent, SetupStoppedEvent):
            self._eval_skipif()
            if self.route and self.route not in context.testbench.routes:
                self.skip_(f"Can't find route {self.route} in {context.testbench.routes}")
            self.setup()

        if outcome.success:
            test_method = self.get_test_method()
            with outcome.execute(test_method, TestMethodStartedEvent, TestMethodStoppedEvent):
                test_method(**self.parameters)

            with outcome.execute(self.teardown, TeardownStartedEvent, TeardownStoppedEvent):
                self.teardown()

    def _save_testbench_info(self, testbench) -> NoReturn:
        self.record.testbench_name = testbench.name
        self.record.testbench_type = testbench.type
        self.record.testbench_node = testbench.node

    def _eval_skipif(self) -> NoReturn:
        mark = MarkHelper.get_skipif_mark(self.get_test_method(), self.__class__)
        if mark and mark.check_condition(self):
            self.skip_(mark.reason)

    def _eval_name(self) -> NoReturn:
        if not self.name:
            self.name = self.get_default_name()

            mark = MarkHelper.get_test_mark(self.get_test_method())
            if mark is not None and mark.title is not None:
                if callable(mark.title):
                    sig = inspect.signature(mark.title)
                    if len(sig.parameters) == 1:
                        self.name = mark.title(self)
                    else:
                        self.name = mark.title()
                else:
                    self.name = mark.title
            self.name = self.name.format(**self.parameters)

    def eval_log_name(self, marker, mark_as_postfix=True) -> str:
        decorator = MarkHelper.get_test_mark(self.get_test_method())
        if decorator and decorator.log_name:
            log_name = decorator.log_name(self)
        else:
            if marker == "index":
                pst_name = f"${self.index:04d}"
            elif marker == "ident":
                pst_name = f"${self.id}"
            else:
                raise ValueError
            if mark_as_postfix:
                log_name = f"{remove_path_illegal_chars(self.get_default_name())}_{pst_name}.log"
            else:
                log_name = f"{pst_name}_{remove_path_illegal_chars(self.get_default_name())}.log"
        return log_name

    def _on_started(self, event_on=True):
        if event_on:
            self.context.dispatch_event(TestCaseStartedEvent(self), reverse=False)

        self.record.started_at = datetime.now(timezone.utc).astimezone()
        self._eval_name()
        if self.context.testbench:
            self._save_testbench_info(self.context.testbench)

    def _on_stopped(self, event_on=True):
        self.record.stopped_at = datetime.now(timezone.utc).astimezone()
        if event_on:
            self.context.dispatch_event(TestCaseStoppedEvent(self), reverse=True)

    def _handle_rerun(self, event_on):
        record = self.record
        mark = MarkHelper.get_rerun_mark(self.get_test_method(), self.__class__)
        if mark is not None:
            rerun_cause = None
            match record.status:
                case record.Status.FAILED:
                    rerun_when = RerunDecorator.When.FAILED
                    for checkpoint in reversed(record.checkpoints):
                        if checkpoint.error:
                            rerun_cause = checkpoint.error
                case record.Status.ERRONEOUS:
                    rerun_when = RerunDecorator.When.ERRONEOUS
                    rerun_cause = record.error
                case _:
                    rerun_when = 0

            if (rerun_cause is not None
                    and mark.scope & rerun_cause.scope
                    and mark.when & rerun_when
                    and record.rerun_counts < mark.retry
            ):
                record.rerun_causes.append(str(rerun_cause))
                logger.debug("Rerun: %s with %s", self, mark)

                try:
                    if callable(mark.pre_action):
                        mark.pre_action(self)
                    self._exec(event_on)
                finally:
                    if callable(mark.post_action):
                        mark.post_action(self)

                self._handle_rerun(event_on)
                if record.status == record.Status.PASSED:
                    record.status = mark.remark

    def as_dict(self) -> dict:
        cls = self.__class__
        method_name = self._method_name
        method = self.get_test_method()

        defs = []
        signature = inspect.signature(method)
        for name, parameter in signature.parameters.items():
            d = {
                "name": name,
                "type": getattr(parameter.annotation, "__name__", str(parameter.annotation))
            }
            if parameter.default is not inspect.Parameter.empty:
                d['default'] = str(parameter.default)
            defs.append(d)

        test_mark = MarkHelper.get_test_mark(method)
        if test_mark and test_mark.title is not None:
            if callable(test_mark.title):
                name = test_mark.title()
            else:
                name = test_mark.title
        else:
            name = self.get_default_name()

        cls_path = cls.__module__ + "." + cls.__name__
        return dict(
            path=cls_path + "." + method_name,
            name=name,
            type="method",
            args=dict(self.parameters),
            tags=self.tags,
            route=self.route,
            setup=cls.setup.__doc__,
            teardown=cls.teardown.__doc__,
            detail=self.description(),
            is_manual=self.is_manual,
            parametrize_defs=defs,
            parametrize_data=MarkHelper.get_parametrize_data(method),
            code=get_source_code(method)
        )


class FunctionTestCase(TestCase):
    """
    Wrapper class to execute function.

    Parameters
    ----------
    func: function object
        test function.

    setup: function object, optional
        setup fixture.

    teardown: function object, optional
        teardown fixture.

    *args, **kwargs:
        pass-through to TestCase.__init__.
    """

    def __init__(self, func: FunctionType, setup: FunctionType = None, teardown: FunctionType = None, *args, **kwargs):
        setattr(self, func.__name__, func)
        super().__init__(func.__name__, *args, **kwargs)
        self._func = func
        self._setup = setup
        self._teardown = teardown
        self.record.path = f"{inspect.getmodule(func).__name__}.{func.__name__}"

    def setup(self) -> NoReturn:
        if self._setup is not None:
            self._setup()

    def teardown(self) -> NoReturn:
        if self._teardown is not None:
            self._teardown()

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented

        return self._func == other._func and self._setup == other.setup and self._teardown == other._teardown

    def __hash__(self):
        return hash((type(self), self._func, self._setup, self._teardown))

    def get_default_name(self) -> str:
        return self._method_name


def is_testcase_instance(test):
    return isinstance(test, TestCase) or issubclass(test.__class__, TestCase)


def is_testcase_subclass(cls):
    if inspect.isclass(cls) and issubclass(cls, TestCase):
        return True
    else:
        return False


__current_testcase_id = 0


def fetch_current_testcase_id():
    global __current_testcase_id
    __current_testcase_id += 1
    name = get_current_process_name()
    return f'{name}-tc-{__current_testcase_id}'


def sign_params(func, parameters: dict) -> dict:
    signature = inspect.signature(func)
    try:
        logger.debug("bind params %s on %s", parameters, func)
        ba = signature.bind(None, **parameters)
        ba.apply_defaults()
        ba.arguments.pop('self')  # remove self argument
    except TypeError:
        logger.error("bind params failed, maybe missing @parametrize on '%s'", func)
        raise
    else:
        logger.debug("test params: %s", ba.kwargs)
        return ba.kwargs


ParamsSignatureCallbackType = Callable[[Callable, dict], dict]


def get_valid_params(obj, params: Dict[str, Any], strict: bool = None) -> Dict[str, Any]:
    sig = inspect.signature(obj)
    expected_keys = set()
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            expected_keys.add(name)
    actual_keys = set(params.keys())

    if strict and expected_keys != actual_keys:
        raise ArgumentError(f"params signature mismatch of {obj}: {actual_keys=} != {expected_keys=}")

    valid_params = {}
    for k, v in params.items():
        if k in expected_keys:
            valid_params[k] = v
        else:
            logger.warning("param '%s' not in signature of %s, ignore it", k, obj)
    return valid_params


class TestCaseModel(pydantic.BaseModel, extra='allow'):
    id: Optional[str | int] = None
    name: Optional[str] = None
    path: str
    index: Optional[int] = None
    parameters: dict = pydantic.Field(default_factory=dict)
    is_prerequisite: bool = False
    enable_mock: Optional[bool] = None
    strict: Optional[bool] = None
    rerun: int | dict = None

    def as_test(self,
                params_signature: ParamsSignatureCallbackType = None,
                ) -> TestCase:
        """
        construct as a testcase instance from model.

        Parameters
        ----------
        params_signature: callable, optional
            try signature testcase's parameters.
        """
        logger.info("load_testcase_from_data: %s", self.model_dump())

        parameters = self.parameters
        func = locate(self.path)

        if params_signature:
            parameters = params_signature(func, parameters)

        # TODO: check for test method's arguments **kwargs
        # if self.strict:
        #     named_args_size = 0
        #     has_var_kwd = False
        #     for k, v in signature.parameters.items():
        #         match v.kind:
        #             case inspect.Parameter.VAR_POSITIONAL:
        #                 raise ArgumentError("Test method's arguments include *args, it is forbidden.")
        #             case inspect.Parameter.VAR_KEYWORD:
        #                 has_var_kwd = True
        #             case _:
        #                 named_args_size += 1
        #
        #     if named_args_size == 1 and has_var_kwd:
        #         raise ArgumentError("Test method's arguments only include **kwargs, it is forbidden.")

        mark = MarkHelper.get_test_mark(func) or TestDecorator()

        if self.id is None:
            self.id = mark.ident or fetch_current_testcase_id()

        name = self.name
        if name:
            name = name.format(**parameters)

        rerun = self.rerun
        if rerun:
            kw = dict(retry=rerun) if isinstance(rerun, int) else rerun
            func = RerunDecorator(**kw)(func)

        cls = get_class_that_defined_method(func)
        extras = self.model_dump(exclude=set(self.model_fields.keys()))

        if cls:
            testcase = cls(
                method_name=func.__name__,
                id=self.id,
                name=name,
                index=self.index,
                parameters=parameters,
                is_prerequisite=self.is_prerequisite,
                enable_mock=self.enable_mock,
                strict=self.strict,
                **get_valid_params(cls, extras, self.strict)
            )
        else:
            testcase = FunctionTestCase(
                func=func,
                setup=mark.setup,
                teardown=mark.teardown,
                id=self.id,
                name=name,
                parameters=parameters,
                is_prerequisite=self.is_prerequisite,
                enable_mock=self.enable_mock,
                strict=self.strict,
                **extras
            )
        return testcase


def is_testcase_model(data: TestCaseModel):
    return isinstance(data, TestCaseModel)
