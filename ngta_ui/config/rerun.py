# coding: utf-8

from typing import List, Optional, Sequence
from ..constants import FilePathType
from ..result import TestResult
from ..suite import TestCaseResultRecord, TestSuiteResultRecord, TestSuiteModel
from ..serialization import pformat_json

from .base import BaseConfig, TestRunnerType
from .yml import new_yml_config, HtmlNode, BaseTestReport

import logging
logger = logging.getLogger(__name__)


class RerunConfig(BaseConfig):
    result: TestResult
    statuses: Sequence[int]

    def __init__(self,
                 config_yml: FilePathType,
                 output_dir: FilePathType,
                 result: TestResult,
                 statuses: Sequence[int]
                 ):
        self.config = new_yml_config(config_yml, output_dir)
        self.old_result = result
        self.new_result = None
        self.statuses = statuses

    def get_log_level_and_layout(self):
        return self.config.get_log_level_and_layout()

    def get_result(self) -> TestResult:
        return self.config.get_result()

    def get_runners(self, result: TestResult = None) -> List[TestRunnerType]:
        runners = self.config.get_runners(result)
        assert len(runners) == 1        # FIXME: currently only support single runner
        self.new_result = runners[0].result
        testsuites = self._get_testsuites()
        logger.debug('Rerun testsuites: \n%s', pformat_json(testsuites))
        runners[0].clear()          # this step will clear all testsuites and records
        runners[0].add_testsuites(testsuites)
        return runners

    def _gen_testsuite_from_record(self, record: TestSuiteResultRecord) -> Optional[TestSuiteModel]:
        tests = []
        new_tc_records = self.new_result.tc_records()
        for sub_record in record.records:
            if isinstance(sub_record, TestSuiteResultRecord):
                sub_testsuite = self._gen_testsuite_from_record(sub_record)
                tests.append(sub_testsuite)
            elif isinstance(sub_record, TestCaseResultRecord):
                if sub_record.status.value in self.statuses:
                    new_parameters = new_tc_records.get(sub_record.id, sub_record).parameters
                    test = sub_record.as_test_model(parameters=new_parameters)
                    tests.append(test)
            else:
                raise NotImplementedError

        if tests:
            testsuite = record.as_test_model(tests=tests)
            return testsuite
        return None

    def _get_testsuites(self) -> List[TestSuiteModel]:
        testsuites = []
        for ts_record in self.old_result.ts_records:
            testsuite = self._gen_testsuite_from_record(ts_record)
            if testsuite:
                testsuites.append(testsuite)
        return testsuites

    def get_reports(self, result) -> List[BaseTestReport]:
        return self.config.get_reports(result)

    def get_report_nodes(self) -> List[HtmlNode]:
        return self.config.get_report_nodes()

    def get_post_processes(self):
        return self.config.get_post_processes()
