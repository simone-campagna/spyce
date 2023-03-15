# spyce: start spyce_api
# spyce: - flavor="api"
# spyce: - type="text"
import abc
import base64
import datetime
import fnmatch
import inspect
import io
import json
import re
import sys
import tarfile

from collections.abc import Mapping
from pathlib import Path
from operator import attrgetter


__all__ = [
    'get_spyce', 'get_max_line_length', 'set_max_line_length',
    'Pattern', 'SpyceFilter', 'Spyce', 'TextSpyce', 'BytesSpyce',
    'SpyceJar', 'SpycyFile',
]

SPYCE_API_VERSION = '0.1.0'

MAX_LINE_LENGTH = 120

def get_max_line_length():
    return MAX_LINE_LENGTH


def set_max_line_length(value):
    global MAX_LINE_LENGTH
    MAX_LINE_LENGTH = int(value)


class Timestamp(datetime.datetime):
    def __str__(self):
        return self.strftime('%Y%m%d-%H%M%S')


class SpyceError(RuntimeError):
    pass


class SpyceMeta(abc.ABCMeta):
    def __new__(mcls, class_name, class_bases, class_dict):
        cls = super().__new__(mcls, class_name, class_bases, class_dict)
        if not inspect.isabstract(cls):
            cls.__registry__[cls.class_spyce_type()] = cls
        return cls


UNDEF = object()


class Spyce(metaclass=SpyceMeta):
    __registry__ = {}

    def __init__(self, name, init, conf=None, path=None):
        if isinstance(init, (str, bytes)):
            self.content = init
            self.lines = self.encode(self.content)
        else:
            self.lines = list(init)
            self.content = self.decode(self.lines)
        self.name = name
        self.conf = conf or {}
        if path:
            path = Path(path)
        self.path = path

    @property
    def flavor(self):
        return self.conf.get('flavor', None)

    @classmethod
    def spyce_class(cls, spyce_type, default=UNDEF):
        if default is UNDEF:
            return cls.__registry__[spyce_type]
        else:
            return cls.__registry__.get(spyce_type, default)

    @classmethod
    @abc.abstractmethod
    def class_spyce_type(cls):
        raise NotImplementedError()

    @property
    def spyce_type(self):
        return self.class_spyce_type()

    @classmethod
    @abc.abstractmethod
    def encode(cls, content):
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
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
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_file(self, path):
        path = self._build_path(path)
        content = self.get_content()
        with open(path, self._file_mode()) as file:
            file.write(content)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f'{type(self).__name__}({self.spycy_file!r}, {self.name!r}, {self.start!r}, {self.end!r})'


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
    __data_prefix__ = '#|'

    @classmethod
    def encode(cls, content):
        lines = []
        data = str(base64.b85encode(content), 'utf-8')
        data_prefix = cls.__data_prefix__
        dlen = max(get_max_line_length() - len(data_prefix), len(data_prefix) + 1)
        for index in range(0, len(data), dlen):
            lines.append(f'{data_prefix}{data[index:index+dlen]}\n')
        return lines

    @classmethod
    def decode(cls, lines):
        data_prefix = cls.__data_prefix__
        data = ''.join(line[len(data_prefix):].strip() for line in lines if line.startswith(data_prefix))
        return base64.b85decode(data)

    @classmethod
    def class_spyce_type(cls):
        return 'bytes'

    def _file_mode(self):
        return 'wb'

    def untar(self, path, mode='r|*'):
        path = self._build_path(path)
        b_file = io.BytesIO(self.get_content())
        with tarfile.open(fileobj=b_file, mode=mode) as t_file:
            t_file.extractall(path)


