# coding: utf-8

from datetime import datetime, timedelta
from typing import Optional, NoReturn, ClassVar, Dict, List
from .serialization import BaseModel, Field, AttrDict
from .case import TestCaseResultRecord
from .suite import TestSuiteResultRecordList, TestSuiteResultRecord
from .bench import TestBenchRecord


import logging
logger = logging.getLogger(__name__)


class TestResult(BaseModel, arbitrary_types_allowed=True, extra='ignore'):
    """
    Used to store testcase result record and testsuite result record, and also provide some hook methods to be called.
    """
    PAUSE_INTERVAL: ClassVar = 0.5
    PREV_TEST_CLASS: ClassVar = None
    MODULE_SETUP_ERROR: ClassVar = None

    ts_records: TestSuiteResultRecordList = Field(default_factory=TestSuiteResultRecordList)    # filled by testsuite.
    tb_records: List[TestBenchRecord] = Field(default_factory=list)    # filled by testrunner.
    failfast: bool = False

    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    should_pause: bool = False
    should_abort: bool = False

    @property
    def duration(self) -> Optional[timedelta]:
        if not self.stopped_at or not self.started_at:
            return None
        return self.stopped_at - self.started_at

    def add_testsuite_record(self, record: TestSuiteResultRecord):
        self.ts_records.append(record)

    def statistics(self):
        statistics = AttrDict()
        for status in TestCaseResultRecord.Status:
            statistics[status.name.lower()] = 0

        totals = 0
        for tc_record in self.tc_records().values():
            status = tc_record.get_status_name()
            statistics[status] += 1
            totals += 1

        statistics.totals = totals
        return statistics

    def pause(self) -> NoReturn:
        self.should_pause = True

    def resume(self) -> NoReturn:
        self.should_pause = False

    def abort(self) -> NoReturn:
        self.should_abort = True

    def tc_records(self) -> Dict[int | str, TestCaseResultRecord]:
        tc_records = {}

        def recur(_ts_record):
            for record in _ts_record.records:
                if isinstance(record, TestCaseResultRecord):
                    tc_records[record.id] = record
                elif isinstance(record, TestSuiteResultRecord):
                    recur(record)
                else:
                    raise NotImplementedError

        for ts_record in self.ts_records:
            recur(ts_record)

        return tc_records

    def update(self, other: 'TestResult', mark_as_warning_if_rerun=True):
        # called when rerun test program
        old_tc_records = self.tc_records()
        new_tc_records = other.tc_records()
        for ident, new_record in new_tc_records.items():
            old_record = old_tc_records[ident]
            rerun_causes = old_record.rerun_causes
            old_status = old_record.status

            if old_record.status == TestCaseResultRecord.Status.FAILED:
                error = None
                for checkpoint in reversed(old_record.checkpoints):
                    if checkpoint.error:
                        error = checkpoint.error
                        break
                if error:
                    rerun_causes.append(error.trace)

            if old_record.status == TestCaseResultRecord.Status.ERRONEOUS:
                rerun_causes.append(old_record.error.trace)

            old_record.update(new_record)
            old_record.rerun_causes = rerun_causes

            if old_status in (TestCaseResultRecord.Status.FAILED, TestCaseResultRecord.Status.ERRONEOUS) \
                    and new_record.status == TestCaseResultRecord.Status.PASSED and mark_as_warning_if_rerun:
                old_record.status = TestCaseResultRecord.Status.WARNING

    def extend(self, other: 'TestResult'):
        self.ts_records.extend(other.ts_records)
        self.tb_records.extend(other.tb_records)

        if not self.started_at or self.started_at and other.started_at and self.started_at > other.started_at:
            self.started_at = other.started_at

        if not self.stopped_at or self.stopped_at and other.stopped_at and self.stopped_at < other.stopped_at:
            self.stopped_at = other.stopped_at

    def clear(self):
        self.ts_records.clear()
        self.tb_records.clear()
        self.started_at = None
        self.stopped_at = None
        self.__class__.PREV_TEST_CLASS = None
        self.__class__.MODULE_SETUP_ERROR = None

    def dict(self, *args, **kwargs):
        d = super().dict(*args, **kwargs)
        statistics = self.statistics()
        d.update(statistics)
        return d
