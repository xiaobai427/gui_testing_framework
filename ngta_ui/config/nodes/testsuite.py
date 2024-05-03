# coding: utf-8

import functools
import inspect
import itertools
import logging
import os
import re
import sys

import unittest.util
from abc import ABCMeta, abstractmethod
from typing import List, Sequence, Union, Callable, Iterator, Type, Optional, Dict, Any, Literal
if sys.version_info >= (3, 9):
    from typing import Annotated
else:
    from typing_extensions import Annotated

import pydantic
import yaml
from coupling.module import is_package, walk_module

from ...case import TestCase, TestCaseModel, is_testcase_model, is_testcase_subclass
from ...suite import TestSuiteModel, TestModelType, is_testsuite_model
from ...constants import FilePathType
from ...environment import WorkEnv
from ...errors import ConfigError, DeserializeError, SerializeError
from ...mark import is_test_function, MarkHelper
from ...util import locate, str_class, str_func

logger = logging.getLogger(__name__)


def get_test_path(obj) -> str:
    if inspect.ismodule(obj):
        return obj.__name__
    elif inspect.isclass(obj):
        return str_class(obj)
    elif inspect.ismethod(obj) or inspect.isfunction(obj):
        return str_func(obj)
    else:
        raise DeserializeError("Can't get path from: %s" % obj)


def get_test_method_names(testcase_class: Type[TestCase]) -> List[str]:
    method_names = []

    # NOTE: only load testcase defined in current class, ignore test inherited from base class.
    for name, attr in testcase_class.__dict__.items():
        if is_test_function(attr):
            method_names.append(name)
    method_names.sort(key=functools.cmp_to_key(unittest.util.three_way_cmp))
    return method_names


class Argument:
    def __init__(self, args: list = None, kwds: dict = None):
        self.args = args or []
        self.kwds = kwds or {}

    def fill(self, value, name=None):
        if name:
            self.kwds[name] = value
        else:
            self.args.append(value)

    def copy(self):
        return self.__class__(self.args.copy(), self.kwds.copy())

    def __copy__(self):
        return self.copy()

    def __repr__(self):
        return f"<Argument(args:{self.args}, kwds: {self.kwds})>"


def convert_argument_to_parameters(func, argument: Argument) -> dict:
    signature = inspect.signature(func)
    try:
        logger.debug("bind params %s on %s", argument, func)
        ba = signature.bind(None, *argument.args, **argument.kwds)
        ba.apply_defaults()
        ba.arguments.pop('self')                          # remove self argument
    except TypeError:
        logger.error("bind params failed, maybe missing @parametrize on '%s'", func)
        raise
    else:
        parameters = ba.kwargs
        logger.debug("test params: %s", parameters)

    return parameters


ParametersType = Dict[str, Any]
IterationsType = Union[List[ParametersType], Dict[str, List]]


def _generate_testcase_model_from_func(func: Callable,
                                       arguments: Sequence[Argument] = None,
                                       is_prerequisite: bool = False,
                                       start_index: int = None,
                                       ) -> Iterator[TestCaseModel]:

    base_case = TestCaseModel(path=str_func(func), is_prerequisite=is_prerequisite)

    is_parameterize_mark_used = False

    if not arguments:
        arguments = []
        data = MarkHelper.get_parametrize_data(func)

        if data:
            is_parameterize_mark_used = True
            for item in data:
                if isinstance(item, dict):
                    argument = Argument(kwds=item)
                elif isinstance(item, (list, tuple)):
                    argument = Argument(item)
                else:
                    raise NotImplementedError
                arguments.append(argument)
        else:
            argument = Argument()
            arguments.append(argument)

    mark = MarkHelper.get_parametrize_mark(func)
    if arguments:
        for i, argument in enumerate(arguments):
            case_model = base_case.model_copy()
            if start_index is not None:
                case_model.index = start_index + i

            case_model.parameters = convert_argument_to_parameters(func, argument)

            if is_parameterize_mark_used and mark.titles:
                try:
                    case_model.title = mark.titles[i]
                except IndexError:
                    logger.warning("can't find title for '%s' with param %s", case_model.path, case_model.parameters)
            yield case_model


