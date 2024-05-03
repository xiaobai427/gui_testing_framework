# coding: utf-8

import functools
from tornado import web
from ngta.util import locate
from ngta.case import is_testcase_subclass
from .base import BaseResource
from .util import get_testcases_dict_by_module, get_hierarchy_by_module

import logging
logger = logging.getLogger(__name__)


class TestBenchListResource(BaseResource):
    def get(self):
        self.finish(self.application.executor.dump_testbenches())

    def put(self):
        items = self.json()
        for item in items:
            state = item.get("state", None)
            if state is not None:
                self.application.executor.update_testbench_state(item["name"], state)


class TestBenchDetailResource(BaseResource):
    def put(self, name):
        data = self.json()
        state = data.get("state", None)
        if state is not None:
            self.application.executor.update_testbench_state(name, state)


class TestRunnerListResource(BaseResource):
    def get(self):
        self.finish(self.application.executor.dump_testrunners())


@functools.lru_cache()
def get_hierarchy(module_name):
    hierarchy = get_hierarchy_by_module(module_name, reload=True)
    return hierarchy


class TestHierarchyResource(BaseResource):
    def get(self):
        try:
            name = self.get_query_argument("name")
        except web.MissingArgumentError as err:
            self.set_status(400)
            self.finish({"message": str(err)})
        else:
            try:
                case_dir = self.application.work_env.case_dir
                if case_dir.joinpath(name).is_dir():
                    hierarchy = get_hierarchy(name)
                    self.finish(hierarchy)
                else:
                    self.set_status(404)
                    self.finish({"message": f"Can't find testcase directory by name {name}"})
            except Exception as err:
                logger.exception("")
                self.set_status(500)
                self.finish({"message": str(err)})


@functools.lru_cache()
def get_testcases_dict(module_name):
    data = get_testcases_dict_by_module(module_name)
    return data


class TestCaseListResource(BaseResource):
    class ResultType:
        DICT = "dict"
        LIST = "list"

    def get(self):
        try:
            name = self.get_query_argument("name")
            result_type = self.get_query_argument("result_type", default=self.ResultType.LIST)
        except web.MissingArgumentError as err:
            self.set_status(400)
            self.finish({"message": str(err)})
        else:
            try:
                case_dir = self.application.work_env.case_dir
                if case_dir.joinpath(name).is_dir():
                    data = get_testcases_dict(name)
                    if result_type.lower() == self.ResultType.DICT:
                        self.finish(data)
                    elif result_type.lower() == self.ResultType.LIST:
                        self.finish(list(data.values()))
                    else:
                        self.set_status(400)
                        self.finish({"message": "Query argument 'result_type' should be list or dict."})
                else:
                    self.set_status(404)
                    self.finish({"message": f"Can't find testcase directory with name {name}"})
            except Exception as err:
                logger.exception("")
                self.set_status(500)
                self.finish({"message": str(err)})


class TestCaseDetailResource(BaseResource):
    def get(self, path):
        logger.debug("get testcase by path: %s", path)
        class_name, sep, method_name = path.rpartition(".")

        try:
            cls = locate(class_name)
            if is_testcase_subclass(cls):
                self.finish(cls(method_name).as_dict())
            else:
                self.set_status(400)
                self.finish({"message": "specified path is not a valid test method path."})
        except Exception as err:
            self.finish({"message": str(err)})
