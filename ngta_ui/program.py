# coding: utf-8

import os
import logging
import logging.config
import json
import shutil
from pathlib import Path
from typing import NoReturn, List, Tuple, Sequence
from abc import ABCMeta, abstractmethod

from .concurrent import RunnersBundle
from .environment import WorkEnv
from .config import (
    BaseConfig,
    BaseYamlConfig, new_yml_config,
    RerunConfig, CommandArgsConfig,
    TestRunnerType, ObjLoaderPathType
)
from .constants import FilePathType, DEFAULT_HTML_REPORT_BASENAME, DEFAULT_LOG_BASENAME
from .report import new_report
from .result import TestResult
from .serialization import parse_dict
from .util import is_samefile

logger = logging.getLogger(__name__)


class BaseTestProgram(metaclass=ABCMeta):
    """
    Base class to run tests.

    Parameters
    ----------
    output_dir: FilePathType
        Output dir which used to store logs and report.
    """

    config: BaseConfig

    def __init__(self, output_dir: FilePathType):
        self.output_dir = Path(output_dir)

    @abstractmethod
    def new_runners(self, result: TestResult) -> List[TestRunnerType]:
        pass

    def new_result(self) -> TestResult:
        return self.config.get_result()

    @abstractmethod
    def call_post_processes(self, result, runners):
        pass

    def enable_logging(self, filename=None):
        log_level, log_layout = self.config.get_log_level_and_layout()
        filename = filename or self.get_default_log_filename()
        handlers = {
            'console': {
                'class': 'logging.StreamHandler',
                'level': log_level,
                'formatter': 'verbose'
            }
        }

        if filename:
            handlers["file_main"] = {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': log_level,
                'formatter': 'verbose',
                'filename': filename,
                'maxBytes': 50000000,
                'backupCount': 99
            }

        log_conf = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'verbose': {
                    '()': 'coupling.log.NameTruncatedFormatter',
                    'format': log_layout
                },
            },
            'handlers': handlers,
            'loggers': {
                'sqlalchemy': {
                    'level': log_level,
                    'propagate': True,
                }
            },
            'root': {
                'level': log_level,
                'handlers': list(handlers.keys()),
            }
        }
        logging.config.dictConfig(log_conf)

    def generate_report(self, result: TestResult, basename: str = None) -> Path:
        """
        Base class to run tests.

        Parameters
        ----------
        result: TestResult
            Specify test result to generate test report.

        basename: str, optional
            Specify test report file basename.
        """

        filename = self.output_dir.joinpath(basename or DEFAULT_HTML_REPORT_BASENAME)

        report = new_report(result=result)
        report.render(filename)
        return filename

    def run(self, report_basename: str = None) -> Tuple[TestResult, Path]:
        os.makedirs(self.output_dir, exist_ok=True)
        self.enable_logging()
        result = self.new_result()
        runners = self.new_runners(result)
        bundle = RunnersBundle(result, runners)
        try:
            bundle.start()
        finally:
            bundle.join()
            try:
                self.generate_report(result, report_basename)
            except:
                logger.exception('')
        self.call_post_processes(result, runners)
        return result, self.output_dir

    def get_default_log_filename(self) -> str:
        return os.path.join(self.output_dir, DEFAULT_LOG_BASENAME)


class FileTestProgram(BaseTestProgram):
    """
    A class used to run tests defined in configuration file.

    Parameters
    ----------
    config_yml: FilePathType
        Configuration yaml to be run.

    output_dir: FilePathType
        Output dir which used to store logs and report.
    """
    config: BaseYamlConfig

    def __init__(self, config_yml: FilePathType, output_dir: FilePathType):
        super().__init__(output_dir)
        self.config_yml = Path(config_yml)
        self.config = new_yml_config(self.config_yml, output_dir)

    def new_runners(self, result: TestResult) -> List[TestRunnerType]:
        try:
            shutil.copy2(self.config_yml, self.output_dir)
        except shutil.SameFileError:
            pass
        return self.config.get_runners(result)

    def call_post_processes(self, result, runners):
        post_processes = self.config.get_post_processes()
        for post_process in post_processes:
            post_process(result, runners, self.output_dir, self.config_yml)

    def generate_report(self, result: TestResult, basename: str = None):
        attachments = []
        reports = self.config.get_reports(result)
        if reports:
            for report in reports:
                report.render()
                attachments.append(report.output)
        else:
            filename = super().generate_report(result, basename)
            attachments.append(filename)


class ArgsTestProgram(BaseTestProgram):
    """
    A class used to run tests defined in arguments.

    Parameters
    ----------
    output_dir: str
        Output dir which used to store logs and report.

    *args, **kwargs
        pass-through to ArgsConfig
    """
    def __init__(self, output_dir: FilePathType, *args, **kwargs):
        super().__init__(output_dir)
        self.config = CommandArgsConfig(*args, **kwargs)

    def new_runners(self, result: TestResult) -> List[TestRunnerType]:
        return self.config.get_runners(self.new_result())


class RerunTestProgram(FileTestProgram):
    """
    A class used to run tests defined in arguments.

    Parameters
    ----------
    result_dir: FilePathType
        result dir which which want to rerun.

    output_dir: FilePathType
        Output dir which used to store logs and report.

    statuses: Sequence[int], optional
        Statuses to rerun

    # FIXME: don't support rerun with nested testsuite. because of pydantic parse Union[TestCaseResultRecord, TestSuiteResultRecord] has some limitation.
    """

    config: RerunConfig

    def __init__(self, result_dir: FilePathType, output_dir: FilePathType,
                 statuses: Sequence[int] = None, mark_warning: bool = False):
        self.result_dir = Path(result_dir)
        report_json = None
        config_yaml = None
        for name in os.listdir(self.result_dir):
            path = self.result_dir.joinpath(name)
            if name.endswith(".json"):
                report_json = path
            elif name.endswith(".yml") or name.endswith(".yaml"):
                config_yaml = path
            else:
                pass

        self.statuses = statuses
        self.mark_warning = mark_warning
        self.report_data = json.loads(report_json.read_text(encoding='utf-8'))
        self.orig_result: TestResult = parse_dict(self.report_data['result'])
        super().__init__(config_yaml, output_dir)
        self.config = RerunConfig(self.config_yml, self.output_dir, self.orig_result, self.statuses)

    def new_runners(self, result: TestResult) -> List[TestRunnerType]:
        if not is_samefile(self.result_dir, self.output_dir):
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
            shutil.copytree(self.result_dir, self.output_dir, dirs_exist_ok=True)
        return self.config.get_runners(result)

    def generate_report(self, result: TestResult, basename: str = None):
        self.orig_result.update(result, self.mark_warning)
        super().generate_report(self.orig_result, basename)


def main(path: ObjLoaderPathType = '__main__',
         output_dir: FilePathType = None,
         *args, **kwargs
         ) -> NoReturn:
    env = WorkEnv.instance()
    if not output_dir:
        if os.path.exists(path):
            output_dir = path if os.path.isdir(path) else os.path.dirname(path)
        else:
            output_dir = os.getcwd()
    abs_output_dir = os.path.abspath(output_dir)
    env.work_dir = abs_output_dir
    env.case_dir = abs_output_dir
    env.libs_dir = abs_output_dir
    program = ArgsTestProgram(abs_output_dir, [path], *args, **kwargs)
    program.run()
