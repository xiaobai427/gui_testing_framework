# coding: utf-8

import time
import queue
import multiprocessing.queues

from typing import NoReturn
from abc import ABCMeta, abstractmethod

from .runner import TestRunner
from .suite import TestSuite, TestModelType

import logging
logger = logging.getLogger(__name__)


class BaseTestConsumer(TestRunner, metaclass=ABCMeta):
    """
    Base consumer class.
    Subclass must implement method: _consume()

    Parameters
    ----------
    *args,  **kwargs:
        pass-through to TestRunner
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args,  **kwargs)
        self._testsuite = TestSuite()

    def _run_tests(self):
        self._consume()

    @abstractmethod
    def _consume(self):
        pass


class QueueTestConsumer(BaseTestConsumer):
    """
    Consume test from Queue.

    Parameters
    ----------
    queue: queue.Queue or multiprocessing.queues.JoinableQueue
        The queue consume from.

    auto_stop: bool, optional
        Auto stop when queue is empty.

    *args,  **kwargs:
        pass-through to TestRunner
    """

    def __init__(self,
                 queue: queue.Queue | multiprocessing.queues.JoinableQueue,
                 auto_stop: bool = True,
                 *args, **kwargs):
        super().__init__(*args,  **kwargs)
        self.queue = queue
        self.auto_stop = auto_stop

    def _consume(self) -> NoReturn:
        while True:
            try:
                data: TestModelType = self.queue.get_nowait()
            except queue.Empty:
                if self.auto_stop:
                    break
            else:
                try:
                    test = data.as_test()
                    if test:
                        # self._testsuite.add_test(test)
                        self._testsuite.run_test(test, self.result)
                except Exception as err:
                    logger.exception(err)
                finally:
                    self.queue.task_done()
            finally:
                if self.result.should_abort:
                    break
                else:
                    while self.result.should_pause:
                        time.sleep(self.result.PAUSE_INTERVAL)
