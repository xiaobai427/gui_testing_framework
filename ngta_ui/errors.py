# coding: utf-8

import os
import inspect
import traceback
from typing import Optional
from .serialization import BaseModel
from .mark import RerunDecorator
from .constants import PACKAGE_NAME
from .environment import WorkEnv
from .util import str_class


import logging
logger = logging.getLogger(__name__)


class Error(Exception):
    pass


class ConfigError(Error):
    pass


class ArgumentError(Error):
    pass


class SerializeError(Error):
    pass


class DeserializeError(Error):
    pass


class FailureError(Error):
    pass


class UnexpectedSuccessError(FailureError):
    pass


class SoftAssertionsError(FailureError):
    pass


class WarningError(Error):
    pass


class SkippedError(Error):
    pass


class HookError(Error):
    pass


class HookBeginError(HookError):
    pass


class HookEndError(HookError):
    pass


class FixtureError(HookError):
    pass


class ReportTemplateNotExistsError(Exception):
    pass


def is_relevant_call(f_code) -> bool:
    is_relevant = True
    if f_code.co_name in ("<module>", "__exit__"):
        is_relevant = False

    co_filename = os.path.normpath(f_code.co_filename)
    if PACKAGE_NAME in co_filename or co_filename.endswith("runpy.py"):
        is_relevant = False

    work_dir = WorkEnv.instance().work_dir
    if work_dir and str(work_dir) not in co_filename:
        is_relevant = False

    return is_relevant


class ErrorInfo(BaseModel):
    type_: Optional[str] = None
    value: Optional[str] = None
    trace: Optional[str] = None
    scope: Optional[int] = RerunDecorator.Scope.METHOD.value

    @classmethod
    def from_exception(cls, err: BaseException | tuple | str = None):
        scope = RerunDecorator.Scope.METHOD.value
        if err is None or isinstance(err, str):
            type_ = None
            value = None
            trace = err
        else:
            if isinstance(err, BaseException):
                exc_info = (type(err), err, err.__traceback__)
            else:
                exc_info = err
            type_ = str_class(exc_info[0])
            value = str(exc_info[1])
            trace = cls.exc_info_to_string(exc_info)

            for frame, line_no in traceback.walk_stack(exc_info[2].tb_frame):
                f_code = frame.f_code
                # logger.debug("%s: %s, %s", f_code.co_filename, f_code.co_name, is_relevant_call(f_code))
                if is_relevant_call(f_code):
                    match f_code.co_name:
                        case "setup":
                            scope = RerunDecorator.Scope.SETUP.value
                        case "teardown":
                            scope = RerunDecorator.Scope.TEARDOWN.value
                        case _:
                            scope = RerunDecorator.Scope.METHOD.value

        return cls(type_=type_, value=value, trace=trace, scope=scope)

    def __str__(self) -> str:
        return self.trace

    @classmethod
    def exc_info_to_string(cls, exc_info) -> str:
        """
        If exception is FailureError or WarningError, only return relevant stack traces.
        otherwise, return all stack traces.

        Parameters
        ----------
        exc_info : tuple
            should a tuple return by sys.exc_info()


        Returns
        -------
        str:
            string include exception traceback.
        """
        exc_class = exc_info[0]
        exc_value = exc_info[1]
        exc_trace = exc_info[2]

        exc_line = traceback.format_exception_only(exc_class, exc_value)
        if issubclass(exc_class, (FailureError, WarningError)):
            title = "Traceback (relevant call)"
            stack_traces = []
            for frame, line_no in traceback.walk_stack(exc_trace.tb_frame):
                f_code = frame.f_code
                if is_relevant_call(f_code):
                    co_filename = os.path.normpath(f_code.co_filename)
                    source, _ = inspect.findsource(frame)
                    template = '  File "{co_filename}", line {line_number}, in {co_name}\n    {line_content}'
                    trace = template.format(co_filename=co_filename, line_number=line_no,
                                            co_name=f_code.co_name, line_content=source[frame.f_lineno-1].strip())
                    stack_traces.append(trace)
            return "{}:\n{}\n{}".format(title, "\n".join(stack_traces), "".join(exc_line))
        else:
            return cls._dump_all_traceback(exc_trace, exc_line)

    @classmethod
    def _dump_all_traceback(cls, tb, exc_line):
        title = "Traceback"
        stack_traces = traceback.extract_tb(tb)
        return "{}:\n{}{}".format(title, "".join(traceback.format_list(stack_traces)), "".join(exc_line))
