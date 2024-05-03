import logging
import logging.handlers
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread

from ngta_ui import TestContext, TestCase
from ngta_ui.context import register_context
from ngta_ui.interceptor import LogLevelType
from ngta_ui.constants import FilePathType, DEFAULT_LOG_LEVEL, DEFAULT_LOG_LAYOUT
from ngta_ui.events import (
    TestEventHandler,
    TestCaseStartedEvent, TestCaseStoppedEvent
)

import os
from datetime import datetime

from multiprocessing import Lock, Process

from pathlib import Path
from typing import NoReturn, Union

from coupling import log

logger = logging.getLogger(__name__)
LOG_DIR = Path(__file__).parent.parent


class ThreadNamePrefixFilter(logging.Filter):
    def __init__(self, prefix=None, include_main=True):
        super().__init__()
        self.prefix = prefix
        self.include_main = include_main

    def filter(self, record):
        return self.prefix in record.threadName or self.include_main and record.threadName == "MainThread"


class TestCaseLogFileInterceptor(TestEventHandler):
    _lock = Lock()

    def __init__(self,
                 log_dir: FilePathType,
                 log_level: LogLevelType = DEFAULT_LOG_LEVEL,
                 log_layout: str = DEFAULT_LOG_LAYOUT,
                 max_bytes: int = 50000000,
                 backup_count: int = 99,
                 # postfix: str = "ident"
                 postfix: str = "index"
                 ):
        super().__init__()
        self.log_dir = Path(log_dir).joinpath("logs")
        self.log_level = log_level
        self.log_layout = log_layout
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.postfix = postfix
        self._consumer_log_dirs = {}
        if not self.log_dir.exists():
            os.mkdir(self.log_dir)

    def __str__(self):
        return f"<{self.__class__.__name__}(log_dir:{self.log_dir}, log_level:{self.log_level})>"

    def on_testcase_started(self, event: TestCaseStartedEvent) -> NoReturn:
        testcase: TestCase = event.target

        if not testcase.log_path:
            timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
            if not Path(self.log_dir.joinpath(timestamp)).exists():
                os.mkdir(Path(self.log_dir.joinpath(timestamp)))
                os.mkdir(Path(self.log_dir.joinpath(timestamp)).joinpath(testcase.get_default_name()))
            log_path = Path(self.log_dir.joinpath(timestamp)).joinpath(testcase.get_default_name())
            testcase.log_path = log_path.joinpath(testcase.eval_log_name(self.postfix))
        testcase.log_handler = logging.handlers.RotatingFileHandler(str(testcase.log_path),
                                                                    maxBytes=self.max_bytes,
                                                                    backupCount=self.backup_count,
                                                                    delay=True)
        log.add_log_handler(testcase.log_handler, self.log_level, self.log_layout)

    def on_testcase_stopped(self, event: TestCaseStoppedEvent) -> NoReturn:
        testcase: TestCase = event.target
        log_handler = getattr(testcase, "log_handler", None)
        if log_handler:
            log.remove_log_handler(log_handler)


