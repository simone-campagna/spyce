import datetime
import re
import shutil

from collections.abc import MutableMapping
from contextlib import contextmanager
from pathlib import Path

from .error import SpyceError
from .spyce import (
    default_spyce_type, Spyce, SpyceFarm,
)

__all__ = [
    'Dish',
]

class Timestamp(datetime.datetime):
    def __str__(self):
        return self.strftime('%Y%m%d-%H%M%S')


DEFAULT_BACKUP_FORMAT = '{path}.bck.{timestamp}'


class Dish(MutableMapping):
    __re_section__ = re.compile(r'\# spyce:\s+section\s+(?P<section>source|data)\s*')
    __re_spyce__ = re.compile(r'\# spyce:\s+(?P<action>start|end)\s+(?P<section>source|data)/(?P<name>[^\s\/\:]+)(?:\:(?P<type>\S+))?')
    __sections__ = {'source', 'data'}

    def __init__(self, file=__file__, lines=None):
        if lines is None:
            if isinstance(file, (str, Path)):
                path = Path(file)
                with open(file, 'r') as fh:
                    lines = fh.readlines()
            else:
                path = getattr(file, 'name', None)
                lines = file.readlines()
        self.path = path
        self.filename = str(self.path) if self.path is not None else '<stdin>'
        self.lines = lines
        self.spyces = {}
        self.section = {'source': None, 'data': None}
        self._parse_lines()
        self.content_version = 0

    def _build_spyce(self, start, section, name, spyce_type):
        filename = self.filename
        if spyce_type is None:
            spyce_type = default_spyce_type(section, name)
        spyce_class = Spyce.spyce_class(spyce_type, None)
        if spyce_class is None:
            raise SpyceError(f"{filename}@{start + 1}: unknown spyce type {spyce_type!r}")
        return spyce_class(self, section=section, name=name, start=start, end=None)

    def _parse_lines(self):
        filename = self.filename
        lines = self.lines
        re_spyce = self.__re_spyce__
        re_section = self.__re_section__
        spyces = self.spyces

        spyce = None
        def _store_spyce(line_index):
            nonlocal spyces, spyce
            if spyce:
                spyce.end = line_index + 1
                spyces[spyce.key] = spyce
                spyce = None

        for cur_index, line in enumerate(lines):
            m_section = re_section.match(line)
            if m_section:
                self.section[m_section['section']] = cur_index

            m_spyce = re_spyce.match(line)
            if m_spyce:
                cur_section, cur_action, cur_name, cur_type = (
                    m_spyce['section'], m_spyce['action'], m_spyce['name'], m_spyce['type'])
                if cur_action == 'end':
                    if spyce and cur_section == spyce.section and cur_name == spyce.name:
                        _store_spyce(cur_index)
                        continue
                    else:
                        raise SpyceError(f'{filename}@{cur_index + 1}: unexpected directive "{cur_section} {cur_action} {cur_name}"')
                elif cur_action == 'start':
                    if spyce:
                        # empty spyce
                        _store_spyce(spyce.start)
                    spyce = self._build_spyce(cur_index, cur_section, cur_name, cur_type)
                    if spyce.key in self.spyces:
                        raise SpyceError(f"{filename}@{spyce.start + 1}: duplicated spyce {spyce!r}")
                    continue
        if spyce:
            _store_spyce(spyce.start)

    def _update_lines(self, l_start, l_diff):
        for spyce in self.spyces.values():
            if spyce.start > l_start:
                spyce.start += l_diff
                spyce.end += l_diff
        for section in self.section:
            if self.section[section] is not None and self.section[section] > l_start:
                self.section[section] += l_diff

    def __delitem__(self, key):
        spyce = self.spyces.pop(key)
        del self.lines[spyce.start:spyce.end]
        self._update_lines(spyce.start, -(spyce.end - spyce.start))
        self.content_version += 1

    def __setitem__(self, key, spyce_farm):
        if not isinstance(spyce_farm, SpyceFarm):
            raise TypeError(spyce_farm)
        section = spyce_farm.section
        name = spyce_farm.name
        spyce_type = spyce_farm.spyce_type
        content = spyce_farm.content()
        spyce_class = spyce_farm.spyce_class()

        if spyce_class is None:
            raise SpyceError(f'unknown spyce type {spyce_type!r}')
        key = spyce_class.spyce_key(section, name)

        self.content_version += 1
        deleted_spyce = self.get(key, None)
        if deleted_spyce:
            # replace existing block
            del self[key]
            start = deleted_spyce.start
        else:
            spc_ends = [spc.end for spc in self.spyces.values() if spc.section == section]
            if spc_ends:
                # append to the existing section
                start = max(spc_ends)
            else:
                # create the first spyce in the section
                if self.section[section]:
                    # use custom-specified section start
                    start =  self.section[section] + 1
                else:
                    # use default section start
                    if section == 'source':
                        for l_index, line in enumerate(self.lines):
                            if not line.startswith('#!'):
                                break
                        start = l_index
                    else:
                        start = len(self.lines)
        spyce_lines = [f'# spyce: start {key}:{spyce_type}\n']
        spyce_lines.extend(spyce_class.encode(content))
        spyce_lines.append(f'# spyce: end {key}:{spyce_type}\n')
        self.lines[start:start] = spyce_lines
        l_diff = len(spyce_lines)
        self._update_lines(start, l_diff)
        spyce = spyce_class(self, section=section, name=name, start=start, end=start + len(spyce_lines))
        self.spyces[key] = spyce

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

    def __len__(self):
        return len(self.spyces)

    def __iter__(self):
        yield from self.spyces

    def __getitem__(self, key):
        return self.spyces[key]

    def __repr__(self):
        return f'{type(self).__name__}({self.file!r})'
