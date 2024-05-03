# coding: utf-8

import json
import json.decoder
import typing
import requests
from urllib.parse import urlsplit

from ngta.bench import TestBench as BaseTestBench
from ngta.ext.database import HelperFactory, Helpers
from ngta.serialization import pformat_json
from .record import HttpApiTestCaseResultRecord


import logging
logger = logging.getLogger(__name__)


class RequestsSession(requests.Session):
    def __init__(self, record: HttpApiTestCaseResultRecord = None):
        super().__init__()
        self.record = record

    @staticmethod
    def _pformat(headers):
        return "\n".join([f"{key}: {value}" for key, value in headers.items()])

    def send(self, request, **kwargs):
        resp = super().send(request, **kwargs)

        send_body = resp.request.body if resp.request.body else ""

        try:
            recv_body = pformat_json(resp.json())
        except ValueError:
            recv_body = resp.text if resp.text else ""
        logger.debug("Http Request: %s %s\n%s\n\n%s\n",
                     resp.request.method, resp.request.url, self._pformat(resp.request.headers), send_body)
        logger.debug("Http Response: \n%s\n\n%s", self._pformat(resp.headers), recv_body)

        if self.record is not None:
            pair = [self.record.Request(), self.record.Response()]
            self.record.histories.append(pair)

            parts = urlsplit(resp.request.url)
            pair[0].url = resp.request.url
            pair[0].netloc = parts[1]
            pair[0].path = parts[2]
            pair[0].method = resp.request.method
            pair[0].headers = resp.request.headers
            pair[0].params = parts[4]
            pair[0].body = self._pformat_body(resp.request.body)

            pair[1].url = resp.url
            pair[1].status_code = resp.status_code
            pair[1].reason = resp.reason
            pair[1].headers = resp.headers
            pair[1].body = self._pformat_body(resp.text)
            pair[1].elapsed = resp.elapsed

        return resp

    @classmethod
    def _pformat_body(cls, body=None):
        if body:
            try:
                data = json.loads(body)
                return pformat_json(data)
            except ValueError:
                pass
        return body

    def __getstate__(self):
        state = super().__getstate__()
        state['record'] = self.record
        return state


class TestBench(BaseTestBench):
    def __init__(self, name: str, type: str, base_url: str, databases: typing.Sequence[dict] = None, **kwargs):
        super().__init__(name, type, **kwargs)
        self.session = RequestsSession()
        self.base_url = base_url
        self.databases = databases or ()
        self.db_helpers = None          # type: Helpers
        self._current_record = None

    def new_http_session(self):
        return RequestsSession(self._current_record)

    def on_testrunner_started(self, event):
        """
        init db_helpers when testrunner started.
        """
        self.db_helpers = HelperFactory.new_helpers(self.databases)

    def on_testcase_started(self, event):
        """
        set current testcase's record, so http session can store request and response into record automatically.
        """
        testcase = event.target
        self._current_record = testcase.record
        self.session.record = testcase.record

    def on_testcase_stopped(self, event):
        """
        It may send multiple http requests during testing. Find the target test request.
        """
        testcase = event.target
        record = testcase.record    # type: HttpApiTestCaseResultRecord
        record.request_line = testcase.PATH
        for history in record.histories:
            if testcase.PATH in history[0].path:
                record.request_line = f'{history[0].method.upper()} {record.request_line}'
                break
