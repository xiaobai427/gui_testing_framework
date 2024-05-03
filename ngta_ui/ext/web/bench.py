# coding: utf-8

from selenium import webdriver
from ngta.bench import TestBench as BaseTestBench


class TestBench(BaseTestBench):
    def __init__(self,
                 name: str,
                 type: str,
                 browser: str,
                 executable_path: str = None,
                 options=None,
                 url: str = None,
                 auto_close: bool = False):
        super().__init__(name, type)
        self.browser = browser
        self.executable_path = executable_path
        self.options = options
        self.webdriver = None
        self.url = url
        self.auto_close = auto_close

    def on_testrunner_started(self, event):
        kwargs = dict(
            options=self.options,
        )
        if self.executable_path:
            kwargs['executable_path'] = self.executable_path
        self.webdriver = getattr(webdriver, self.browser)(**kwargs)      # type: webdriver.Remote
        if self.url:
            # self.webdriver.implicitly_wait(10)
            self.webdriver.get(self.url)
            self.webdriver.maximize_window()

    def on_testrunner_stopped(self, event):
        if self.auto_close and self.url:
            self.webdriver.close()
            self.webdriver = None