def _get_arguments_from_parameters_and_iterations(
        parameters: ParametersType,
        iterations: IterationsType,
        variables: ParametersType
) -> List[Argument]:
    """
    Sample1:
        parameters:
          value1: 1
          value2: 2

    Sample2:
        iterations:
          - [1, 2]
          - [3, 3]

    Sample3:
        parameters:
          value1: 1
        iterations:
          value2: [1, 2 ,3]

    Sample4:
        iterations:
          value1: [1, 2, 3]
          value2: [4, 5 ,6]
    """
    parameters = parameters or {}
    iterations = iterations or {}

    para_vars = {k: eval_vars(v, variables) for k, v in parameters.items()}
    if isinstance(iterations, dict):
        arguments = []
        if para_vars:
            arguments.append(Argument(kwds=para_vars))

        if arguments:
            for k, values in iterations.items():
                try:
                    iter(values)
                except TypeError as e:
                    raise ConfigError(str(e))

                new_arguments = []
                for argument in arguments:
                    for value in iter(values):
                        new_argument = argument.copy()
                        new_argument.fill(eval_vars(value, variables), k)
                        new_arguments.append(new_argument)
                arguments = new_arguments
        else:
            if iterations:
                for values in itertools.product(*iterations.values()):
                    vals = [eval_vars(value, variables) for value in values]
                    kwds = dict(zip(iterations.keys(), vals))
                    arguments.append(Argument(kwds=kwds))

        return arguments
    elif isinstance(iterations, list):
        arguments = []
        for iteration in iterations:
            iter_vars = {k: eval_vars(v, variables) for k, v in iteration.items()}
            argument = Argument()
            argument.kwds.update(para_vars)
            argument.kwds.update(iter_vars)
            arguments.append(argument)
        return arguments
    else:
        raise NotImplementedError


def _repeat(generator: Iterator[TestModelType],
            repeat_number: int, foreach: bool = True) -> List[TestModelType]:
    new = []
    if foreach:
        for d in generator:
            for i in range(repeat_number):
                new.append(d.model_copy())
    else:
        t = tuple(generator)
        for i in range(repeat_number):
            for d in t:
                new.append(d.model_copy())
    return new


def eval_vars(s, variables: ParametersType):
    if isinstance(s, str):
        if s.startswith("${") and s.endswith("}"):
            var = s[2:-1]
            if ':' in var:
                pattern, _, default = var.partition(':')
                try:
                    return eval(pattern, globals(), variables)
                except NameError:
                    return eval(default, globals(), variables)
            else:
                v = eval(var, globals(), variables)
                return v
        else:
            matches = re.findall(r'\$\{.*?\}', s)
            for match in matches:
                value = eval(match[2:-1], globals(), variables)
                s = s.replace(match, str(value))
            return s
    elif isinstance(s, list):
        l = []
        for item in s:
            l.append(eval_vars(item, variables))
        return l
    elif isinstance(s, dict):
        d = {}
        for k, v in s.items():
            d[k] = eval_vars(v, variables)
        return d
    else:
        return s


def is_test_module(obj, pattern: str = "test") -> bool:
    return inspect.ismodule(obj) and (re.match(pattern, obj.__name__.split(".")[-1]) or obj.__name__ == "__main__")


