# coding: utf-8

from abc import ABCMeta, abstractmethod
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver import Remote as RemoteWebDriver, ActionChains
from selenium.webdriver.remote.webelement import WebElement as BaseWebElement


class BasePage:
    DEFAULT_TIMEOUT = 10

    def __init__(self, webdriver):
        self.webdriver = webdriver        # type: RemoteWebDriver
        # WebDriverWait(webdriver, timeout).until(
        #     lambda drv: drv.execute_script('return document.readyState') == 'complete'
        # )

    def wait_until(self, target, timeout=DEFAULT_TIMEOUT):
        if callable(target):
            WebDriverWait(self.webdriver, timeout).until(target)
        else:
            WebDriverWait(self.webdriver, timeout).until(lambda driver: driver.find_element(*target))

    def move_to(self, locator):
        element = self.webdriver.find_element(locator)
        ActionChains(self.webdriver).move_to_element(element).perform()

    def scroll_to_bottom(self):
        self.webdriver.execute_script('window.scrollTo(0, document.body.scrollHeight)')

    def find_element_by_locator(self, locator, timeout=DEFAULT_TIMEOUT, callback=None):
        if timeout:
            target = callback if callback else locator
            self.wait_until(target, timeout)
        return self.webdriver.find_element(*locator)

    def find_elements_by_locator(self, locator, timeout=DEFAULT_TIMEOUT, callback=None):
        if timeout:
            target = callback if callback else locator
            self.wait_until(target, timeout)
        return self.webdriver.find_elements(*locator)


class BaseElement(metaclass=ABCMeta):
    @property
    @abstractmethod
    def locator(self):
        pass

    def __get__(self, page: BasePage, owner) -> BaseWebElement:
        return page.find_element_by_locator(self.locator)


class BaseTextElement(BaseElement, metaclass=ABCMeta):
    class WebElement(BaseWebElement):
        def __init__(self, locator, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._locator = locator

        def set(self, value):
            WebDriverWait(self.parent, BasePage.DEFAULT_TIMEOUT).until(
                lambda driver: driver.find_element(*self._locator).is_displayed()
            )
            element = self.parent.find_element(*self._locator)
            element.clear()
            element.send_keys(value)

        def get(self):
            WebDriverWait(self.parent, BasePage.DEFAULT_TIMEOUT).until(
                lambda driver: driver.find_element(*self._locator).is_displayed()
            )
            element = self.parent.find_element(*self._locator)
            return element.get_attribute("value")

    def __get__(self, page: BasePage, owner) -> 'BaseTextElement.WebElement':
        element = page.find_element_by_locator(self.locator)
        return self.WebElement(self.locator, element.parent, element.id, element._w3c)


class BaseSelectElement(BaseElement, metaclass=ABCMeta):
    class WebElement(BaseWebElement):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def as_select(self):
            return Select(self)

        def __getattr__(self, item):
            select = self.as_select()
            return getattr(select, item)

    def __get__(self, page: BasePage, owner) -> 'BaseSelectElement.WebElement':
        element = page.find_element_by_locator(self.locator)
        return self.WebElement(element.parent, element.id, element._w3c)


def get_locator(by, value=None):
    if isinstance(by, (list, tuple)):
        locator = by
    else:
        locator = (by, value)
    return locator


def elem(by, value=None) -> BaseElement:
    element_cls = type('CommonElement', (BaseElement, ), dict(locator=get_locator(by, value)))
    return element_cls()


def select(by, value=None) -> BaseSelectElement:
    element_cls = type('SelectElement', (BaseSelectElement, ), dict(locator=get_locator(by, value)))
    return element_cls()


def text(by, value=None) -> BaseTextElement:
    element_cls = type('TextElement', (BaseTextElement, ), dict(locator=get_locator(by, value)))
    return element_cls()
