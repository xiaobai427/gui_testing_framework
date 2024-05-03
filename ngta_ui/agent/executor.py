# coding: utf-8

import io
import json
import requests
import threading
import time
import uuid
import socket
import datetime
import amqp
import yaml
import kombu
import kombu.exceptions

from pprint import pformat
from datetime import datetime, timezone
from typing import NoReturn, Sequence, Dict, List, Tuple, Optional, Type, Union

from .bench import TestBench
from .. import TestContext
from ..events import TestEventHandler, TestCaseStartedEvent, TestCaseStoppedEvent, EventNotifyError
from ..environment import WorkEnv
from ..consumer import BaseTestConsumer
from ..concurrent import TestRunnerProcess, get_testrunner_params
from ..context import current_context
from ..case import TestCase, TestCaseModel, sign_params, TestCaseResultStatus
from ..suite import TestSuiteModel, TestModelType
from ..assertions import ErrorInfo

import logging
logger = logging.getLogger(__name__)


NODE = f"{uuid.getnode():x}"
HOSTNAME = socket.gethostname()
AMQP_CONSUMER_DEFAULT_HEARTBEAT = 60
AMQP_CONSUMER_DEFAULT_PREFETCH_COUNT = 1

STR_TO_BOOL_MAPPING = {
    "true": True,
    "false": False,
}


class NoNeedToRun(Exception):
    pass


def dispatch_testrecord_err_by_model(context, model: TestModelType, err):
    if isinstance(model, TestCaseModel):
        testbench = context.testbench

        testcase = TestCase('',
                            id=model.id,
                            name=model.name,
                            parameters=model.parameters,
                            is_prerequisite=model.is_prerequisite,
                            enable_mock=model.enable_mock)
        testcase.record.path = model.path
        testcase.record.status = TestCase.Record.Status.ERRONEOUS
        testcase.record.error = ErrorInfo.from_exception(err)
        testcase.record.started_at = datetime.now(timezone.utc).astimezone()
        testcase.record.testbench_name = testbench.name
        testcase.record.testbench_type = testbench.type
        context.dispatch_event(TestCaseStartedEvent(testcase))
        testcase.record.stopped_at = datetime.now(timezone.utc).astimezone()
        context.dispatch_event(TestCaseStoppedEvent(testcase))
    else:
        for m in model.tests:
            dispatch_testrecord_err_by_model(context, m, err)


def try_convert_params(func, parameters: dict) -> dict:
    new_parameters = {}
    for k, v in parameters.items():
        if isinstance(v, str):
            try:
                with io.StringIO(v) as f:
                    v = yaml.load(f, Loader=yaml.Loader)
            except yaml.YAMLError:
                logger.warning("try convert %r failed", v)
        new_parameters[k] = v

    return sign_params(func, new_parameters)


def get_conn_id(conn):
    return conn.connection._connection_id


def check_testcase_should_be_run(magna_url, model: TestCaseModel) -> bool:
    url = f"{magna_url}/testrecords/{model.id}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        if resp.ok:
            data = resp.json()
            if data["status"] == TestCaseResultStatus.NOT_RUN.value:
                logger.debug("%s not run yet", model.id)
                return True
            elif data["status"] == TestCaseResultStatus.CANCELED.value:
                logger.debug("%s has already been canceled, skip it.", model.id)
                return False
            else:
                logger.debug("%s had already been executed, skip it.", model.id)
                return False
    except requests.exceptions.RequestException as err:
        logger.exception("request %s error: %s", url, err)
        return False


def remove_executed_tests_from_testsuite_model(magna_url: str, model: TestSuiteModel):
    logger.debug("filter not run tests from testsuite model: %s", model)
    tests = []
    for sub_test in model.tests:
        if isinstance(sub_test, TestSuiteModel):
            remove_executed_tests_from_testsuite_model(magna_url, sub_test)
            tests.append(sub_test)
        else:
            should_run = check_testcase_should_be_run(magna_url, sub_test)
            if should_run:
                tests.append(sub_test)
    model.tests = tests


