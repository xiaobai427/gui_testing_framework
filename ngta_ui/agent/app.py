# coding: utf-8

import os
import sys
import uuid
import json
import signal
import asyncio

import yaml
import etcd3gw
from etcd3gw.exceptions import Etcd3Exception

from typing import NoReturn
from tornado import ioloop
from tornado import web
from .executor import AmqpMultiProcessExecutor
from .resources import test
from .setting import AgentSetting, BenchSetting
from ..environment import WorkEnv
from ..constants import DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT, PACKAGE_NAME

import logging
import logging.config
logger = logging.getLogger(__name__)


if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Application(web.Application):
    def __init__(self, work_env: WorkEnv, executor: AmqpMultiProcessExecutor):
        self.work_env = work_env
        self.executor = executor
        handlers = [
            (r"/api/testbenches", test.TestBenchListResource),
            (r"/api/testbenches/(.+)", test.TestBenchDetailResource),
            (r"/api/testrunners", test.TestRunnerListResource),
            (r"/api/testhierarchy/?", test.TestHierarchyResource),
            (r"/api/testcases/?", test.TestCaseListResource),
            (r"/api/testcases/(.+)", test.TestCaseDetailResource),
        ]
        web.Application.__init__(self, handlers)


NODE = uuid.getnode()


class TestAgent:
    ETCD_BENCHES_KEY = f"/{PACKAGE_NAME}/benches/{NODE:x}"
    ETCD_RUNNERS_KEY = f"/{PACKAGE_NAME}/runners/{NODE:x}"
    ETCD_TTL = 20

    def __init__(self, work_env: WorkEnv, agent_yml=None, bench_yml=None, trace_yml=None):
        self.work_env = work_env
        self.agent_yml = agent_yml or self.work_env.work_dir.joinpath("conf", "agent.yml")
        self.bench_yml = bench_yml or self.work_env.work_dir.joinpath("conf", "bench.yml")
        self.trace_yml = trace_yml or self.work_env.work_dir.joinpath("conf", "logging.yml")
        self.agent_setting = AgentSetting(self.agent_yml)
        self.bench_setting = BenchSetting(self.bench_yml)
        self.executor = AmqpMultiProcessExecutor(
            self.work_env, self.bench_setting.get_testbenches(), **self.agent_setting.get("executor")
        )
        self.webapp = Application(self.work_env, self.executor)

        self.exiting = False
        self.etcd = etcd3gw.client(**self.agent_setting.get("etcd"))

        self._leases = {}

    def startup(self) -> NoReturn:
        self._enable_logging()

        status = self.etcd.status()
        logger.debug("Query ETCD status successful: %s", status)

        self.webapp.listen(**self.agent_setting.get("webapp.listen"))
        self.executor.start()

        # always dump testrunners before testbenches, because the testbench.state will be updated by testrunner.
        if self.executor.runners:
            self._leases[self.ETCD_RUNNERS_KEY] = self.etcd.lease(self.ETCD_TTL)
            ioloop.PeriodicCallback(
                lambda: self._set_etcd_value(self.ETCD_RUNNERS_KEY, self.executor.dump_testrunners),
                self.ETCD_TTL * 500     # milliseconds, half duration of ETCD TTL
            ).start()

        if self.executor.benches:
            self._leases[self.ETCD_BENCHES_KEY] = self.etcd.lease(self.ETCD_TTL)
            ioloop.PeriodicCallback(
                lambda: self._set_etcd_value(self.ETCD_BENCHES_KEY, self.executor.dump_testbenches),
                self.ETCD_TTL * 500     # milliseconds, half duration of ETCD TTL
            ).start()

        signal.signal(signal.SIGTERM, self._sig_exit_handler)
        signal.signal(signal.SIGINT, self._sig_exit_handler)
        ioloop.PeriodicCallback(self._try_exit, 500).start()

        ioloop.IOLoop.current().start()

    def shutdown(self) -> NoReturn:
        ioloop.IOLoop.current().stop()
        self.executor.stop(5)
        logging.info('TestAgent exit success!')

    def _set_etcd_value(self, key, dump_method):
        old_value = []
        lease = self._leases[key]
        try:
            for item in self.etcd.get(key):
                if isinstance(item, bytes):
                    old_value.extend(json.loads(item))
                elif isinstance(item, dict):
                    old_value.extend(item)
                else:
                    raise NotImplementedError
            logger.debug('GET etcd key: %s, value: %s', key, old_value)

            new_value = dump_method()
            if new_value != old_value:
                logger.debug('The values are not same of etcd key: %s, update with: %s', key, new_value)
                resp = self.etcd.put(key, json.dumps(new_value), lease=lease)
                logger.debug('PUT etcd key: %s, resp: %s', key, resp)
        except Etcd3Exception:
            logger.exception("encounter error, retry...")
            self._leases[key] = self.etcd.lease(self.ETCD_TTL)
            self._set_etcd_value(key, dump_method)
        else:
            lease.refresh()

    def _try_exit(self) -> NoReturn:
        if self.exiting:
            self.shutdown()

    def _sig_exit_handler(self, signum, frame) -> NoReturn:
        logging.info("Receive (%d), exiting...", signum)
        self.exiting = True

    def _enable_logging(self) -> NoReturn:
        if os.path.exists(self.trace_yml):
            with open(self.trace_yml, "r", encoding='utf-8') as f:
                log_conf = yaml.load(f.read(), Loader=yaml.Loader)
            logging.config.dictConfig(log_conf)
        else:
            logging.basicConfig(level=DEFAULT_LOG_LEVEL, format=DEFAULT_LOG_LAYOUT)
            logger.debug("%s not exists, use basic logging config.", self.trace_yml)
