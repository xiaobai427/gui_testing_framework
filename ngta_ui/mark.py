# coding: utf-8
from __future__ import annotations

import enum
import inspect
import itertools
import typing

from typing import TYPE_CHECKING, Sequence, List, Type, Callable, Optional, ClassVar
from abc import ABCMeta
from .constants import PACKAGE_NAME

import logging
logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .case import TestCase, TestCaseResultRecord


def _is_test_class(item):
    from .case import is_testcase_subclass
    return is_testcase_subclass(item)


def is_test_function(item):
    if inspect.isfunction(item) and (getattr(item, TestDecorator.MARK_NAME, None) or item.__name__.startswith('test')):
        return True
    return False


def _is_test_class_or_method(item):
    if _is_test_class(item) or is_test_function(item):
        return True
    return False


class BaseDecorator(metaclass=ABCMeta):
    MARK_NAME: ClassVar[str]

    MARK_ON_TEST_CLASS: ClassVar[bool]

    MARK_ON_TEST_METHOD: ClassVar[bool]

    def __call__(self, item):
        """
        Can NOT use is_test_function to check the decorator marked on test function, for example:

        @test
        @tag
        def test():
            pass

        In previous sample:
            first parse @tag, it will check whether the testcase marked with @test;
            but at this time, it does not marked with @test.
        """

        if self.MARK_ON_TEST_CLASS and _is_test_class(item) or self.MARK_ON_TEST_METHOD and inspect.isfunction(item):
            pass
        else:
            msg = f"{self} can't be marked on {item}, it can only be marked on TestCase class or test method"
            raise TypeError(msg)

        setattr(item, self.MARK_NAME, self)
        return item


class TestDecorator(BaseDecorator):
    MARK_NAME = f"_{PACKAGE_NAME}_test"
    MARK_ON_TEST_CLASS = False
    MARK_ON_TEST_METHOD = True

    def __init__(self,
                 title: str | Callable = None,
                 ident: str = None,
                 setup: Callable = None,
                 teardown: Callable = None,
                 is_manual: bool = False,
                 log_name: Callable[["TestCase"], str] = None,
                 ):
        self.title = title
        self.ident = ident
        self.setup = setup
        self.teardown = teardown
        self.is_manual = is_manual
        self.log_name = log_name

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and not kwargs:
            item = args[0]
            if inspect.isfunction(item):
                mark = self.__class__(self.title)
                setattr(item, self.MARK_NAME, mark)
                return item
        mark = self.__class__(*args, **kwargs)
        return mark

    def __str__(self):
        return f"<{self.__class__.__name__}(title:{self.title}, ident:{self.ident}, setup:{self.setup}, " \
               f"teardown:{self.teardown}, is_manual:{self.is_manual})>"


class ParametrizeDecorator(BaseDecorator):
    """
    Decorator @parametrize.
    It can only be marked on test method or test function.

    Parameters
    ----------
    data: Sequence[Sequence] | Callable, optional
        parametrize test arguments.

    titles: Sequence[str], optional
        specify testcase title for each item of data

    **kwargs:
        Generate data by cartesian product. The key should be argument name, value should be a sequence or scalar.
    """

    MARK_NAME = f"_{PACKAGE_NAME}_parametrize"
    MARK_ON_TEST_CLASS = False
    MARK_ON_TEST_METHOD = True

    def __init__(self, data: Sequence[Sequence] | Callable = None, titles: Sequence[str] = None, **kwargs):
        if not data and not kwargs:
            raise ValueError("data or kwargs is alternative.")

        self.data = data
        self.titles = titles
        self.kwargs = kwargs

    def get_data(self, method):
        if self.data:
            if callable(self.data):
                return self.data()
            return self.data
        else:
            sig = inspect.signature(method)
            values = []
            for name in sig.parameters.keys():
                value = self.kwargs.get(name, None)
                if value:
                    values.append(value)
            return itertools.product(*values)

    def __str__(self):
        return f"<{self.__class__.__name__}(parameters:{self.data})>"


class RouteDecorator(BaseDecorator):
    """
    Decorator @route, mark the test should be run on a specified testbench.
    Can be marked on test class or test method.
    Used to integrate with test platform.

    Parameters
    ----------
    route: str
        route to specified testbench.
    """

    MARK_NAME = f"_{PACKAGE_NAME}_route"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    def __init__(self, route: str):
        self.route = route

    def __str__(self):
        s = f"<RouteDecorator(route:{self.route})>"
        return s


