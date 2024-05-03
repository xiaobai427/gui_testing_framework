# coding: utf-8

import os
import socket
import queue
import multiprocessing.queues
from multiprocessing import Lock
from urllib.parse import urljoin

from pathlib import Path
from typing import NoReturn, Union
from abc import ABCMeta, abstractmethod
from pprint import pformat

import kombu

from coupling import log
from .constants import IdType, FilePathType, DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT, CALLEE_KEY
from .events import (
    TestEventHandler,
    TestRunnerStartedEvent, TestRunnerStoppedEvent,
    TestSuiteStartedEvent,
    TestCaseStartedEvent, TestCaseStoppedEvent
)
from .case import TestCase, TestCaseResultRecord, ErrorInfo
from .environment import WorkEnv
from .suite import TestSuite
from .runner import TestRunner
from .consumer import BaseTestConsumer
from .serialization import json_dumps
from .util import get_current_process_name, str_class


import logging
import logging.handlers
logger = logging.getLogger(__name__)


RedisDBType = LogLevelType = Union[int, str]


class ThreadNamePrefixFilter(logging.Filter):
    def __init__(self, prefix=None, include_main=True):
        super().__init__()
        self.prefix = prefix
        self.include_main = include_main

    def filter(self, record):
        return self.prefix in record.threadName or self.include_main and record.threadName == "MainThread"


class BaseTestRunnerLogInterceptor(TestEventHandler, metaclass=ABCMeta):
    def __init__(self, log_level: LogLevelType, log_layout: str, log_filter: logging.Filter = None):
        super().__init__()
        self.log_level = log_level
        self.log_layout = log_layout
        self.log_filter = log_filter
        self._log_handler = None

    @abstractmethod
    def create_log_handler(self, runner_id: IdType) -> logging.Handler:
        pass

    def on_testrunner_started(self, event: TestRunnerStartedEvent) -> NoReturn:
        testrunner = event.target
        self._log_handler = self.create_log_handler(testrunner.id)
        log.add_log_handler(self._log_handler, self.log_level, self.log_layout, self.log_filter)

    def on_testrunner_stopped(self, event: TestRunnerStoppedEvent) -> NoReturn:
        if self._log_handler is not None:
            log.remove_log_handler(self._log_handler)
            self._log_handler = None


class TestRunnerLogFileInterceptor(BaseTestRunnerLogInterceptor):
    def __init__(self, log_dir: FilePathType, log_level: LogLevelType = DEFAULT_LOG_LEVEL,
                 log_layout: str = DEFAULT_LOG_LAYOUT, max_bytes=50000000, backup_count=99):
        super().__init__(log_level, log_layout)
        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.backup_count = backup_count

    def __str__(self):
        return f"<{self.__class__.__name__}(log_dir:{self.log_dir}, log_level:{self.log_level})>"

    def create_log_handler(self, runner_id) -> logging.handlers.RotatingFileHandler:
        os.makedirs(self.log_dir, exist_ok=True)
        filename = os.path.join(self.log_dir, str(runner_id) + ".log")
        return logging.handlers.RotatingFileHandler(filename, maxBytes=self.max_bytes,
                                                    backupCount=self.backup_count, delay=True)


class TestCaseLogFileInterceptor(TestEventHandler):
    _lock = Lock()

    def __init__(self,
                 log_dir: FilePathType,
                 log_level: LogLevelType = DEFAULT_LOG_LEVEL,
                 log_layout: str = DEFAULT_LOG_LAYOUT,
                 max_bytes: int = 50000000,
                 backup_count: int = 99,
                 postfix: str = "index"
                 ):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_level = log_level
        self.log_layout = log_layout
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.postfix = postfix
        self._consumer_log_dirs = {}

    def __str__(self):
        return f"<{self.__class__.__name__}(log_dir:{self.log_dir}, log_level:{self.log_level})>"

    @staticmethod
    def _gen_testsuite_log_dir(base_dir: Path, testsuite: TestSuite) -> Path:
        log_dir = base_dir.joinpath("%s" % testsuite.name.strip())
        return log_dir

    def on_testrunner_started(self, event: TestRunnerStartedEvent) -> NoReturn:
        testrunner: TestRunner = event.target
        testrunner.log_dir = self.log_dir

        for testsuite in getattr(testrunner, "_testsuites"):
            testsuite.log_dir = self._gen_testsuite_log_dir(testrunner.log_dir, testsuite)

        if isinstance(testrunner, BaseTestConsumer):
            testsuite = testrunner._testsuite
            self._consumer_log_dirs[get_current_process_name()] = testsuite.log_dir

    def on_testsuite_started(self, event: TestSuiteStartedEvent) -> NoReturn:
        testsuite: TestSuite = event.target

        # handle testsuite called by consumer
        if not testsuite.log_dir:
            testsuite.log_dir = self._consumer_log_dirs[get_current_process_name()].joinpath(testsuite.name)

        with self._lock:
            os.makedirs(testsuite.log_dir, exist_ok=True)
        for test in getattr(testsuite, "_tests"):
            if isinstance(test, TestCase):
                test.log_path = testsuite.log_dir.joinpath(test.eval_log_name(self.postfix))
            elif isinstance(test, TestSuite):
                test.log_dir = testsuite.log_dir.joinpath(test.name)
            else:
                raise ValueError

    def on_testcase_started(self, event: TestCaseStartedEvent) -> NoReturn:
        testcase: TestCase = event.target

        # If test runner is consumer, should output consumed test into consumer dir.
        if not testcase.log_path:
            log_dir = self._consumer_log_dirs[get_current_process_name()]
            testcase.log_path = log_dir.joinpath(testcase.eval_log_name(self.postfix))

        if hasattr(testcase, "log_handler"):
            logger.error("%s already has log handler %s", testcase, testcase.log_handler)

        testcase.log_handler = logging.handlers.RotatingFileHandler(str(testcase.log_path),
                                                                    maxBytes=self.max_bytes,
                                                                    backupCount=self.backup_count,
                                                                    delay=True)
        log.add_log_handler(testcase.log_handler, self.log_level, self.log_layout,
                            ThreadNamePrefixFilter(testcase.log_path.stem))

    def on_testcase_stopped(self, event: TestCaseStoppedEvent) -> NoReturn:
        testcase: TestCase = event.target
        log_handler = getattr(testcase, "log_handler", None)
        if log_handler:
            log.remove_log_handler(log_handler)