def generate_test_from_obj(obj,
                           injections: dict = None,
                           skip_callback: Callable[[Callable, TestCase, str], bool] = None,
                           pattern: str = "test"
                           ) -> Iterator[TestModelType]:
    if not injections:
        injections = {}

    if is_package(obj) or is_test_module(obj, pattern):
        testsuites = getattr(obj, "__testsuites__", None)
        if testsuites:
            for testsuite in testsuites:
                yield testsuite
        else:
            case_dir = WorkEnv.instance().case_dir
            if case_dir and str(case_dir) in os.path.abspath(obj.__file__):
                for sub_obj in walk_module(obj):
                    for test in generate_test_from_obj(sub_obj, injections, skip_callback, pattern):
                        yield test
    elif is_testsuite_model(obj):
        yield obj
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            if is_testsuite_model(item) or is_testcase_model(item):
                yield item
            else:
                raise NotImplementedError(f"Unsupported obj: {item}")
    elif is_testcase_subclass(obj):
        class_ = obj
        for method_name in get_test_method_names(class_):
            method = getattr(class_, method_name)
            fullname = str_class(class_) + "." + method.__name__
            if callable(skip_callback) and skip_callback(method, class_, fullname):
                continue

            injection = injections.get(fullname, None)
            arguments = _get_arguments_from_parameters_and_iterations(**injection) if injection else None
            for testcase_model in _generate_testcase_model_from_func(method, arguments):
                yield testcase_model.model_copy()
    elif is_test_function(obj):
        func = obj
        fullname = str_func(func)
        should_skip = callable(skip_callback) and skip_callback(func, None, fullname)
        if not should_skip:
            injection = injections.get(fullname, None)
            arguments = _get_arguments_from_parameters_and_iterations(**injection) if injection else None
            for testcase_model in _generate_testcase_model_from_func(obj, arguments):
                yield testcase_model.model_copy()
    else:
        pass


class BaseTestNode(pydantic.BaseModel, metaclass=ABCMeta):
    @abstractmethod
    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        pass


