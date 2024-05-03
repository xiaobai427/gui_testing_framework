# coding: utf-8

import sys
import uuid
import time
import pprint

import pydantic
from pathlib import Path
from typing import Iterable, Union, Any, NoReturn, Iterator, List, Literal, TYPE_CHECKING, Callable, Optional, Annotated
from .assertions import ErrorInfo
from .case import TestCase, TestCaseModel, TestCaseResultRecord, ParamsSignatureCallbackType, get_valid_params
from .context import current_context
from .mark import MarkHelper, RerunDecorator

from .events import (
    TestSuiteStartedEvent, TestSuiteStoppedEvent,
    SetupClassStartedEvent, SetupClassStoppedEvent, TeardownClassStartedEvent, TeardownClassStoppedEvent,
    SetupModuleStartedEvent, SetupModuleStoppedEvent, TeardownModuleStartedEvent, TeardownModuleStoppedEvent,
    TestCaseStoppedEvent
)
from .constants import (
    IdType, FilePathType,
    SETUP_CLASS_NAME, SETUP_MODULE_NAME, TEARDOWN_CLASS_NAME, TEARDOWN_MODULE_NAME
)
from .serialization import pformat_json, AttrDict, parse_dict, BaseModel
from .util import locate, get_current_process_name

if TYPE_CHECKING:
    from .result import TestResult

import logging
logger = logging.getLogger(__name__)


TestResultRecord = Annotated[
    Union['TestSuiteResultRecord', TestCaseResultRecord],
    pydantic.Field(discriminator='record_type')
]


class TestSuiteResultRecord(BaseModel):
    """Used to save result of test suite."""
    testsuite_id: IdType
    name: Optional[str] = None
    path: Optional[str] = None
    records: List[TestResultRecord] = pydantic.Field(default_factory=list)
    log_dir: Optional[Path] = None
    index: Optional[int] = None

    record_type: Literal['TestSuiteResultRecord'] = pydantic.Field('TestSuiteResultRecord')

    def add_sub_test_record(self, record: TestResultRecord) -> NoReturn:
        # logger.debug("%s add a new sub-record: %s", self, record)
        self.records.append(record)

    def get_last_testcase_record(self) -> TestCaseResultRecord:
        last = self.records[-1]
        if isinstance(last, TestSuiteResultRecord):
            return last.get_last_testcase_record()
        else:
            return last

    def statistics(self, deep: bool = True) -> AttrDict:
        statistics = AttrDict()
        statistics.total = 0

        for record in self.records:
            if isinstance(record, TestCaseResultRecord):
                status = record.get_status_name()
                if status not in statistics:
                    statistics[status] = 0
                statistics[status] += 1
                statistics.total += 1
            elif isinstance(record, self.__class__) and deep:
                sub_statistics = record.statistics(deep)
                for key in statistics.keys():
                    statistics[key] += sub_statistics.get(key, 0)
            else:
                pass
        return statistics

    def as_test_model(self, **kwargs) -> 'TestSuiteModel':
        tests = [record.as_test_model() for record in self.records]
        model = TestSuiteModel(id=self.testsuite_id, name=self.name, path=self.path, tests=tests)
        for k, v in kwargs.items():
            setattr(model, k, v)
        return model

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}(name:{self.name}, records:{pprint.pformat(self.records)})>"


class TestSuiteResultRecordList(list):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        records = cls()
        for item in v:
            o = parse_dict(item)
            records.append(o)
        return records

    def expand(self) -> List[TestSuiteResultRecord]:
        ts_records = []

        def recur(orig_ts_record, ancestors=None):
            ancestors = ancestors or []
            sub_tc_records = []
            sub_ts_records = []

            sub_ancestors = []
            sub_ancestors.extend(ancestors)
            sub_ancestors.append(orig_ts_record.name)

            for sub_record in orig_ts_record.records:
                if isinstance(sub_record, TestSuiteResultRecord):
                    sub_ts_records.append(sub_record)
                else:
                    sub_tc_records.append(sub_record)

            # for making sure testcase display first.
            # handle sub-testcase record first, then sub-testsuite record.
            if sub_tc_records:
                params = orig_ts_record.dict()
                params["name"] = " / ".join(sub_ancestors)
                params["records"] = sub_tc_records
                ts_record = orig_ts_record.__class__(**params)
                ts_records.append(ts_record)

            for sub_ts_record in sub_ts_records:
                recur(sub_ts_record, sub_ancestors)

        for suite_record in iter(self):
            recur(suite_record)
        return ts_records


