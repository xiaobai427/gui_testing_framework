# coding: utf-8

import uuid
import time
import ctypes
import inspect
import datetime
import logging
import collections
import multiprocessing
import queue
import _thread
import threading
import traceback

from datetime import datetime, timezone
from typing import NoReturn, Type
import psutil

from .constants import DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT, IdType
from .runner import TestRunner
from .context import TestContext
from .consumer import QueueTestConsumer
from .case import TestCaseResultRecord, fetch_current_testcase_id
from .suite import TestSuite, TestSuiteResultRecord, TestSuiteModel, is_testsuite_model, fetch_current_testsuite_id
from .result import TestResult
from .events import EventType
from .interceptor import TestRecordQueueInterceptor, TestEventHandler, get_current_process_name


logger = logging.getLogger(__name__)


def _get_dotted_attribute(obj, attr_name: str):
    names = attr_name.split('.')
    for name in names:
        obj = getattr(obj, name, None)
    return obj


def _set_dotted_attribute(obj, attr_name: str, value):
    names = attr_name.split('.')
    for index in range(len(names)):
        if index != len(names) - 1:
            obj = getattr(obj, names[index])
        else:
            setattr(obj, names[index], value)


def get_testrunner_params(*args, **kwargs) -> dict:
    args = list(args)
    args.insert(0, None)        # provide self as None when getcallargs of TestRunner
    params = inspect.getcallargs(TestRunner, *args, **kwargs)
    params.pop("self")     # remove self from getcallargs result
    return params


def raise_exception_in_thread(thread_obj: threading.Thread, exception_cls: Type[BaseException]):
    # this won't interrupt sockets/sleeps
    found = False
    target_tid = 0
    for tid, tobj in threading._active.items():
        if tobj is thread_obj:
            found = True
            target_tid = tid
            break

    if not found:
        raise ValueError("Invalid thread object")

    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(target_tid), ctypes.py_object(exception_cls))
    # ref: http://docs.python.org/c-api/init.html#PyThreadState_SetAsyncExc
    if ret == 0:
        raise ValueError("Invalid thread ID")
    elif ret > 1:
        # Huh? Why would we notify more than one threads?
        # Because we punch a hole into C level interpreter.
        # So it is better to clean up the mess.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(target_tid), 0)
        raise SystemError("PyThreadState_SetAsyncExc failed")
    logger.debug("Successfully set asynchronized exception for %s", target_tid)


class SimpleTestRunnerProcess(multiprocessing.Process):
    """
    A simple sub-process to run tests.

    Parameters
    ----------
    log_level : str, optional
        Specify log level.

    log_layout : str, optional
        Specify log layout.

    id, result, context:
        pass-through to TestRunner.
    """

    def __init__(self, log_level=None, log_layout=None,
                 id: IdType = None, result: TestResult = None, context: TestContext = None):
        self.id = id
        self._result = result
        self._context = context
        name = str(self.id) if self.id is not None else None
        super().__init__(name=name)
        self._testsuites = []
        self.log_level = log_level or DEFAULT_LOG_LEVEL
        self.log_layout = log_layout or DEFAULT_LOG_LAYOUT

    @property
    def context(self) -> TestContext:
        return self._context

    def add_testsuite(self, testsuite: TestSuiteModel | TestSuite) -> NoReturn:
        if not isinstance(testsuite, TestSuiteModel):
            raise TypeError("The type of argument 'testsuite' should be DictType.")
        self._testsuites.append(testsuite)

    def run(self):
        self._init_logging()

        runner = TestRunner(id=self.id, result=self._result, context=self._context)
        for testsuite in self._testsuites:
            runner.add_testsuite(testsuite)
        try:
            runner.run()
        except:
            logger.exception("")

    def _init_logging(self):
        root = logging.getLogger()
        handler = logging.StreamHandler()
        handler.setLevel(self.log_level)
        handler.setFormatter(logging.Formatter(self.log_layout))
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

    def __str__(self):
        return f"<{self.__class__.__name__}(id:{self.id}, pid:{self.ident}, is_alive:{self.is_alive()})>"

    def shutdown(self):
        self.kill()