class BaseTestLoaderNode(BaseTestNode, metaclass=ABCMeta):
    as_testsuite: str = pydantic.Field("", alias="as-testsuite")

    @abstractmethod
    def _load_as_tests(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestSuiteModel]:
        pass

    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestSuiteModel]:
        if self.as_testsuite:
            data = TestSuiteModel(name=self.as_testsuite, tests=self._load_as_tests(cfg_yaml, variables))
            return [data]
        return self._load_as_tests(cfg_yaml, variables)

    def as_model_data(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> TestSuiteModel:
        if self.as_testsuite:
            return TestSuiteModel(name=self.as_testsuite, tests=self._load_as_tests(cfg_yaml, variables))
        raise SerializeError("as_testsuite is empty.")


class MethodNode(pydantic.BaseModel):
    name: str
    repeat_number: int = pydantic.Field(1, alias="repeat-number")
    is_prerequisite: bool = pydantic.Field(False, alias="is-prerequisite")
    parameters: ParametersType = None
    iterations: IterationsType = None

    def arguments(self, variables: ParametersType = None):
        return _get_arguments_from_parameters_and_iterations(self.parameters, self.iterations, variables)


class ClsLoaderNode(BaseTestLoaderNode):
    """
    - cls-loader:
        path: sample.base.test_equal.EqualTestCase
        as-testsuite: cls-loader suite
        repeat-number: 2
        repeat-foreach: true
        methods:
          - name: test_int
            repeat-number: 2
            parameters:
              value1: 2
              value2: 3
            iterations:
    """
    type: Literal['cls-loader'] = pydantic.Field('cls-loader')
    path: str
    methods: List[MethodNode] = pydantic.Field(default_factory=list)
    repeat_number: int = pydantic.Field(1, alias="repeat-number")
    repeat_foreach: bool = pydantic.Field(False, alias="repeat-foreach")

    def _load_as_tests(self, cfg_yaml: FilePathType = None, variables: ParametersType = None):
        logger.debug("load tests from cls: %s", self.path)
        tests = []
        class_fullname = self.path.strip()
        class_obj = locate(class_fullname)

        if not self.methods:
            for method_name in get_test_method_names(class_obj):
                self.methods.append(
                    MethodNode(
                        name=method_name, repeat_number=1, is_prerequisite=False, parameters={}, iterations={}
                    )
                )

        for method in self.methods:
            method_obj = getattr(class_obj, method.name)
            generator = _generate_testcase_model_from_func(method_obj, method.arguments(variables), method.is_prerequisite)

            if self.repeat_foreach:
                repeat_number = self.repeat_number * method.repeat_number
            else:
                repeat_number = method.repeat_number

            tests.extend(_repeat(generator, repeat_number))

        if not self.repeat_foreach:
            tests = _repeat(tests, self.repeat_number)
        return tests


class ObjLoaderNode(BaseTestLoaderNode):
    """
    - obj-loader:
        path: sample.base.test_equal
        as-testsuite: pkg-loader suite
        repeat-number: 2
        repeat-foreach: true
        filter:
          includes: []
          excludes: []
        inject:
          EqualTestCase.test_int:
            parameters:
              value1: 3
            iterations:
              value2: [3, 4, 5]
    """
    type: Literal['obj-loader'] = pydantic.Field('obj-loader')
    path: str
    repeat_number: int = pydantic.Field(1, alias="repeat-number")
    repeat_foreach: bool = pydantic.Field(False, alias="repeat-foreach")
    tags: List[str] = None
    filter: dict = pydantic.Field(default_factory=dict)
    inject: dict = pydantic.Field(default_factory=dict)

    @property
    def includes(self):
        return self.filter.get("includes", None)

    @property
    def excludes(self):
        return self.filter.get("excludes", None)

    def _skip_callback(self, cls: TestCase, method: Callable, fullname: str) -> bool:
        if self.excludes and [exclude for exclude in self.excludes if re.search(exclude, fullname)]:
            return True

        if self.includes and not [include for include in self.includes if re.search(include, fullname)]:
            return True

        if self.tags:
            for tag in MarkHelper.get_tags(method, cls):
                if tag in self.tags:
                    return False
            return True
        return False

    def _generate_from_objects(self) -> Iterator[TestModelType]:
        for test in generate_test_from_obj(locate(self.path), self.inject, self._skip_callback):
            yield test

    def _load_as_tests(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        logger.debug("load tests from obj: %s", self.path)

        generator = self._generate_from_objects()
        return _repeat(generator, self.repeat_number, self.repeat_foreach)


class TagLoaderNode(BaseTestLoaderNode):
    """
    - tag-loader:
        tag: regression
        as-testsuite: tag-loader suite
        repeat-number: 2
        repeat-foreach: true
        locates:
          - path: sample.base.test_equal.EqualTestCase
            inject:
              test_int:
                parameters:
                  value1: 3
                iterations:
                  value2: [3, 4, 5]
    """
    type: Literal['tag-loader'] = pydantic.Field('tag-loader')
    tag: str
    repeat_number: int = pydantic.Field(1, alias="repeat-number")
    repeat_foreach: bool = pydantic.Field(False, alias="repeat-foreach")
    locates: Optional[List[dict]] = None
    inject: Optional[dict] = None

    def _generate_from_objects(self) -> Iterator[TestModelType]:
        locations = []
        injections = []

        for locate_dict in self.locates:
            location = locate_dict["path"]
            locations.append(location)
            for inject_path, inject_value in locate_dict.get("inject", {}).items():
                if inject_path:
                    inject_path = f"{location}.{inject_path}"
                else:
                    inject_path = location
                injections[inject_path] = inject_value

        objects = [locate(location) for location in locations]
        for obj in objects:
            for test in generate_test_from_obj(obj, injections, self._skip_callback):
                yield test

    def _skip_callback(self, method: Callable, class_: TestCase = None, fullname: str = "") -> bool:
        tags = MarkHelper.get_tags(method, class_)
        for tag in tags:
            if re.search(self.tag, tag):
                return False
        return True

    def _load_as_tests(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        generator = self._generate_from_objects()
        return _repeat(generator, self.repeat_number, self.repeat_foreach)


class YmlLoaderConfigNode(BaseTestLoaderNode):
    """
    yml-loader:
        as-testsuite:
        filename:
        includes:
        excludes:
        parameters:
    """
    type: Literal['yml-loader'] = pydantic.Field('yml-loader')
    filename: str
    includes: List[str] = None
    excludes: List[str] = None
    parameters: ParametersType = pydantic.Field(default_factory=dict)

    def _should_skip(self, model: TestCaseModel | TestSuiteModel) -> bool:
        if self.excludes:
            for exclude in self.excludes:
                if isinstance(exclude, str):
                    if (model.path and re.search(exclude, model.path)) or (model.name and re.search(exclude, model.name)):
                        logger.debug('exclude: %s', model)
                        return True
                elif isinstance(exclude, dict):
                    matches = 0
                    for k, v in exclude.items():
                        if k in ('name', 'path'):
                            if re.search(v, getattr(model, k)):
                                matches += 1
                        if isinstance(model, TestCaseModel) and k == 'parameters':
                            if v == getattr(model, k):
                                matches += 1
                    if matches == len(exclude):
                        logger.debug('exclude: %s', model)
                        return True
                else:
                    raise NotImplementedError

        if self.includes:
            for include in self.includes:
                if isinstance(include, str):
                    if (model.path and re.search(include, model.path)) or (model.name and re.search(include, model.name)):
                        return False
                elif isinstance(include, dict):
                    for k, v in include.items():
                        raise NotImplementedError
                else:
                    raise NotImplementedError
            logger.debug('exclude: %s', model)
            return True
        return False

    def _filter(self, models: List[TestModelType]) -> List[TestModelType]:
        old_models = models
        new_models = []
        for model in old_models:
            if isinstance(model, TestSuiteModel):
                if not self._should_skip(model):
                    tests = self._filter(model.tests)
                    if tests:
                        new_models.append(model)
            elif isinstance(model, TestCaseModel):
                if not self._should_skip(model):
                    new_models.append(model)
            else:
                raise NotImplementedError
        return new_models

    def _load_as_tests(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        logger.debug("load tests from yml: %s", self.filename)
        if os.path.isabs(self.filename):
            path = self.filename
        else:
            path = os.path.join(os.path.dirname(cfg_yaml), self.filename)
        logger.debug('load tests from yml: %s', path)
        with open(path) as f:
            d = yaml.load(f, Loader=yaml.Loader)

        parameters = {k: eval_vars(v, variables) for k, v in self.parameters.items()}
        if isinstance(d, list):
            data = {'iterations': [parameters], 'tests': d}
        elif isinstance(d, dict):
            d['iterations'] = [parameters]
            data = d
        else:
            raise NotImplementedError

        config = ForNode(**data)
        models = config.as_model_list(cfg_yaml, variables)
        return self._filter(models)


class TestCaseNode(BaseTestNode):
    """
    testcase:
        name: test title
        index:
        path: sample.base.test_equal.test_function
        parameters:
        iterations:
        is-prerequisite:
        enable-mock:
        strict:
        repeat-number:
        rerun:
    """

    type: Literal['testcase'] = pydantic.Field('testcase')
    path: str
    name: Optional[str] = None
    index: Optional[int] = None
    parameters: Optional[ParametersType] = None
    iterations: Optional[IterationsType] = None
    is_prerequisite: bool = pydantic.Field(False, alias="is-prerequisite")
    enable_mock: bool = pydantic.Field(False, alias="enable-mock")
    strict: Optional[bool] = None
    repeat_number: int = pydantic.Field(1, alias="repeat-number")
    rerun: Optional[int | dict] = None

    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestCaseModel]:
        logger.debug("load tests from testcase: %s", self.path)
        tests = []
        func = locate(self.path)
        arguments = _get_arguments_from_parameters_and_iterations(self.parameters, self.iterations, variables)
        for testcase_model in _generate_testcase_model_from_func(func, arguments, self.is_prerequisite, self.index):
            testcase_model.name = eval_vars(self.name, variables)
            testcase_model.enable_mock = self.enable_mock
            testcase_model.strict = self.strict
            testcase_model.rerun = self.rerun
            for i in range(self.repeat_number):
                tests.append(testcase_model.model_copy())
        return tests


class TestNode(pydantic.RootModel):
    root: Annotated[
        Union[
            TestCaseNode, 'TestSuiteNode', 'ForNode',
            ClsLoaderNode, ObjLoaderNode, TagLoaderNode, YmlLoaderConfigNode,
        ],
        pydantic.Field(discriminator='type')
    ]

    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        return self.root.as_model_list(cfg_yaml, variables)


def validate_tests(values):
    tests = []
    for value in values:
        try:
            for k, v in value.items():
                kwargs = dict(type=k, **v)
                test = TestNode.model_validate(kwargs)
                tests.append(test)
        except pydantic.ValidationError as err:
            logger.exception(err)
    return tests


class TestSuiteNode(BaseTestNode, extra='allow'):
    """
    testsuite:
        name: test title
        tests:
            - testcase:
            - testsuite:
            - cls-loader:
            - yml-loader:
            - obj-loader:
            - tag-loader:
        iterations:
        path:
        flat:
    """
    type: Literal['testsuite'] = pydantic.Field('testsuite')
    name: str
    tests: List[TestNode]
    parameters: Optional[ParametersType] = None
    iterations: Optional[IterationsType] = None
    path: Optional[str] = None
    flat: bool = False

    @pydantic.field_validator("tests", mode="before")
    def validate_tests(cls, values):
        tests = validate_tests(values)
        return tests

    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestSuiteModel]:
        if variables is None:
            variables = {}

        if not self.iterations:
            params = dict()
            params.update(variables)
            if self.parameters:
                params.update(self.parameters)
            return [self.as_model_data(cfg_yaml, params)]

        models = []
        arguments = _get_arguments_from_parameters_and_iterations(self.parameters, self.iterations, variables)
        for argument in arguments:
            argument.kwds.update(variables)     # merge parent variables
            models.append(self.as_model_data(cfg_yaml, argument.kwds))
        return models

    def as_model_data(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> TestSuiteModel:
        if variables is None:
            variables = {}

        tests = []
        for test in self.tests:
            tests.extend(test.as_model_list(cfg_yaml, variables))

        exclude_keys = set()
        exclude_keys.update(self.model_fields.keys())

        model = TestSuiteModel(
            name=eval_vars(self.name, variables),
            tests=tests,
            path=eval_vars(self.path, variables),
            flat=self.flat,
            **self.model_dump(exclude=exclude_keys)
        )
        return model


class ForNode(BaseTestNode):
    """
    for:
        iterations:
            x: [1, 2]
            y: [1, 3]
        tests:
            - testcase:
            - testsuite:
            - cls-loader:
            - yml-loader:
            - tag-loader:
            - obj-loader:
    """
    type: Literal['for'] = pydantic.Field('for')
    iterations: IterationsType
    tests: List[TestNode]

    @pydantic.field_validator("tests", mode="before")
    def validate_tests(cls, values):
        return validate_tests(values)

    def as_model_list(self, cfg_yaml: FilePathType = None, variables: ParametersType = None) -> List[TestModelType]:
        logger.debug("load tests from for: %s", self)
        tests = []
        iters = self.iterations

        if isinstance(iters, list):
            params_list = iters
        elif isinstance(iters, dict):
            params_list = []
            for result in itertools.product(*iters.values()):
                params = dict(zip(iters.keys(), result))
                params_list.append(params)
        else:
            raise ValueError

        for params in params_list:
            params.update(variables)
            for test in self.tests:
                tests.extend(test.as_model_list(cfg_yaml, params))
        return tests


ForNode.model_rebuild()
TestSuiteNode.model_rebuild()
TestNode.model_rebuild()
