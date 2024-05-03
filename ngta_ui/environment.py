# coding: utf-8

import os
import sys
import time
import difflib
import threading
import importlib
import shutil
from pathlib import Path
from typing import NoReturn, Optional

import yaml
from .constants import (
    PACKAGE_NAME, CACHE_YML_BASENAME, INIT_DIR_BASENAME,
    CASE_DIR_BASENAME, LIBS_DIR_BASENAME, LOGS_DIR_BASENAME, CONF_DIR_BASENAME,
    ExitCode
)

import logging
logger = logging.getLogger(__name__)


def _diff(src: str, dst: str) -> NoReturn:
    with open(src) as f1:
        lines1 = f1.readlines()
    with open(dst) as f2:
        lines2 = f2.readlines()

    changes = list(difflib.context_diff(lines1, lines2))
    if changes:
        dst_dir = os.path.dirname(dst)
        dst_new_basename = os.path.basename(src)
        dst_new_fullname = os.path.join(dst_dir, dst_new_basename)
        shutil.copy2(src, dst_new_fullname)
        print(f"WARNING: {dst_new_fullname}'s content is not same with {dst}, check and revise it manually!")


class WorkEnv:
    """
    A class which include each kind of directory, config files and etc.

    Parameters
    ----------
    work_dir: str, optional
        Specify work directory.
        If not provided, it would find .ngta's dir as work dir.
    """

    _inst = None
    _lock = threading.Lock()

    work_dir: Optional[Path]
    cache_yml: Optional[Path]
    cache_data: dict
    case_dir: Optional[Path]
    libs_dir: Optional[Path]
    logs_dir: Optional[Path]
    anchor: Optional[Path]

    # cfg: Optional[yaml.Loader]

    @classmethod
    def instance(cls, *args, **kwargs):
        if cls._inst is None:
            with cls._lock:
                if cls._inst is None:
                    cls._inst = cls(*args, **kwargs)
        return cls._inst

    def __init__(self, work_dir: Path = None):
        work_dir = work_dir or self.find_work_dir(self.cwd)
        if work_dir:
            self.init_by_work_dir(work_dir)
        else:
            self.work_dir = None
            self.case_dir = None
            self.libs_dir = None
            self.logs_dir = None
            self.anchor = None
            self.cfg = None
            self.cache_yml = None

    def init_by_work_dir(self, work_dir: Path):
        self.work_dir = work_dir.absolute()

        self.anchor = self.work_dir.joinpath(".%s" % PACKAGE_NAME)
        with self.anchor.open('r', encoding='utf-8') as f:
            self.cfg = yaml.load(f, Loader=yaml.Loader)

        self.cache_yml = self._get_path_from_cfg("cache_yml", CACHE_YML_BASENAME)
        if self.cache_yml.exists():
            with self.cache_yml.open('r', encoding='utf-8') as f:
                self.cache_data = yaml.load(f, Loader=yaml.Loader)
                if self.cache_data is None:
                    self.cache_data = {}
        else:
            self.cache_data = {}

        self.case_dir = self._get_path_from_cfg("case_dir", CASE_DIR_BASENAME)
        self.libs_dir = self._get_path_from_cfg("libs_dir", LIBS_DIR_BASENAME)
        self.logs_dir = self._get_path_from_cfg("logs_dir", LOGS_DIR_BASENAME)

        # Add lib and cases dir into sys.path
        sys.path.insert(0, str(self.libs_dir))
        sys.path.insert(0, str(self.case_dir))
        self._do_pre_imports()

    def _get_path_from_cfg(self, key, default) -> Path:
        """
        Load configurations from .ngta file.
        """
        path = self.cfg.get(key, None)
        if path:
            if not os.path.isabs(path):
                path = self.work_dir.joinpath(path).absolute()
        else:
            path = self.work_dir.joinpath(default)
        return path

    def _do_pre_imports(self) -> NoReturn:
        pre_imports = self.cfg.get('pre_imports', None)
        if pre_imports:
            module_names = pre_imports.split(',')
            for module_name in module_names:
                stripped = module_name.strip()
                if stripped:
                    importlib.import_module(stripped)

    @property
    def cwd(self) -> Path:
        return Path(os.getcwd())

    def new_output_dir(self) -> Optional[Path]:
        if self.work_dir:
            return self.work_dir.joinpath(LOGS_DIR_BASENAME, time.strftime("%Y-%m-%d_%H-%M-%S"))
        return None

    @classmethod
    def find_work_dir(cls, current_dir: Path = Path(os.getcwd())) -> Optional[Path]:
        """
        Find work dir from cwd and its ancestors by locate .ngta file.
        """
        for filename in current_dir.iterdir():
            if filename.name == f".{PACKAGE_NAME}":
                return current_dir

        parent_dir = current_dir.parent
        if parent_dir.samefile(current_dir):
            return None
        else:
            return cls.find_work_dir(parent_dir)

    @classmethod
    def init(cls, dest_dir: str, include_sample: bool = True) -> NoReturn:
        """
        Init destination dir as work dir.

        Parameters
        ----------
        dest_dir: str
            Specify destination dir.

        include_sample: bool, optional
            Whether include sample cases when initialize work dir.
        """
        logging.basicConfig(level=logging.DEBUG)
        os.makedirs(dest_dir, exist_ok=True)
        ngta_dir = os.path.dirname(__file__)
        init_dir = os.path.join(ngta_dir, INIT_DIR_BASENAME)
        conf_dir: str = os.path.join(init_dir, CONF_DIR_BASENAME)
        ignore = None if include_sample else lambda src, names: [name for name in names if "sample" in name]

        shutil.copytree(init_dir, dest_dir, ignore=ignore, dirs_exist_ok=True)
        os.makedirs(os.path.join(dest_dir, LIBS_DIR_BASENAME), exist_ok=True)
        os.makedirs(os.path.join(dest_dir, LOGS_DIR_BASENAME), exist_ok=True)

        for basename in os.listdir(conf_dir):
            src_conf = os.path.join(conf_dir, basename)
            dst_conf = os.path.join(dest_dir, CONF_DIR_BASENAME, basename.replace("_sample", ""))
            if os.path.exists(dst_conf):
                _diff(src_conf, dst_conf)
            else:
                shutil.copy2(src_conf, dst_conf)

    def get_last_failed_output_dir(self) -> Optional[Path]:
        if self.cache_yml and self.cache_yml.exists():
            histories = self.cache_data.get('histories', [])
            for history in reversed(histories):
                if history['exit_code'] != ExitCode.OK:
                    return Path(history['output_dir'])
            return None

    def add_history(self, history):
        if self.cache_yml and self.cache_yml.exists():
            histories = self.cache_data.setdefault('histories', [])
            histories.append(history)
            with self.cache_yml.open('w', encoding='utf-8') as f:
                yaml.dump(self.cache_data, f)

    def get_current_commit(self) -> dict | None:
        import git

        if self.work_dir:
            try:
                repo = git.Repo(self.work_dir)
            except git.exc.InvalidGitRepositoryError:
                return
            else:
                head = repo.head
                commit = repo.head.commit

                return {
                    'active_branch': None if head.is_detached else str(repo.active_branch),
                    # 'current_tags': [str(tag) for tag in repo.tags if tag.commit == repo.head.commit],
                    'working_dir': str(self.work_dir),
                    'hexsha': commit.hexsha,
                    'author_name': commit.author.name,
                    'author_mail': commit.author.email,
                    'authored_datetime': commit.authored_datetime.isoformat(),
                    'message': commit.message,
                }