class HeartbeatThread(threading.Thread):
    def __init__(self, conn):
        super().__init__()
        self._conn = conn
        self._should_stop = threading.Event()

    def run(self):
        logger.debug("start heartbeat thread for %s", self._conn)
        prev_ts = time.time()
        while not self._should_stop.wait(1):
            curt_ts = time.time()
            if curt_ts - prev_ts > self._conn.heartbeat / 2:
                logger.debug("sending amqp heartbeat for %s", get_conn_id(self._conn))
                try:
                    self._conn.connection.frame_writer(8, 0, None, None, None)
                except Exception as err:
                    logger.error("sending amqp heartbeat failed: %s, thread exiting...", err)
                    raise
                finally:
                    prev_ts = curt_ts

    def stop(self, wait=False):
        logger.debug("stopping heartbeat thread.")
        self._should_stop.set()
        if wait:
            self.join()


class DryIndexedQueueConsumer(kombu.Consumer):
    # make sure higher priority queue consumed first, and then consume lower priority queues.
    def consume(self, no_ack=None):
        # cancel previous consume to make sure each loop consume the queues according to the priority.
        self.cancel()

        queues = list(self._queues.values())
        if queues:
            no_ack = self.no_ack if no_ack is None else no_ack

            for queue in queues:
                try:
                    ret = queue.queue_declare(passive=True)
                    if ret.message_count == 0:
                        continue
                    else:
                        self._basic_consume(queue, no_ack=no_ack, nowait=False)
                        break
                except (amqp.ConsumerCancelled, amqp.NotFound) as err:
                    logger.error(err)


