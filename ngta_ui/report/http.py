# coding: utf-8

import os
from typing import ClassVar
from .base import TestReport


CURRENT_DIR = os.path.dirname(__file__)


class HttpTestReport(TestReport):
    STYLE: ClassVar = "http"
    TEMPLATE: ClassVar = os.path.join(CURRENT_DIR, "html", f"{STYLE}.html")
