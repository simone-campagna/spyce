import abc
import functools
import itertools
import json
import shutil
import sys

from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from pathlib import Path

import yaml

from .color import colored, Console, C
from .flavor import Flavor, FlavorParseError
from .log import LOG
from .spyce import SpyceError, SpycyFile, Spyce, SpyceJar, SpyceFilter
from .util import diff_files

__all__ = [
    'MutableSpycyFile',
    'Wok',
]


class Position(abc.ABC):
    @abc.abstractmethod
    def __call__(self, spyce_file):
        raise NotImplemented()


class Begin(Position):
    def __call__(self, spyce_file):
        for l_index, line in enumerate(spyce_file.lines):
            if not line.startswith('#!'):
                return l_index
        return 0


class End(Position):
    def __call__(self, spyce_file):
        return len(spyce_file.lines)


class _Relative(Position):
    def __init__(self, filters):
        self.filters = filters

    @classmethod
    def build(cls, value):
        return cls([SpyceFilter.build(value)])

    def filtered_spyce_jars(self, spyce_file):
        spyce_jars = [spyce_file[name] for name in spyce_file.filter(self.filters)]
        if not spyce_jars:
            raise SpyceError(f'filters {self.filters}: 0 spyces selected')
        return spyce_jars

class Before(_Relative):
    def __call__(self, spyce_file):
        spyce_jars = self.filtered_spyce_jars(spyce_file)
        return min(spyce_jar.start for spyce_jar in self.filtered_spyce_jars(spyce_file))


class After(_Relative):
    def __call__(self, spyce_file):
        spyce_jars = self.filtered_spyce_jars(spyce_file)
        return max(spyce_jar.end for spyce_jar in self.filtered_spyce_jars(spyce_file))


class AtLine(Position):
    def __init__(self, line_index):
        self.line_index = line_index

    def __call__(self, spyce_file):
        return self.line_index


class MutableSpycyFile(MutableMapping, SpycyFile):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content_version = 0

    def _update_lines(self, l_start, l_diff):
        for spyce_jar in self.spyce_jars.values():
            if spyce_jar.start >= l_start:
                spyce_jar.start += l_diff
                spyce_jar.end += l_diff

    def __delitem__(self, name):
        self.del_spyce(name, content_only=False)

    def del_spyce(self, name, content_only=False):
        if content_only:
            spyce_jar = self.spyce_jars[name]
            start, end = spyce_jar.index_range(headers=False)
        else:
            spyce_jar = self.spyce_jars.pop(name)
            start, end = spyce_jar.index_range(headers=True)
        del self.lines[start:end]
        self._update_lines(spyce_jar.start, -(end - start))
        self.content_version += 1

    def __setitem__(self, name, spyce):
        self.set_spyce(name, spyce)

    def set_spyce(self, name, spyce, empty=False, position=None):
        if isinstance(spyce, Flavor):
            spyce = flavor()
        if not isinstance(spyce, Spyce):
            raise TypeError(spyce)

        name = spyce.name
        spyce_type = spyce.spyce_type
        if empty:
            content_lines = None
        else:
            content_lines = spyce.encode(spyce.get_content())

        self.content_version += 1
        deleted_spyce_jar = self.spyce_jars.get(name, None)
        if deleted_spyce_jar:
            # replace existing block
            del self[name]
            start = deleted_spyce_jar.start
            if position is None:
                position = AtLine(start)
        else:
            if position is None:
                if spyce_type == 'text':
                    position = Begin()
                else:
                    position = End()
        start = position(self)
        spyce_lines = [f'# spyce: start {name}\n']
        for key, value in spyce.conf.items():
            serialized_value = json.dumps(value)
            spyce_lines.append(f'# spyce: - {key}={serialized_value}\n')
        if content_lines is not None:
            spyce_lines.extend(content_lines)
        spyce_lines.append(f'# spyce: end {spyce.name}\n')
        self.lines[start:start] = spyce_lines
        l_diff = len(spyce_lines)
        self._update_lines(start, l_diff)
        spyce_jar = SpyceJar(self, name=name, start=start, end=start + len(spyce_lines), conf=spyce.conf)
        self.spyce_jars[spyce_jar.name] = spyce_jar

    @contextmanager
    def refactor(self, output_path=None):
        if self.path is None:
            raise SpyceError('{self}: path is not set')
        content_version = self.content_version
        yield
        if output_path is None:
            output_path = self.path
        else:
            output_path = Path(output_path)
        in_place = False
        if output_path.is_file() and output_path.resolve() == self.path.resolve():
            in_place = True
        write = True
        if content_version == self.content_version and in_place:
            write = False
        if write:
            st_mode = self.path.stat().st_mode
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as fh:
                fh.writelines(self.lines)
            output_path.chmod(st_mode)


