# coding: utf-8

import re
import inspect
from typing import Optional, TYPE_CHECKING, NoReturn
from assertpy import assertpy
from deepdiff import DeepDiff
from deepdiff.helper import strings, numbers
from collections.abc import Mapping, Iterable
from .checkpoint import CheckPoint
from .errors import ErrorInfo, SkippedError, SoftAssertionsError
from .util import truncate_str

import logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .case import TestCase


class Diff(DeepDiff):
    def __getattr__(self, item):
        method = DeepDiff.__getattribute__(self, item.replace('Diff', 'DeepDiff'))
        return method

    def _DeepDiff__diff(self, level, parents_ids=frozenset({})):
        """override original method, still diff data if it's type is Mapping or Iterable"""
        if level.t1 is level.t2:
            return

        if self.__skip_this(level):
            return

        if type(level.t1) != type(level.t2) and \
                not (isinstance(level.t1, Iterable) and isinstance(level.t2, Iterable)
                     or isinstance(level.t1, Mapping) and isinstance(level.t2, Mapping)):
                self.__diff_types(level)
        elif isinstance(level.t1, strings):
            self.__diff_str(level)
        elif isinstance(level.t1, numbers):
            self.__diff_numbers(level)
        elif isinstance(level.t1, Mapping):
            self.__diff_dict(level, parents_ids)
        elif isinstance(level.t1, tuple):
            self.__diff_tuple(level, parents_ids)
        elif isinstance(level.t1, (set, frozenset)):
            self.__diff_set(level)
        elif isinstance(level.t1, Iterable):
            if self.ignore_order:
                self.__diff_iterable_with_contenthash(level)
            else:
                self.__diff_iterable(level, parents_ids)
        else:
            self.__diff_obj(level, parents_ids)
        return


