# coding: utf-8

import os
from typing import Union, Optional, Dict, List
import pydantic

from ...constants import FilePathType, DEFAULT_HTML_REPORT_BASENAME
from ...report import new_report, BaseTestReport
from ...errors import ReportTemplateNotExistsError

import logging
logger = logging.getLogger(__name__)


class HtmlNode(pydantic.BaseModel):
    template: Optional[str] = None
    props: Optional[Dict[str, str]] = None
    output: Optional[str] = None

    def update_report_template_and_filename(self, output_dir: FilePathType, config_yml: FilePathType):
        if self.output is None:
            if self.template is None:
                self.output = os.path.join(output_dir, DEFAULT_HTML_REPORT_BASENAME)
            else:
                self.output = os.path.join(output_dir, os.path.basename(self.template))
        logger.debug("template: %s", self.template)
        logger.debug("output: %s", self.output)

        if self.template:
            if not os.path.isabs(self.template):
                self.template = os.path.join(os.path.dirname(config_yml), self.template)

            if not os.path.isfile(self.template):
                raise ReportTemplateNotExistsError(f'{self.template} not exists')

    def as_report(self, result) -> BaseTestReport:
        return new_report(None, result=result, **self.model_dump())


class TestReportNode(pydantic.BaseModel):
    html: Union[HtmlNode, List[HtmlNode], None] = None