class _ControlThread(threading.Thread):
    """
    A thread used to receive action in pipe, and then execute it.
    """

    def __init__(self, runner: TestRunner, dst_conn):
        super().__init__()
        self._runner = runner
        self._dst_conn = dst_conn
        self._should_stop = threading.Event()

    def stop(self):
        self._should_stop.set()

    def run(self):
        thread_logger = logging.getLogger(f"{__name__}.ControlThread")
        ident = multiprocessing.current_process().ident
        while not self._should_stop.is_set():
            readable = self._dst_conn.poll(0.1)
            if readable:
                name, args, kwargs = self._dst_conn.recv()
                thread_logger.debug("PROCESS %s <- PIPE: name=%s, args=%s, kwargs=%s",
                             ident, name, args, kwargs)
                resp = None
                try:
                    if name == 'stop':
                        logger.debug("process(%s) control thread exiting.", ident)
                        self.stop()
                    else:
                        attr = _get_dotted_attribute(self._runner, name)
                        if callable(attr):
                            resp = attr(*args, **kwargs)
                            if name == "abort":
                                logger.debug("interrupt main thread.")
                                _thread.interrupt_main()
                        else:
                            if args or kwargs:
                                _set_dotted_attribute(self._runner, name, *args, **kwargs)
                            else:
                                resp = attr
                finally:
                    thread_logger.debug("PROCESS %s -> PIPE: %s", ident, resp)
                    self._dst_conn.send(resp)


