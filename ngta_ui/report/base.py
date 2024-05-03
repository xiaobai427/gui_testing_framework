# coding: utf-8

import os
import sys
import jinja2
from typing import NoReturn, ClassVar, List
from pathlib import Path
import shutil

from abc import ABCMeta, abstractmethod
from ..result import TestResult
from ..serialization import json_dumps, Serializable

import logging
logger = logging.getLogger(__name__)


CURRENT_DIR = Path(__file__).parent
HTML_DIR = CURRENT_DIR.joinpath("html")
ECHARTS_JS_PATH = HTML_DIR.joinpath("echarts.min.js")


class BaseTestReport(Serializable, metaclass=ABCMeta):
    STYLE: ClassVar
    TEMPLATE: ClassVar

    def __init__(self, result: TestResult, output: Path = None):
        self.result = result
        self.output = output

    @abstractmethod
    def render(self, filename: Path = None):
        pass


class TestReport(BaseTestReport):
    STYLE: ClassVar = "base"
    TEMPLATE: ClassVar = CURRENT_DIR.joinpath("html", "base.html")

    def __init__(self, result: TestResult, output: Path = None,
                 template: Path = None, props: dict = None, chart_position: str = "head", chart_display: str = "none",
                 detail_display: str = "block"):
        super().__init__(result, output)
        self.template = template
        self.props = props
        self.chart_position = chart_position
        self.chart_display = chart_display
        self.detail_display = detail_display

    def render(self, filename: Path = None) -> NoReturn:
        filename = Path(filename or self.output)
        output_dir = str(filename.parent)
        os.makedirs(output_dir, exist_ok=True)
        shutil.copy(ECHARTS_JS_PATH, output_dir)

        self.render_json(filename.with_suffix(".json"))
        self.render_html(filename)

    def render_html(self, filename: Path, relative: bool = True) -> NoReturn:
        template_dirs = [str(HTML_DIR)]
        template = Path(self.template or self.TEMPLATE)

        logger.info("Generating html test report: %s, template: %s", filename, template)
        if str(template.parent) not in template_dirs:
            template_dirs.append(str(template.parent))

        j2_loader = jinja2.FileSystemLoader(template_dirs)
        j2_env = jinja2.Environment(loader=j2_loader, trim_blocks=True, lstrip_blocks=True, autoescape=True)
        j2_env.filters["path_basename"] = os.path.basename
        j2_env.filters["path_dirname"] = os.path.dirname
        j2_env.filters["path_relpath"] = os.path.relpath
        j2_template = j2_env.get_template(template.name)

        props = dict(
            _result_=self.result,
            _benches_=self.result.tb_records,
            _echarts_js_path_=ECHARTS_JS_PATH,
            _chart_position_=self.chart_position,
            _chart_display_=self.chart_display,
            _detail_display_=self.detail_display,
            _output_dir_=str(filename.parent),
            **(self.props or {})
        )
        stream = j2_template.stream(**props)
        stream.dump(str(filename))

        if relative:
            text = filename.read_text(encoding='utf-8')
            output_dir = str(filename.parent)
            text = self._make_path_relative(text, output_dir)
            filename.write_text(text, encoding='utf-8')

    def dict(self, *, include=None, exclude=None) -> dict:
        d = super().dict(include=include, exclude=exclude)
        return d

    def render_json(self, filename: Path, relative: bool = True):
        text = json_dumps(self.dict())
        if relative:
            output_dir = str(filename.parent)
            text = self._make_path_relative(text, output_dir, True)
        filename.write_text(text, encoding='utf-8')

    @staticmethod
    def _make_path_relative(text, start, double_slash=False):
        if sys.platform == "win32":
            if double_slash:
                replaced = start.replace("\\", r"\\") + r"\\"
            else:
                replaced = start + "\\"
        else:
            replaced = start + r"/"
        return text.replace(replaced, "")