class AmqpTestConsumer(BaseTestConsumer):
    def __init__(self,
                 url: str,
                 queues: List[kombu.Queue],
                 passive: bool = False,
                 auto_stop: bool = False,
                 heartbeat: int = AMQP_CONSUMER_DEFAULT_HEARTBEAT,
                 magna_url: str = None,
                 prefetch_count: int = AMQP_CONSUMER_DEFAULT_PREFETCH_COUNT,
                 consumer_class: Type[kombu.Consumer] = kombu.Consumer,
                 *args, **kwargs
                 ):
        super().__init__(*args,  **kwargs)
        self._conn = kombu.Connection(url, heartbeat=heartbeat)
        self._queues = queues
        self._passive = passive
        self._heartbeat = heartbeat
        self._magna_url = magna_url
        self._prefetch_count = prefetch_count
        self._consumer_class = consumer_class
        self.auto_stop: bool = auto_stop
        self.is_busy: Optional[bool] = None      # will be got by process pipe. Maybe none if testbench start failed.

        self._heartbeat_thread = HeartbeatThread(self._conn)
        self._should_stop = False

    def _consume(self):
        self.is_busy = False
        self._conn.ensure_connection(errback=self._on_connection_error)
        for queue in self._queues:
            queue.maybe_bind(self._conn)
            queue.queue_declare(passive=self._passive)
            queue.queue_bind()

        heartbeat = HeartbeatThread(self._conn)
        heartbeat.start()

        logger.debug("Start consume from queues: \n%s", pformat(self._queues))

        consumer = self._consumer_class(
            self._conn,
            queues=self._queues,
            no_ack=False,
            accept=['json'],
            auto_declare=False,
            on_decode_error=self._on_message_decode_error,
            prefetch_count=self._prefetch_count
        )
        consumer.register_callback(self.on_message)

        try:
            while not self._should_stop:
                should_revive = False
                try:
                    consumer.consume()
                    self._conn.drain_events(timeout=1)
                except TimeoutError:
                    logger.debug("drain_events timeout from %s, continue", get_conn_id(self._conn))
                except Exception as err:
                    logger.exception("%s", err)
                    should_revive = True
                finally:
                    self._conn.ensure_connection(errback=self._on_connection_error)
                    if not heartbeat.is_alive():
                        # heartbeat thread also maybe encounter error which will cause thread exit.
                        # at this scenario, should restart heartbeat thread and revive consumer.
                        should_revive = True
                        logger.warning("heartbeat thread is not alive, restart it...")
                        heartbeat.stop(wait=True)
                        heartbeat = HeartbeatThread(self._conn)
                        heartbeat.start()

                    if should_revive:
                        logger.debug("revive consumer from %s", get_conn_id(self._conn))
                        consumer.revive(self._conn)

                    self._try_auto_stop()
        finally:
            logger.debug("consumer exiting.")
            consumer.cancel()
            heartbeat.stop()
            self._conn.close()

    def _try_auto_stop(self):
        if self.auto_stop:
            empty = []
            for queue in self._queues:
                try:
                    ret = queue.queue_declare(passive=True)
                    if ret.message_count == 0:
                        logger.debug("%s is empty.", queue)
                        empty.append(queue)
                except (amqp.ConsumerCancelled, amqp.NotFound) as err:
                    logger.error(err)

            if len(empty) == len(self._queues):
                logger.debug("All queues in consumer are empty, exiting.")
                self._should_stop = True

    @staticmethod
    def _on_message_decode_error(message, exc):
        logger.error(
            "Can't decode message body: %r (type:%r encoding:%r raw:%r')",
            exc, message.content_type, message.content_encoding, message.body
        )
        message.reject()

    @staticmethod
    def _on_connection_error(exc, interval):
        logger.error("Broker connection error, trying again in %s seconds: %r.", interval, exc)

    def on_message(self, body, message) -> NoReturn:
        if self._should_stop:
            return

        logger.debug("RECEIVE MESSAGE: %s", body)
        self.is_busy = True
        try:
            data = json.loads(body) if isinstance(body, (str, bytes)) else body
            conf = data.pop("config", {})

            if "tests" in data:
                model = TestSuiteModel(**data)

                if self._magna_url:
                    remove_executed_tests_from_testsuite_model(self._magna_url, model)

                if model.count_testcases() == 0:
                    raise NoNeedToRun(f"don't need to run {model}, because it is empty")
            else:
                model = TestCaseModel(**data)
                if self._magna_url and not check_testcase_should_be_run(self._magna_url, model):
                    raise NoNeedToRun(f"don't need to run {model}")
        except NoNeedToRun as err:
            logger.warning("%s", err)
            logger.info("ack message: %s", message)
            message.ack()
        except KeyboardInterrupt:
            logger.error('KeyboardInterrupt!')
            logger.error("requeue message: %s", message)
            message.requeue()
            self.abort()
        except Exception as err:
            logger.error("%s", err)
            logger.error("reject message: %s", message)
            message.reject()
        else:
            self._execute_test(current_context(), message, model, conf)
        finally:
            self.is_busy = False
            if self.result.should_abort:
                logger.debug("set should_stop to true for exiting consumer")
                self._should_stop = True     # set ConsumerMixin.should_stop to true for exiting consumer.
            else:
                while self.result.should_pause:
                    time.sleep(self.result.PAUSE_INTERVAL)

    def _execute_test(self, context, message, model, conf):
        testbench: TestBench = context.testbench
        try:
            test = model.as_test(params_signature=try_convert_params)
        except Exception as err:
            logger.exception(err)
            logger.warning("ack message: %s", message)

            # Don't reject the message here, rejected message will route to DLX queue and processed by manga.
            # Manga will set testrecord to rejected, and this is conflict with following testrecord dispatched.
            message.ack()
            dispatch_testrecord_err_by_model(context, model, err)
        except KeyboardInterrupt:
            logger.error('KeyboardInterrupt when constructing model as test')
            logger.warning("requeue message: %s", message)
            message.requeue()

            self.abort()
        else:
            try:
                logger.debug("invoke on_agent_exec_test_begin: %s, %s", test, conf)
                testbench.on_agent_exec_test_begin(test, conf)
            except Exception as err:
                logger.exception(err)
                test.skip_test(str(err))

                logger.info("ack message: %s", message)
                message.ack()
            except KeyboardInterrupt:
                logger.error('KeyboardInterrupt when invoking on_agent_exec_test_begin')
                logger.warning("requeue message: %s", message)
                message.requeue()
                self.abort()
            else:
                try:
                    self._testsuite.run_test(test, self.result)
                except EventNotifyError:
                    logger.error('EventNotifyError when running %s', test)
                    logger.info("ack message: %s", message)
                    message.ack()
                except KeyboardInterrupt:
                    logger.error('KeyboardInterrupt when running %s', test)
                    logger.warning("requeue message: %s", message)
                    message.requeue()
                    self.abort()
                except Exception as err:
                    logger.exception(err)
                    logger.error("reject message: %s", message)
                    message.reject()
                else:
                    logger.info("ack message: %s", message)
                    message.ack()
            finally:
                logger.debug("invoke on_agent_exec_test_end: %s, %s", test, conf)
                testbench.on_agent_exec_test_end(test, conf)


