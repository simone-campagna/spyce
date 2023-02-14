from collections.abc import Mapping
from pathlib import Path

import yaml

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


class WokFile(Mapping):
    def __init__(self, path, source, spyces):
        self.path = Path(path)
        if source is None:
            source = self.path
        self.source = Path(source)
        self.spyces = dict(spyces)

    @property
    def name(self):
        return str(self.path)

    def __getitem__(self, name):
        return self.spyces[name]

    def __iter__(self):
        yield from self.spyces

    def __len__(self):
        return len(self.spyces)

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.source!r}, {self.spyces!r})'

    def _use_source(self):
        source = self.source
        if not source.is_file():
            raise WokError('file {source}: source file missing')
        source_stat = source.stat()
        target = self.path
        if target.is_file():
            if source_stat.st_ctime > target.stat().st_ctime:
                return source
            else:
                return target
        else:
            return source

    def __call__(self):
        source_file = self._use_source()
        target_file = self.path
        spycy_file = SpycyFile(source_file)
        LOG.info(f'{source_file} -> {target_file}')
        with spycy_file.refactor(target_file):
            for flavor in self.spyces.values():
                spyce = flavor()
                spycy_file[spyce.key] = spyce


class Wok(Mapping):
    def __init__(self, wok_files):
        self.wok_files = dict(wok_files)

    def __getitem__(self, file):
        return self.wok_files[file]

    def __iter__(self):
        yield from self.wok_files

    def __len__(self):
        return len(self.wok_files)

    def __repr__(self):
        return f'{type(self).__name__}({self.wok_files!r})'

    def __call__(self):
        for wok_file in self.wok_files.values():
            wok_file()


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
    category = data.get('category', 'file')
    try:
        flavor_class = Flavor.flavor_class(category)
    except KeyError:
        raise _build_err(filename, f'wok.files.{file}.spyces.{name}', f'unknown category {category!r}')
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


def parse_wok_file(base_dir, filename, file, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, f'wok.files.{file}', 'not a mapping')
    source = data.get('source', file)
    if source:
        source = Path(source)
        if not source.is_absolute():
            source = base_dir / source
    spyces = parse_wok_file_spyces(base_dir, filename, file, data.get('spyces', []))
    return WokFile(file, source=source, spyces=spyces)


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
    return Wok(files)


def load_wok(path):
    path = Path(path).absolute()
    base_dir = path.parent
    with open(path, 'r') as file:
        data = yaml.safe_load(file)
    return parse_wok(base_dir, path, data)


def parse_wok(base_dir, filename, data):
    if not isinstance(data, Mapping):
        raise _build_err(filename, None, 'not a mapping')
    if 'wok' not in data:
        raise _build_err(filename, None, 'missing wok section')
    wok_section = data.get('wok')
    return parse_wok_section(base_dir, filename, wok_section)
