# coding: utf-8

from abc import ABCMeta
from selenium.webdriver import Remote as RemoteWebDriver
from uuid import uuid1

from ngta import TestCase as BaseTestCase
from .bench import TestBench

import logging
logger = logging.getLogger(__name__)


class TestCase(BaseTestCase, metaclass=ABCMeta):
    @property
    def testbench(self) -> TestBench:
        return self.context.testbench

    @property
    def webdriver(self) -> RemoteWebDriver:
        return self.testbench.webdriver

    def screenshot(self, filename=None):
        filename = filename or self.log_path.with_name(f'{self.get_default_name()}_screen_{uuid1().hex}.png')
        self.webdriver.save_screenshot(filename)
        return filename
