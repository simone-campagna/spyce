# spyce: start source/spyce_api:text
import abc
import base64
import datetime
import fnmatch
import inspect
import io
import json
import re
import shutil
import sys
import tarfile

from collections.abc import Mapping, MutableMapping
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from operator import attrgetter


__all__ = [
    'get_spyce', 'get_max_line_length', 'set_max_line_length',
    'Pattern', 'SpyceFilter', 'Spyce', 'TextSpyce', 'BytesSpyce',
    'SpyceJar', 'SpycyFile',
]

SPYCE_API_VERSION = '0.1.0'

DEFAULT_BACKUP_FORMAT = '{path}.bck.{timestamp}'
MAX_LINE_LENGTH = 120

def get_max_line_length():
    return MAX_LINE_LENGTH


def set_max_line_length(value):
    global MAX_LINE_LENGTH
    MAX_LINE_LENGTH = int(value)


class Timestamp(datetime.datetime):
    def __str__(self):
        return self.strftime('%Y%m%d-%H%M%S')


def default_spyce_type(section, name):
    return 'text' if section == 'source' else 'bytes'


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

    def __init__(self, section, name, init, conf=None):
        if isinstance(init, (str, bytes)):
            self.content = init
            self.lines = self.encode(self.content)
        else:
            self.lines = list(init)
            self.content = self.decode(self.lines)
        self.section = section
        self.name = name
        self.conf = conf or {}

    @property
    def flavor(self):
        return self.conf.get('flavor', None)

    @classmethod
    def spyce_class(cls, spyce_type, /, default=UNDEF):
        if default is UNDEF:
            return cls.__registry__[spyce_type]
        else:
            return cls.__registry__.get(spyce_type, default)

    @classmethod
    @abc.abstractmethod
    def class_spyce_type(cls):
        raise NotImplementedError()

    @property
    def fq_name(self):
        return self.build_fq_name(self.section, self.name, self.spyce_type)

    @staticmethod
    def build_fq_name(section, name, spyce_type):
        return f'{section}/{name}:{spyce_type}'

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
        return self.fq_name

    def __repr__(self):
        return f'{type(self).__name__}({self.spycy_file!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r})'


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
    def __init__(self, spycy_file, section, name, spyce_type, start, end, conf=None):
        self.spycy_file = spycy_file
        self.section = section
        self.name = name
        if spyce_type is None:
            spyce_type = default_spyce_type(section, name)
        self.spyce_type = spyce_type
        self.fq_name = Spyce.build_fq_name(section, name, spyce_type)
        self.start = start
        self.end = end
        spyce_class = Spyce.spyce_class(spyce_type, None)
        if spyce_class is None:
            raise SpyceError(f"{self.spycy_file.filename}@{self.start + 1}: unknown spyce type {spyce_type!r}")
        self.spyce_class = spyce_class
        self._spyce = None
        self.conf = conf or {}
        self.num_params = 0

    @property
    def flavor(self):
        return self.conf.get('flavor', None)

    def merge_conf(self, line_index, key, value):
        if line_index != (self.start + self.num_params + 1):
            raise SpyceError(f"{self.spycy_file.filename}@{line_index + 1}: unexpected spyce conf")
        self.conf[key] = value
        self.num_params += 1

    @property
    def spyce(self):
        if self._spyce is None:
            self._spyce = self.spyce_class(section=self.section, name=self.name, init=self.get_lines(), conf=self.conf)
        return self._spyce

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
        return f'{type(self).__name__}({self.spycy_file!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r})'


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
    __regex__ = re.compile(r'(?P<op>[\^\:\%])?(?P<pattern>[^\^\:\%]+)\s*')
    __key_dict__ = {'': 'name', ':': 'spyce_type', '^': 'section', '%': 'flavor'}

    def __init__(self, section=None, name=None, spyce_type=None, flavor=None):
        self.patterns = []
        if section:
            self.patterns.append(('section', Pattern.build(section), attrgetter('section')))
        if name:
            self.patterns.append(('name', Pattern.build(name), attrgetter('name')))
        if spyce_type:
            self.patterns.append(('spyce_type', Pattern.build(spyce_type), attrgetter('spyce_type')))
        if flavor:
            self.patterns.append(('flavor', Pattern.build(flavor), attrgetter('flavor')))

    @classmethod
    def build(cls, value):
        # name :type ^section %flavor
        kwargs = {}
        for op, pattern in cls.__regex__.findall(value):
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


