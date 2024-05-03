# coding: utf-8

import os
import yaml
import json
import jmespath
import pydantic
from pathlib import Path
from typing import Union, List, Dict, Optional
from abc import ABCMeta, abstractmethod

from ..constants import (
    FilePathType, DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT,
    YML_OBJECT_NEW_TAG, YML_OBJECT_LOCATE_TAG
)
from ..errors import ConfigError
from ..result import TestResult
from ..report import BaseTestReport
from ..serialization import parse_dict
from ..util import locate

from .base import BaseConfig, TestRunnerType
from .nodes import (
    parse_dict_by_path,
    TestResultNode, TestRunnerNode,
    TestContextNode, TestBenchNode, EventObservableNode,
    HtmlNode, TestReportNode,
    TestSuiteNode,
)


class BaseYamlConfig(pydantic.BaseModel, BaseConfig, metaclass=ABCMeta):
    log_level: str = pydantic.Field(DEFAULT_LOG_LEVEL, alias="log-level")
    log_layout: str = pydantic.Field(DEFAULT_LOG_LAYOUT, alias="log-layout")
    fail_fast: bool = pydantic.Field(False, alias="fail-fast")
    enable_mock: bool = pydantic.Field(False, alias="enable-mock")
    strict: bool = True
    post_processes: List[str | dict] = pydantic.Field(default_factory=list, alias="post-processes")
    result: Optional[TestResultNode] = None
    report: Optional[TestReportNode] = None

    output_dir: str
    config_yml: str

    def get_log_level_and_layout(self):
        return self.log_level, self.log_layout

    def get_post_processes(self):
        post_processes = []
        for item in self.post_processes:
            if isinstance(item, str):
                post_processes.append(locate(item))
            elif isinstance(item, dict):
                post_processes.append(parse_dict_by_path(item))
            else:
                raise NotImplementedError
        return post_processes

    def get_result(self) -> TestResult:
        result = self.result.as_result() if self.result else TestResult()
        result.failfast = self.fail_fast
        return result

    @abstractmethod
    def get_runner_nodes(self) -> List[TestRunnerNode]:
        pass

    def get_runners(self, result: TestResult = None) -> List[TestRunnerType]:
        if not result:
            result = self.get_result()

        runners = []
        for index, runner_node in enumerate(self.get_runner_nodes()):
            runner = runner_node.as_runner(self.output_dir, self.config_yml, result, index,
                                           self.enable_mock, self.strict)
            runners.append(runner)
        return runners

    def get_report_nodes(self) -> List[HtmlNode]:
        nodes = []
        if self.report and self.report.html:
            if isinstance(self.report.html, list):
                nodes.extend(self.report.html)
            else:
                nodes.append(self.report.html)

        for node in nodes:
            node.update_report_template_and_filename(self.output_dir, self.config_yml)
        return nodes

    def get_reports(self, result) -> List[BaseTestReport]:
        reports = []
        for report_node in self.get_report_nodes():
            reports.append(report_node.as_report(result))
        return reports


class V4YamlConfig(BaseYamlConfig, extra='ignore'):
    testbench: Optional[TestBenchNode] = None
    event_observable: Optional[EventObservableNode] = pydantic.Field(None, alias="event-observable")
    testsuites: List[TestSuiteNode]

    def get_runner_nodes(self) -> List[TestRunnerNode]:
        context = TestContextNode(testbench=self.testbench)
        context.event_observable = self.event_observable
        runner = TestRunnerNode(context=context, testsuites=self.testsuites,
                                log_level=self.log_level, log_layout=self.log_layout)
        return [runner]


class V5YamlConfig(BaseYamlConfig, extra='ignore'):
    runners: List[TestRunnerNode]

    def get_runner_nodes(self) -> List[TestRunnerNode]:
        return self.runners


class YamlLoader(yaml.Loader):
    # def construct_object(self, node, deep=False):
    #     """
    #     Auto construct object with property "()"
    #     """
    #     if isinstance(node, yaml.MappingNode):
    #         if node.tag != YML_OBJECT_NEW_TAG:
    #             for key_node, val_node in node.value:
    #                 if key_node.value == CALLEE_KEY:
    #                     node.tag = YML_OBJECT_NEW_TAG
    #                     break
    #     return super().construct_object(node, deep)

    def construct_new_object(self, node):
        data = self.construct_mapping(node, deep=True)
        return parse_dict(data)

    def construct_locate_object(self, node):
        data = self.construct_mapping(node, deep=True)
        return locate(data['path'])

    def ref(self, node):
        kv = {}
        for key_node, val_node in node.value:
            kv[key_node.value] = val_node.value

        filename = Path(kv["filename"])

        match filename.suffix:
            case ".yml" | ".yaml":
                with filename.open("r", encoding="utf-8") as f:
                    data = yaml.load(f, Loader=YamlLoader)
            case ".json":
                with filename.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            case _:
                raise NotImplementedError(f"DONT support file suffix: {filename}")

        found = jmespath.search(kv["jmespath"], data)
        return found


YamlLoader.add_constructor("!ref", YamlLoader.ref)
YamlLoader.add_constructor(YML_OBJECT_NEW_TAG, YamlLoader.construct_new_object)
YamlLoader.add_constructor(YML_OBJECT_LOCATE_TAG, YamlLoader.construct_locate_object)


def new_yml_config(filename: FilePathType, output_dir: FilePathType):
    root, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext == ".yml" or ext == ".yaml":
        with open(filename, 'r', encoding='utf-8') as f:
            data = yaml.load(f, Loader=YamlLoader)

        if "runners" in data:
            return V5YamlConfig(config_yml=str(filename), output_dir=str(output_dir), **data)
        else:
            return V4YamlConfig(config_yml=str(filename), output_dir=str(output_dir), **data)
    else:
        raise ConfigError(f"Unsupported config file extension '{ext}'.")
