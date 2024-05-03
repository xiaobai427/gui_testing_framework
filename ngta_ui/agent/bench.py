# coding: utf-8

import socket
import pydantic
from typing import List, Optional
from ..bench import TestBench as BaseTestBench, TestBenchRecord as BaseTestBenchRecord


class TestBenchState:
    OFFLINE = 0b00
    IDLE = 0b01
    BUSY = 0b11
    RESERVED = 0b100


class TestBenchRecord(BaseTestBenchRecord):
    hostname: str
    group: Optional[str] = None
    workers: int
    queues: List[dict] = pydantic.Field(default_factory=list)
    state: int = TestBenchState.IDLE


class TestBench(BaseTestBench):
    _BASE_QUEUE_TEMPLATE = "bench.{}"
    Record = TestBenchRecord
    State = TestBenchState

    def __init__(self,
                 group: str = None,
                 workers: int = 1,
                 state: int = TestBenchState.IDLE,
                 consumer_timeout: int = None,
                 consumer_prefetch_count: int = 1,
                 consumer_priority_strategy: int = 1,       # 0: kombu.Consumer    1: DryIndexedQueueConsumer
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hostname = socket.gethostname()
        self.group = group      # usually used for hardware test scenario.
        self.workers = workers
        self.state = state      # FIXME: updated only when AmqpTestConsumerProcess.is_busy is invoked.
        self.consumer_timeout = consumer_timeout
        self.consumer_prefetch_count = consumer_prefetch_count
        self.consumer_priority_strategy = consumer_priority_strategy
        self.dlx_routing_key = self._BASE_QUEUE_TEMPLATE.format(self.type)
        self.queues = []

    def get_queue_names(self) -> List[str]:
        queue_names = []
        common_queue_name = self.dlx_routing_key

        queue_names.append(f"{common_queue_name}.{self.name}")

        if self.group:
            common_queue_name += f".{self.group}"

        for route in self.routes:
            queue_name = ".".join((common_queue_name, route))
            queue_names.append(queue_name)

        queue_names.append(common_queue_name)
        return queue_names

    def on_agent_exec_test_begin(self, test, config: dict):
        """
        A hook method, which will be invoked before running test.
        :param test: TestSuite | TestCase
        :param config: dict, the structure is customized.
        :return:
        """
        pass

    def on_agent_exec_test_end(self, test, config: dict):
        """
        A hook method, which will be invoked after running test.
        :param test: TestSuite | TestCase
        :param config: dict, the structure is customized.
        :return:
        """
        pass


class FakeTestBench(TestBench):
    def get_queue_names(self) -> List[str]:
        return []

    def as_record(self):
        return None
