# coding: utf-8

import os
from multiprocessing import Lock
from pathlib import Path
from typing import NoReturn
from coupling import log
from ..case import TestCase, remove_path_illegal_chars
from ..suite import TestSuite
from ..runner import TestRunner
from ..constants import DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT, FilePathType
from ..events import (
    TestEventHandler,
    TestRunnerStartedEvent, TestRunnerStoppedEvent,
    TestSuiteStartedEvent,
    TestCaseStartedEvent, TestCaseStoppedEvent
)
from ..interceptor import ThreadNamePrefixFilter, LogLevelType

import logging
import logging.handlers
logger = logging.getLogger(__name__)


class LoggerNamePrefixFilter(logging.Filter):
    def __init__(self, prefix):
        super().__init__()
        self.prefix = prefix

    def filter(self, record):
        return record.name.startswith(self.prefix)


class TestLogFileInterceptor(TestEventHandler):
    _lock = Lock()

    def __init__(self, log_dir: FilePathType, log_level: LogLevelType = DEFAULT_LOG_LEVEL,
                 log_layout: str = DEFAULT_LOG_LAYOUT, max_bytes=50000000, backup_count=99):
        super().__init__()
        self.log_level = log_level
        self.log_layout = log_layout
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._main_log_handler = None
        self._main_log_dir = None

        self._pipe_log_handler = None
        self._pipe_log_name = "ngta.concurrent.ControlThread"

    def __str__(self):
        return f"<{self.__class__.__name__}(log_dir:{self.log_dir}, log_level:{self.log_level})>"

    def on_testrunner_started(self, event: TestRunnerStartedEvent) -> NoReturn:
        testrunner: TestRunner = event.target
        testbench = testrunner.context.testbench
        bench_type = testbench.type
        self._main_log_dir = self.log_dir.joinpath(bench_type, str(testrunner.id))
        os.makedirs(self._main_log_dir, exist_ok=True)

        self._main_log_handler = logging.handlers.RotatingFileHandler(
            self.log_dir.joinpath(self._main_log_dir, "main.log"),
            maxBytes=self.max_bytes, backupCount=self.backup_count, delay=True
        )
        log.add_log_handler(self._main_log_handler, self.log_level, self.log_layout)

        self._pipe_log_handler = logging.handlers.RotatingFileHandler(
            self.log_dir.joinpath(self._main_log_dir, "pipe.log"),
            maxBytes=self.max_bytes, backupCount=self.backup_count, delay=True
        )
        pipe_logger = log.add_log_handler(
            self._pipe_log_handler, self.log_level, self.log_layout,
            LoggerNamePrefixFilter(self._pipe_log_name), self._pipe_log_name
        )
        pipe_logger.propagate = False

    def on_testrunner_stopped(self, event: TestRunnerStoppedEvent) -> NoReturn:
        if self._pipe_log_handler is not None:
            log.remove_log_handler(self._pipe_log_handler, self._pipe_log_name)
            self._pipe_log_handler = None

        if self._main_log_handler is not None:
            log.remove_log_handler(self._main_log_handler)
            self._main_log_handler = None

    def on_testsuite_started(self, event: TestSuiteStartedEvent) -> NoReturn:
        testsuite: TestSuite = event.target

        if not testsuite.log_dir:
            testsuite.log_dir = self._main_log_dir.joinpath(
                remove_path_illegal_chars(f"${testsuite.id}_{testsuite.name}")
            )

        with self._lock:
            os.makedirs(testsuite.log_dir, exist_ok=True)
        for test in getattr(testsuite, "_tests"):
            if isinstance(test, TestCase):
                test.log_path = testsuite.log_dir.joinpath(test.eval_log_name("ident", False))
            elif isinstance(test, TestSuite):
                test.log_dir = testsuite.log_dir.joinpath(remove_path_illegal_chars(f"${test.id}_{test.name}"))
            else:
                raise ValueError

    def on_testcase_started(self, event: TestCaseStartedEvent) -> NoReturn:
        testcase: TestCase = event.target

        if not testcase.log_path:
            testcase.log_path = self._main_log_dir.joinpath(testcase.eval_log_name("ident", False))

        testcase.log_handler = logging.handlers.RotatingFileHandler(
            str(testcase.log_path), maxBytes=self.max_bytes, backupCount=self.backup_count, delay=True
        )
        log.add_log_handler(testcase.log_handler, self.log_level, self.log_layout,
                            ThreadNamePrefixFilter(testcase.log_path.stem))

    def on_testcase_stopped(self, event: TestCaseStoppedEvent) -> NoReturn:
        testcase: TestCase = event.target
        log_handler = getattr(testcase, "log_handler", None)
        if log_handler:
            log.remove_log_handler(log_handler)
