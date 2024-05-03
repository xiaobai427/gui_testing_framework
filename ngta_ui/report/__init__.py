# coding: utf-8

from .base import TestReport, BaseTestReport, ECHARTS_JS_PATH
from .http import HttpTestReport


def new_report(style=None, **kwargs):
    if style == TestReport.STYLE or style is None:
        return TestReport(**kwargs)
    elif style == HttpTestReport.STYLE:
        return HttpTestReport(**kwargs)
    else:
        raise ValueError(f"Unsupported TestReport with style {style}")
