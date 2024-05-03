# coding: utf-8

from ngta import TestBench as BaseTestBench

import logging
logger = logging.getLogger(__name__)


class TestBench(BaseTestBench):
    def __init__(self):
        super().__init__("bench_name", "bench_type")

    def on_testrunner_started(self, event):
        logger.info("%s handle %s start", self, event)

    def on_testrunner_stopped(self, event):
        logger.info("%s handle %s start", self, event)

    def on_testsuite_started(self, event):
        logger.info("%s handle %s start", self, event)

    def on_testsuite_stopped(self, event):
        logger.info("%s handle %s start", self, event)

    def on_testcase_started(self, event):
        logger.info("%s handle %s start", self, event)

    def on_testcase_stopped(self, event):
        logger.info("%s handle %s start", self, event)