class SpycyFile(MutableMapping):
    __re_section__ = r'\# spyce:\s+section\s+(?P<section>source|data)\s*'
    __re_spyce__ = r'\# spyce:\s+(?P<action>start|end)\s+(?P<section>source|data)/(?P<name>[^\s\/\:]+)(?:\:(?P<type>\S+))?'
    __re_conf__ = r'\# spyce:\s+conf:\s+(?P<key>\w+)\s*=\s*(?P<value>.*)\s*$'
    __sections__ = {'source', 'data'}

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
        self.section = {'source': None, 'data': None}
        self._parse_lines()
        self.content_version = 0

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

    def code_lines(self):
        spyced_indices = set()
        for jar in self.spyce_jars.values():
            spyced_indices.update(range(jar.start, jar.end))
        cur_index = 0
        cur_lines = []
        for index, line in enumerate(self.lines):
            if index not in spyced_indices:
                cur_lines.append((cur_index, line))
                cur_index += 1
        return cur_lines

    def _parse_lines(self):
        filename = self.filename
        lines = self.lines
        re_spyce = re.compile(self.__re_spyce__)
        re_section = re.compile(self.__re_section__)
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
            m_section = re_section.match(line)
            if m_section:
                self.section[m_section['section']] = cur_index
                continue

            m_spyce = re_spyce.match(line)
            if m_spyce:
                cur_section, cur_action, cur_name, cur_type = (
                    m_spyce['section'], m_spyce['action'], m_spyce['name'], m_spyce['type'])
                if cur_action == 'end':
                    if spyce_jar and cur_section == spyce_jar.section and cur_name == spyce_jar.name:
                        _store_spyce_jar(cur_index)
                        continue
                    else:
                        raise SpyceError(f'{filename}@{cur_index + 1}: unexpected directive "{cur_action} {cur_section}/{cur_name}:{cur_type}"')
                elif cur_action == 'start':
                    if spyce_jar:
                        # empty spyce
                        _store_spyce_jar(None)
                    spyce_jar = SpyceJar(self, section=cur_section, name=cur_name, spyce_type=cur_type, start=cur_index, end=None)
                    if spyce_jar.name in self.spyce_jars:
                        raise SpyceError(f"{filename}@{spyce_jar.start + 1}: duplicated spyce {spyce_jar}")
                    continue
                continue

            m_conf = re_conf.match(line)
            if m_conf:
                if spyce_jar is None:
                    raise SpyceError(f"{filename}@{cur_index + 1}: unexpected conf: {type(err).__name__}: {err}")
                key = m_conf['key']
                serialized_value = m_conf['value']
                try:
                    value = json.loads(serialized_value)
                except Exception as err:
                    raise SpyceError(f"{filename}@{cur_index + 1}: conf key {key}={serialized_value!r}: {type(err).__name__}: {err}")
                spyce_jar.merge_conf(cur_index, key, value)

        if spyce_jar:
            _store_spyce_jar(None)

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
        if not isinstance(spyce, Spyce):
            raise TypeError(spyce)
        section = spyce.section
        name = spyce.name
        spyce_type = spyce.spyce_type
        content = spyce.get_content()

        self.content_version += 1
        deleted_spyce_jar = self.spyce_jars.get(name, None)
        if deleted_spyce_jar:
            # replace existing block
            del self[name]
            start = deleted_spyce_jar.start
        else:
            spc_ends = [spc.end for spc in self.spyce_jars.values() if spc.section == section]
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
        fq_name = spyce.fq_name
        spyce_lines = [f'# spyce: start {fq_name}\n']
        for key, value in spyce.conf.items():
            serialized_value = json.dumps(value)
            spyce_lines.append(f'# spyce: conf: {key}={serialized_value}\n')
        spyce_lines.extend(spyce.encode(content))
        spyce_lines.append(f'# spyce: end {fq_name}\n')
        self.lines[start:start] = spyce_lines
        l_diff = len(spyce_lines)
        self._update_lines(start, l_diff)
        spyce_jar = SpyceJar(self, section=section, name=name, spyce_type=spyce_type, start=start, end=start + len(spyce_lines))
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

    def __len__(self):
        return len(self.spyce_jars)

    def __iter__(self):
        yield from self.spyce_jars

    def __getitem__(self, name):
        return self.spyce_jars[name].spyce

    def get_spyce_jar(self, name):
        return self.spyce_jars[name]

    def __repr__(self):
        return f'{type(self).__name__}({self.filename!r})'


def get_spyce(name, file=None):
    spycy_file = SpycyFile(file)
    if name not in spycy_file:
        raise SpyceError(f'spyce {name} not found')
    return spycy_file[name]

# spyce: end source/spyce_api:text