class Wok(MutableSpycyFile):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.path is None:
            self.base_dir = Path.cwd()
        else:
            self.base_dir = self.path.parent
        self.flavors = {}
        for spyce_name, spyce_jar in self.items():
            flavor_class = Flavor.flavor_class(spyce_jar.flavor)
            flavor_class.fix_conf(spyce_jar.conf)
            parsed_conf = flavor_class.parse_conf(self.base_dir, self.path, spyce_jar.conf)
            flavor = flavor_class(name=spyce_jar.name, **parsed_conf)
            self.flavors[flavor.name] = flavor

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

    def __paths(self, output_file=None):
        source_path = self.path
        source_rel_path = self.rel_path(source_path)
        if output_file is None:
            target_rel_path, target_path = source_rel_path, source_path
        else:
            target_path = Path(output_file).absolute()
            target_rel_path = self.rel_path(target_path)
        return source_rel_path, source_path, target_rel_path, target_path

    def set_flavor(self, flavor, output_file=None, replace=False, position=None, empty=False):
        source_rel_path, source_path, target_rel_path, target_path = self.__paths(output_file)

        LOG.info(f'{source_rel_path} -> {target_rel_path}')
        if flavor.name in self and not replace:
            raise SpyceError(f'cannot overwrite spyce {flavor.name}')
        with self.refactor(target_path):
            self.set_spyce(flavor.name, flavor(), position=position, empty=empty)

    def del_spyces(self, output_file=None, filters=None, content_only=False):
        source_rel_path, source_path, target_rel_path, target_path = self.__paths(output_file)

        LOG.info(f'{source_rel_path} -> {target_rel_path}')
        with self.refactor(target_path):
            names = self.filter(filters)
            for name in names:
                self.del_spyce(name, content_only=content_only)

    def update(self, output_file=None, filters=None, stream=sys.stdout, info_level=0):
        console = Console(stream=stream, info_level=info_level)
        source_rel_path, source_path, target_rel_path, target_path = self.__paths(output_file)

        LOG.info(f'{source_rel_path} -> {target_rel_path}')
        with self.refactor(target_path):
            if filters:
                included_names = self.filter(filters)
                excluded_names = set(self).difference(included_names)
                # print(filters, included_names, excluded_names)
            else:
                excluded_names = set()
            for flavor in self.flavors.values():
                name = flavor.name
                if name not in self or name not in excluded_names:
                    console.print(C.xxb(name), end=' ')
                    try:
                        e_spyce = flavor()
                        if name in self:
                            f_spyce = self[name].spyce
                            if f_spyce.get_lines() == e_spyce.get_lines():
                                console.print(C.cxx('skipped'))
                                continue
                        self.set_spyce(name, e_spyce, empty=False)
                        console.print(C.gxx('added'))
                    except:
                        console.print(C.rxx('add failed!'))
                        raise
            for discarded_name in set(self).difference(self.flavors):
                console.print(C.xxb(name), end=' ')
                try:
                    del self[discarded_name]
                    console.print(C.gxx('removed'))
                except:
                    console.print(C.rxx('remove failed!'))
                    raise

    def status(self, stream=sys.stdout, info_level=0, filters=None):
        console = Console(stream=stream, info_level=info_level)
        if not self.path.is_file():
            console.error(f'file {self.path} is missing')
            return
        names = self.filter(filters)
        for name in names:
            flavor = self.flavors[name]
            spyce_jar = self[name]
            try:
                spyce = spyce_jar.spyce
            except Exception as err:
                console.error(f'{name} cannot be loaded: {type(err).__name__}: {err}')
            found_lines = spyce.get_lines()
            flavor_spyce = flavor()
            expected_lines = flavor_spyce.get_lines()
            if found_lines != expected_lines:
                console.error(f'{C.xxb(name)} {C.rxx("out-of-date")}')
            else:
                console.info(f'{C.xxb(name)} {C.gxx("up-to-date")}')

    def diff(self, stream=sys.stdout, info_level=0, filters=None, binary=False):
        console = Console(stream=stream, info_level=info_level)
        if not self.path.is_file():
            console.error(f'file {rel_path} is missing')
            return
        names = self.filter(filters)
        for name in names:
            flavor = self.flavors[name]
            spyce_jar = self[name]
            start, end = spyce_jar.index_range(headers=False)
            try:
                spyce = spyce_jar.spyce
            except Exception as err:
                console.error(f'{C.xxb(name)} cannot be loaded: {type(err).__name__}: {err}')
            f_lines = spyce.get_lines()
            flavor_spyce = flavor()
            e_lines = flavor_spyce.get_lines()
            if f_lines != e_lines:
                console.error(f'{C.xxb(name)} {colored("out-of-date", "red")}')
                if (not binary) and spyce_jar.spyce_type == 'bytes':
                    console.error(C.xxi('(binary diff)'), continuation=True)
                else:
                    all_f_lines = ['\n' for line in self.lines]
                    all_e_lines = all_f_lines[:]
                    all_f_lines[start:] = f_lines
                    all_e_lines[start:] = e_lines
                    diff_files(f'found', f'expected', all_f_lines, all_e_lines,
                               stream=stream,
                               num_context_lines=3,
                    )
            else:
                console.info(f'{C.xxb(name)} {colored("up-to-date", "green")}')

    def show_spyce_conf(self, stream=sys.stdout, filters=None):
        console = Console(stream=stream)
        names = self.filter(filters)
        for name in names:
            console.print(f'{C.xxb(name)}')
            spyce = self[name].spyce
            for var_name, var_value in spyce.conf.items():
                console.print(C.xxi(f'    {var_name}={json.dumps(var_value)}'))

    def show_spyce_lines(self, stream=sys.stdout, filters=None):
        console = Console(stream=stream)
        names = self.filter(filters)
        for name in names:
            console.print(f'{C.xxb(name)} x')
            spyce_jar = self[name]
            spyce = spyce_jar.spyce
            offset = spyce_jar.start
            for index, line in enumerate(spyce.get_lines()):
                console.print(f'    {index + offset:6d}| {C.xxi(line)}', end='')

    def list_spyces(self, stream=sys.stdout, show_header=True, filters=None):
        console = Console(stream=stream)
        table = []
        names = self.filter(filters)
        for name in names:
            spyce_jar = self[name]
            flavor = spyce_jar.flavor or ''
            num_chars = len(spyce_jar.get_text())
            table.append([spyce_jar.name, spyce_jar.spyce_type, flavor,
                          f'{spyce_jar.start+1}:{spyce_jar.end+1}', str(num_chars)])
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
