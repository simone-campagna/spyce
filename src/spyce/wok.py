import itertools
import functools
import sys

from collections.abc import Mapping
from pathlib import Path

import yaml

from .color import colored
from .flavor import Flavor, FlavorParseError
from .log import LOG
from .spyce import SpyceError, SpycyFile

__all__ = [
    'default_wok_filename',
    'find_wok_path',
    'WokError',
    'WokFile',
    'Wok',
    'load_wok',
]


DEFAULT_WOK_FILENAME = '.wok-project.yaml'


def default_wok_filename():
    return DEFAULT_WOK_FILENAME


def find_wok_path(base_dir=None):
    if base_dir is None:
        base_dir = Path.cwd()
    while True:
        wpath = base_dir / DEFAULT_WOK_FILENAME
        if wpath.is_file():
            return wpath
        if base_dir.parent == base_dir:
            return None
        base_dir = base_dir.parent


class WokError(SpyceError):
    pass


class WokMixin:
    def __init__(self, base_dir, filename):
        self.base_dir = Path(base_dir).absolute()
        self.filename = Path(filename).absolute()

    def abs_path(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.base_dir / path
        return path

    def rel_path(self, path):
        path = Path(path).absolute()
        if self.base_dir in path.parents:
            return path.relative_to(self.base_dir)
        return path


class WokFile(WokMixin, Mapping):
    def __init__(self, base_dir, filename, target_path, source_path, spyces):
        super().__init__(base_dir, filename)
        self.target_path = self.abs_path(target_path)
        if source_path is None:
            source_path = self.target_path
        else:
            source_path = self.abs_path(source_path)
        self.source_path = source_path
        self.target_rel_path = self.rel_path(self.target_path)
        self.source_rel_path = self.rel_path(self.source_path)
        self.spyces = dict(spyces)

    @property
    def name(self):
        return str(self.target_rel_path)

    def __getitem__(self, name):
        return self.spyces[name]

    def __iter__(self):
        yield from self.spyces

    def __len__(self):
        return len(self.spyces)

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.source!r}, {self.spyces!r})'

    def _use_source(self):
        source_path = self.source_path
        if not source_path.is_file():
            raise WokError('file {self.source_rel_path}: source file missing')
        source_stat = source_path.stat()
        target_path = self.target_path
        if target_path.is_file() and target_path.stat().st_ctime > source_stat.st_ctime:
            return self.target_rel_path, target_path
        return self.source_rel_path, source_path

    def fry(self, filters=None):
        source_rel_path, source_path = self._use_source()
        target_rel_path, target_path = self.target_rel_path, self.target_path
        spycy_file = SpycyFile(source_path)
        LOG.info(f'{source_rel_path} -> {target_rel_path}')
        with spycy_file.refactor(target_path):
            if filters:
                included_names = spycy_file.filter(filters)
                excluded_names = set(spycy_file).difference(included_names)
                # print(filters, included_names, excluded_names)
            else:
                excluded_names = set()
            for flavor in self.spyces.values():
                name = flavor.name
                if name not in spycy_file or name not in excluded_names:
                    LOG.info(f'file {spycy_file.filename}: setting spyce {name}')
                    spyce = flavor()
                    spycy_file[name] = spyce
            for discarded_name in set(spycy_file).difference(self.spyces):
                del spycy_file[discarded_name]

    def status(self, stream=sys.stdout, info_level=0):
        hdr = {
            0: colored('I', 'blue'),
            1: colored('W', 'yellow'),
            2: colored('E', 'red'),
        }
        def _print(text):
            print(text, file=stream)

        def _log(level, text):
            if level >= info_level:
                print(f'{hdr[level]} {text}', file=stream)

        def _bcg(text):
            return colored(text, 'green', attrs=['bold'])

        def _cg(text):
            return colored(text, "green")

        def _cy(text):
            return colored(text, "yellow")

        _print = functools.partial(print, file=stream)
        source_rel_path, source_path = self.source_rel_path, self.source_path
        target_rel_path, target_path = self.target_rel_path, self.target_path
        if not target_path.is_file():
            _print(f'target {target_rel_path}: missing file')
        if source_path == target_path:
            _print(f'{_cg("=")} {_bcg(target_rel_path)}')
        else:
            _print(f'{_cg("=")} {_bcg(target_rel_path)} [source: {_cy(source_rel_path)}]')
            if not source_path.is_file():
                _log(1, f'source {source_rel_path}: missing file')
            if target_path.is_file():
                if source_path.is_file():
                    target_stat = target_path.stat()
                    source_stat = source_path.stat()
                    if target_stat.st_ctime > source_stat.st_ctime:
                        _log(0, f'target is younger than source')
                    target_spycy_file = SpycyFile(target_path)
                    source_spycy_file = SpycyFile(source_path)
                    target_code_lines = target_spycy_file.code_lines()
                    source_code_lines = source_spycy_file.code_lines()
                    if source_code_lines != target_code_lines:
                        _log(1, f'target and source does not match; first diff is:')
                        for s_iline, t_iline in itertools.zip_longest(source_code_lines, target_code_lines, fillvalue=None):
                            if s_iline is None:
                                l_index, l_line = '-' , '(missing)'
                                r_index, r_line = t_iline
                            elif t_iline is None:
                                l_index, l_line = s_iline
                                r_index, r_line = '-' , '(missing)'
                            elif s_iline[1] != t_iline[1]:
                                l_index, l_line = s_iline
                                r_index, r_line = t_iline
                            else:
                                continue
                            l_line = l_line.rstrip('\n')
                            r_line = r_line.rstrip('\n')
                            _print(f'   @{l_index} : {r_index}')
                            _print(f'   -{l_line}')
                            _print(f'   +{r_line}')
                            break
                for flavor in self.spyces.values():
                    name = flavor.name
                    if name not in target_spycy_file:
                        _log(2, f'target {target_rel_path}: spyce {name} is missing')
                for name in target_spycy_file:
                    if name not in self.spyces:
                        _log(2, f'target {target_rel_path}: spyce {name} not expected')


