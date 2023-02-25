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
from .spyce import SpyceError, SpycyFile, Spyce, SpyceJar
from .util import diff_files

__all__ = [
    'MutableSpycyFile',
    'Wok',
]


DEFAULT_BACKUP_FORMAT = '{path}.bck.{timestamp}'


class MutableSpycyFile(MutableMapping, SpycyFile):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content_version = 0

    def _update_lines(self, l_start, l_diff):
        for spyce_jar in self.spyce_jars.values():
            if spyce_jar.start >= l_start:
                spyce_jar.start += l_diff
                spyce_jar.end += l_diff
        for section in self.section:
            if self.section[section] is not None and self.section[section] > l_start:
                self.section[section] += l_diff

    def __delitem__(self, name):
        spyce_jar = self.spyce_jars.pop(name)
        del self.lines[spyce_jar.start:spyce_jar.end]
        self._update_lines(spyce_jar.start, -(spyce_jar.end - spyce_jar.start))
        self.content_version += 1

    def __setitem__(self, name, spyce):
        self.add_spyce(name, spyce)

    def add_spyce(self, name, spyce, section=None):
        if not isinstance(spyce, Spyce):
            raise TypeError(spyce)
        if section is None:
            section = 'data' if spyce.spyce_type == 'bytes' else 'source'

        section_index = dict(self.section)
        explicit_section = True
        if section_index['source'] is None:
            explicit_section = False
            for l_index, line in enumerate(self.lines):
                if not line.startswith('#!'):
                    section_index['source'] = l_index
                    break

        if section_index['data'] is None:
            explicit_section = False
            section_index['data'] = len(self.lines)

        sections = sorted(section_index.items(), key=lambda x: x[1])
        cats = {}
        for spyce_name, spyce_jar in self.items():
            cat = None
            for kind, index in sections:
                if spyce_jar.start > index:
                    cat = kind
            cats.setdefault(cat, []).append(spyce_jar)

        name = spyce.name
        content = spyce.get_content()

        self.content_version += 1
        deleted_spyce_jar = self.spyce_jars.get(name, None)
        if deleted_spyce_jar:
            # replace existing block
            del self[name]
            start = deleted_spyce_jar.start
        else:
            if explicit_section and cats.get(section, None):
                start = max(spc.end for spc in cats[section])
            else:
                start = section_index[section]
        spyce_lines = [f'# spyce: start {spyce.name}\n']
        for key, value in spyce.conf.items():
            if key not in {'section', 'spyce_type'}:
                serialized_value = json.dumps(value)
                spyce_lines.append(f'# spyce: - {key}={serialized_value}\n')
        spyce_lines.extend(spyce.encode(content))
        spyce_lines.append(f'# spyce: end {spyce.name}\n')
        self.lines[start:start] = spyce_lines
        l_diff = len(spyce_lines)
        self._update_lines(start, l_diff)
        spyce_jar = SpyceJar(self, name=name, start=start, end=start + len(spyce_lines), conf=spyce.conf)
        self.spyce_jars[spyce_jar.name] = spyce_jar

    @contextmanager
    def refactor(self, output_path=None, backup=False, backup_format=DEFAULT_BACKUP_FORMAT):
        if self.path is None:
            raise SpyceError('{self}: path is not set')
        content_version = self.content_version
        yield
        if output_path is None:
            if content_version != self.content_version:
                output_path = self.path
            else:
                output_path = None
        else:
            output_path = Path(output_path)
        if output_path is self.path or not self.path.is_file():
            backup = False
            if backup and self.path.is_file():
                if backup_format is None:
                    backup_format = DEFAULT_BACKUP_FORMAT
                backup_path = Path(str(backup_format).format(
                    path=self.path,
                    timestamp=Timestamp.now(),
                ))
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(self.path, backup_path)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as fh:
                fh.writelines(self.lines)
            if self.path.is_file():
                shutil.copymode(self.path, output_path)


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

    def add_flavor(self, flavor, output_file=None, replace=False):
        source_rel_path, source_path, target_rel_path, target_path = self.__paths(output_file)

        LOG.info(f'{source_rel_path} -> {target_rel_path}')
        if flavor.name in self and not replace:
            raise SpyceError(f'cannot overwrite spyce {flavor.name}')
        with self.refactor(target_path):
            self.add_spyce(flavor.name, flavor(), section=flavor.section)

    def mix(self, output_file=None, filters=None):
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
                    LOG.info(f'file {self.filename}: setting spyce {name}')
                    spyce = flavor()
                    self[name] = spyce
            for discarded_name in set(self).difference(self.flavors):
                del self[discarded_name]

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

    def list_spyces(self, stream=sys.stdout, show_header=True, filters=None, show_lines=False, show_conf=False):
        console = Console(stream=stream)
        table = []
        data = {}
        names = self.filter(filters)
        for name in names:
            spyce_jar = self[name]
            flavor = spyce_jar.flavor or ''
            num_chars = len(spyce_jar.get_text())
            table.append([spyce_jar.name, spyce_jar.spyce_type, flavor,
                          f'{spyce_jar.start+1}:{spyce_jar.end+1}', str(num_chars)])
            data[name] = spyce_jar
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
                        spyce = self[name]
                        for line in yaml.dump(spyce.conf).split('\n'):
                            console.print('  ' + line)
                    if show_lines:
                        spyce_jar = data[name]
                        for ln, line in enumerate(spyce.get_lines()):
                            line_no = ln + spyce_jar.start + 1
                            console.print(f'  {line_no:<6d} {line.rstrip()}')