class RerunDecorator(BaseDecorator):
    """
    Decorator @rerun, used to rerun testcase with conditions.
    Can be marked on test class and test method.

    Parameters
    ----------
    retry: int, optional
        Retry times.

    scope: enum, optional
        Rerun testcase if failed in setup, method or teardown.

    when: enum, optional
        Rerun testcase when failed or erroneous.
    """

    MARK_NAME = f"_{PACKAGE_NAME}_rerun"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    class Scope(enum.IntEnum):
        SETUP = 1
        METHOD = 2
        TEARDOWN = 4

    class When(enum.IntEnum):
        FAILED = 1
        ERRONEOUS = 2

    def __init__(self, retry: int = 1, scope: Scope = Scope.METHOD, when: When = When.FAILED,
                 remark: 'TestCaseResultRecord.Status' = 2,
                 pre_action: typing.Callable = None, post_action: typing.Callable = None):
        self.retry = retry
        self.scope = scope
        self.when = when
        self.remark = remark
        self.pre_action = pre_action
        self.post_action = post_action

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and not kwargs:
            item = args[0]
            if _is_test_class_or_method(item):
                mark = self.__class__(self.retry, self.scope, self.when, self.remark, self.pre_action, self.post_action)
                setattr(item, self.MARK_NAME, mark)
                return item
        mark = self.__class__(*args, **kwargs)
        return mark

    def __str__(self):
        return f"<RerunDecorator(retry:{self.retry}, scope:{self.scope}, when:{self.when}, remark:{self.remark})>"


class SkipIfDecorator(BaseDecorator):
    """
    Decorator @skipif, used to skip test with condition.
    Can be marked on test class and test method.

    Parameters
    ----------
    condition: bool or str or callable
        Condition to evaluate. If it is a callable, it can accept one additional argument which is testcase object.

    reason: str, optional
        The reason.
    """

    MARK_NAME = f"_{PACKAGE_NAME}_skipif"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    def __init__(self, condition: bool | str | Callable, reason: str = None):
        self.condition = condition
        self.reason = reason

    def check_condition(self, testcase: "TestCase") -> bool:
        if inspect.isfunction(self.condition):
            sig = inspect.signature(self.condition)
            if len(sig.parameters) == 1:
                return self.condition(testcase)
            else:
                return self.condition()
        else:
            return (isinstance(self.condition, bool) and self.condition) \
                   or (isinstance(self.condition, str) and eval(self.condition))

    def __str__(self):
        return f"<SkipIfDecorator(condition:{self.condition}, reason: {self.reason})>"


class SkipDecorator(SkipIfDecorator):
    """
    Decorator @skip, used to skip test.
    Can be marked on test class and test method.

    Parameters
    ----------
    reason: str
        The reason.
    """
    def __init__(self, reason):
        super().__init__(True, reason)


class TagDecorator(BaseDecorator):
    """
    Decorator @tag, mark the test's tags.
    Can be marked on test class and test method.

    Parameters
    ----------
    *tags: Tuple[str, ...]
        Specify test's tags.
    """

    MARK_NAME = f"_{PACKAGE_NAME}_tag"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    def __init__(self, *tags):
        self.tags = tags

    def __str__(self):
        s = f"<TagDecorator(tags:{self.tags})>"
        return s


class NestDecorator(BaseDecorator, metaclass=ABCMeta):
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    def __call__(self, item):
        mark_name = self.MARK_NAME

        # getattr() will get the marks from the base class if current class has not attribute with mark_name
        # so use item.__dict__ instead of.
        if mark_name not in item.__dict__:
            setattr(item, mark_name, [])

        marks = getattr(item, mark_name)
        marks.append(self)
        return item


class IgnoreInheritedMarksDecorator(BaseDecorator):
    MARK_NAME = f"_{PACKAGE_NAME}_ignore_inherited_marks"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = False

    def __init__(self, *args: Sequence[BaseDecorator]):
        self.args = args

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and not kwargs:
            item = args[0]
            if _is_test_class(item):
                super().__call__(item)
                return item
        mark = self.__class__(*args)
        return mark


class ManualDecorator(BaseDecorator):
    MARK_NAME = f"_{PACKAGE_NAME}_manual"
    MARK_ON_TEST_CLASS = True
    MARK_ON_TEST_METHOD = True

    def __init__(self):
        pass

    def __str__(self):
        s = "<ManualDecorator>"
        return s


