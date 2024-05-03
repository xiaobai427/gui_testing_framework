# coding: utf-8

import uuid
from typing import NoReturn, Optional, List

from .events import TestEventHandler
from .serialization import BaseModel
from .util import pick, str_class

import logging
logger = logging.getLogger(__name__)


class TestBenchRecord(BaseModel):
    name: str
    type: str
    node: str
    exclusive: bool
    routes: List[str]

    @property
    def path(self):
        return str_class(self.__class__)

    def dict(self, **kwargs):
        d = super().dict(**kwargs)
        exclude = kwargs.get('exclude') or {}
        if 'path' not in exclude:
            d['path'] = self.path
        return d


class TestBench(TestEventHandler):
    """
    Used to store test resource in whole test life cycle.
    It inherit from TestEventHandler, so any hook methods are supported.

    Parameters
    ----------
    name: str
        test bench name

    type: str
        test bench type, could be set as product or project name.

    exclusive: bool, optional
        Set according to relevance with hardware.
        If is True, a test bench can only be used for one test process.

    routes: tuple or list, optional
        Used by integrating with test platform.
        This testbench will only consume messages with specified routes from RabbitMQ.

    node: str, optional
        The machine info which testbench running on
    """
    Record = TestBenchRecord

    def __init__(self,
                 name: str,
                 type: str,
                 exclusive: bool = False,
                 routes: list | tuple | str = None,
                 node: str = None
                 ):
        super().__init__()
        self.name = name
        self.type = type
        self.node = node or f'{uuid.getnode():x}'
        self.exclusive = exclusive
        if isinstance(routes, str):
            self.routes = self.get_routes_from_string(routes)
        else:
            self.routes = routes or []

    @staticmethod
    def get_routes_from_string(s: str, separator: str = ",") -> Optional[List[str]]:
        """
        Parse routes from string.

        Parameters
        ----------
        s: str
            routes string

        separator: str, optional
            separator char, default is ','

        Returns
        -------
        list or None
            list include separated routes string, or None if provided parameter s is empty.
        """
        if s:
            return [route.strip() for route in s.split(separator)]
        else:
            return None

    def open(self) -> NoReturn:
        """
        Hook method for opening testbench.
        """
        pass

    def close(self) -> NoReturn:
        """
        Hook method for closing testbench.
        """
        pass

    def __str__(self):
        return f'<TestBench(name:{self.name}, type:{self.type})>'

    def as_record(self):
        d = pick(self.__dict__, keys=self.Record.model_fields.keys())
        return self.Record(**d)
