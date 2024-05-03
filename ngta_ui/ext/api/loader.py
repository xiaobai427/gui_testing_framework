# coding: utf-8

import re
import os
import json
import copy
import typing
import itertools

import yaml
import jsonschema

from coupling import fs, jsonpath
from coupling.dict import AttrDict
from abc import ABCMeta, abstractmethod

from ngta.util import str_func
from ngta.loader import BaseLoaderConfig, ConfigMapping, ObjLoaderConfig
from ngta.constants import PACKAGE_NAME
import logging
logger = logging.getLogger(__name__)


CURRENT_DIR = os.path.dirname(__file__)
SCHEMA_FILENAME = os.path.join(CURRENT_DIR, "schema.json")


def _construct_attr_dict(loader: yaml.Loader, node):
    loader.flatten_mapping(node)
    return AttrDict(loader.construct_pairs(node, deep=True))


class BaseTag(metaclass=ABCMeta):
    KEY = f'_{PACKAGE_NAME}_yml_tag'

    @property
    @abstractmethod
    def TAG(self):
        pass

    @classmethod
    @abstractmethod
    def constructor(cls, *args, **kwargs):
        pass

    def __init__(self, tag):
        self.tag = tag

    def as_dict(self):
        d = self.__dict__.copy()
        d[self.KEY] = self.tag
        return d

    def __str__(self):
        return str(self.as_dict())


class Exec(BaseTag):
    TAG = '!exec:'

    class Type:
        SQL = 1
        CYPHER = 2

    def __init__(self, tag, type, value):
        super().__init__(tag)
        self.type = type
        self.value = value

    def __repr__(self):
        return f'<{self.__class__.__name__}(tag:{self.tag}, type:{self.type}, value:{self.value})>'

    @classmethod
    def constructor(cls, loader, tag_suffix, node):
        tag = cls.TAG + tag_suffix
        type_ = getattr(cls.Type, tag_suffix.upper())
        loader.flatten_mapping(node)
        value = AttrDict(loader.construct_pairs(node, deep=True))
        return cls(tag, type_, value)


class Assert(BaseTag):
    TAG = '!assert'

    class Type:
        DEFAULT = 0
        CALLBACK = 1

    def __init__(self, tag, type, value):
        super().__init__(tag)
        self.type = type
        self.value = value

    @classmethod
    def constructor(cls, loader, tag_suffix, node):
        tag = cls.TAG + tag_suffix
        suffix = tag_suffix or ':'
        type_ = getattr(cls.Type, suffix[1:].upper(), cls.Type.DEFAULT)
        loader.flatten_mapping(node)
        value = AttrDict(loader.construct_pairs(node, deep=True))
        return cls(tag, type_, value)


class _CustomizedLoader(yaml.Loader):
    pass


# Change dict to AttrDict
_CustomizedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_attr_dict)

# Add !exec
_CustomizedLoader.add_multi_constructor(Exec.TAG, Exec.constructor)

# Add !assert
_CustomizedLoader.add_multi_constructor(Assert.TAG, Assert.constructor)


class ApiLoaderConfig(BaseLoaderConfig):
    TAG = "api-loader"

    def __init__(self, path: str, as_testsuite: str = "") -> None:
        assert os.path.exists(path)
        super().__init__(as_testsuite)
        self.path = path
        with open(SCHEMA_FILENAME, encoding="utf-8") as f:
            self.schema = json.load(f)

    @classmethod
    def from_config_dict(cls, d: dict) -> "ApiLoaderConfig":
        raise NotImplementedError

    def _validate(self, data):
        logger.debug("validate file %s by schema: %s", self.path, SCHEMA_FILENAME)
        jsonschema.validate(data, self.schema)

    @classmethod
    def _load_yaml(cls, filename):
        with open(filename, encoding='utf-8') as f:
            data = yaml.load(f, Loader=_CustomizedLoader)
        return data

    def _generate_from_yml(self, filename):
        from .http.case import HttpApiYmlTestCase

        logger.debug("found api test by yaml: %s", filename)
        data = self._load_yaml(filename)
        self._validate(data)

        api_type = jsonpath.search("$.api.type", data)
        if api_type == "http":
            path = str_func(HttpApiYmlTestCase.test_api_by_rule)
        else:
            raise NotImplementedError

        kwargs = jsonpath.search("$.api.define", data, default=AttrDict())
        tests = jsonpath.search("$.api.tests", data)
        if isinstance(tests, dict):
            for name, test in tests.items():
                yield self._handle_test(path, name, test, kwargs)
        elif isinstance(tests, list):
            for test in jsonpath.search("$.api.tests", data):   # type: dict
                name = test.pop('name')
                yield self._handle_test(path, name, test, kwargs)
        else:
            pass

    def _handle_test(self, path: str, name: str, rule: dict, kwargs: dict):
        parameters = rule.pop("parametrize", None)
        if parameters:
            for result in itertools.product(*parameters.values()):
                kwargs.update(zip(parameters.keys(), result))
                test = {
                    "name": self._format_str(name, kwargs),
                    "path": path,
                    "parameters": {
                        "rule": self._recur_format_data(copy.deepcopy(rule), kwargs)
                    }

                }
                yield test
        else:
            test = {
                "name": self._format_str(name, kwargs),
                "path": path,
                "parameters": {
                    "rule": self._recur_format_data(rule, kwargs)
                }
            }
            yield test

    def _load_as_tests(self) -> typing.List[dict]:
        tests = []

        for found in fs.find(self.path):
            if os.path.isfile(found):
                basename = os.path.basename(found)
                if re.search(r'^test.*\.ya?ml$', basename, re.I):
                    for handle_test in self._generate_from_yml(found):
                        for test in handle_test:
                            tests.append(test)
                elif re.search(r'^test.*\.py$', basename, re.I):
                    logger.debug("found api test by py: %s", found)
                    loader = ObjLoaderConfig(found)
                    tests.extend(loader.as_list())
                else:
                    pass
        return tests

    @staticmethod
    def _format_str(s, kwargs):
        if s.startswith("${") and s.endswith("}"):
            return eval(s[2:-1], globals(), kwargs)
        else:
            matches = re.findall(r'\$\{.*?\}', s)
            for match in matches:
                value = eval(match[2:-1], globals(), kwargs)
                s = s.replace(match, str(value))
            return s

    def _recur_format_data(self, data, kwargs):
        if isinstance(data, dict):
            # when can't format str with ${}, it will raise AttributeError
            # capture the error and remove the key from dict
            should_removed = []
            for k, v in data.items():
                try:
                    data[k] = self._recur_format_data(v, kwargs)
                except AttributeError:
                    should_removed.append(k)
                    logger.error("Can't format %s: %s, remove it.", k, v)
            for k in should_removed:
                del data[k]
        elif isinstance(data, list):
            for i, v in enumerate(data):
                data[i] = self._recur_format_data(v, kwargs)
        elif isinstance(data, str):
                data = self._format_str(data, kwargs)
        elif isinstance(data, (Exec, Assert)):
            data.value = self._recur_format_data(data.value, kwargs)
        return data


ConfigMapping.register(ApiLoaderConfig)
