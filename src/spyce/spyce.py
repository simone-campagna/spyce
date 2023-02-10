__all__ = [
    'Spyce',
    'TextSpyce',
    'BytesSpyce',
    'SpyceFarm',
    'ApiSpyceFarm',
    'SourceSpyceFarm',
    'FileSpyceFarm',
    'DirSpyceFarm',
    'UrlSpyceFarm',
]


import abc
import base64
import inspect
import io
import tarfile
import urllib.parse
import urllib.request

from pathlib import Path

from . import api
from .error import SpyceError


class SpyceMeta(abc.ABCMeta):
    def __new__(mcls, class_name, class_bases, class_dict):
        cls = super().__new__(mcls, class_name, class_bases, class_dict)
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
    @abc.abstractmethod
    def class_spyce_type(cls):
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
    def encode(cls, content):
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
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
        lines = []
        data = str(base64.b64encode(content), 'utf-8')
        dlen = cls.__data_line_length__
        for index in range(0, len(data), dlen):
            lines.append(f'#|{data[index:index+dlen]}\n')
        data_prefix = cls.__data_prefix__
        return lines

    @classmethod
    def decode(cls, lines):
        data_prefix = cls.__data_prefix__
        data = ''.join(line[len(data_prefix):].strip() for line in lines if line.startswith(data_prefix))
        return base64.b64decode(data)

    def get_content(self):
        return ''.join(self.get_lines())

    @classmethod
    def class_spyce_type(cls):
        return 'bytes'


def default_spyce_type(section, name):
    return 'text' if section == 'source' else 'bytes'


class SpyceFarm(abc.ABC):
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

    @abc.abstractmethod
    def content(self):
        raise NotImplemented()

    def __repr__(self):
        return f'{type(self).__name__}({self.section!r}, {self.name!r}, {self.spyce_type!r})'


class PathSpyceFarm(SpyceFarm):
    def __init__(self, path, section=None, name=None, spyce_type=None):
        self.path = Path(path)
        self._check_path()
        super().__init__(name, section, spyce_type)

    def _check_path(self):
        if self._path is None:
            raise RuntimeError(f'{type(self).__name__}: path not set')

    def _default_name(self):
        return self.path.name

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'


class FileSpyceFarm(PathSpyceFarm):
    def _check_path(self):
        path = self.path
        if not path.is_file():
            raise RuntimeError(f'{type(self).__name__}: {path} is not a file')
        super()._check_name()

    def content(self):
        mode = 'r'
        if self.spyce_type == 'bytes':
            mode += 'b'
        with open(self.path, mode) as fh:
            return fh.read()


class SourceSpyceFarm(FileSpyceFarm):
    @classmethod
    def _default_section(cls):
        return 'source'


class DirSpyceFarm(PathSpyceFarm):
    def _check_path(self):
        path = self.path
        if not path.is_dir():
            raise RuntimeError(f'{type(self).__name__}: {path} is not a directory')
        super()._check_name()

    def content(self):
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w|gz') as tf:
            tf.add(self.path)
        return bf.getvalue()


class UrlSpyceFarm(SpyceFarm):
    def __init__(self, url, section=None, name=None, spyce_type=None):
        self.url = url
        self.parsed_url = urllib.parse.urlparse(self.url)
        if name is None:
            name = Path(self.parsed_url.path).name
        super().__init__(section=section, name=name, spyce_type=spyce_type)
        self._check_url()

    def _check_url(self):
        if self.url is None:
            raise RuntimeError(f'{type(self).__name__}: url not set')

    def content(self):
        with urllib.request.urlopen(self.url) as response:
            return response.read()

    def __repr__(self):
        return f'{type(self).__name__}({self.url!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'


class ApiSpyceFarm(SpyceFarm):
    def __init__(self, implementation, section=None, name=None, spyce_type=None):
        self.implementation = implementation
        super().__init__(section=section, name=name, spyce_type=spyce_type)
        self._check_implementation()

    def _default_section(self):
        return 'source'

    def _default_name(self):
        return 'spyce'

    def _check_implementation(self):
        if self.implementation is None:
            self.implementation = api.default_api_implementation()
        elif self.implementation not in api.get_api_implementations():
            raise RuntimeError(f'{type(self).__name__}: api implementation {self.implementation} is not a directory')

    def content(self):
        return api.get_api(self.name, self.implementation)

    def __repr__(self):
        return f'{type(self).__name__}({self.implementation!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'
