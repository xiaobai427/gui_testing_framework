# coding: utf-8

import queue
from typing import NoReturn, Union, Optional
import threading
import time
from abc import ABCMeta, abstractmethod


import logging
logger = logging.getLogger(__name__)


class BaseLogObservable(metaclass=ABCMeta):
    Observer = None
    NOTIFY_INTERVAL = 0.5

    def __init__(self):
        self._observers = []
        self._lock = threading.Lock()
        self._should_stop = threading.Event()
        self._thread = None

    def open(self) -> NoReturn:
        self._should_stop.clear()
        self._thread = threading.Thread(target=self.notify)
        # framework using runner name to collect case log, if not set the runner sub-thread name same as the runner name
        # this sub-thread's log will not be add into case log file
        self._thread.name = threading.current_thread().name
        self._thread.start()

    def close(self) -> NoReturn:
        self._should_stop.set()
        if self._thread:
            self._thread.join()

    def listen(self, *args, **kwargs) -> "BaseLogObserver":
        if self.Observer is None:
            raise AttributeError("Attribute 'Observer' is None.")
        if not issubclass(self.Observer, BaseLogObserver):
            raise TypeError("Attribute 'Observer' should be sub class of BaseLogObserver")

        listener = self.Observer(self, *args, **kwargs)
        self.attach(listener)
        return listener

    def attach(self, listener: "BaseLogObserver") -> NoReturn:
        with self._lock:
            if listener not in self._observers:
                self._observers.append(listener)

    def detach(self, listener: "BaseLogObserver") -> NoReturn:
        with self._lock:
            if listener in self._observers:
                self._observers.remove(listener)

    @abstractmethod
    def notify(self, *args, **kwargs) -> NoReturn:
        pass


class BaseLogObserver:
    def __init__(self, subject: BaseLogObservable, keyword: str):
        self.subject = subject
        self.keyword = keyword
        self.queue = queue.Queue()

    def get(self, block: bool = True, timeout: int | float = None) -> Optional[object]:
        logger.debug("waiting for keyword '%s' with block=%s and timeout=%s in %s",
                     self.keyword,
                     block,
                     timeout,
                     self.subject)
        try:
            content = self.queue.get(block, timeout)
            self.queue.task_done()
            logger.debug("%s recv content '%s' from %s", self, content, self.subject)
            return content
        except queue.Empty:
            return None

    def __str__(self):
        return f"<{self.__class__.__name__}(keyword:{self.keyword})>"

    def __enter__(self):
        logger.debug("%s ENTER ON %s", self, self.subject)
        return self

    def __exit__(self, *excinfo):
        if excinfo != (None, None, None):
            logger.exception("")
        logger.debug("%s EXIT ON %s", self, self.subject)
        self.subject.detach(self)


class SerialLogObserver(BaseLogObserver):
    pass


class SerialLogObservable(BaseLogObservable):
    Observer = SerialLogObserver

    def __init__(self, comport: str, baudrate: int = 19200, log_name: str = None):
        super().__init__()
        import serial
        self._serial = serial.Serial()
        self._serial.port = comport
        self._serial.baudrate = baudrate
        self._log_name = log_name

    def open(self) -> NoReturn:
        self._serial.open()
        super().open()

    def close(self) -> NoReturn:
        super().close()
        self._serial.close()

    @property
    def log_name(self) -> str:
        return self._log_name

    @log_name.setter
    def log_name(self, logname: str) -> NoReturn:
        logger.debug("Set %s logname to '%s'", self, logname)
        self._log_name = logname
        with open(self.log_name, "a") as logfile:
            logfile.write("")

    def notify(self):
        buff = ""
        while not self._should_stop.is_set():
            num_of_bytes = self._serial.inWaiting()
            if num_of_bytes > 0:
                recv = self._serial.read(num_of_bytes)
                if self.log_name is not None:
                    with open(self.log_name, "a") as logfile:
                        logfile.write(recv)
                buff += recv

                if buff.count("\n") > 0:
                    slices = buff.split("\n")
                    lines = slices[:-1]
                    remind = slices[-1]
                    logger.debug("%s LOG:\n%s",
                                 self._serial.port,
                                 "\n".join([line.replace("\r", "") for line in lines]))
                    for line in lines:
                        with self._lock:
                            for listener in self._observers:
                                if listener.keyword is None or listener.keyword in line:
                                    listener.queue.put(line)
                    buff = remind
            time.sleep(self.NOTIFY_INTERVAL)

    def __str__(self):
        return f"<{self.__class__.__name__} '{self._serial.port}'>"


class FileLogObserver(BaseLogObserver):
    pass


class FileLogSubject(BaseLogObservable):
    Observer = FileLogObserver

    def __init__(self, log_name: str):
        super().__init__()
        self.log_name = log_name

    def notify(self) -> NoReturn:
        line_number = 0
        while not self._should_stop.is_set():
            with open(self.log_name, "r") as logfile:
                lines = logfile.readlines()

            for index in range(line_number, len(lines)):
                line = lines[index]
                with self._lock:
                    for listener in self._observers:
                        if listener.keyword in line:
                            listener.queue.put(line)
            line_number = len(lines)
            time.sleep(self.NOTIFY_INTERVAL)

    def __str__(self):
        return f"<{self.__class__.__name__} '{self.log_name}'>"


class QueueLogObserver(BaseLogObserver):
    pass


class QueueLogObservable(BaseLogObservable):
    Observer = QueueLogObserver

    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def notify(self):
        buff = ""
        while not self._should_stop.is_set():
            recv = ""
            try:
                recv = self.queue.get(block=False, timeout=0.5)
                self.queue.task_done()
            except queue.Empty:
                pass
            buff += recv

            if buff.count("\n") > 0:
                slices = buff.split("\n")
                lines = slices[:-1]
                remind = slices[-1]
                logger.debug("LOG:\n%s", "\n".join([line.replace("\r", "") for line in lines]))
                for line in lines:
                    with self._lock:
                        for listener in self._observers:
                            if listener.keyword is None or listener.keyword in line:
                                listener.queue.put(line)
                buff = remind

    def __str__(self):
        return f"<{self.__class__.__name__} '{self.queue}'>"


class _NonBlockingStreamReader(threading.Thread):
    def __init__(self, stream):
        self.__stream = stream
        self.__queue = queue.Queue()
        super().__init__()
        self.start()

    def run(self):
        while True:
            line = self.__stream.readline()
            if line:
                self.__queue.put(line)
            else:
                break

    def readlines_in_buffer(self):
        lines = []
        try:
            qsize = self.__queue.qsize()
            if qsize > 0:
                for _ in range(qsize):
                    line = self.__queue.get_nowait()
                    self.__queue.task_done()
                    lines.append(line.rstrip()+"\n")
        except queue.Empty:
            pass
        finally:
            return lines