class Wok(WokMixin, Mapping):
    def __init__(self, base_dir, filename, wok_files):
        super().__init__(base_dir, filename)
        self.wok_files = dict(wok_files)

    def __getitem__(self, file):
        return self.wok_files[file]

    def __iter__(self):
        yield from self.wok_files

    def __len__(self):
        return len(self.wok_files)

    def __repr__(self):
        return f'{type(self).__name__}({self.wok_files!r})'

    def fry(self, filters=None):
        for wok_file in self.wok_files.values():
            wok_file.fry(filters=filters)

    def status(self, stream=sys.stdout):
        for wok_file in self.wok_files.values():
            wok_file.status(stream)


def _build_err(filename, section, message):
    msg = f'wok file {filename}'
    if section:
        msg += f', section {section}'
    msg += f': {message}'
    return WokError(msg)


def parse_wok_file_spyce(base_dir, filename, file, name, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, f'wok.files.{file}.spyces.{name}', 'not a mapping')
    defaults = {
        'name': name,
        'section': None,
        'spyce_type': None,
    }
    def _add_key(key):
        if key not in data:
            raise _build_err(filename, f'wok.files.{file}.spyces.{name}', f'missing key {key}')
        defaults[key] = data[key]
    flavor = data.get('flavor', 'file')
    try:
        flavor_class = Flavor.flavor_class(flavor)
    except KeyError:
        raise _build_err(filename, f'wok.files.{file}.spyces.{name}', f'unknown flavor {flavor!r}')
    try:
        g_args = flavor_class.parse_data(base_dir, filename, data)
    except FlavorParseError as err:
        raise _build_err(filename, f'wok.files.{file}.spyces.{name}', str(err))
    defaults.update(g_args)
    return flavor_class(**defaults)


def parse_wok_file_spyces(base_dir, filename, file, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, f'wok.files.{file}.spyces', 'not a mapping')
    spyces = {}
    for name, entry in data.items():
        spyces[name] = parse_wok_file_spyce(base_dir, filename, file, name, entry)
    return spyces


def parse_wok_file(base_dir, filename, target_path, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, f'wok.files.{target_path}', 'not a mapping')
    source_path = data.get('source', target_path)
    spyces = parse_wok_file_spyces(base_dir, filename, target_path, data.get('spyces', []))
    return WokFile(base_dir, filename, target_path=target_path, source_path=source_path, spyces=spyces)


def parse_wok_files(base_dir, filename, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, 'wok.files', 'not a mapping')
    files = {}
    for file, file_data in data.items():
        file = Path(file)
        if not file.is_absolute():
            file = base_dir / file
        wok_file = parse_wok_file(base_dir, filename, file, file_data)
        files[wok_file.name] = wok_file
    return files

def parse_wok_section(base_dir, filename, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, 'wok', 'not a mapping')
    files = parse_wok_files(base_dir, filename, data.get('files', {}))
    return Wok(base_dir, filename, files)


def load_wok(path=None):
    if path is None:
        path = find_wok_path()
        if path is None:
            raise WokError(f'cannot find a wok configuration file {DEFAULT_WOK_FILENAME!r}')
    else:
        path = Path(path).absolute()
    if path.is_dir():
        path = path / DEFAULT_WOK_FILENAME
    if not path.exists():
        raise WokError(f'wok file {path} does not exist')
    if not path.is_file():
        raise WokError(f'{path} is not a wok file')
    base_dir = path.parent
    try:
        with open(path, 'r') as file:
            data = yaml.safe_load(file)
    except Exception as err:
        raise WokError(f'wok file {path}: YAML parse error: {type(err).__name__}: {err}')
    return parse_wok(base_dir, path, data)


def parse_wok(base_dir, filename, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, None, 'not a mapping')
    if 'wok' not in data:
        raise _build_err(filename, None, 'missing wok section')
    wok_section = data.get('wok')
    return parse_wok_section(base_dir, filename, wok_section)