class TestRecordAmqpInterceptor(TestEventHandler):
    ROUTING_KEY_TEMPLATE = "runner.{}.record.{}"

    def __init__(self, url: str, log_base_dir, exchange_name: str, exchange_type: str = "topic", heartbeat=60):
        super().__init__()
        self.url = url
        self.exchange_name = exchange_name
        self.exchange_type = exchange_type
        self.heartbeat = heartbeat
        self.log_base_dir = log_base_dir
        self._conn = None
        self._producer = None
        self._runner_id = None

    def __str__(self):
        return f"<{self.__class__.__name__}(url:{self.url}, exchange:{self.exchange_name})>"

    def on_testrunner_started(self, event: TestRunnerStartedEvent) -> NoReturn:
        testrunner = event.target       # type: TestRunner
        self._conn = kombu.Connection(self.url, heartbeat=self.heartbeat, transport_options={'confirm_publish': True})
        exchange = kombu.Exchange(self.exchange_name, self.exchange_type, channel=self._conn, durable=True)
        exchange.declare()
        self._producer = self._conn.Producer(exchange=exchange, auto_declare=False)
        self._runner_id = testrunner.id

    def on_testrunner_stopped(self, event: TestRunnerStoppedEvent) -> NoReturn:
        logger.debug("Release %s for TestRecordAmqpInterceptor", self._conn)
        if self._conn is not None:
            self._conn.release()

    def on_testcase_stopped(self, event: TestCaseStoppedEvent) -> NoReturn:
        testcase = event.target         # type: TestCase
        self.publish_record(testcase.record)

    def publish_record(self, record: TestCaseResultRecord):
        if record.error and record.error.type_ == str_class(KeyboardInterrupt):
            logger.warning("Don't publish test record when KeyboardInterrupt, because testcase will be requeued.")
            return

        d = record.dict(exclude={
            CALLEE_KEY: ...,
            "checkpoints": {
                "__all__": {CALLEE_KEY}
            }
        })

        error = d["error"]
        if error is not None:
            d["error"] = error["trace"]

        d["duration"] = int(record.duration * 1000) if record.duration else None
        d["git_commit"] = WorkEnv.instance().get_current_commit()

        if record.log_path:
            if record.log_path.is_absolute():
                log_url_path = record.log_path.relative_to(os.path.abspath(self.log_base_dir)).as_posix()
            else:
                log_url_path = record.log_path.as_posix()
            d["extras"]["log_url"] = urljoin(f"http://{socket.gethostname()}", log_url_path)
        else:
            d["extras"]["log_url"] = None

        s = json_dumps(d)
        routing_key = self.ROUTING_KEY_TEMPLATE.format(self._runner_id, record.id)
        logger.debug("AMQP publishing: -> %s -> routing_key(%s), data: \n%s", self.exchange_name, routing_key, s)
        self._producer.publish(s,
                               routing_key=routing_key,
                               retry=True,
                               delivery_mode=2,
                               content_type="application/json",
                               content_encoding="utf-8")
        logger.debug("AMQP published: -> %s -> routing_key(%s)", self.exchange_name, routing_key)


class TestRecordQueueInterceptor(TestEventHandler):
    def __init__(self, queue: queue.Queue | multiprocessing.queues.Queue):
        super().__init__()
        self.queue = queue

    def on_testcase_stopped(self, event: TestCaseStoppedEvent) -> NoReturn:
        testcase = event.target         # type: TestCase
        record = testcase.record
        logger.debug("SEND: %s", record)
        self.queue.put(record)

    def __str__(self):
        return f"<{self.__class__.__name__}(queue:{self.queue})>"
