# spyce: start source/spyce:text
import abc as _spyce_abc
import datetime as _spyce_datetime
from collections.abc import MutableMapping as _spyce_MutableMapping
from contextlib import contextmanager as _spyce_contextmanager
from pathlib import Path as _spyce_Path


__all__ = [
    'Spyce',
    'TextSpyce',
    'BytesSpyce',
    'SpiceFarm',
    'Dish',
]

SPYCE_API_VERSION = '0.1.0'

DEFAULT_BACKUP_FORMAT = '{path}.bck.{timestamp}'
class Timestamp(_spyce_datetime.datetime):
    def __str__(self):
        return self.strftime('%Y%m%d-%H%M%S')


def default_spyce_type(section, name):
    return 'text' if section == 'source' else 'bytes'


class SpyceError(RuntimeError):
    pass


class SpyceMeta(_spyce_abc.ABCMeta):
    def __new__(mcls, class_name, class_bases, class_dict):
        cls = super().__new__(mcls, class_name, class_bases, class_dict)
        import inspect
        if not inspect.isabstract(cls):
            cls.__registry__[cls.class_spyce_type()] = cls
        return cls


UNDEF = object()

class Spyce(metaclass=SpyceMeta):
    __registry__ = {}

    def __init__(self, dish, section, name, start, end):
        self.dish = dish
        self.section = section
        self.name = name
        self.key = self.spyce_key(section, name)
        self.start = start
        self.end = end

    @classmethod
    def spyce_class(cls, spyce_type, /, default=UNDEF):
        if default is UNDEF:
            return cls.__registry__[spyce_type]
        else:
            return cls.__registry__.get(spyce_type, default)

    @staticmethod
    def spyce_key(section, name):
        return f'{section}/{name}'

    def fq_key(self):
        return f'{self.section}/{self.name}:{self.spyce_type}'

    @property
    def spyce_type(self):
        return self.class_spyce_type()

    @classmethod
    @_spyce_abc.abstractmethod
    def class_spyce_type(cls):
        raise NotImplementedError()

    @classmethod
    @_spyce_abc.abstractmethod
    def encode(cls, content):
        raise NotImplementedError()

    @classmethod
    @_spyce_abc.abstractmethod
    def decode(cls, lines):
        raise NotImplementedError()

    def get_lines(self, headers=False):
        if headers:
            s_offset, e_offset = 0, 0
        else:
            s_offset, e_offset = 1, 1
        return self.dish.lines[self.start+s_offset:self.end-e_offset]

    def get_text(self, headers=False):
        return ''.join(self.get_lines(headers=headers))

    def get_content(self):
        return self.decode(self.get_lines())

    def _file_mode(self):
        return 'w'

    def _build_path(self, path):
        path = _spyce_Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_file(self, path):
        path = self._build_path(path)
        content = self.get_content()
        with open(path, self._file_mode()) as file:
            file.write(content)

    def __str__(self):
        return self.key

    def __repr__(self):
        return f'{type(self).__name__}({self.dish!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r})'


class TextSpyce(Spyce):
    @classmethod
    def encode(cls, content):
        return [line + '\n' for line in content.split('\n')]

    @classmethod
    def decode(cls, lines):
        return ''.join(lines)

    @classmethod
    def class_spyce_type(cls):
        return 'text'


class BytesSpyce(Spyce):
    __data_line_length__ = 120
    __data_prefix__ = '#|'

    @classmethod
    def encode(cls, content):
        import base64
        lines = []
        data = str(base64.b64encode(content), 'utf-8')
        dlen = cls.__data_line_length__
        for index in range(0, len(data), dlen):
            lines.append(f'#|{data[index:index+dlen]}\n')
        data_prefix = cls.__data_prefix__
        return lines

    @classmethod
    def decode(cls, lines):
        import base64
        data_prefix = cls.__data_prefix__
        data = ''.join(line[len(data_prefix):].strip() for line in lines if line.startswith(data_prefix))
        return base64.b64decode(data)

    @classmethod
    def class_spyce_type(cls):
        return 'bytes'

    def _file_mode(self):
        return 'wb'

    def untar(self, path, mode='r|*'):
        import io, tarfile
        path = self._build_path(path)
        b_file = io.BytesIO(self.get_content())
        with tarfile.open(fileobj=b_file, mode=mode) as t_file:
            t_file.extractall(path)


class SpyceFarm(_spyce_abc.ABC):
    def __init__(self, section=None, name=None, spyce_type=None):
        self.section = section
        self.name = name
        self.spyce_type = spyce_type

        self._check_section()
        self._check_name()
        self._check_spyce_type()

    def spyce_class(self):
        return Spyce.spyce_class(self.spyce_type)

    def _default_section(self):
        return 'data'

    def _default_name(self):
        return None

    def _default_spyce_type(self):
        return None

    def _check_section(self):
        if self.section is None:
            self.section = self._default_section()

    def _check_name(self):
        if self.name is None:
            self.name = self._default_name()
        if self.name is None:
            raise RuntimeError(f'{type(self).__name__}: spyce name not set')

    def _check_spyce_type(self):
        if self.spyce_type is None:
            self.spyce_type = self._default_spyce_type()
        if self.spyce_type is None:
            self.spyce_type = default_spyce_type(self.section, self.name)
        if self.spyce_type not in {'text', 'bytes'}:
            raise RuntimeError(f'{type(self).__name__}: unknown spyce type {self.spyce_type!r}')

    @_spyce_abc.abstractmethod
    def content(self):
        raise NotImplemented()

    def __repr__(self):
        return f'{type(self).__name__}({self.section!r}, {self.name!r}, {self.spyce_type!r})'


def get_file():
    try:
        return __file__
    except NameError:
        # if __file__ is not available:
        import inspect
        import sys
        return inspect.getfile(sys.modules[__name__])


class Dish(_spyce_MutableMapping):
    __re_section__ = r'\# spyce:\s+section\s+(?P<section>source|data)\s*'
    __re_spyce__ = r'\# spyce:\s+(?P<action>start|end)\s+(?P<section>source|data)/(?P<name>[^\s\/\:]+)(?:\:(?P<type>\S+))?'
    __sections__ = {'source', 'data'}

    def __init__(self, file=None, lines=None):
        if file is None:
            file = get_file()
        if lines is None:
            if isinstance(file, (str, _spyce_Path)):
                path = _spyce_Path(file)
                with open(file, 'r') as fh:
                    lines = fh.readlines()
            else:
                path = getattr(file, 'name', None)
                lines = file.readlines()
        self.file = file
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
        import re
        filename = self.filename
        lines = self.lines
        re_spyce = re.compile(self.__re_spyce__)
        re_section = re.compile(self.__re_section__)
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
                        raise SpyceError(f"{filename}@{spyce.start + 1}: duplicated spyce {spyce}")
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

    @_spyce_contextmanager
    def refactor(self, output_path=None, backup=False, backup_format=DEFAULT_BACKUP_FORMAT):
        import shutil
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
            output_path = _spyce_Path(output_path)
        if output_path is self.path or not self.path.is_file():
            backup = False
            if backup and self.path.is_file():
                if backup_format is None:
                    backup_format = DEFAULT_BACKUP_FORMAT
                backup_path = _spyce_Path(str(backup_format).format(
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
        return f'{type(self).__name__}({self.filename!r})'


def get_spyce(key, file=None):
    if '/' not in key:
        key = 'data/' + key
    dish = Dish(file)
    if key not in dish:
        raise SpyceError(f'spyce {key} not found')
    return dish[key]

# spyce: end source/spyce:text
