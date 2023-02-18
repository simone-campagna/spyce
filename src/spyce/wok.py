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
from .util import diff_files

__all__ = [
    'default_wok_filename',
    'find_wok_path',
    'WokError',
    'WokFile',
    'Wok',
    'load_wok',
    'import_wok',
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


def select_lines(classified_lines, selected_kinds):
    kinds = set(selected_kinds)
    result = []
    for kind, line in classified_lines:
        if kind in kinds:
            result.append(line)
    return result


class WokFile(WokMixin, Mapping):
    def __init__(self, base_dir, filename, target_path, source_path, flavors):
        super().__init__(base_dir, filename)
        self.target_path = self.abs_path(target_path)
        if source_path is None:
            source_path = self.target_path
        else:
            source_path = self.abs_path(source_path)
        self.source_path = source_path
        self.target_rel_path = self.rel_path(self.target_path)
        self.source_rel_path = self.rel_path(self.source_path)
        self.flavors = dict(flavors)

    @property
    def name(self):
        return str(self.target_rel_path)

    def __getitem__(self, name):
        return self.flavors[name]

    def __iter__(self):
        yield from self.flavors

    def __len__(self):
        return len(self.flavors)

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.source!r}, {self.flavors!r})'

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
            for flavor in self.flavors.values():
                name = flavor.name
                if name not in spycy_file or name not in excluded_names:
                    LOG.info(f'file {spycy_file.filename}: setting spyce {name}')
                    spyce = flavor()
                    spycy_file[name] = spyce
            for discarded_name in set(spycy_file).difference(self.flavors):
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
            return colored(text, 'green', styles=['bold'])

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
            _log(0, f'target and source are the same file')
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
                    target_code_lines = select_lines(target_spycy_file.classify_lines(), {'code'})
                    source_code_lines = select_lines(source_spycy_file.classify_lines(), {'code'})
                    if source_code_lines != target_code_lines:
                        _log(1, f'target and source code does not match')
                for flavor in self.flavors.values():
                    name = flavor.name
                    if name not in target_spycy_file:
                        _log(2, f'target {target_rel_path}: spyce {name} is missing')
                    else:
                        spyce = target_spycy_file[name]
                        if flavor.conf() != spyce.conf:
                            _log(2, f'target {target_rel_path}: spyce {name}: configuration changed')
                            _log(2, f'source: {flavor.conf()}')
                            _log(2, f'target: {spyce.conf}')
                for name in target_spycy_file:
                    if name not in self.flavors:
                        _log(2, f'target {target_rel_path}: spyce {name} not expected')

    def diff(self, stream=sys.stdout):
        _print = functools.partial(print, file=stream)
        source_rel_path, source_path = self.source_rel_path, self.source_path
        target_rel_path, target_path = self.target_rel_path, self.target_path
        if not target_path.is_file():
            _print(f'target {target_rel_path}: missing file')
            return
        source_spycy_file = SpycyFile(source_path)
        target_spycy_file = SpycyFile(target_path)
        place_holder = '//a1d4ce46-d476-48d3-8458-c79390e07527//'

        def _select_lines(classified_lines):
            result = []
            for kind, line in classified_lines:
                # if kind not in {'spyce-header', 'code'}:
                if kind not in {'code'}:
                    line = place_holder
                result.append(line)
            return result

        source_code_lines = _select_lines(source_spycy_file.classify_lines())
        target_code_lines = _select_lines(target_spycy_file.classify_lines())
        collapse_lines = lambda line: place_holder in line
        collapse_format = '... ({num} spyce lines)'
        diff_files(source_rel_path, target_rel_path, source_code_lines, target_code_lines,
                   collapse_lines=collapse_lines,
                   collapse_format=collapse_format,
                   stream=stream)

    @classmethod
    def import_spycy_file(cls, spycy_file):
        if not isinstance(spycy_file, SpycyFile):
            spycy_file = SpycyFile(spycy_file)
        filename = spycy_file.path
        base_dir = filename.parent
        target_path = spycy_file.path
        source_path = target_path
        flavors = {}
        for spyce in spycy_file.values():
            flavor_class = Flavor.flavor_class(spyce.flavor)
            parsed_conf = flavor_class.parse_conf(base_dir, filename, spyce.conf)
            flavor = flavor_class(name=spyce.name, **parsed_conf)
            flavors[flavor.name] = flavor
        return cls(
            base_dir=base_dir,
            filename=filename,
            target_path=target_path,
            source_path=source_path,
            flavors=flavors)


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

    def diff(self, stream=sys.stdout):
        for wok_file in self.wok_files.values():
            wok_file.diff(stream)

    def list_spyces(self, stream=sys.stdout, show_header=True, filters=None, show_lines=False, show_conf=False):
        def _print(text):
            print(text, file=stream)
        table = []
        data = {}
        for wok_file in self.wok_files.values():
            if not wok_file.target_path.is_file():
                continue
            spycy_file = SpycyFile(wok_file.target_path)
            names = spycy_file.filter(filters)
            for name in names:
                spyce_jar = spycy_file.get_spyce_jar(name)
                num_chars = len(spyce_jar.get_text())
                flavor = spyce_jar.flavor or ''
                table.append((spyce_jar.section, spyce_jar.name, spyce_jar.spyce_type, flavor,
                              f'{spyce_jar.start+1}:{spyce_jar.end+1}', str(num_chars),
                              str(wok_file.target_rel_path)))
                data[name] = (spycy_file, spyce_jar)
        if table:
            if show_header:
                names.insert(0, None)
                table.insert(0, ['section', 'name', 'type', 'flavor', 'lines', 'size', 'target'])
            mlen = [max(len(row[c]) for row in table) for c in range(len(table[0]))]
            if show_header:
                names.insert(1, None)
                table.insert(1, ['-' * ml for ml in mlen])

            fmt = ' '.join(f'{{:{ml}s}}' for ml in mlen)
            for name, row in zip(names, table):
                _print(fmt.format(*row))
                if name is not None:
                    if show_conf:
                        spyce_file = data[name][0]
                        spyce = spycy_file[name]
                        for line in yaml.dump(spyce.conf).split('\n'):
                            _print('  ' + line)
                    if show_lines:
                        spyce_jar = data[name][1]
                        for ln, line in enumerate(spyce.get_lines()):
                            line_no = ln + spyce_jar.start + 1
                            _print(f'  {line_no:<6d} {line.rstrip()}')

    @classmethod
    def import_spycy_file(cls, spycy_file):
        wok_file = WokFile.import_spycy_file(spycy_file)
        return cls(
            base_dir=wok_file.base_dir,
            filename=wok_file.filename,
            wok_files={wok_file.target_path: wok_file})


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
        g_args = flavor_class.parse_conf(base_dir, filename, data)
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
    flavors = parse_wok_file_spyces(base_dir, filename, target_path, data.get('spyces', []))
    return WokFile(base_dir, filename, target_path=target_path, source_path=source_path, flavors=flavors)


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


def import_wok(path):
    return Wok.import_spycy_file(path)


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
