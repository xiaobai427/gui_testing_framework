# coding: utf-8

from tornado import web, escape
from ngta.serialization import json_dumps
from typing import Union


class BaseResource(web.RequestHandler):
    def json(self):
        content_type = self.request.headers.get("Content-Type", "")
        content_length = self.request.headers.get("Content-Length", -1)
        if 'application/json' in content_type and 0 < int(content_length):
            return escape.json_decode(self.request.body)
        return None

    def write(self, chunk):
        if self._finished:
            raise RuntimeError("Cannot write() after finish()")
        if isinstance(chunk, dict) or isinstance(chunk, list):
            chunk = json_dumps(chunk).replace("</", "<\\/")
            self.set_header("Content-Type", "application/json; charset=UTF-8")
        chunk = escape.utf8(chunk)
        self._write_buffer.append(chunk)

    def data_received(self, chunk):
        pass

    def finish(self, chunk: Union[str, bytes, dict, list] = None):
        return super().finish(chunk)