class TestSuite:
    """
    A collection which include testcase or testsuite to run.

    Parameters
    ----------
    tests: List[TestCase | TestSuite], optional
        which should be run in current testsuite. The test item can be a testcase or testsuite.

    id: IdType, optional
        checkpoint status

    name: str, optional
        test suite name
    """

    Record = TestSuiteResultRecord

    def __init__(self, tests: Iterable = (), id: IdType = None, name: str = "testsuite"):
        self._tests = []
        self.record = self.Record(testsuite_id=(id or uuid.uuid1()), name=name)
        self.record.path = f"{self.__module__}.{self.__class__.__name__}"
        self.add_tests(tests)
        self.is_top_level = True

    def __iter__(self) -> Iterator:
        return iter(self._tests)

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return list(self) == list(other)

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}(id:{self.id}, name:{self.name})>"

    def count_testcases(self, deep: bool = True) -> int:
        return len(list(self.yield_testcases(deep)))

    def yield_testcases(self, deep: bool = True):
        for test in self._tests:
            if is_testsuite(test):
                if deep:
                    for sub_testcase in test.yield_testcases(deep):
                        yield sub_testcase
            else:
                yield test

    @property
    def name(self) -> str:
        return self.record.name

    @name.setter
    def name(self, name: str) -> NoReturn:
        self.record.name = name

    @property
    def id(self) -> IdType:
        return self.record.testsuite_id

    @id.setter
    def id(self, id: IdType) -> NoReturn:
        self.record.id = id

    @property
    def index(self) -> int:
        return self.record.index

    @index.setter
    def index(self, index: int) -> NoReturn:
        self.record.index = index

    @property
    def log_dir(self) -> Path:
        return self.record.log_dir

    @log_dir.setter
    def log_dir(self, log_dir: FilePathType) -> NoReturn:
        self.record.log_dir = Path(log_dir)

    def add_test(self, test) -> NoReturn:
        if test.index is None:
            try:
                prev_test = self._tests[-1]
            except IndexError:
                test.index = 1
            else:
                test.index = prev_test.index + 1

        if is_testsuite(test):
            test.is_top_level = False

        self._tests.append(test)
        self.record.add_sub_test_record(test.record)

    def add_tests(self, tests: Iterable) -> NoReturn:
        for test in tests:
            self.add_test(test)

    def run(self, result: 'TestResult' = None) -> 'TestSuiteResultRecord':
        from .result import TestResult
        result = result or TestResult()
        context = current_context()

        try:
            context.dispatch_event(TestSuiteStartedEvent(self), reverse=False)

            self._run_tests(result)
            if self.is_top_level:
                self._handle_class_teardown(None, result)
                self._handle_module_teardown(result)
                result.__class__.PREV_TEST_CLASS = None
        finally:
            context.dispatch_event(TestSuiteStoppedEvent(self), reverse=True)

        return self.record

    def skip_test(self, reason: str) -> NoReturn:
        for sub_test in self._tests:
            sub_test.skip_test(reason)

    def _run_tests(self, result: 'TestResult') -> NoReturn:
        for index, test in enumerate(self._tests):
            if result.should_abort:
                break
            else:
                while result.should_pause:
                    time.sleep(result.PAUSE_INTERVAL)

            self.run_test(test, result)

            if not is_testsuite(test):
                # skip all following tests in current testsuite if prerequisite not reach
                if test.is_prerequisite and test.record.status in (
                        test.record.Status.FAILED,
                        test.record.Status.SKIPPED,
                        test.record.Status.ERRONEOUS
                ):
                    for follow in self._tests[index + 1:]:
                        follow.skip_test(f"Prerequisite '{test}' failed")
                    break

    def run_test(self, test: Union['TestSuite', 'TestCase'], result: 'TestResult') -> NoReturn:
        if is_testsuite(test):
            test.run(result)
        else:
            record = test.record

            self._handle_class_teardown(test, result)
            self._handle_module_setup(test, result)
            self._handle_class_setup(test, result)
            result.__class__.PREV_TEST_CLASS = test.__class__

            class_setup_error = test.__class__.CLASS_SETUP_ERROR
            module_setup_error = result.__class__.MODULE_SETUP_ERROR
            if class_setup_error or module_setup_error:
                record.error = class_setup_error or module_setup_error

                # still dispatch TestCaseStoppedEvent if setup module or class failed.
                context = current_context()
                context.dispatch_event(TestCaseStoppedEvent(test), reverse=True)
                return

            logger.debug("*** Start %s ***", test)
            try:
                record = test.run()
                if record.status == record.Status.FAILED and result.failfast:
                    result.abort()
            finally:
                logger.debug("*** Finish %s ***", test)

    @classmethod
    def _get_previous_module(cls, result):
        prev_module = None
        prev_class = result.__class__.PREV_TEST_CLASS
        if prev_class is not None:
            prev_module = prev_class.__module__
        return prev_module

    @classmethod
    def _handle_fixture(cls, fixture, started_event_cls, stopped_event_cls):
        context = current_context()
        context.dispatch_event(started_event_cls(fixture), reverse=False)
        try:
            logger.debug('call fixture: %s', fixture)
            fixture()
        except Exception as err:
            error = ErrorInfo.from_exception(err)
            logger.error(error.trace)
            return error
        finally:
            context.dispatch_event(stopped_event_cls(fixture), reverse=True)

    @classmethod
    def _handle_module_setup(cls, test, result):
        prev_module = cls._get_previous_module(result)
        curt_module = test.__class__.__module__
        if curt_module == prev_module:
            return

        cls._handle_module_teardown(result)

        result.__class__.MODULE_SETUP_ERROR = None
        try:
            module = sys.modules[curt_module]
        except KeyError:
            return

        setup = getattr(module, SETUP_MODULE_NAME, None)
        if setup is not None:
            error = cls._handle_fixture(setup, SetupModuleStartedEvent, SetupModuleStoppedEvent)
            if error:
                result.__class__.MODULE_SETUP_ERROR = error

    @classmethod
    def _handle_module_teardown(cls, result):
        prev_module = cls._get_previous_module(result)
        if prev_module is None:
            return

        if result.__class__.MODULE_SETUP_ERROR:
            return

        try:
            module = sys.modules[prev_module]
        except KeyError:
            return
        teardown = getattr(module, TEARDOWN_MODULE_NAME, None)
        if teardown is not None:
            cls._handle_fixture(teardown, TeardownModuleStartedEvent, TeardownModuleStoppedEvent)

    @classmethod
    def _handle_class_setup(cls, test, result):
        prev_class = result.__class__.PREV_TEST_CLASS
        curt_class = test.__class__
        if curt_class == prev_class:
            return

        if result.__class__.MODULE_SETUP_ERROR:
            return

        # handle @skip marked on class
        mark = MarkHelper.get_skipif_mark_by_class(curt_class)
        if mark and mark.condition is True:
            return

        curt_class.CLASS_SETUP_ERROR = None

        setup = getattr(curt_class, SETUP_CLASS_NAME, None)
        if setup is not None:
            error = cls._handle_fixture(setup, SetupClassStartedEvent, SetupClassStoppedEvent)
            if error:
                curt_class.CLASS_SETUP_ERROR = error

    @classmethod
    def _handle_class_teardown(cls, test, result):
        prev_class = result.__class__.PREV_TEST_CLASS
        curt_class = test.__class__
        if curt_class == prev_class:
            return

        if prev_class and prev_class.CLASS_SETUP_ERROR:
            return

        if result.__class__.MODULE_SETUP_ERROR:
            return

        # handle @skip marked on class
        mark = MarkHelper.get_skipif_mark_by_class(curt_class)
        if mark and mark.condition is True:
            return

        teardown = getattr(prev_class, TEARDOWN_CLASS_NAME, None)
        if teardown is not None:
            cls._handle_fixture(teardown, TeardownClassStartedEvent, TeardownClassStoppedEvent)


