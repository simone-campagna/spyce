import datetime
import re
import shutil

from collections.abc import MutableMapping
from contextlib import contextmanager
from pathlib import Path

from .dose import default_spice_type, Dose
from .error import SpiceError
from .spice import Spice

__all__ = [
    'Dish',
]

class Timestamp(datetime.datetime):
    def __str__(self):
        return self.strftime('%Y%m%d-%H%M%S')


DEFAULT_BACKUP_FORMAT = '{path}.bck.{timestamp}'


class Dish(MutableMapping):
    __re_section__ = re.compile(r'\# spice:\s+section\s+(?P<section>source|data)\s*')
    __re_spice__ = re.compile(r'\# spice:\s+(?P<action>start|end)\s+(?P<section>source|data)/(?P<name>[^\s\/\:]+)(?:\:(?P<type>\S+))?')
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
        self.spices = {}
        self.section = {'source': None, 'data': None}
        self._parse_lines()
        self.content_version = 0

    def _build_spice(self, start, section, name, spice_type):
        filename = self.filename
        spice_type = default_spice_type(section, name, spice_type)
        spice_class = Spice.spice_class(spice_type, None)
        if spice_class is None:
            raise SpiceError(f"{filename}@{start + 1}: unknown spice type {spice_type!r}")
        return spice_class(self, section=section, name=name, start=start, end=None)

    def _parse_lines(self):
        filename = self.filename
        lines = self.lines
        re_spice = self.__re_spice__
        re_section = self.__re_section__
        spices = self.spices

        spice = None
        def _store_spice(line_index):
            nonlocal spices, spice
            if spice:
                spice.end = line_index + 1
                spices[spice.key] = spice
                spice = None

        for cur_index, line in enumerate(lines):
            m_section = re_section.match(line)
            if m_section:
                self.section[m_section['section']] = cur_index

            m_spice = re_spice.match(line)
            if m_spice:
                cur_section, cur_action, cur_name, cur_type = (
                    m_spice['section'], m_spice['action'], m_spice['name'], m_spice['type'])
                if cur_action == 'end':
                    if spice and cur_section == spice.section and cur_name == spice.name:
                        _store_spice(cur_index)
                        continue
                    else:
                        raise SpiceError(f'{filename}@{cur_index + 1}: unexpected directive "{cur_section} {cur_action} {cur_name}"')
                elif cur_action == 'start':
                    if spice:
                        # empty spice
                        _store_spice(spice.start)
                    spice = self._build_spice(cur_index, cur_section, cur_name, cur_type)
                    if spice.key in self.spices:
                        raise SpiceError(f"{filename}@{spice.start + 1}: duplicated spice {spice!r}")
                    continue
        if spice:
            _store_spice(spice.start)

    def _update_lines(self, l_start, l_diff):
        for spice in self.spices.values():
            if spice.start > l_start:
                spice.start += l_diff
                spice.end += l_diff
        for section in self.section:
            if self.section[section] is not None and self.section[section] > l_start:
                self.section[section] += l_diff

    def __delitem__(self, key):
        spice = self.spices.pop(key)
        del self.lines[spice.start:spice.end]
        self._update_lines(spice.start, -(spice.end - spice.start))
        self.content_version += 1

    def __setitem__(self, key, dose):
        if not isinstance(dose, Dose):
            raise TypeError(dose)
        section = dose.section
        name = dose.name
        spice_type = dose.spice_type
        content = dose.content()

        spice_class = Spice.spice_class(spice_type, None)
        if spice_class is None:
            raise SpiceError(f'unknown spice type {spice_type!r}')
        key = spice_class.spice_key(section, name)

        self.content_version += 1
        deleted_spice = self.get(key, None)
        if deleted_spice:
            # replace existing block
            del self[key]
            start = deleted_spice.start
        else:
            spc_ends = [spc.end for spc in self.spices.values() if spc.section == section]
            if spc_ends:
                # append to the existing section
                start = max(spc_ends) + 1
            else:
                # create the first spice in the section
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
        spice_lines = [f'# spice: start {key}:{spice_type}\n']
        spice_lines.extend(spice_class.encode(content))
        spice_lines.append(f'# spice: end {key}:{spice_type}\n')
        self.lines[start:start] = spice_lines
        l_diff = len(spice_lines)
        self._update_lines(start, l_diff)
        spice = spice_class(self, section=section, name=name, start=start, end=start + len(spice_lines))
        self.spices[key] = spice

    @contextmanager
    def refactor(self, output_path=None, backup=False, backup_format=DEFAULT_BACKUP_FORMAT):
        if self.path is None:
            raise SpiceError('{self}: path is not set')
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
        return len(self.spices)

    def __iter__(self):
        yield from self.spices

    def __getitem__(self, key):
        return self.spices[key]

    def __repr__(self):
        return f'{type(self).__name__}({self.file!r})'