class SpyceJar:
    def __init__(self, spycy_file, name, start, end, conf=None):
        self.spycy_file = spycy_file
        self.name = name
        self.start = start
        self.end = end
        self._spyce = None
        self.conf = dict(conf or {})
        self.num_params = 0

    def index_range(self, headers=False):
        if headers:
            return self.start, self.end
        else:
            return self.start + self.num_params + 1, self.end - 1

    @property
    def spyce_type(self):
        return self.conf.get('type', None)

    @property
    def spyce_class(self):
        spyce_type = self.spyce_type
        spyce_class = Spyce.spyce_class(spyce_type, None)
        if spyce_class is None:
            raise SpyceError(f"{self.spycy_file.filename}@{self.start + 1}: unknown spyce type {spyce_type!r}")
        return spyce_class

    @property
    def spyce(self):
        if self._spyce is None:
            self._spyce = self.spyce_class(
                name=self.name,
                init=self.get_lines(), conf=self.conf,
                path=self.spycy_file.path)
        return self._spyce

    @property
    def flavor(self):
        return self.conf.get('flavor', None)

    def merge_conf(self, line_index, key, value):
        if line_index != (self.start + self.num_params + 1):
            raise SpyceError(f"{self.spycy_file.filename}@{line_index + 1}: unexpected spyce conf")
        self.conf[key] = value
        self.num_params += 1

    def get_lines(self, headers=False):
        if headers:
            s_offset, e_offset = 0, 0
        else:
            s_offset, e_offset = self.num_params + 1, 1
        return self.spycy_file.lines[self.start+s_offset:self.end-e_offset]

    def get_text(self, headers=True):
        return '\n'.join(self.get_lines(headers=headers))

    def __str__(self):
        return self.name

    def __repr__(self):
        return f'{type(self).__name__}({self.spycy_file!r}, {self.name!r}, {self.start!r}, {self.end!r})'


def get_file():
    try:
        return __file__
    except NameError:
        # if __file__ is not available:
        return inspect.getfile(sys.modules[__name__])


class Pattern:
    def __init__(self, pattern, reverse=False):
        self.pattern = pattern
        self.reverse = reverse

    @classmethod
    def build(cls, value):
        if value.startswith('~'):
            reverse, pattern = True, value[1:]
        else:
            reverse, pattern = False, value
        return cls(pattern, reverse)

    def __call__(self, value):
        return self.reverse != bool(fnmatch.fnmatch(value, self.pattern))

    def __str__(self):
        if self.reverse:
            return f'~{self.pattern}'
        return self.pattern

    def __repr__(self):
        return f'{type(self).__name__}({self.pattern!r}, {self.reverse!r})'


class SpyceFilter:
    __regex__ = re.compile(r'(?P<op>[\^\:\/])?(?P<pattern>[^\^\:]+)\s*')
    __key_dict__ = {'': 'name', ':': 'spyce_type', '^': 'flavor', '/': 'path'}

    def __init__(self, name=None, spyce_type=None, flavor=None, path=None):
        self.patterns = []
        if name:
            self.patterns.append(('name', Pattern.build(name), attrgetter('name')))
        if spyce_type:
            self.patterns.append(('spyce_type', Pattern.build(spyce_type), attrgetter('spyce_type')))
        if flavor:
            self.patterns.append(('flavor', Pattern.build(flavor), attrgetter('flavor')))
        if path:
            if not path.startswith('/'):
                path = '*/' + path
            self.patterns.append(('path', Pattern.build(path), attrgetter('path')))

    @classmethod
    def build(cls, value):
        kwargs = {}
        for token in value.split():
            for op, pattern in cls.__regex__.findall(token):
                kwargs[cls.__key_dict__[op]] = pattern
        return cls(**kwargs)

    def __call__(self, spyce):
        return all(pattern(getter(spyce)) for _,  pattern, getter in self.patterns)

    def __repr__(self):
        args = ', '.join(f'{key}={pattern!r}' for key, pattern, _ in self.patterns)
        return f'{type(self).__name__}({args})'

    def __str__(self):
        key_rev = {value: key for key, value in self.__key_dict__.items()}
        return ' '.join(key_rev[key] + str(pattern) for key, pattern, _ in self.patterns)


