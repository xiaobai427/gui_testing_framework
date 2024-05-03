# coding: utf-8

import yaml
import jmespath
from typing import List, Union

from .bench import TestBench
from ..config import YamlLoader as BaseYamlLoader
from ..constants import YML_OBJECT_NEW_TAG, CALLEE_KEY, FilePathType

import logging
logger = logging.getLogger(__name__)


class YamlLoader(BaseYamlLoader):
    def construct_object(self, node, deep=True):
        """
        Auto construct object with property "()"
        """
        if isinstance(node, yaml.MappingNode):
            if node.tag != YML_OBJECT_NEW_TAG:
                for key_node, val_node in node.value:
                    if key_node.value == CALLEE_KEY:
                        node.tag = YML_OBJECT_NEW_TAG
                        break
        return super().construct_object(node, deep)


class BenchSetting:
    def __init__(self, yml_path: FilePathType):
        self.yml_path = yml_path
        self.data = None
        self.load_setting()

    def load_setting(self):
        with open(self.yml_path, "r", encoding='utf-8') as f:
            self.data = yaml.load(f.read(), Loader=YamlLoader)

    def get_testbenches(self) -> List[TestBench]:
        return self.data.get("testbenches", [])


class AgentSetting:
    def __init__(self, yml_path: FilePathType):
        self.yml_path = yml_path
        self.data = None
        self.load_setting()

    def load_setting(self):
        with open(self.yml_path, "r", encoding='utf-8') as f:
            self.data = yaml.load(f.read(), Loader=YamlLoader)

    def get(self, path: str) -> Union[int, float, str, list, dict, None]:
        return jmespath.search(path, self.data)
