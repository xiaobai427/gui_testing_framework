# coding: utf-8

from ngta.events import EventObservable, EventType, TestEventHandler


import logging
logger = logging.getLogger(__name__)

observable = EventObservable()


@observable.listen_for(EventType.ON_SETUP_STARTED)
def handle_setup_started_event(event):
    logger.debug("handle_setup_started_event: %s", event)


@observable.listen_for(EventType.ON_SETUP_CLASS_STARTED)
def handle_setup_class_started_event(event):
    logger.debug("handle_setup_class_started_event: %s", event)


@observable.listen_for(EventType.ON_SETUP_MODULE_STOPPED, ignore_errors=True, is_async=True)
def handle_setup_module_started_event(event):
    logger.debug("handle_setup_module_stopped_event: %s", event)


@observable.listen_for()
class EventHandler(TestEventHandler):
    def on_testrunner_started(self, event):
        logger.debug("EventHandler RECV: %s", event)

    def on_testrunner_stopped(self, event):
        logger.debug("EventHandler RECV: %s", event)


def hook(result, runners, output_dir, config_yaml):
    logger.debug("call hook")