class AmqpTestConsumerProcess(TestRunnerProcess):
    def __init__(self,
                 url: str,
                 queues,
                 passive: bool = False,
                 auto_stop: bool = False,
                 heartbeat: int = AMQP_CONSUMER_DEFAULT_HEARTBEAT,
                 magna_url: str = None,
                 prefetch_count: int = AMQP_CONSUMER_DEFAULT_PREFETCH_COUNT,
                 consumer_class: Type[kombu.Consumer] = kombu.Consumer,
                 *args, **kwargs
                 ):
        super().__init__(*args, **kwargs)
        self._url = url
        self._queues = queues
        self._heartbeat = heartbeat
        self._magna_url = magna_url
        self._prefetch_count = prefetch_count
        self._consumer_class = consumer_class
        self._passive = passive
        self._auto_stop = auto_stop
        self._params = get_testrunner_params(*args, **kwargs)
        self._start_time = datetime.now()
        context = self._params["context"]
        self._bench = context.testbench if context.testbench else None
        self._is_busy = None

    def is_busy(self) -> bool | None:
        try:
            self._is_busy = self._pipe("is_busy")       # Get is_busy from AmqpTestConsumer
        except TestRunnerProcess.PipeCallError:
            self._is_busy = None
        return self._is_busy

    def _create_inner_testrunner(self) -> AmqpTestConsumer:
        queues = []
        # sort queue here
        for queue_opts in sorted(self._queues, key=lambda q: q.pop("priority", 0)):
            queue_name = queue_opts.pop("name")
            queue = kombu.Queue.from_dict(queue_name, **queue_opts)
            queues.append(queue)

        return AmqpTestConsumer(
            self._url, queues, self._passive, self._auto_stop, self._heartbeat,
            self._magna_url, self._prefetch_count, self._consumer_class,
            **self._params
        )

    def as_dict(self) -> dict:
        return dict(
            pid=self.pid,
            name=self.name,
            url=self._url,
            queues=self._queues,
            is_stopped=self._is_stopped,
            is_busy=self._is_busy,
            testbench_name=self._bench.name if self._bench else None,
            testbench_type=self._bench.type if self._bench else None,
            testbench_node=self._bench.node if self._bench else None,
            testbench_group=self._bench.group if self._bench else None,
            hostname=HOSTNAME,
            start_time=self._start_time.isoformat(),
            prefetch_count=self._prefetch_count,
        )


