# coding: utf-8

import re
import sys
import types
import typing
import inspect
import unittest
import pkgutil
import importlib
from ngta import TestCase
from ngta.case import is_testcase_subclass
from ngta.util import get_source_code

import logging
logger = logging.getLogger(__name__)


ModuleType = typing.Union[str, types.ModuleType]
CLASS_NODE_ATTR_NAME = "_node_"
MODULE_NODE_ATTR_NAME = "_node_"


def _get_class_node_name(clazz):
    name = getattr(clazz, CLASS_NODE_ATTR_NAME, None)
    return name if name else clazz.__name__


def _get_module_node_name(module):
    name = getattr(module, MODULE_NODE_ATTR_NAME, None)
    return name or module.__name__.rpartition('.')[2]


def get_hierarchy_by_testcase_class(cls: typing.Type[TestCase]):
    children = []
    for method_name in unittest.TestLoader().getTestCaseNames(cls):
        child = cls(method_name).as_dict()
        child["name"] = method_name     # overwrite default name to method name.
        children.append(child)
    return dict(
        path=cls.__module__ + "." + cls.__name__,
        name=_get_class_node_name(cls),
        type="class",
        children=children,
        code=get_source_code(cls)
    )


def get_module_by_str_or_obj(module: ModuleType, reload: bool = False) -> types.ModuleType:
    if isinstance(module, str):
        if module in sys.modules:
            module = sys.modules[module]
        else:
            module = importlib.import_module(module)

    if reload:
        logger.debug("reload %s", module.__name__)
        module = importlib.reload(module)
    return module


def _is_namespace(module) -> bool:
    if hasattr(module, "__path__") and getattr(module, "__file__", None) is None:
        return True
    return False


def get_hierarchy_by_module(module: ModuleType,
                            pattern: str = ".*", reload: bool = False):
    module = get_module_by_str_or_obj(module, reload)
    children = []

    hierarchy = dict(
        path=module.__name__,
        type="module",
        name=_get_module_node_name(module),
        children=children,
    )

    if not _is_namespace(module):
        hierarchy["code"] = get_source_code(module)

    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if is_testcase_subclass(obj) and not inspect.isabstract(obj):
            case_hierarchy = get_hierarchy_by_testcase_class(obj)
            if case_hierarchy["children"]:
                children.append(case_hierarchy)

    imp_loader = pkgutil.get_loader(module)
    if imp_loader and imp_loader.is_package(module.__name__):
        hierarchy["type"] = "package"
        for module_loader, sub_module_name, is_pkg in pkgutil.iter_modules(path=module.__path__):
            if is_pkg or (not is_pkg and pattern and re.match(pattern, sub_module_name)):
                sub_suite_hierarchy = get_hierarchy_by_module(module.__name__ + "." + sub_module_name, pattern, reload)
                if sub_suite_hierarchy["children"]:
                    children.append(sub_suite_hierarchy)
    return hierarchy


def get_testcases_dict_by_module(module: ModuleType, pattern: str = ".*", reload: bool = False) -> dict:
    logger.debug("get_testcases_dict_by_module: %s, pattern: %s, reload: %s", module, reload)
    module = get_module_by_str_or_obj(module, reload)
    data = {}

    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if is_testcase_subclass(obj) and not inspect.isabstract(obj):
            for method_name in unittest.TestLoader().getTestCaseNames(obj):
                child = obj(method_name).as_dict()
                data[child["path"]] = child

    imp_loader = pkgutil.get_loader(module)
    if imp_loader and imp_loader.is_package(module.__name__):
        for module_loader, sub_module_name, is_pkg in pkgutil.iter_modules(path=module.__path__):
            if is_pkg or (not is_pkg and re.match(pattern, sub_module_name)):
                print(sub_module_name, is_pkg)
                sub_suite_data = get_testcases_dict_by_module(module.__name__ + "." + sub_module_name, pattern, reload)
                data.update(sub_suite_data)
    return data
