# coding: utf-8

import os
import sys
import argparse
from pathlib import Path
from typing import List, Sequence

from .program import FileTestProgram, ArgsTestProgram, RerunTestProgram
from .environment import WorkEnv
from .constants import PACKAGE_NAME, ExitCode
from .case import TestCaseResultRecord
from .serialization import parse_dict

import logging
logger = logging.getLogger(__name__)


env = WorkEnv.instance()
TestCaseStatus = TestCaseResultRecord.Status


def run_configs(cfg_paths: List[str], output_dir: str = None):
    work_dir = env.work_dir
    exit_code = ExitCode.OK
    for i, cfg_path in enumerate(cfg_paths):
        abs_cfg_path = os.path.abspath(cfg_path)
        if not output_dir:
            # When cwd is not correct, try locate work dir and re-init WorkEnv by yml config path.
            work_dir = work_dir or env.find_work_dir(Path(cfg_path).parent)
            if work_dir:
                env.init_by_work_dir(work_dir)
                output_dir = env.new_output_dir()
            else:
                output_dir = os.path.dirname(abs_cfg_path)

        program = FileTestProgram(abs_cfg_path, output_dir)
        exit_code += _run_program(program) * (10 ** i)
    sys.exit(exit_code)


def run_locate(**kwargs):
    work_dir = env.work_dir
    if not kwargs["output_dir"]:
        kwargs["output_dir"] = env.cwd if work_dir is None else env.new_output_dir()
    program = ArgsTestProgram(**kwargs)
    exit_code = _run_program(program)
    sys.exit(exit_code)


def rerun(result_dir: str = None, output_dir: str = None, statuses: Sequence[int] = None,
          overwrite: bool = False, mark_warning=False):
    if not result_dir:
        result_dir = env.get_last_failed_output_dir()
    print(f'rerun tests with statues {statuses} in {result_dir}')

    if not output_dir:
        if overwrite:
            output_dir = result_dir
        else:
            output_dir = env.new_output_dir()
    program = RerunTestProgram(result_dir, output_dir, statuses, mark_warning)
    exit_code = _run_program(program)
    sys.exit(exit_code)


def merge(result_dirs, output_dir: str = None):
    import json
    from .result import TestResult
    from .report import TestReport

    result_all = TestResult()
    for result_dir in result_dirs:
        report = TestReport.parse_file(Path(result_dir).joinpath('report.json'))
        # report_json =
        # report_data = json.loads(report_json.read_text())
        # result_obj: TestResult = parse_dict(report_data['result'])
        # result_all.ts_records.extend(result_obj.ts_records)

    raise NotImplementedError


def gen_report(result_dir):
    import json
    from pathlib import Path
    from .config import new_yml_config
    from .report import TestReport
    from .constants import DEFAULT_HTML_REPORT_BASENAME, DEFAULT_LOG_LAYOUT
    from .interceptor import TestCaseLogFileInterceptor
    from .events import TestSuiteStartedEvent, TestSuiteStoppedEvent, TestCaseStartedEvent, TestCaseStoppedEvent
    from .util import locate

    import logging.config
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                '()': 'coupling.log.NameTruncatedFormatter',
                'format': DEFAULT_LOG_LAYOUT
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'verbose'
            },
            'file_main': {
                'class': 'logging.FileHandler',
                'level': 'DEBUG',
                'formatter': 'verbose',
                'filename': os.path.join(result_dir, 'gen_report.log'),
            }
        },
        'root': {
            'level': 'DEBUG',
            'handlers': ['console', 'file_main'],
        }
    })

    result_dir = Path(result_dir)
    report_json = None
    config_yaml = None
    for name in os.listdir(result_dir):
        if name.endswith(".json"):
            report_json = result_dir.joinpath(name)
        elif name.endswith(".yml") or name.endswith(".yaml"):
            config_yaml = result_dir.joinpath(name)
        else:
            pass

    report_data = json.loads(report_json.read_text())
    os.chdir(report_json.parent)
    config = new_yml_config(config_yaml, result_dir)

    runner = config.get_runners(report_json.parent)[0]      # FIXME: only support one test runner configured in yaml.
    report_data['result'] = parse_dict(report_data['result'])
    report = TestReport.construct(report_data)
    report.template = result_dir.joinpath(DEFAULT_HTML_REPORT_BASENAME)

    observable = runner.context.event_observable
    for observer in observable.get_observers():
        if isinstance(observer, TestCaseLogFileInterceptor):
            observable.detach(observer)

    for ts_record in report.result.ts_records:
        testsuite = locate(ts_record.path)()
        testsuite.record = ts_record
        observable.notify(TestSuiteStartedEvent(testsuite))
        for tc_record in ts_record.records:
            class_, sep, method = tc_record.path.rpartition('.')
            testcase = locate(class_)(method)
            observable.notify(TestCaseStartedEvent(testcase))
            testcase.record = tc_record
            observable.notify(TestCaseStoppedEvent(testcase))
        observable.notify(TestSuiteStoppedEvent(testsuite))

    report.render_html(report_json.with_name("report.html"))


def _run_program(program):
    exit_code = ExitCode.OK
    output_dir = None
    try:
        result, output_dir = program.run()
        statistics = result.statistics()
        if statistics.totals == 0:
            exit_code = ExitCode.NO_TESTS_COLLECTED
        elif statistics.failed > 0:
            exit_code = ExitCode.TESTS_FAILED
        elif statistics.erroneous > 0:
            exit_code = ExitCode.TESTS_ERROR
        elif statistics.warning > 0:
            exit_code = ExitCode.TESTS_WARNING
        elif statistics.not_run == statistics.totals:
            exit_code = ExitCode.ALL_TESTS_NOT_RUN
        elif statistics.skipped == statistics.totals:
            exit_code = ExitCode.ALL_TESTS_SKIPPED
        else:
            pass
    except KeyboardInterrupt:
        exit_code = ExitCode.INTERRUPTED
    except Exception as err:
        logger.exception(str(err))
        exit_code = ExitCode.UNKNOWN_EXCEPTION
    finally:
        env.add_history({
            'exit_code': exit_code.value,
            'output_dir': output_dir
        })
        return exit_code.value


