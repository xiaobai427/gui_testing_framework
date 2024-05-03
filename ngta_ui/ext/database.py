# coding: utf-8

import enum
import logging
import typing
import warnings
from abc import ABCMeta, abstractmethod
from contextlib import contextmanager
import sqlalchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.orm import sessionmaker, scoped_session

import records

logger = logging.getLogger(__name__)


class BaseHelper(metaclass=ABCMeta):
    @abstractmethod
    def query(self, *args, **kwargs):
        pass


class HelperType(enum.IntEnum):
    RMDBS = 1


class SqlAlchemyHelper(records.Database, BaseHelper):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._base = None
        self.inspector = sqlalchemy.inspect(self._engine)     # type: Inspector
        self.SessionFactory = sessionmaker(bind=self._engine, expire_on_commit=False)

    @property
    def models(self):
        if not self._base:
            self._base = automap_base()        # auto map existing database.
            self._base.prepare(self._engine, reflect=True)
        return self._base.classes

    @contextmanager
    def session(self):
        session = scoped_session(self.SessionFactory)
        try:
            yield session
        finally:
            session.remove()


_UNSET = object()


class Helpers:
    Type = HelperType

    def __init__(self):
        self._helpers = dict()

    def __getattr__(self, item):
        """
        try get specify helper by name or type.
        """
        return self.get(item, item.upper())

    def add(self, name, helper):
        self._helpers[name] = helper

    def get(self, name=None, type=None, default=_UNSET):
        """
        Used to find helper object.
        if there is no name, but type provided, it would return first ma
        :param name: helper name
        :param type: helper type
        :param kwargs: check whether
        :return: helper object or None
        """
        try:
            if name in self._helpers:
                return self._helpers[name]
            else:
                if type is not None:
                    found = []
                    helper_cls = HelperFactory.MAPPING.get(type)
                    for helper_obj in self._helpers.values():
                        if isinstance(helper_obj, helper_cls):
                            found.append(helper_obj)
                    if found:
                        if len(found) > 1:
                            raise LookupError(f'Multiple db helpers found by type {type}.')
                        else:
                            return found[0]
                    else:
                        raise LookupError(f"Can't find db helpers by type {type}.")
                else:
                    return self.first()
        except LookupError:
            if default is _UNSET:
                raise
            else:
                return default

    def first(self) -> BaseHelper:
        if not self._helpers:
            raise LookupError('There are no db helpers configured.')
        return list(self._helpers.values())[0]


class HelperFactory:
    MAPPING = {
        'SQLALCHEMY': SqlAlchemyHelper,
        'FIREBIRD': SqlAlchemyHelper,
        'MYSQL': SqlAlchemyHelper,
        'MSSQL': SqlAlchemyHelper,
        'ORACLE': SqlAlchemyHelper,
        'POSTGRESQL': SqlAlchemyHelper,
        'SQLITE': SqlAlchemyHelper,
        'SYBASE': SqlAlchemyHelper,
        HelperType.RMDBS.name: SqlAlchemyHelper,
        HelperType.RMDBS.value: SqlAlchemyHelper,
    }

    @classmethod
    def register(cls, type, helper_cls):
        if type in cls.MAPPING:
            msg = f'{type} has already registered, the original value will be overwrited by {helper_cls}.'
            warnings.warn(msg)
        cls.MAPPING[type] = helper_cls

    @classmethod
    def new_helper(cls, type, *args, **kwargs) -> BaseHelper:
        if isinstance(type, str):
            type = type.upper()
        helper_cls = cls.MAPPING[type]
        return helper_cls(*args, **kwargs)

    @classmethod
    def new_helpers(cls, configs) -> Helpers:
        """
        :param configs: sample
            [
                {'name': 'question', 'type': 'rmdbs', 'url': 'mysql+pymysql://root:root@192.168.41.17/test'},
            ]
        :return:
        """
        helpers = Helpers()
        for config in configs:
            db_name = config.pop('name')
            db_type = config.pop('type', HelperType.RMDBS)
            if 'db_url' not in config:
                config['db_url'] = config.pop('url')
            db_helper = HelperFactory.new_helper(db_type, **config)
            helpers.add(db_name, db_helper)
        return helpers


class BaseOperation(metaclass=ABCMeta):
    def __init__(self, helper=None):
        self._helper = helper

    @abstractmethod
    def exec(self):
        pass

    @abstractmethod
    def undo(self):
        pass

    @property
    def helper(self):
        if self._helper:
            if isinstance(self._helper, str):
                raise NotImplementedError
            return self._helper
        else:
            raise NotImplementedError

    @helper.setter
    def helper(self, helper):
        self._helper = helper


class SelectSQLCommand(BaseOperation):
    def __init__(self, sql: str, helper=None):
        super().__init__(helper)
        self.sql = sql

    def exec(self):
        return self.helper.execute(self.sql)

    def undo(self):
        pass

    def __repr__(self):
        return f"{self.__class__.__name__}<sql:{self.sql}>"


class ChangeCommand(BaseOperation, metaclass=ABCMeta):
    def __init__(self, table: str, helper=None):
        super().__init__(helper)
        self.table = table

    @property
    def model(self):
        return getattr(self.helper.models, self.table)


class InsertCommand(ChangeCommand):
    def __init__(self,
                 table: str,
                 cols: typing.Sequence,
                 rows: typing.Sequence,
                 helper=None):
        super().__init__(table, helper)
        self.cols = cols
        self.rows = rows
        self.data = []

    def exec(self):
        model = self.model
        with self.helper.session() as session:
            for row in self.rows:
                kwargs = dict(zip(self.cols, row))
                obj = model(**kwargs)
                session.add(obj)
                self.data.append(obj)
            session.commit()
        return self.data

    def undo(self):
        with self.helper.session() as session:
            for obj in self.data:
                session.delete(obj)
            session.commit()


class UpdateCommand(ChangeCommand):
    def __init__(self,
                 table: str,
                 values,
                 criterion: typing.Sequence = None,
                 condition: dict = None,
                 helper=None):
        super().__init__(table, helper)
        self.value = values
        self.criterion = criterion
        self.condition = condition

    def exec(self):
        pass

    def undo(self):
        pass


class DeleteCommand(ChangeCommand):
    def __init__(self,
                 table: str,
                 criterion: typing.Sequence = None,
                 condition: dict = None,
                 helper=None):
        super().__init__(table, helper)
        if criterion is None and condition is None:
            raise ValueError("criterion or condition is alternative.")
        self.criterion = criterion
        self.condition = condition
        self.data = None

    def exec(self):
        with self.helper.session() as session:
            if self.criterion:
                query = session.query(self.model).filter(*self.criterion)
            else:
                query = session.query(self.model).filter_by(**self.condition)
            self.data = query.all()
            query.delete()
            session.commit()
        return self.data

    def undo(self):
        with self.helper.session() as session:
            for obj in self.data:
                session.add(obj)
            session.commit()