def is_testsuite(test: Any) -> bool:
    return isinstance(test, TestSuite) or issubclass(test.__class__, TestSuite)


__current_testsuite_id = 0


def fetch_current_testsuite_id():
    global __current_testsuite_id
    __current_testsuite_id += 1
    name = get_current_process_name()
    return f'{name}-ts-{__current_testsuite_id}'


TestModelType = Union['TestSuiteModel', TestCaseModel]


class TestSuiteModel(pydantic.BaseModel, extra='allow'):
    id: str | int = None
    name: str = "testsuite"
    path: Optional[str] = None
    tests: List[TestModelType]
    flat: bool = False

    def as_test(self, params_signature: ParamsSignatureCallbackType = None) -> TestSuite:
        """
        construct as a testsuite instance from model.

        Parameters
        ----------
        params_signature: callable, optional
            try signature testcase's parameters.
        """
        logger.info("load_testsuite_from_data: \n%s", pformat_json(self.model_dump()))

        if self.id is None:
            self.id = fetch_current_testsuite_id()

        ident = self.id
        name = self.name
        path = self.path
        tests = self.tests
        flat = self.flat

        extras = self.model_dump(exclude=set(self.model_fields.keys()))

        if path:
            cls = locate(path)
            params = get_valid_params(cls, extras)
            suite = cls(tests=(), id=ident, name=name, **params)
        else:
            cls = TestSuite
            suite = cls(tests=(), id=ident, name=name)

        for sub_data in tests:
            test = sub_data.as_test(params_signature)
            if isinstance(test, TestSuite):
                if flat:
                    suite.add_tests(test._tests)
                else:
                    suite.add_test(test)
            elif isinstance(test, TestCase):

                suite.add_test(test)
            else:
                pass
        return suite

    def count_testcases(self) -> int:
        count = 0
        for sub_test in self.tests:
            if isinstance(sub_test, TestCaseModel):
                count += 1
            else:
                count += sub_test.count_testcases()
        return count


TestSuiteModel.model_rebuild()


def is_testsuite_model(data: TestModelType):
    return isinstance(data, TestSuiteModel)