class AmqpMultiProcessExecutor(threading.Thread):
    BASE_QUEUE_TEMPLATE = "bench.{}"

    def __init__(self,
                 work_env: WorkEnv,
                 benches: List[TestBench],
                 url: str,
                 topic: str,
                 dlx_topic: str,
                 heartbeat: int = AMQP_CONSUMER_DEFAULT_HEARTBEAT,
                 magna_url: str = None,
                 consumer_timeout: int = None,
                 observers: Sequence[TestEventHandler] = None,
                 runner_recover_interval: float = 5,
                 runner_recover_attempts: int = 10,
                 ):
        super().__init__()
        self.work_env = work_env
        self.url = url
        self.topic = topic
        self.dlx_topic = dlx_topic
        self.heartbeat = heartbeat
        self.magna_url = magna_url
        self.consumer_timeout = consumer_timeout
        self.observers = observers or []
        self.runner_recover_interval = runner_recover_interval
        self.runner_recover_attempts = runner_recover_attempts
        self._runners: Dict[str, List[AmqpTestConsumerProcess]] = {}     # bench name to bench's runners mapping
        self._benches: Dict[str, TestBench] = {}
        self._lock = threading.RLock()
        self._should_stop = threading.Event()

        for bench in benches:
            self._benches[bench.name] = bench

    @property
    def runners(self) -> List[AmqpTestConsumerProcess]:
        with self._lock:
            runners = []
            for bench_runners in self._runners.values():
                runners.extend(bench_runners)
        return runners

    @property
    def benches(self) -> Tuple[TestBench]:
        with self._lock:
            return tuple(self._benches.values())

    def is_testbench_online(self, testbench) -> bool:
        with self._lock:
            runners = self._runners.get(testbench.name, [])
        return bool(runners)

    def update_testbench_state(self, name, state):
        testbench = self._benches[name]
        if state == testbench.State.RESERVED and self.is_testbench_online(testbench):
            self._delete_runners_by_testbench(testbench)
        elif state == testbench.State.IDLE and not self.is_testbench_online(testbench):
            self._create_runners_by_testbench(testbench)
        else:
            pass
        testbench.state = state

    def dump_testbenches(self):
        dataset = []
        for bench in self._benches.values():
            record = bench.as_record()
            if record:                      # only dump if record exists, because fake testbench don't need to dump
                data = bench.as_record().dict(exclude={'path', '()'})
                data["git_commit"] = self.work_env.get_current_commit()
                dataset.append(data)
        return dataset

    def dump_testrunners(self):
        return [runner.as_dict() for runner in self.runners]

    def _new_context(self, testbench) -> TestContext:
        context = TestContext()
        context.testbench = testbench

        observers = []
        observers.extend(self.observers)
        for observer in observers:
            context.event_observable.attach(observer)
        return context

    def _new_process(self, name, testbench) -> AmqpTestConsumerProcess:
        consumer_class = DryIndexedQueueConsumer if testbench.consumer_priority_strategy else kombu.Consumer
        return AmqpTestConsumerProcess(
            self.url,
            testbench.queues,
            heartbeat=self.heartbeat,
            magna_url=self.magna_url,
            prefetch_count=testbench.consumer_prefetch_count,
            consumer_class=consumer_class,
            id=name,
            context=self._new_context(testbench)
        )

    def _create_runners_by_testbench(self, testbench: TestBench):
        testbench.queues.clear()
        for i, queue_name in enumerate(testbench.get_queue_names()):
            queue_args = {
                "x-dead-letter-exchange": self.dlx_topic,
                "x-dead-letter-routing-key": testbench.dlx_routing_key,
                # "x-max-priority": 255,
                # 'x-message-ttl': self.ttl,               # Set all messages' TTL in this queue.
            }

            consumer_timeout = self.consumer_timeout
            if testbench.consumer_timeout:
                consumer_timeout = testbench.consumer_timeout

            if consumer_timeout:
                queue_args["x-consumer-timeout"] = consumer_timeout * 1000      # consumer ack message timeout

            queue_opts = dict(
                name=queue_name,
                exchange=self.topic,
                exchange_type='topic',
                exchange_durable=True,
                routing_key=queue_name,
                auto_delete=False,
                queue_arguments=queue_args,
                priority=i,
            )

            testbench.queues.append(queue_opts)

        with self._lock:
            runners = self._runners.setdefault(testbench.name, [])

        process_count = testbench.workers
        for i in range(process_count):
            runner_name = f'{testbench.name}@{testbench.type}-{i}'
            runner_proc = self._new_process(runner_name, testbench)
            runner_proc.start()
            runners.append(runner_proc)

    def _delete_runners_by_testbench(self, testbench: TestBench, wait: float = None):
        logger.info("Stop runners by testbench: %s", testbench.name)
        with self._lock:
            runners = self._runners.pop(testbench.name, [])

        for runner in runners:
            logger.debug("Shutdown %s.", runner)
            runner.shutdown(wait)

    def run(self) -> None:
        for testbench in self._benches.values():
            self._create_runners_by_testbench(testbench)

        recovered_runner_counts = {}

        # 1. update testbench state
        # 2. try restore testrunner process if it is not alive.
        while not self._should_stop.wait(self.runner_recover_interval):
            with self._lock:
                runners_kv = self._runners.copy()

            for bench_name, old_runners in runners_kv.items():
                testbench = self._benches[bench_name]

                # ONLY exclusive testbench have state
                if testbench.exclusive:
                    try:
                        runner = old_runners[0]
                        match runner.is_busy():
                            case None:
                                testbench.state = TestBench.State.OFFLINE
                            case True:
                                testbench.state = TestBench.State.BUSY
                            case False:
                                testbench.state = TestBench.State.IDLE
                    except IndexError:
                        testbench.state = TestBench.State.OFFLINE

                new_runners = []
                for old_runner in old_runners:
                    if old_runner.is_alive() and not old_runner.is_stopped():
                        new_runners.append(old_runner)
                        recovered_runner_counts[old_runner.name] = 0        # reset count to 0 if runner is alive
                    else:
                        logger.warning("runner %s is not alive, shutdown it.", old_runner)
                        old_runner.shutdown()

                        runner_name = old_runner.name
                        if recovered_runner_counts.setdefault(old_runner.name, 0) < self.runner_recover_attempts:
                            new_runner = self._new_process(runner_name, testbench)
                            new_runner.start()
                            new_runners.append(new_runner)
                            logger.debug("recover %s a new runner: %s", runner_name, new_runner)

                            recovered_runner_counts[runner_name] += 1
                        else:
                            logger.info("%s reach max recover attempts %s, don't recover it",
                                        runner_name, self.runner_recover_attempts)

                with self._lock:
                    self._runners[bench_name] = new_runners

    def stop(self, wait: float = None) -> None:
        self._should_stop.set()
        for testbench in self._benches.values():
            self._delete_runners_by_testbench(testbench, wait)
        logger.info("Executor exit successfully.")
