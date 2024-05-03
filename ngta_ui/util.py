# coding: utf-8

import os
import sys
import pydoc
import inspect
import multiprocessing
from typing import Callable, List, Optional
from fnmatch import fnmatch

try:
    from os.path import samefile as is_samefile
except ImportError:
    from shutil import _samefile as is_samefile

import logging
logger = logging.getLogger(__name__)


def get_class_that_defined_method(method):
    if inspect.ismethod(method):
        for cls in inspect.getmro(method.__self__.__class__):
            if cls.__dict__.get(method.__name__) is method:
                return cls
        method = method.__func__  # fallback to __qualname__ parsing
    if inspect.isfunction(method):
        cls = getattr(inspect.getmodule(method),
                      method.__qualname__.split('.<locals>', 1)[0].rsplit('.', 1)[0])
        if isinstance(cls, type):
            return cls
    return getattr(method, '__objclass__', None)  # handle special descriptor objects


def str_class(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def str_func(func) -> str:
    cls = get_class_that_defined_method(func)
    if cls:
        return f"{str_class(cls)}.{func.__name__}"
    else:
        return f"{inspect.getmodule(func).__name__}.{func.__name__}"


def get_test_path(obj):
    if inspect.isclass(obj):
        return str_class(obj)

    if inspect.isfunction(obj) or inspect.ismethod(obj):
        return str_func(obj)

    raise NotImplementedError


def remove_path_illegal_chars(name: str) -> str:
    illegal_chars = r'/\*?<>|:"' if sys.platform == "win32" else '/\0'
    return name.translate({ord(i): None for i in illegal_chars})


def revise_path(path: str) -> str:
    return r"\\?\%s" % path if len(path) > 255 and sys.platform == "win32" else path


def get_module_name_safely(path: str, package_dir: str = None) -> str:
    if not package_dir:
        package_dir = os.path.dirname(path)
    if package_dir not in sys.path:
        sys.path.insert(0, package_dir)
    path_without_ext = os.path.splitext(path)[0]
    return os.path.relpath(path_without_ext, package_dir).replace(os.path.sep, '.')


def get_object_name_list_by_path(path: str, package_dir: str = None, pattern: str = "test*.py") -> List[str]:
    """
    Base class for handling test event.

    Parameters
    ----------
    path : str
        path can be a file, dir, link or python path of package, module, function, class and method.

    package_dir : bool, optional
        package dir for locate path

    pattern : bool, optional
        used to found matched test file.
    """
    names = []
    if os.path.isfile(path):
        module_name = get_module_name_safely(path, package_dir)
        names.append(module_name)
    elif os.path.isdir(path):
        for dir_path, dir_names, filenames in os.walk(path):
            for filename in filenames:
                if fnmatch(filename, pattern):
                    module_name = get_module_name_safely(os.path.join(dir_path, filename), package_dir)
                    names.append(module_name)
    elif os.path.islink(path):
        names.extend(get_object_name_list_by_path(os.path.realpath(path), package_dir, pattern))
    else:
        names.append(path)
    return names


def locate(path: str):
    obj = pydoc.locate(path.strip())
    if obj is None:
        raise LookupError(f"Can't locate object with path: {path}")
    return obj


def truncate_str(s: str, length: int = 255, placeholder: str = "..."):
    if not isinstance(s, str):
        s = str(s)
    if len(s) > length:
        return s[0:length] + placeholder
    return s


def pick(d: dict, *args, keys=(), ignore_error=True):
    includes = []
    includes.extend(args)
    includes.extend(keys)
    new = d.__class__()
    for k in includes:
        try:
            new[k] = d[k]
        except KeyError:
            if not ignore_error:
                raise
    return new


def pick_callee_kwargs(callee: Callable, data: dict):
    sig = inspect.signature(callee)
    kwargs = pick(data, keys=sig.parameters.keys())
    ba = sig.bind(**kwargs)
    ba.apply_defaults()
    return ba.arguments


def get_first_non_whitespace_char_index(s):
    return len(s) - len(s.lstrip())


def trim_doc(doc: str) -> Optional[str]:
    if doc is None:
        return doc

    lines = doc.splitlines()
    count = get_first_non_whitespace_char_index(lines[1])
    for index, line in enumerate(lines[1:]):
        # ignore trim empty line.
        if len(line) == 0 or len(line.strip()) == 0:
            continue

        if get_first_non_whitespace_char_index(line) > count:
            lines[index] = line[count:]
    return '\n'.join(lines).strip()


def get_source_code(obj) -> Optional[str]:
    try:
        return inspect.getsource(obj)
    except (IndexError, OSError):
        pass


def get_current_process_name():
    return multiprocessing.current_process().name