class ThreadLauncher:
    def __init__(self, testbench, test_class, max_workers=10, *args, **kwargs):
        self.current_thread = None
        self.lock = Lock()
        self.test_class = test_class
        self.testbench = testbench(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def _execute(self, method_name, index=0, parameters=None):
        time.sleep(0.1)
        with self.lock:
            test_context = TestContext(testbench=self.testbench)
            test_case_log_file_interceptor = TestCaseLogFileInterceptor(log_dir=LOG_DIR)
            test_context.event_observable.attach(test_case_log_file_interceptor)
            register_context(test_context)
            test_instance = self.test_class(method_name=method_name, index=index, parameters=parameters)
            test_instance.run()

    def launch(self, method_name, index=0, parameters=None):
        # 使用线程池来调度任务，锁保护资源
        self.executor.submit(self._execute, method_name, index, parameters)

# class ThreadLauncher:
#     def __init__(self, chip, test_class, device_base, slave_instrument_list=None, message_box=None, max_workers=1):
#         self.chip = chip
#         self.test_class = test_class
#         self.device_base = device_base
#         self.slave_instrument_list = slave_instrument_list
#         self.message_box = message_box
#         self.task_queue = Queue()
#         self.executor = ThreadPoolExecutor(max_workers=max_workers)
#         self.stop_event = threading.Event()
#         self.worker_thread = threading.Thread(target=self.process_tasks)
#         self.worker_thread.start()
#         print("线程启动器初始化完成，工作线程已启动。")
#
#     def process_tasks(self):
#         while not self.stop_event.is_set() or not self.task_queue.empty():
#             try:
#                 method_name, index, parameters = self.task_queue.get(timeout=1)
#                 if method_name is None:  # 通过发送 None 作为方法名称来作为停止信号
#                     break
#                 print(f"任务开始执行：{method_name}，参数为 {parameters}")
#                 self._execute(method_name, index, parameters)
#                 self.task_queue.task_done()
#                 print(f"任务完成：{method_name}，参数为 {parameters}")
#             except Empty:
#                 continue
#
#     def _execute(self, method_name, index=0, parameters=None):
#         time.sleep(1)
#         print(f"执行方法 {method_name}。")
#         testbench = create_testbench(chip=self.chip,
#                                      slave_instrument_list=self.slave_instrument_list,
#                                      message_box=self.message_box)
#         test_context = TestContext(testbench=testbench)
#         test_case_log_file_interceptor = TestCaseLogFileInterceptor(log_dir=LOG_DIR)
#         test_context.event_observable.attach(test_case_log_file_interceptor)
#         register_context(test_context)
#         test_instance = self.test_class(method_name=method_name, index=index, parameters=parameters)
#         test_instance.run()
#         self.device_base.close_all_spi_device()
#         print(f"方法执行完成：{method_name}。")
#         # 执行任务的具体逻辑
#
#     def launch(self, method_name, index=0, parameters=None):
#         self.task_queue.put((method_name, index, parameters))
#         print(f"将任务添加到队列：{method_name}，参数为 {parameters}")
#
#     def stop(self):
#         print("正在停止线程...")
#         self.stop_event.set()
#         self.task_queue.put((None, None, None))  # 发送停止信号
#         self.worker_thread.join(timeout=10)  # 设置超时时间
#         if self.worker_thread.is_alive():
#             print("警告：工作线程在指定时间内未能停止。")
#         self.executor.shutdown(wait=True)
#         print("线程启动器已停止。")
#
#     def __del__(self):
#         self.stop()
#         print("线程启动器实例已删除。")

# class ThreadLauncher:
#     def __init__(self, chip, test_class, device_base, slave_instrument_list=None, message_box=None, max_workers=10):
#         self.chip = chip
#         self.test_class = test_class
#         self.device_base = device_base
#         self.slave_instrument_list = slave_instrument_list
#         self.message_box = message_box
#         self.lock = Lock()
#         self.executor = ThreadPoolExecutor(max_workers=max_workers)
#
#     def _execute(self, method_name, index=0, parameters=None):
#         time.sleep(0.1)
#         with self.lock:
#             testbench = create_testbench(chip=self.chip,
#                                          slave_instrument_list=self.slave_instrument_list,
#                                          message_box=self.message_box)
#             test_context = TestContext(testbench=testbench)
#             test_case_log_file_interceptor = TestCaseLogFileInterceptor(log_dir=LOG_DIR)
#             test_context.event_observable.attach(test_case_log_file_interceptor)
#             register_context(test_context)
#             test_instance = self.test_class(method_name=method_name, index=index, parameters=parameters)
#             test_instance.run()
#             self.device_base.close_all_spi_device()
#
#     def launch(self, method_name, index=0, parameters=None):
#         # 使用线程池来调度任务，锁保护资源
#         self.executor.submit(self._execute, method_name, index, parameters)

# class ProcessLauncher:
#     def __init__(self, checkbox_map_all, chip, test_class):
#         self.checkbox_map_all = checkbox_map_all
#         self.chip = chip
#         self.test_class = test_class
#         self.current_process = None
#
#     def _execute(self, method_name, index=0):
#         self.device_base = DeviceBase(self.checkbox_map_all)
#         test_bench = create_testbench(self.chip)
#         test_context = TestContext(testbench=test_bench)
#         test_case_log_file_interceptor = TestCaseLogFileInterceptor(log_dir=LOG_DIR)
#         test_context.event_observable.attach(test_case_log_file_interceptor)
#         register_context(test_context)
#         test_instance = self.test_class(method_name=method_name, index=index)
#         test_instance.run()
#         self.device_base.close_all_spi_device()  # 进程程序执行完毕后关闭SPI设备
#
#     def launch(self, method_name, index=0):
#         if self.current_process and self.current_process.is_alive():
#             self.current_process.terminate()  # 如果需要，您可以决定是否在启动新进程前终止旧进程
#         self.current_process = Process(target=self._execute, args=(method_name, index))
#         self.current_process.start()