class TestRunnerProcess(SimpleTestRunnerProcess):
    """
    A process to run tests, but it support more methods than SimpleTestRunnerProcess.

    Parameters
    ----------
    log_level : str, optional
        Specify log level.

    log_layout : str, optional
        Specify log layout.

    *args, **kwargs:
        pass-through to SimpleTestRunnerProcess.
    """

    State = TestRunner.State  # Can't pickle if define the enum directly.

    class PipeCallError(multiprocessing.ProcessError):
        pass

    def __init__(self,  observer: TestRunner.BaseObserver = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observer = observer
        self._src_conn, self._dst_conn = multiprocessing.Pipe()
        self._pipe_lock = threading.RLock()
        self._is_stopped = None         # inner testrunner is stopped

    def _create_inner_testrunner(self) -> TestRunner:
        return TestRunner(id=self.id, result=self._result, context=self._context)

    def __getstate__(self):
        excludes = ("_pipe_lock", )
        state = {k: v for k, v in self.__dict__.items() if k not in excludes}
        return state

    def _pipe(self, name, get_resp=True, *args, **kwargs):
        if not self.is_alive():
            raise self.PipeCallError("pipe call can only be used when process is alive.")

        logger.debug("PIPE -> PROCESS(%s): name=%s, args=%s, kwargs=%s", self.name, name, args, kwargs)
        with self._pipe_lock:
            self._src_conn.send((name, args, kwargs))
            if get_resp:
                resp = self._src_conn.recv()
                logger.debug("PIPE <- PROCESS %s: %s", self.name, resp)
                return resp

    @property
    def result(self):
        return self._pipe("result")

    @property
    def context(self):
        return self._pipe("context")

    def pause(self):
        self._pipe("pause")
        psutil.Process(self.ident).suspend()

    def resume(self):
        psutil.Process(self.ident).resume()
        self._pipe("resume")

    def abort(self):
        self._pipe("abort")

    interrupt_main = abort

    @property
    def state(self):
        return self._pipe("state")

    def is_stopped(self) -> bool:
        self._is_stopped = self._pipe("is_stopped")
        return self._is_stopped

    def shutdown(self, wait: float = None):
        try:
            if not self.is_stopped():
                self.abort()
            self._pipe('stop')
        except self.PipeCallError as err:
            logger.error(err)
        finally:
            logger.debug("wait process(%s) join, timeout: %ss", self.pid, wait)
            self.join(wait)
            logger.debug("force kill process(%s)", self.pid)
            self.kill()

    def run(self):
        try:
            self._init_logging()
            runner = self._create_inner_testrunner()
            if self._observer is not None:
                runner.observable.attach(self._observer)
                runner.state = runner.State.INITIAL

            ctrl = _ControlThread(runner, self._dst_conn)

            try:
                for suite in self._testsuites:
                    runner.add_testsuite(suite)

                ctrl.start()
                runner.run()
            except:
                runner.state = runner.State.UNEXPECTED
                logger.exception("")
            finally:
                ctrl.join()
                if self._observer is not None:
                    runner.observable.detach(self._observer)
        except:
            if self._observer is not None:
                self._observer.update(TestRunner.Observable(self.id, TestRunner.State.UNEXPECTED))
            msg = traceback.format_exc()
            logger.error(msg)
            self._dst_conn.send(msg)
        finally:
            self._src_conn.close()
            self._dst_conn.close()
            logger.debug("process(%s) main thread exited" % self.pid)


class QueueTestConsumerProcess(TestRunnerProcess):
    """
    A process to consume test from queue.

    Parameters
    ----------
    queue: multiprocessing.Queue
        Queue to consume test.

    *args, **kwargs:
        pass-through to QueueTestConsumerProcess.
    """

    def __init__(self, queue: multiprocessing.Queue, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = queue

    def _create_inner_testrunner(self) -> QueueTestConsumer:
        return QueueTestConsumer(self.queue, auto_stop=True, id=self.id, result=self._result, context=self._context)


class _TestRecordQueueConsumeThread(threading.Thread):
    """
    A thread to consume test result record from queue, and store it.

    Parameters
    ----------
    consumer: MultiProcessQueueTestConsumer
        specify the consumer to store test result.
    """

    def __init__(self, consumer: "MultiProcessQueueTestConsumer"):
        super().__init__()
        self.consumer = consumer
        self.should_stop = threading.Event()

    def run(self):
        self.should_stop.clear()
        logger.debug("Start to consume record from TestRecordQueue.")
        while True:
            try:
                tc_record = self.consumer.tr_queue.get(block=False, timeout=0.1)
            except queue.Empty:
                pass
            else:
                logger.debug("RECV: %s", tc_record)
                self.consumer.add_tc_record(tc_record)
                self.consumer.result.totals += 1
                self.consumer.tr_queue.task_done()

                assert self.consumer.totals != 0
                completion = round(float(self.consumer.result.totals) / float(self.consumer.totals) * 100, 2)
                remain = self.consumer.totals - self.consumer.result.totals
                logger.debug("*** Completion: %s%%, Remain: %s", completion, remain)

                failed = tc_record.status in (tc_record.Status.FAILED, tc_record.Status.ERRONEOUS)
                if self.consumer.result.failfast and failed:
                    self.consumer.abort()
            finally:
                if self.should_stop.is_set():
                    break

    def stop(self) -> NoReturn:
        self.consumer.tr_queue.join()
        self.should_stop.set()
        self.join()


class MultiProcessQueueTestConsumer:
    """
    Used create multi-processes to run tests, and collect the result.

    Parameters
    ----------
    processes: int
        process count to create.

    result: TestResult, optional
        TestResult to store all records of testsuites and testcases.

    context: TestContext, optional
         Used to specified testbench and event observable.

    log_level: str, int, optional
         Log level.

    log_layout: str, optional
         Log layout.
    """

    def __init__(self,
                 processes: int,
                 result: TestResult = None,
                 context: TestContext = None,
                 log_level: str | int = None,
                 log_layout: str = None
                 ):
        self._context = context
        self.result = result or TestResult()
        self.tc_queue = multiprocessing.JoinableQueue()
        self.tr_queue = multiprocessing.JoinableQueue()
        self._testsuites = []
        self._tc_records = {}
        self.runners = []
        self.totals = 0
        self.log_level = log_level
        self.log_layout = log_layout

        if self._context is not None:
            interceptor = TestRecordQueueInterceptor(self.tr_queue)
            self._context.event_observable.attach(interceptor)

        for i in range(processes):
            # Handle failfast when receiving record from record_queue
            # So don't assign failfast param for process.
            pid = f"Process-{i+1}"
            runner = QueueTestConsumerProcess(self.tc_queue, id=pid, context=self._context,
                                              log_level=self.log_level, log_layout=self.log_layout)
            self.runners.append(runner)

    @property
    def context(self):
        return self._context

    def add_testsuite(self, testsuite: TestSuiteModel) -> NoReturn:
        self._testsuites.append(testsuite)
        self._assign_id_for_test(testsuite)
        self._extract_testsuite_into_queue(testsuite)

    def add_tc_record(self, tc_record: TestCaseResultRecord):
        self._tc_records[tc_record.id] = tc_record

    def abort(self) -> NoReturn:
        for runner in self.runners:
            runner.abort()

    def pause(self) -> NoReturn:
        for runner in self.runners:
            runner.pause()

    def resume(self) -> NoReturn:
        for runner in self.runners:
            runner.resume()

    @staticmethod
    def _is_combined_testsuite(testsuite: TestSuiteModel) -> bool:
        for test in testsuite.tests:
            if getattr(test, "is_prerequisite", False):
                return True
        return False

    def _assign_id_for_test(self, test: TestSuiteModel) -> NoReturn:
        if is_testsuite_model(test):
            test.id = fetch_current_testsuite_id()
            for test in test.tests:
                self._assign_id_for_test(test)
        else:
            self.totals += 1
            test.id = fetch_current_testcase_id()

    def _extract_testsuite_into_queue(self, testsuite: TestSuiteModel) -> NoReturn:
        if self._is_combined_testsuite(testsuite):
            logger.debug("Add testsuite %s", testsuite)
            self.tc_queue.put(testsuite)
        else:
            for index, test in enumerate(testsuite.tests):
                if "tests" in test:
                    self._extract_testsuite_into_queue(test)
                else:
                    logger.debug("Add testcase %s", test)
                    self.tc_queue.put(test)

    def run(self):
        thread = _TestRecordQueueConsumeThread(self)
        thread.start()
        try:
            # only set result.started_at when it is empty.
            # when there are multiple runners defined in config yml, result.started_at would be set by previous runner.
            if not self.result.started_at:
                self.result.started_at = datetime.now(timezone.utc).astimezone()

            for runner in self.runners:
                runner.start()

            while True:
                remain = []
                for runner in self.runners:
                    if runner.is_stopped():
                        runner.shutdown()
                        runner.join()
                    else:
                        remain.append(runner)
                if not remain:
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            for runner in self.runners:
                runner.shutdown()
                runner.join()
        finally:
            self.result.stopped_at = datetime.now(timezone.utc).astimezone()
            thread.stop()

            for testsuite in self._testsuites:
                ts_record = self.generate_testsuite_record(testsuite, self._tc_records)
                self.result.add_testsuite_record(ts_record)

    def generate_testsuite_record(self, testsuite: TestSuiteModel, testcase_record_mapping: dict = None) -> TestSuiteResultRecord:
        testsuite_id = testsuite.id or uuid.uuid1()
        testsuite_name = testsuite.name
        testsuite_record = TestSuiteResultRecord(testsuite_id=testsuite_id, name=testsuite_name)
        for test in testsuite.tests:
            if "tests" in test:
                testsuite_record.add_sub_test_record(
                    self.generate_testsuite_record(test, testcase_record_mapping)
                )
            else:
                test_id = test.id
                if test_id in testcase_record_mapping:
                    testsuite_record.add_sub_test_record(testcase_record_mapping[test_id])
                else:
                    testcase_record = TestCaseResultRecord(id=test_id)
                    testcase_record.name = test.name or '.'.join(test.path.split('.')[-2:])
                    testcase_record.path = test.path
                    testsuite_record.add_sub_test_record(testcase_record)
        return testsuite_record


TestProgressMessage = collections.namedtuple('TestProgressMessage', ['process', 'type', 'data', 'progress'])


class TestProgressMessageQueueInterceptor(TestEventHandler):
    def __init__(self, q: queue.Queue | multiprocessing.queues.Queue):
        super().__init__()
        self.queue = q
        self._result = None
        self._totals = 0
        self._counts = 0

    def on_testrunner_started(self, event) -> NoReturn:
        runner = event.target         # type: TestRunner
        self._result = runner.result
        self._totals = self._result.statistics().totals

    def on_testcase_stopped(self, event) -> NoReturn:
        testcase = event.target
        record = testcase.record
        self._counts += 1
        progress = self._counts / self._totals
        msg = TestProgressMessage(get_current_process_name(), EventType.ON_TESTCASE_STOPPED, record, progress)
        # logger.debug("SEND: %s", msg)
        self.queue.put(msg)

    def on_testrunner_stopped(self, event) -> NoReturn:
        runner = event.target         # type: TestRunner
        result = runner.result
        msg = TestProgressMessage(get_current_process_name(), EventType.ON_TESTRUNNER_STOPPED, result, 1)
        # logger.debug("SEND: %s", msg)
        self.queue.put(msg)

    def __str__(self):
        return f"<{self.__class__.__name__}(queue:{self.queue})>"


class RunnersBundle:
    def __init__(self, result, runners):
        self._result = result
        self._m_process_runners = []
        self._s_process_runners = {}
        self._s_queue = multiprocessing.Queue()
        for runner in runners:
            if hasattr(runner, 'start'):
                runner._context.event_observable.attach(TestProgressMessageQueueInterceptor(self._s_queue))
                self._s_process_runners[runner.id] = runner
            else:
                self._m_process_runners.append(runner)

    def _shutdown_all_sub_process_runners(self, wait=True):
        for runner in self._s_process_runners.values():
            runner.shutdown()
            if wait:
                runner.join()

    def _run_runners_in_main_process(self, is_prerequisite):
        # test result has already in main process runner, so don't need to merge result again.
        for runner in self._m_process_runners:
            try:
                if runner.is_prerequisite == is_prerequisite:
                    runner.run()
            except Exception as err:
                logger.exception(str(err))

    def start(self):
        try:
            self._run_runners_in_main_process(is_prerequisite=True)

            for runner in self._s_process_runners.values():
                runner.start()

            self._run_runners_in_main_process(is_prerequisite=False)
        except KeyboardInterrupt:
            self._shutdown_all_sub_process_runners()
            for runner in self._m_process_runners:
                runner.abort()

    def join(self):
        results = {}
        while len(results) != len(self._s_process_runners):
            try:
                msg = self._s_queue.get(timeout=1)        # type: TestProgressMessage
            except queue.Empty:
                pass
            except KeyboardInterrupt:
                for i, runner in enumerate(self._s_process_runners):
                    runner.abort()
            else:
                if msg.type == EventType.ON_TESTCASE_STOPPED:
                    logger.info('*** PROCESS(%s) completion percentage: %.1f%%', msg.process, msg.progress * 100)
                else:
                    results[msg.process] = msg.data
                    logger.info('*** PROCESS(%s) stopped!', msg.process)

        for name in self._s_process_runners.keys():
            try:
                result = results[name]
                self._result.extend(result)
            except KeyError:
                pass

        self._shutdown_all_sub_process_runners()
