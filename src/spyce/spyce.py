# spyce: start source/spyce:text
import abc as _spyce_abc
import datetime as _spyce_datetime
from collections.abc import MutableMapping as _spyce_MutableMapping
from collections.abc import Sequence as _spyce_Sequence
from contextlib import contextmanager as _spyce_contextmanager
from pathlib import Path as _spyce_Path


__all__ = [
    'Spyce',
    'TextSpyce',
    'BytesSpyce',
    'Curry',
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

    def __init__(self, section, name, init):
        if isinstance(init, (str, bytes)):
            self.content = init
            self.lines = self.encode(self.content)
        else:
            self.lines = list(init)
            self.content = self.decode(self.lines)
        self.section = section
        self.name = name

    @classmethod
    def spyce_class(cls, spyce_type, /, default=UNDEF):
        if default is UNDEF:
            return cls.__registry__[spyce_type]
        else:
            return cls.__registry__.get(spyce_type, default)

    @classmethod
    @_spyce_abc.abstractmethod
    def class_spyce_type(cls):
        raise NotImplementedError()

    @property
    def key(self):
        return f'{self.section}/{self.name}'

    @property
    def fq_key(self):
        return f'{self.section}/{self.name}:{self.spyce_type}'

    @property
    def spyce_type(self):
        return self.class_spyce_type()

    @classmethod
    @_spyce_abc.abstractmethod
    def encode(cls, content):
        raise NotImplementedError()

    @classmethod
    @_spyce_abc.abstractmethod
    def decode(cls, lines):
        raise NotImplementedError()

    def get_lines(self):
        return self.lines

    def get_text(self):
        return ''.join(self.get_lines())

    def get_content(self):
        return self.content

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
        return self.fq_key

    def __repr__(self):
        return f'{type(self).__name__}({self.curry!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r})'


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


class SpyceItem:
    def __init__(self, curry, section, name, spyce_type, start, end):
        self.curry = curry
        self.section = section
        self.name = name
        if spyce_type is None:
            spyce_type = default_spyce_type(section, name)
        self.spyce_type = spyce_type
        self.key = self.spyce_key(section, name)
        self.fq_key = self.spyce_fq_key(section, name, spyce_type)
        self.start = start
        self.end = end
        spyce_class = Spyce.spyce_class(spyce_type, None)
        if spyce_class is None:
            raise SpyceError(f"{self.curry.filename}@{self.start + 1}: unknown spyce type {spyce_type!r}")
        self.spyce_class = spyce_class
        self._spyce = None

    @property
    def spyce(self):
        if self._spyce is None:
            self._spyce = self.spyce_class(section=self.section, name=self.name, init=self.get_lines())
        return self._spyce

    @staticmethod
    def spyce_key(section, name):
        return f'{section}/{name}'

    @staticmethod
    def spyce_fq_key(section, name, spyce_type):
        return f'{section}/{name}:{spyce_type}'

    def get_lines(self, headers=False):
        if headers:
            s_offset, e_offset = 0, 0
        else:
            s_offset, e_offset = 1, 1
        return self.curry.lines[self.start+s_offset:self.end-e_offset]

    def get_text(self, headers=True):
        return '\n'.join(self.get_lines(headers=headers))

    def __str__(self):
        return self.key

    def __repr__(self):
        return f'{type(self).__name__}({self.curry!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r})'


def get_file():
    try:
        return __file__
    except NameError:
        # if __file__ is not available:
        import inspect
        import sys
        return inspect.getfile(sys.modules[__name__])


class Curry(_spyce_MutableMapping):
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
        self.spyce_items = {}
        self.section = {'source': None, 'data': None}
        self._parse_lines()
        self.content_version = 0

    def _parse_lines(self):
        import re
        filename = self.filename
        lines = self.lines
        re_spyce = re.compile(self.__re_spyce__)
        re_section = re.compile(self.__re_section__)
        spyce_items = self.spyce_items

        spyce_item = None
        def _store_spyce_item(line_index):
            nonlocal spyce_items, spyce_item
            if spyce_item:
                spyce_item.end = line_index + 1
                spyce_items[spyce_item.key] = spyce_item
                spyce_item = None

        for cur_index, line in enumerate(lines):
            m_section = re_section.match(line)
            if m_section:
                self.section[m_section['section']] = cur_index

            m_spyce = re_spyce.match(line)
            if m_spyce:
                cur_section, cur_action, cur_name, cur_type = (
                    m_spyce['section'], m_spyce['action'], m_spyce['name'], m_spyce['type'])
                if cur_action == 'end':
                    if spyce_item and cur_section == spyce_item.section and cur_name == spyce_item.name:
                        _store_spyce_item(cur_index)
                        continue
                    else:
                        raise SpyceError(f'{filename}@{cur_index + 1}: unexpected directive "{cur_section} {cur_action} {cur_name}"')
                elif cur_action == 'start':
                    if spyce_item:
                        # empty spyce
                        _store_spyce_item(spyce_item.start)
                    spyce_item = SpyceItem(self, section=cur_section, name=cur_name, spyce_type=cur_type, start=cur_index, end=None)
                    if spyce_item.key in self.spyce_items:
                        raise SpyceError(f"{filename}@{spyce_item.start + 1}: duplicated spyce {spyce_item}")
                    continue
        if spyce_item:
            _store_spyce_item(spyce_item.start)

    def _update_lines(self, l_start, l_diff):
        for spyce_item in self.spyce_items.values():
            if spyce_item.start > l_start:
                spyce_item.start += l_diff
                spyce_item.end += l_diff
        for section in self.section:
            if self.section[section] is not None and self.section[section] > l_start:
                self.section[section] += l_diff

    def __delitem__(self, key):
        spyce_item = self.spyce_items.pop(key)
        del self.lines[spyce_item.start:spyce_item.end]
        self._update_lines(spyce_item.start, -(spyce_item.end - spyce_item.start))
        self.content_version += 1

    def __setitem__(self, key, spyce):
        if not isinstance(spyce, Spyce):
            raise TypeError(spyce)
        section = spyce.section
        name = spyce.name
        spyce_type = spyce.spyce_type
        content = spyce.get_content()

        self.content_version += 1
        deleted_spyce_item = self.spyce_items.get(key, None)
        if deleted_spyce_item:
            # replace existing block
            del self[key]
            start = deleted_spyce_item.start
        else:
            spc_ends = [spc.end for spc in self.spyce_items.values() if spc.section == section]
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
        spyce_lines.extend(spyce.encode(content))
        spyce_lines.append(f'# spyce: end {key}:{spyce_type}\n')
        self.lines[start:start] = spyce_lines
        l_diff = len(spyce_lines)
        self._update_lines(start, l_diff)
        spyce_item = SpyceItem(self, section=section, name=name, spyce_type=spyce_type, start=start, end=start + len(spyce_lines))
        self.spyce_items[key] = spyce_item

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
        return len(self.spyce_items)

    def __iter__(self):
        yield from self.spyce_items

    def __getitem__(self, key):
        return self.spyce_items[key].spyce

    def get_spyce_item(self, key):
        return self.spyce_items[key]

    def __repr__(self):
        return f'{type(self).__name__}({self.filename!r})'


def get_spyce(key, file=None):
    if '/' not in key:
        key = 'data/' + key
    curry = Curry(file)
    if key not in curry:
        raise SpyceError(f'spyce {key} not found')
    return curry[key]

# spyce: end source/spyce:text
