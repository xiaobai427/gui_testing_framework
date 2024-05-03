# coding: utf-8

import enum
import uuid
import logging
from pathlib import Path
from typing import Union

PACKAGE_NAME = "ngta"

IdType = Union[int, str, uuid.UUID]
FilePathType = Union[str, Path]

SETUP_MODULE_NAME = "setup_module"
SETUP_CLASS_NAME = "setup_class"
SETUP_METHOD_NAME = "setup"

TEARDOWN_MODULE_NAME = "teardown_module"
TEARDOWN_CLASS_NAME = "teardown_class"
TEARDOWN_METHOD_NAME = "teardown"

DEFAULT_HTML_REPORT_BASENAME = "report.html"
DEFAULT_JSON_REPORT_BASENAME = "report.json"

CASE_DIR_BASENAME = 'cases'
LIBS_DIR_BASENAME = 'lib'
CONF_DIR_BASENAME = 'conf'
LOGS_DIR_BASENAME = 'logs'
INIT_DIR_BASENAME = 'init'

CACHE_YML_BASENAME = '.cache'

DEFAULT_LOG_BASENAME = "main.log"
DEFAULT_LOG_LEVEL = logging.DEBUG
DEFAULT_LOG_LAYOUT = "%(asctime)-15s [%(levelname)-8s] %(processName)-12s %(threadName)-12s " \
                                     "[%(name)20s:%(lineno)4d] - %(message)s"

YML_OBJECT_NEW_TAG = "!object:new"
YML_OBJECT_LOCATE_TAG = "!object:locate"
CALLEE_KEY = "()"


class ExitCode(enum.IntEnum):
    OK = 0                      # all tests passed
    TESTS_FAILED = 1            # tests failed
    TESTS_ERROR = 2             # tests error
    TESTS_WARNING = 3           # tests warning
    INTERRUPTED = 4             # was interrupted by user
    UNKNOWN_EXCEPTION = 5       # an internal error during test
    USAGE_ERROR = 6             # command-line misused
    NO_TESTS_COLLECTED = 7      # can't find tests
    ALL_TESTS_NOT_RUN = 8       # all tests not run
    ALL_TESTS_SKIPPED = 9       # all tests skipped