class AssertionBuilder(assertpy.AssertionBuilder):
    """
    AssertionBuilder inherited from assertpy.AssertionBuilder.
    It extends some methods to integrate with ngta.

    Parameters
    ----------
    checkpoint: CheckPoint
        Used to store checkpoint related info.

    soft_errors: list, optional
        Used to store soft_errors instead of raise FailureError when assert kind is SOFT.

    *args:
        pass-through to assertpy.AssertionBuilder.__init__

    **kwargs:
        pass-through to assertpy.AssertionBuilder.__init__
    """

    class Kind:
        FAIL = 0
        WARN = 1
        SOFT = 2

    VERBOSE = 2

    def __init__(self, checkpoint: 'CheckPoint', soft_errors: list = None, verbose: int = VERBOSE, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checkpoint = checkpoint
        self.soft_errors = soft_errors
        self.verbose = verbose
        if self.soft_errors is None:
            self.soft_errors = []

    def is_equal_to(self, other, **kwargs) -> 'AssertionBuilder':
        """
        Override base class method, use DeepDiff to do the assertion.
        """
        diff = DeepDiff(other, self.val, verbose_level=2, **kwargs)
        if self.verbose >= 2:
            logger.debug("Compare: \n%s\nVS\n%s", self.val, other)

        if diff:
            logger.debug("Diff: %s", diff)
            msg = f'Expected <{truncate_str(self.val, 10)}> to be equal to <{truncate_str(other, 10)}>, but was not.'
            self.error(msg)
        return self

    def described_as(self, description) -> 'AssertionBuilder':
        """
        Override base class method, store description as checkpoint name.
        """
        self.checkpoint.name = description
        return super().described_as(description)

    def error(self, msg: str):
        """
        Override base class method, handle exception and save related info into checkpoint.
        """
        if self.description:
            message = f'[{self.description}]. '
        else:
            message = ''

        if self.verbose >= 1:
            message += truncate_str(msg, 64)

        if self.kind == self.Kind.SOFT:
            try:
                with self.checkpoint.catch():
                    raise self.checkpoint.FailureError(message)
            except self.checkpoint.FailureError as err:
                self.soft_errors.append(ErrorInfo.from_exception(err))
        else:
            exc_class = self.checkpoint.WarningError if self.kind == self.Kind.WARN else self.checkpoint.FailureError
            with self.checkpoint.catch():
                raise exc_class(message)


def find_testcase_in_outer_frames() -> Optional['TestCase']:
    """
    Find testcase from outer frames, but is not reliability

    Parameters
    ----------

    Returns
    -------
    testcase or None
        found testcase, or None if there is no testcase in outer frame.
    """
    from ngta.case import is_testcase_instance

    for frame_info in inspect.getouterframes(inspect.currentframe()):
        f_locals = frame_info[0].f_locals
        found = f_locals.get("self", None)
        if found and is_testcase_instance(found):
            return found
    return None


def _new_checkpoint(test: 'TestCase', **checkpoint_kwargs) -> 'CheckPoint':
    checkpoint = test.CheckPoint(**checkpoint_kwargs)
    test.add_checkpoint(checkpoint)
    return checkpoint


def pass_(message: str, testcase: 'TestCase' = None, **checkpoint_kwargs) -> NoReturn:
    """
    Add passed checkpoint

    Parameters
    ----------
    message : str
        Would be saved as checkpoint name

    testcase : TestCase, optional
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.

    **checkpoint_kwargs:
        Used to construct a CheckPoint instance.
    """
    testcase = testcase or find_testcase_in_outer_frames()
    _new_checkpoint(testcase, name=message, status=testcase.CheckPoint.Status.PASSED, **checkpoint_kwargs)


def fail_(message: str, testcase: 'TestCase' = None, **checkpoint_kwargs) -> NoReturn:
    """
    Add failed checkpoint and raise FailureError.
    If current testcase is not in soft_assertions context, the raised FailureError would be captured.

    Parameters
    ----------
    message : str
        Would be saved as checkpoint name

    testcase : TestCase, optional
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.

    **checkpoint_kwargs:
        Used to construct a CheckPoint instance.
    """
    testcase = testcase or find_testcase_in_outer_frames()
    checkpoint = _new_checkpoint(testcase, name=message, status=testcase.CheckPoint.Status.PASSED, **checkpoint_kwargs)
    try:
        with checkpoint.catch():
            raise checkpoint.FailureError(message)
    except checkpoint.FailureError as err:
        if testcase.soft_errors is not None:
            testcase.soft_errors.append(ErrorInfo.from_exception(err))
        else:
            raise


def warn_(message: str, testcase: 'TestCase' = None, **checkpoint_kwargs) -> NoReturn:
    """
    Add warning checkpoint.

    Parameters
    ----------
    message : str
        Would be saved as checkpoint name

    testcase : TestCase, optional
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.

    **checkpoint_kwargs:
        Used to construct a CheckPoint instance.
    """
    testcase = testcase or find_testcase_in_outer_frames()

    # default status should be PASSED, AssertionBuilder._err will only be called when error.
    checkpoint = _new_checkpoint(testcase, name=message, status=testcase.CheckPoint.Status.PASSED, **checkpoint_kwargs)
    with checkpoint.catch():
        raise checkpoint.WarningError(message)


def skip_(message: str) -> NoReturn:
    """
    Used to skip testcase.

    Parameters
    ----------
    message : str
        Used as message of SkippedError
    """
    raise SkippedError(message)


def assert_that(value,
                message: str = '',
                testcase: 'TestCase' = None,
                is_warning: bool = False,
                verbose: int = AssertionBuilder.VERBOSE,
                **checkpoint_kwargs
                ) -> AssertionBuilder:
    """
    Assert function
    reference: https://github.com/assertpy/assertpy

    Parameters
    ----------
    value:
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.

    message: str, optional
        Would be saved as checkpoint name

    testcase: TestCase, optional
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.

    is_warning: bool, optional
        Mark assertion as a warning checkpoint if failed.

    verbose: int, optional
        Additional log info.

    **checkpoint_kwargs:
        Used to construct a CheckPoint instance.
    """
    testcase = testcase or find_testcase_in_outer_frames()
    # default status should be PASSED, AssertionBuilder._err will only be called when error.
    checkpoint = _new_checkpoint(testcase, name=message, status=testcase.CheckPoint.Status.PASSED, **checkpoint_kwargs)

    kind = AssertionBuilder.Kind.WARN if is_warning else None
    if testcase.soft_errors is not None:
        kind = AssertionBuilder.Kind.SOFT
    builder = AssertionBuilder(checkpoint, testcase.soft_errors, verbose, value, message, kind)
    return builder


def assert_warn(value,
                message: str = '',
                testcase: 'TestCase' = None,
                verbose: int = AssertionBuilder.VERBOSE,
                **checkpoint_kwargs
                ) -> NoReturn:
    return assert_that(value, message, testcase, True, verbose, **checkpoint_kwargs)


class _AssertRaisesContext:
    """
    Assert raise context.
    Used to check the expected exception would be raised in context.

    Parameters
    ----------
    expected_exception: Exception class
        Specify the exception class which to be captured.

    message: str, optional
        Exception message.

    match_expr: str, optional
        Regexp string to be searched in error info.

    testcase: TestCase, optional
        Specify the testcase object to save the checkpoint.
        If not provided, the framework will try to find it in outer frames.
    """

    def __init__(self, expected_exception, message: str = '', match_expr: str = None, testcase: 'TestCase' = None):
        self.expected_exception = expected_exception
        self.message = message
        self.match_expr = match_expr
        self.error_info = None
        self.testcase = testcase or find_testcase_in_outer_frames()

    def __enter__(self):
        self.error_info = ErrorInfo.from_exception(None)
        return self.error_info

    def __exit__(self, *exc_info):
        checkpoint = _new_checkpoint(self.testcase, name=self.message, status=self.testcase.CheckPoint.Status.NONE)
        with checkpoint.catch():
            if exc_info[0] is None:
                msg = f"{self.message}, but no exception raised"
                raise checkpoint.UnexpectedSuccessError(msg)
            self.error_info.__init__(exc_info)
            suppress_exception = issubclass(self.error_info.type, self.expected_exception)
            if suppress_exception:
                if self.match_expr:
                    value = str(self.error_info.value)
                    if not re.search(self.match_expr, value):
                        msg = f"{self.message}, but pattern '{self.match_expr}' not found in '{value}'"
                        raise checkpoint.FailureError(msg)
                else:
                    checkpoint.error = self.error_info
            else:
                msg = f"{self.message}, but raise {self.error_info.type}"
                raise checkpoint.FailureError(msg)
        return suppress_exception


assert_raises = _AssertRaisesContext


class _SoftAssertionsContext:
    """
    Soft assertion context.
    The FailError would be raised only after whole context finished.

    Parameters
    ----------
    testcase: TestCase, optional
        Specify the testcase object to save the errors in context.
        If not provided, the framework will try to find it in outer frames.
    """

    def __init__(self, testcase: 'TestCase' = None):
        self.testcase = testcase or find_testcase_in_outer_frames()
        self._is_top_level = True

    def __enter__(self):
        if self.testcase.soft_errors is None:
            self.testcase.soft_errors = []
        else:
            self._is_top_level = False

        return self.testcase.soft_errors

    def __exit__(self, *exc_info):
        errors = self.testcase.soft_errors

        if self._is_top_level:
            self.testcase.soft_errors = None

        if exc_info[0] is None:
            pass
        elif exc_info[0] == AssertionError:
            info = ErrorInfo.from_exception(exc_info)
            errors.append(info)
            _new_checkpoint(self.testcase, name=exc_info[1], status=self.testcase.CheckPoint.Status.FAILED, error=info)
        else:
            error = ErrorInfo.from_exception(exc_info)
            logger.debug('encounter error: %s', error.trace)

        if errors:
            out = 'Soft assertion failures:'
            for index, error in enumerate(errors):
                out += f'\n{index+1}. {error.value}'
            logger.debug(out)

            if self._is_top_level:
                raise SoftAssertionsError(out)


soft_assertions = _SoftAssertionsContext