class SpycyFile(Mapping):
    __re_spyce__ = r'\# spyce:\s+(?P<action>start|end)\s+(?P<name>[^\s\/\:]+)'
    __re_conf__ = r'\# spyce:\s+-\s+(?P<key>\w+)\s*=\s*(?P<value>.*)\s*$'

    def __init__(self, file=None, lines=None):
        if file is None:
            file = get_file()
        if lines is None:
            if isinstance(file, (str, Path)):
                path = Path(file)
                with open(file, 'r') as fh:
                    lines = fh.readlines()
            else:
                path = getattr(file, 'name', None)
                lines = file.readlines()
        self.file = file
        self.path = path
        self.filename = str(self.path) if self.path is not None else '<stdin>'
        self.lines = lines
        self.spyce_jars = {}
        self._parse_lines()

    def filter(self, spyce_filters):
        if spyce_filters is None:
            spyce_filters = []
        spyces = list(self.values())
        for spyce_filter in spyce_filters:
            new_spyces = []
            for spyce in spyces:
                if spyce_filter(spyce):
                    new_spyces.append(spyce)
            spyces = new_spyces
            if not spyces:
                break
        selected_names = {spyce.name for spyce in spyces}
        return [name for name in self if name in selected_names]

    def _parse_lines(self):
        filename = self.filename
        lines = self.lines
        re_spyce = re.compile(self.__re_spyce__)
        re_conf = re.compile(self.__re_conf__)
        spyce_jars = self.spyce_jars

        spyce_jar = None
        def _store_spyce_jar(line_index=None):
            nonlocal spyce_jars, spyce_jar
            if spyce_jar:
                if line_index is None:
                    line_index = spyce_jar.start + spyce_jar.num_params
                spyce_jar.end = line_index + 1
                spyce_jars[spyce_jar.name] = spyce_jar
                spyce_jar = None

        for cur_index, line in enumerate(lines):
            m_spyce = re_spyce.match(line)
            if m_spyce:
                cur_action, cur_name = (
                    m_spyce['action'], m_spyce['name'])
                if cur_action == 'end':
                    if spyce_jar and cur_name == spyce_jar.name:
                        _store_spyce_jar(cur_index)
                        continue
                    else:
                        raise SpyceError(f'{filename}@{cur_index + 1}: unexpected directive "{cur_action} {cur_name}"')
                elif cur_action == 'start':
                    if spyce_jar:
                        # empty spyce
                        _store_spyce_jar(None)
                    spyce_jar = SpyceJar(self, name=cur_name, start=cur_index, end=None)
                    if spyce_jar.name in self.spyce_jars:
                        raise SpyceError(f"{filename}@{spyce_jar.start + 1}: duplicated spyce {spyce_jar}")
                    continue
                continue

            m_conf = re_conf.match(line)
            if m_conf:
                if spyce_jar is None:
                    raise SpyceError(f"{filename}@{cur_index + 1}: unexpected parameter {m_conf['key']}={m_conf['value']}")
                key = m_conf['key']
                serialized_value = m_conf['value']
                try:
                    value = json.loads(serialized_value)
                except Exception as err:
                    raise SpyceError(f"{filename}@{cur_index + 1}: conf key {key}={serialized_value!r}: {type(err).__name__}: {err}")
                spyce_jar.merge_conf(cur_index, key, value)

        if spyce_jar:
            _store_spyce_jar(None)

    def __len__(self):
        return len(self.spyce_jars)

    def __iter__(self):
        yield from self.spyce_jars

    def __getitem__(self, name):
        return self.spyce_jars[name]

    def get_spyce(self, name):
        return self.spyce_jars[name].spyce

    def __repr__(self):
        return f'{type(self).__name__}({self.filename!r})'


def get_spyce(name, file=None):
    spycy_file = SpycyFile(file)
    if name not in spycy_file:
        raise SpyceError(f'spyce {name} not found')
    return spycy_file.get_spyce(name)

# spyce: end spyce_api
