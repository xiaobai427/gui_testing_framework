# coding: utf-8

import json
import jsonschema
import inspect
import pprint
import difflib
import posixpath

from requests.compat import urljoin
from abc import ABCMeta, abstractmethod
from coupling import jsonpath
from coupling.dict import pick, omit

from ngta import TestCase as BaseTestCase, test
from ngta.assertions import AssertionBuilder
from ngta.ext.database import BaseHelper, Helpers
from ngta.serialization import pformat_json
from ngta.util import locate, truncate_str
from .bench import TestBench, RequestsSession
from .record import HttpApiTestCaseResultRecord
from ..loader import Exec, Assert

import logging
logger = logging.getLogger(__name__)


class TestCase(BaseTestCase, metaclass=ABCMeta):
    """
    base class for http api test
    """
    Record = HttpApiTestCaseResultRecord

    @property
    @abstractmethod
    def PATH(self) -> str:
        pass

    @property
    def url(self) -> str:
        return urljoin(self.base_url, self.PATH)

    @property
    def testbench(self) -> TestBench:
        return self.context.testbench

    @property
    def base_url(self) -> str:
        return self.testbench.base_url

    @property
    def session(self) -> RequestsSession:
        return self.testbench.session

    @property
    def db_helper(self) -> BaseHelper:
        return self.db_helpers.first()

    @property
    def db_helpers(self) -> Helpers:
        return self.testbench.db_helpers

    def new_http_session(self):
        return self.testbench.new_http_session()

    def urljoin(self, *paths):
        paths = [str(path) for path in paths]
        return urljoin(self.base_url, posixpath.join(*paths))

    def check_json_by_schema(self, data, schema):
        msg = "response body with json schema should be successfully."
        try:
            logger.debug("response body with json schema: \n%s", pprint.pformat(schema))
            jsonschema.validate(data, schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError):
            logger.exception("")
            self.fail_(msg)
        else:
            self.pass_(msg)

    @classmethod
    def log_difference(cls, actual, expect):
        pformat_actual = pformat_json(actual)
        pformat_expect = pformat_json(expect)
        logger.debug("actual: %s", pformat_actual)
        logger.debug("expect: %s", pformat_expect)
        diff = difflib.ndiff(pformat_actual.splitlines(), pformat_expect.splitlines())
        logger.debug("compare: \n%s", "\n".join(diff))

    @classmethod
    def pformat_json(cls, data):
        return pformat_json(data)

    @classmethod
    def pprint_json(cls, data):
        print(cls.pformat_json(data))


