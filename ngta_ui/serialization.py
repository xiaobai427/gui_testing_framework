# coding: utf-8

import json
import enum
from pathlib import Path
from abc import ABCMeta
from pydantic import BaseModel as Model, Field
from coupling.dict import omit, pick, AttrDict as BaseDict
from datetime import datetime

from .constants import CALLEE_KEY, FilePathType
from .util import locate, str_class, pick_callee_kwargs

import logging
logger = logging.getLogger(__name__)


class AttrDict(BaseDict):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        d = cls()
        d.update(v)
        return d


def json_dump_fallback(obj):
    if hasattr(obj, "dict"):
        return obj.dict()
    elif isinstance(obj, enum.IntEnum):
        return obj.value
    elif isinstance(obj, enum.Enum):
        return obj.value
    elif isinstance(obj, datetime):
        return obj.isoformat(timespec="milliseconds")
    else:
        return str(obj)


def json_dumps(data, **kwargs):
    params = dict(
        default=json_dump_fallback,
        indent=2
    )
    params.update(kwargs)
    return json.dumps(data, **params)


def pformat_json(data, **kwargs):
    return json_dumps(data, **kwargs)


class Serializable(metaclass=ABCMeta):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, data):
        return cls.parse_data(data)

    def dict(self, *, include=None, exclude=None) -> dict:
        d = self.__dict__.copy()
        if include:
            d = pick(d, keys=include)

        if exclude:
            d = omit(d, keys=exclude)

        d[CALLEE_KEY] = str_class(self.__class__)
        return d

    @classmethod
    def construct(cls, data):
        kwargs = pick_callee_kwargs(cls, data)
        return cls(**kwargs)

    @classmethod
    def parse_data(cls, data: dict):
        if CALLEE_KEY in data:
            path = data[CALLEE_KEY]
            clazz = locate(path)
        else:
            clazz = cls
        return clazz.construct(data)

    @classmethod
    def parse_text(cls, text):
        d = json.loads(text)
        return cls.parse_data(d)

    @classmethod
    def parse_file(cls, path: FilePathType):
        path = Path(path)
        return cls.parse_text(path.read_text())


class BaseModel(Model):
    def __new__(cls, **data):
        """
        try construct an instance with sub-model data.
        """
        if CALLEE_KEY in data:
            path = data[CALLEE_KEY]
            clazz = locate(path)
        else:
            clazz = cls
        obj = object.__new__(clazz)
        # obj.update_forward_refs()
        return obj

    def __setattr__(self, attr, value):
        # Can't set protected and private attribute directly, we need to set it via object.__setattr__
        # https://github.com/samuelcolvin/pydantic/issues/655
        if attr in self.__slots__:
            object.__setattr__(self, attr, value)
        else:
            super().__setattr__(attr, value)

    def dict(self, *args, **kwargs):
        d = super().model_dump(*args, **kwargs)
        exclude = kwargs.get('exclude') or {}
        if CALLEE_KEY not in exclude:
            d[CALLEE_KEY] = str_class(self.__class__)
        return d


def parse_dict(data: dict, key=CALLEE_KEY):
    logger.debug("parse_dict: %s", pformat_json(data))
    path = data[key]
    class_or_func = locate(path)
    kwargs = omit(data, key)
    try:
        obj = class_or_func(**kwargs)
    except Exception as err:
        raise err.__class__(f'call {class_or_func} encounter error: {err}')
    return obj


def parse_text(text: str | bytes):
    d = json.loads(text)
    return parse_dict(d)


def parse_file(path: FilePathType):
    logger.debug("parse_file: %s", path)
    with open(path) as f:
        d = json.load(f)
    return parse_dict(d)
