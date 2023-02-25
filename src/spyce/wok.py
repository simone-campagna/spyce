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
    'WokError',
    'Wok',
]


class WokError(SpyceError):
    pass


def select_lines(classified_lines, selected_kinds):
    kinds = set(selected_kinds)
    result = []
    for kind, line in classified_lines:
        if kind in kinds:
            result.append(line)
    return result


def _cr(text):
    return colored(text, 'red')


def _cg(text):
    return colored(text, 'green')


def _cy(text):
    return colored(text, 'yellow')


def _h(text):
    #return colored(text, styles=['underline']) + ':'
    return colored(text, styles=['bold']) + ':'


class Console:
    INFO = 0
    WARNING = 1
    ERROR = 2
    def __init__(self, stream=sys.stdout, info_level=0):
        self.stream = stream
        self.info_level = info_level
        fmt = '{:7s}'
        self._hdr = {
            self.INFO: colored(fmt.format('info'), 'green'),
            self.WARNING: colored(fmt.format('warning'), 'yellow'),
            self.ERROR: colored(fmt.format('error'), 'red'),
        }

    def print(self, text):
        print(text, file=self.stream)

    def info(self, text):
        self.log(self.INFO, text)

    def warning(self, text):
        self.log(self.WARNING, text)

    def error(self, text):
        self.log(self.ERROR, text)

    def log(self, level, text):
        if level >= self.info_level:
            print(f'{self._hdr[level]} {text}', file=self.stream)


class Wok(Mapping):
    def __init__(self, path, flavors):
        path = Path(path).absolute()
        base_dir = path.parent
        self.base_dir = base_dir
        self.path = path
        self.flavors = dict(flavors)

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

    @property
    def name(self):
        return str(self.rel_path(self.path))

    def __getitem__(self, name):
        return self.flavors[name]

    def __iter__(self):
        yield from self.flavors

    def __len__(self):
        return len(self.flavors)

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.source!r}, {self.flavors!r})'

    def mix(self, target_path=None, filters=None):
        source_path = self.path
        source_rel_path = self.rel_path(source_path)
        if target_path is None:
            target_rel_path, target_path = source_rel_path, source_path
        else:
            target_path = Path(target_path).absolute()
            target_rel_path = self.rel_path(target_path)

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

    def status(self, stream=sys.stdout, info_level=0, filters=None):
        console = Console(stream=stream, info_level=info_level)
        if not self.path.is_file():
            console.error(f'file {self.path} is missing')
            return
        spycy_file = SpycyFile(self.path)
        names = spycy_file.filter(filters)
        for name in names:
            flavor = self[name]
            spyce_jar = spycy_file[name]
            self._fix_jar(spyce_jar)
            try:
                spyce = spyce_jar.spyce
            except Exception as err:
                console.error(f'{name} cannot be loaded: {type(err).__name__}: {err}')
            found_lines = spyce.get_lines()
            flavor_spyce = flavor()
            expected_lines = flavor_spyce.get_lines()
            if found_lines != expected_lines:
                console.error(f'{_h(name)} {_cr("out-of-date")}')
            else:
                console.info(f'{_h(name)} {_cg("up-to-date")}')

    def diff(self, stream=sys.stdout, info_level=0, filters=None):
        console = Console(stream=stream, info_level=info_level)
        if not self.path.is_file():
            console.error(f'file {rel_path} is missing')
            return
        spycy_file = SpycyFile(self.path)
        names = spycy_file.filter(filters)
        for name in names:
            flavor = self[name]
            spyce_jar = spycy_file[name]
            start, end = spyce_jar.index_range(headers=False)
            self._fix_jar(spyce_jar)
            try:
                spyce = spyce_jar.spyce
            except Exception as err:
                console.error(f'{_h(name)} cannot be loaded: {type(err).__name__}: {err}')
            f_lines = spyce.get_lines()
            flavor_spyce = flavor()
            e_lines = flavor_spyce.get_lines()
            if f_lines != e_lines:
                console.error(f'{_h(name)} {colored("out-of-date", "red")}')
                all_f_lines = ['\n' for line in spycy_file.lines]
                all_e_lines = all_f_lines[:]
                all_f_lines[start:] = f_lines
                all_e_lines[start:] = e_lines
                diff_files(f'found', f'expected', all_f_lines, all_e_lines,
                           stream=stream,
                           num_context_lines=3,
                )
            else:
                console.info(f'{_h(name)} {colored("up-to-date", "green")}')

    def _fix_jar(self, spyce_jar):
        flavor = spyce_jar.flavor or ''
        if flavor:
            flavor_class = Flavor.flavor_class(spyce_jar.flavor)
            flavor_class.fix_conf(spyce_jar.conf)
        
    def list_spyces(self, stream=sys.stdout, show_header=True, filters=None, show_lines=False, show_conf=False):
        console = Console(stream=stream)
        table = []
        data = {}
        spycy_file = SpycyFile(self.path)
        names = spycy_file.filter(filters)
        for name in names:
            spyce_jar = spycy_file[name]
            flavor = spyce_jar.flavor or ''
            self._fix_jar(spyce_jar)
            num_chars = len(spyce_jar.get_text())
            table.append([spyce_jar.name, spyce_jar.spyce_type, flavor,
                          f'{spyce_jar.start+1}:{spyce_jar.end+1}', str(num_chars)])
            data[name] = (spycy_file, spyce_jar)
        if table:
            if show_header:
                names.insert(0, None)
                table.insert(0, ['name', 'type', 'flavor', 'lines', 'size'])
            mlen = [max(len(row[c]) for row in table) for c in range(len(table[0]))]
            if show_header:
                names.insert(1, None)
                table.insert(1, ['-' * ml for ml in mlen])

            fmt = ' '.join(f'{{:{ml}s}}' for ml in mlen)
            for name, row in zip(names, table):
                console.print(fmt.format(*row))
                if name is not None:
                    if show_conf:
                        spyce_file = data[name][0]
                        spyce = spycy_file[name]
                        for line in yaml.dump(spyce.conf).split('\n'):
                            console.print('  ' + line)
                    if show_lines:
                        spyce_jar = data[name][1]
                        for ln, line in enumerate(spyce.get_lines()):
                            line_no = ln + spyce_jar.start + 1
                            console.print(f'  {line_no:<6d} {line.rstrip()}')

    @classmethod
    def import_spycy_file(cls, spycy_file):
        if not isinstance(spycy_file, SpycyFile):
            spycy_file = SpycyFile(spycy_file)
        path = spycy_file.path.absolute()
        base_dir = path.parent
        flavors = {}
        for spyce_name in spycy_file:
            spyce_jar = spycy_file[spyce_name]
            flavor_class = Flavor.flavor_class(spyce_jar.flavor)
            parsed_conf = flavor_class.parse_conf(base_dir, path, spyce_jar.conf)
            flavor = flavor_class(name=spyce_jar.name, **parsed_conf)
            flavors[flavor.name] = flavor
        return cls(
            path=path,
            flavors=flavors)
