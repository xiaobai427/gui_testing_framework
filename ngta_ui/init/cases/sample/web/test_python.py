# coding: utf-8

from ngta import test
from ngta.ext.web import TestCase, BasePage, By, Keys

import logging
logger = logging.getLogger(__name__)


class Locators:
    pypi=(By.CSS_SELECTOR, '.pypi-meta > a')


class MainPage(BasePage):
    def goto_pypi(self):
        self.webdriver.find_element(*Locators.pypi).click()


class PythonTest(TestCase):
    @test
    def test(self):
        MainPage(self.webdriver).goto_pypi()
        element = self.webdriver.find_element_by_id('search')
        element.clear()
        element.send_keys('ngta')
        element.send_keys(Keys.ENTER)
