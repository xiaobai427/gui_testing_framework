# coding: utf-8

import unittest.mock
import inspect

from .constants import PACKAGE_NAME
from .mark import NestDecorator


class Patch(unittest.mock._patch, NestDecorator):
    MARK_NAME = f"_{PACKAGE_NAME}_patch"

    def __call__(self, item):
        return NestDecorator.__call__(self, item)


class FakePatch:
    def __enter__(self):
        return unittest.mock.MagicMock()

    def __exit__(self, *exc_info):
        pass

    def start(self):
        return self.__enter__()

    def stop(self):
        return self.__exit__()


def _find_testcase():
    # _find_testcase is not reliability, it search testcase in outer frames.
    from .case import is_testcase_instance
    for frame_info in inspect.getouterframes(inspect.currentframe()):
        f_locals = frame_info[0].f_locals
        found = f_locals.get("self", None)
        if found and is_testcase_instance(found):
            return found
    return None


def patch(*args, **kwargs):
    testcase = _find_testcase()
    if testcase is not None and not testcase.enable_mock:
        return FakePatch()
    else:
        params = inspect.getcallargs(unittest.mock.patch, *args, **kwargs)
        target = params.pop("target")
        getter, attribute = unittest.mock._get_target(target)
        return Patch(getter, attribute, **params)


def _patch_object(*args, **kwargs):
    testcase = _find_testcase()
    if testcase is not None and not testcase.enable_mock:
        return FakePatch()
    else:
        params = inspect.getcallargs(unittest.mock.patch.object, *args, **kwargs)
        target = params.pop("target")
        return Patch(lambda: target, **params)


patch.object = _patch_object


# def _wrap_testmethod(self, context):
#     """
#     wrap test method with mocks, parameters and events.
#
#     if the method require arguments,
#     provide the arguments with following steps：
#     1. search in self.parameters
#     2. use default value.
#     3. finally, set the missed arguments by @patch index.
#     """
#
#     method = getattr(self, self._method_name)
#
#     @functools.wraps(method)
#     def wrapped_method():
#         mocks = []
#         kwargs = {}
#         missed = []
#         entered_patchers = []
#
#         exc_info = tuple()
#
#         try:
#             patchers = self.__class__.get_patchers(self._method_name)
#             for patching in patchers:
#                 if self.enable_mock:
#                     result = patching.__enter__()
#                     entered_patchers.append(patching)
#                 else:
#                     result = unittest.mock.MagicMock()
#                 mocks.append(result)
#         except:
#             if patching not in entered_patchers and unittest.mock._is_started(patching):
#                 # the patcher may have been started, but an exception
#                 # raised whilst entering one of its additional_patchers
#                 entered_patchers.append(patching)
#             exc_info = sys.exc_info()
#             raise
#         else:
#             sig = inspect.signature(method)
#             for name, value in sig.parameters.items():
#                 if name in self.parameters:
#                     kwargs[name] = self.parameters[name]
#                 else:
#                     if value.default is value.empty:
#                         missed.append(name)
#                     else:
#                         kwargs[name] = value.default
#             for index, name in enumerate(missed):
#                 kwargs[name] = mocks[index]
#
#             return method(**kwargs)
#         finally:
#             for patching in reversed(entered_patchers):
#                 patching.__exit__(*exc_info)
#     setattr(self, self._method_name, wrapped_method)