class MarkHelper:
    @classmethod
    def should_ignore_inherited_mark(cls, testcase_class, decorator_class: Type[BaseDecorator]) -> bool:
        ignore_mark = getattr(testcase_class, IgnoreInheritedMarksDecorator.MARK_NAME, None)
        if not ignore_mark:
            return False

        if ignore_mark.args:
            for arg in ignore_mark.args:
                # arg may be an instance such as rerun or other mark class
                if isinstance(arg, decorator_class) or arg is decorator_class:
                    return True
            return False
        else:
            return True

    @classmethod
    def get_single_mark(cls, decorator_class: Type[BaseDecorator],
                        method, clazz=None) -> Optional[BaseDecorator]:
        mark_name = decorator_class.MARK_NAME   # type: str
        mark = getattr(method, mark_name, None)

        if not mark and clazz:
            mark = cls.get_single_mark_by_class(decorator_class, clazz)
        return mark

    @classmethod
    def get_single_mark_by_class(cls, decorator_class: Type[BaseDecorator], clazz):
        mark_name = decorator_class.MARK_NAME   # type: str
        mark = clazz.__dict__.get(mark_name, None)
        if not mark and not cls.should_ignore_inherited_mark(clazz, decorator_class):
            mark = getattr(clazz, mark_name, None)
        return mark

    @classmethod
    def get_test_mark(cls, method) -> Optional[TestDecorator]:
        return cls.get_single_mark(TestDecorator, method)

    @classmethod
    def get_parametrize_mark(cls, method) -> Optional[ParametrizeDecorator]:
        return cls.get_single_mark(ParametrizeDecorator, method)    # type: ParametrizeDecorator

    @classmethod
    def get_parametrize_data(cls, method) -> Sequence:
        mark = cls.get_single_mark(ParametrizeDecorator, method)    # type: ParametrizeDecorator
        if mark:
            return mark.get_data(method)
        else:
            return ()

    @classmethod
    def get_tags(cls, method, clazz=None) -> Sequence[str]:
        mark: TagDecorator = cls.get_single_mark(TagDecorator, method, clazz)
        return mark.tags if mark else ()

    @classmethod
    def get_route(cls, method, clazz=None) -> Optional[str]:
        mark: RouteDecorator = cls.get_single_mark(RouteDecorator, method, clazz)
        return mark.route if mark is not None else None

    @classmethod
    def is_manual(cls, method) -> bool:
        mark: TestDecorator = cls.get_test_mark(method)
        if mark and mark.is_manual:
            return True
        return False

    @classmethod
    def get_rerun_mark(cls, method, clazz=None) -> RerunDecorator:
        return cls.get_single_mark(RerunDecorator, method, clazz)

    @classmethod
    def get_skipif_mark(cls, method, clazz) -> SkipIfDecorator:
        return cls.get_single_mark(SkipIfDecorator, method, clazz)

    @classmethod
    def get_skipif_mark_by_class(cls, clazz) -> SkipIfDecorator:
        return cls.get_single_mark_by_class(SkipIfDecorator, clazz)

    @classmethod
    def get_nested_marks(cls, decorator_class: Type[NestDecorator],
                         method, clazz=None) -> List[NestDecorator]:
        mark_list = []
        mark_name = decorator_class.MARK_NAME   # type: str

        if not cls.should_ignore_inherited_mark(clazz, decorator_class):
            for base_class in clazz.__bases__:
                if hasattr(base_class, mark_name):
                    mark_list.extend(getattr(base_class, mark_name))

        # getattr() will get the marks from the base class if current class has not attribute with mark_name
        # so use cls.__dict__ instead of.
        if mark_name in clazz.__dict__:
            mark_list.extend(clazz.__dict__[mark_name])

        if hasattr(method, mark_name):
            mark_list.extend(getattr(method, mark_name))
        return mark_list

    # @classmethod
    # def get_patchers(cls, method, clazz) -> List[Patch]:
    #     from .mock import Patch
    #     return cls.get_nested_marks(Patch, method, class_)


test = TestDecorator()
parametrize = ParametrizeDecorator
skipif = SkipIfDecorator
skip = SkipDecorator
rerun = RerunDecorator()
tag = TagDecorator
route = RouteDecorator
ignore_inherited_marks = IgnoreInheritedMarksDecorator()
manual = ManualDecorator()
