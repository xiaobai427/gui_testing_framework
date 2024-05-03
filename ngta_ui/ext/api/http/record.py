# coding: utf-8

from ngta.record import TestCaseResultRecord
from coupling.dict import omit
import datetime


class Request:
    def __init__(self):
        self.method = ""
        self.url = ""
        self.netloc = ""
        self.path = ""
        self.params = {}
        self.headers = {}
        self.body = None

    def as_dict(self):
        d = self.__dict__
        d['headers'] = dict(self.headers)
        return d


class Response:
    def __init__(self):
        self.status_code = None
        self.reason = None
        self.headers = {}
        self.body = None
        self.elapsed = datetime.timedelta(0)

    def as_dict(self):
        d = self.__dict__
        d['headers'] = dict(self.headers)
        d['elapsed'] = self.elapsed.total_seconds()
        return d


class HttpApiTestCaseResultRecord(TestCaseResultRecord):
    Request = Request
    Response = Response

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.histories = []
        self.request_line = ''

    def as_dict(self):
        d = super().as_dict()
        histories = []
        for history in self.histories:
            histories.append((history[0].as_dict(), history[1].as_dict()))

        d['extras'] = {
            'request_line': self.request_line,
            'histories': histories
        }
        return omit(d, 'histories', 'request_line')