PROG = f"python -m {PACKAGE_NAME}"


def main():
    print("sys.argv: %s" % sys.argv)
    print("sys.path: %s" % sys.path)
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub_parsers = parser.add_subparsers(dest="func")
    init_sub_parser = sub_parsers.add_parser("init", help=f'init work dir, detail: {PROG} init -h')
    init_sub_parser.add_argument('-d', '--dest-dir', default=env.cwd, help='init dest dir as work dir')
    init_sub_parser.add_argument('-i', '--include-sample', action='store_true',
                                 default=False, help='whether include sample when init work dir')

    run_sub_parser = sub_parsers.add_parser("run", help=f'run test, detail: {PROG} run -h')
    run_sub_parser.add_argument('--output-dir', help='output dir which used to store test result')

    run_config_group = run_sub_parser.add_argument_group("config group",
                                                         description="alternative with locate group")
    run_config_group.add_argument('--config', nargs='+', dest='configs', help='config file with ext: .yml, .yaml')

    run_locate_group = run_sub_parser.add_argument_group("locate group", description="alternative with config group")

    run_locate_group.add_argument(
        '--locate', dest="locates", action="append",
        help="paths for module, class, method, *.py or dir"
    )
    run_locate_group.add_argument(
        '--includes', nargs="*",
        help="regexp filter for tests should be included"
    )
    run_locate_group.add_argument(
        '--excludes', nargs="*",
        help="regexp filter for tests should be excluded"
    )
    run_locate_group.add_argument(
        '--tags',  nargs="*",
        help="include tests with tag"
    )
    run_locate_group.add_argument(
        '--repeat-number', type=int, default=1,
        help="repeat test with number, default: 1"
    )
    run_locate_group.add_argument(
        '--repeat-foreach', action='store_true', default=False,
        help="if provided, repeat would be: test1, test1, test2, test2;"
             "otherwise, repeat would be: test1, test2, test1, test2")
    run_locate_group.add_argument(
        '--pattern', default="test*.py",
        help="when locate is a dir, only parse test in file which match pattern, default: test*.py"
    )
    run_locate_group.add_argument(
        '--failfast', action='store_true', default=False,
        help="stop when encounter fail, default: false"
    )
    run_locate_group.add_argument(
        '--enable-mock', action='store_true', default=False,
        help="whether enable mock, default: false"
    )
    run_locate_group.add_argument(
        '--process-count', type=int, default=1,
        help="process count to run tests concurrently, default: 1"
    )
    run_locate_group.add_argument(
        '--log-level',
        help="log level, check logging package for detail, default: DEBUG"
    )
    run_locate_group.add_argument('--log-layout')

    run_locate_group.add_argument(
        '--event-observable',
        help="specify the path of event-observable"
    )

    run_locate_group.add_argument(
        '--testbench',
        help="specify the path of testbench"
    )

    rerun_sub_parser = sub_parsers.add_parser("rerun", help=f'rerun test, detail: {PROG} rerun -h')
    rerun_sub_parser.add_argument('--result-dir', help='Result directory.')
    rerun_sub_parser.add_argument('--output-dir', help='output dir which used to store test result')
    rerun_sub_parser.add_argument('--statuses', nargs="*",
                                  choices=tuple(range(TestCaseResultRecord.Status.ERRONEOUS+1)),
                                  default=(0, 3, 5),
                                  help='Rerun failures from cache or specified result dir. \
                                        Default rerun last failures. \
                                        0: not run, 1: passed, 2: warning, 3: failed, 4: skipped, 5: erroneous')

    rerun_sub_parser.add_argument('--overwrite', action='store_true', default=False,
                                  help='Rerun failed test cases, and overwrite origin result or into a new one.')
    rerun_sub_parser.add_argument('--mark-warning', action='store_true', default=False,
                                  help='Mark failed or erroneous testcase as warning if rerun passed.')

    merge_sub_parser = sub_parsers.add_parser("merge", help=f'merge test result, detail: {PROG} merge -h')
    merge_sub_parser.add_argument('--result-dirs', nargs='+', required=True, help='Result directories to merge.')
    merge_sub_parser.add_argument('--output-dir', help='output dir which used to store test result')

    regen_sub_parser = sub_parsers.add_parser("gen-report",
                                              help=f're-generate test report, detail: {PROG} gen-report -h')
    regen_sub_parser.add_argument('--result-dir', required=True, help='Re-generate test report.')

    args = parser.parse_args()
    if args.func == "init":
        env.init(args.dest_dir, args.include_sample)
    elif args.func == "run":
        if args.configs:
            run_configs(args.configs, args.output_dir)
        elif args.locates:
            kwargs = vars(args)
            kwargs.pop("func")
            kwargs.pop("configs")
            run_locate(**kwargs)
        else:
            print("--config or --locate required alternatively.")
    elif args.func == "rerun":
        rerun(args.result_dir, args.output_dir, args.statuses, args.overwrite)
    elif args.func == "merge":
        merge(args.result_dirs, args.output_dir)
    elif args.func == "gen-report":
        gen_report(args.result_dir)
    else:
        pass


main()