class HttpApiYmlTestCase(TestCase):
    """
    class for test http api by yaml config.
    """

    PATH = ""

    def __init__(self, *args, **kwargs):
        """
        :param rule: refer to ngta.api.schema.json
        """
        super().__init__(*args, **kwargs)
        self.rule = self.parameters.rule
        self.resp = None

    @property
    def url(self) -> str:
        path = self.rule["request"].get("path", "")
        self.PATH = path
        return urljoin(self.base_url, path)

    @test
    def test_api_by_rule(self, rule: dict):
        skip = rule.get("skip", None)
        if skip:
            reason = "" if isinstance(skip, bool) else skip
            self.skip_(reason)

        kwargs = rule["request"].copy()

        if "url" not in kwargs:
            kwargs.pop("path", None)
            kwargs["url"] = self.url

        if "method" not in kwargs:
            kwargs["method"] = "GET"
        self.resp = self.session.request(**kwargs)     # type: requests.Response
        self.check_status_code()
        self.check_headers()
        self.check_body()

    def check_status_code(self):
        rule = jsonpath.search("$.assertions.status_code", self.rule, None)
        self._check(rule, self.resp.status_code, 'status_code ')

    def check_headers(self):
        rule = jsonpath.search("$.assertions.headers", self.rule, default={})
        if rule:
            self._check(rule, self.resp.headers, 'headers ')

    def check_body(self):
        json_rule = jsonpath.search("$.assertions.json", self.rule, default=None)
        if json_rule:
            self.check_json()

        text_rule = jsonpath.search("$.assertions.text", self.rule, default=None)
        if text_rule:
            self._check(text_rule, self.resp.text, 'text ')

    def check_json(self):
        json_rule = jsonpath.search('$.assertions.json', self.rule, default=None)
        schema_rule = jsonpath.search("$.assertions.json.schema", self.rule, default=None)
        search_rule = jsonpath.search("$.assertions.json.search", self.rule, default=None)

        data = self.resp.json()
        if schema_rule or search_rule:
            if schema_rule:
                with open(schema_rule) as f:
                    schema = json.load(f)
                self.check_json_by_schema(data, schema)

            if search_rule:
                is_list = isinstance(search_rule, list)
                with self.soft_assertions():
                    for path_rule in search_rule:
                        if is_list:
                            path = path_rule.pop("path")      # type: str
                            rule = path_rule
                        else:
                            path = path_rule                    # type: str
                            rule = search_rule[path]

                        try:
                            logger.debug("search by jsonpath: %s", path)
                            value = jsonpath.search(path, data)
                        except jsonpath.NotFoundError:
                            self.assert_that(True, f"jsonpath {path} can't be found").is_false()
                        else:
                            msg_prefix = f'jsonpath <{path}> found value '
                            self._check(rule, value, msg_prefix)
        else:
            self._check(json_rule, data, 'json ')

    def _check(self, rule, value, msg_prefix):
        actual_value = value
        if isinstance(rule, Assert):
            if rule.type == Assert.Type.CALLBACK:
                func = locate(rule.value.path)
                args = rule.value.get('args', ())
                kwds = rule.value.get('kwds', {})
                func(self, actual_value, *args, **kwds)
            elif rule.type == Assert.Type.DEFAULT:
                if isinstance(actual_value, dict):
                    includes = rule.value.pop("includes", ())
                    excludes = rule.value.pop("excludes", ())

                    includes = [includes] if isinstance(includes, str) else includes
                    excludes = [excludes] if isinstance(excludes, str) else excludes

                    if includes:
                        actual_value = pick(actual_value, keys=includes)

                    if excludes:
                        actual_value = omit(actual_value, keys=excludes)

                builder = self.assert_that(actual_value)
                for matching_name, expected_value in rule.value.items():
                    self._assert(builder, matching_name, expected_value, msg_prefix)
            else:
                raise NotImplementedError
        else:
            builder = self.assert_that(actual_value)
            self._assert(builder, 'is_equal_to', rule, msg_prefix)

    def _assert(self, builder: AssertionBuilder, matching_name: str, expect_value, msg_prefix=''):
        actual_value = builder.val
        expect_value = self._get_expect_value(expect_value)

        if not builder.description:
            message = msg_prefix + f"<{truncate_str(actual_value, 10)}> should {matching_name} <{truncate_str(expect_value, 10)}>"
            builder.described_as(message)
        self.log_difference(actual_value, expect_value)
        method = getattr(builder, matching_name)

        sig = inspect.signature(method)
        if sig.parameters:
            method(expect_value)
        else:
            method()

    def _get_expect_value(self, rule):
        if isinstance(rule, Exec):
            if rule.type == Exec.Type.SQL:
                value = self._get_expect_value_by_sql(rule.value)
            else:
                raise NotImplementedError
        else:
            value = rule
        return value

    def _get_expect_value_by_sql(self, sql_rule):
        db_helper_key = sql_rule.get("db_helper", None)
        db_helper_obj = self.db_helpers.get(db_helper_key, self.db_helpers.Type.RMDBS, default=self.db_helper)
        results = db_helper_obj.query(sql_rule.query, **sql_rule.get('params', {}))
        return results.all(as_dict=True)
