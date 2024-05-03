# coding: utf-8

from ngta import TestCase, tag, test, parametrize, main
from ngta.assertions import assert_raises

import logging
logger = logging.getLogger(__name__)


def setup_module():
    logger.debug("setup_module")


def teardown_module():
    logger.debug("teardown_module")


def test_function():
    with assert_raises(NotImplementedError, "should raise NotImplementedError") as error_info:
        pass


class EqualTestCase(TestCase):
    @classmethod
    def setup_class(cls):
        logger.debug("setup_class")

    @classmethod
    def teardown_class(cls):
        logger.debug("teardown_class")

    def setup(self):
        logger.debug("setup")

    def teardown(self):
        logger.debug("teardown")

    @tag("regression")
    @test(u"Test {value1} equal with {value2}")
    def test_int(self, value1=1, value2=1):
        msg = "value1 should equal with value2."
        self.assert_that(value1, msg).is_equal_to(value2)

    @test
    @parametrize([(1, 1), (1, 2), (1, 3)])
    def test_parametrize(self, value1, value2):
        self.assert_that(value1).is_equal_to(value2)

    def test_soft_assertions(self):
        with self.soft_assertions():
            self.assert_that(1, "checkpoint1").is_equal_to(1)
            self.assert_that(1, "checkpoint2").is_equal_to(2)
            self.assert_that(1, "checkpoint3").is_equal_to(1)


if __name__ == "__main__":
    from bench import TestBench
    from listener import observable
    main(testbench=TestBench(), event_observable=observable)
