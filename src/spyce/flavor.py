import abc
import inspect

from pathlib import Path

from .spyce import SpyceError, Spyce, default_spyce_type
from . import api


__all__ = [
    'FlavorError',
    'FlavorParseError',
    'FlavorMeta',
    'Flavor',
    'ApiFlavor',
    'SourceFlavor',
    'FileFlavor',
    'DirFlavor',
    'UrlFlavor',
]


class FlavorError(SpyceError):
    pass


class FlavorParseError(FlavorError):
    pass


class FlavorMeta(abc.ABCMeta):
    def __new__(mcls, class_name, class_bases, class_dict):
        cls = super().__new__(mcls, class_name, class_bases, class_dict)
        if not inspect.isabstract(cls):
            flavor = cls.flavor()
            cls.__registry__[flavor] = cls
        return cls


class Flavor(metaclass=FlavorMeta):
    __registry__ = {}
    def __init__(self, section=None, name=None, spyce_type=None):
        self.section = section
        self.name = name
        self.spyce_type = spyce_type

        self._check_section()
        self._check_name()
        self._check_spyce_type()

    def spyce_key(self):
        return f'{self.section}/{self.name}'

    @classmethod
    @abc.abstractmethod
    def flavor(self):
        raise NotImplemented()
    
    @classmethod
    def flavor_class(cls, flavor):
        return cls.__registry__[flavor]

    @classmethod
    def parse_data(cls, base_dir, filename, data):
        result = {}
        if 'section' in data:
            result['section'] = data['section']
        if 'type' in data:
            result['spyce_type'] = data['type']
        return result

    @classmethod
    def _parse_key(cls, data, key, types):
        value = data.get(key, None)
        if value is None:
            raise FlavorParseError(f'{key} key not set')
        if not isinstance(value, types):
            raise FlavorParseError(f'{key} {value!r}: invalid type')
        return value

    def spyce_class(self):
        return Spyce.spyce_class(self.spyce_type)

    def __call__(self):
        return self.spyce_class()(
            section=self.section,
            name=self.name,
            init=self.content(),
        )

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
            raise FlavorError(f'{type(self).__name__}: spyce name not set')

    def _check_spyce_type(self):
        if self.spyce_type is None:
            self.spyce_type = self._default_spyce_type()
        if self.spyce_type is None:
            self.spyce_type = default_spyce_type(self.section, self.name)
        if self.spyce_type not in {'text', 'bytes'}:
            raise FlavorError(f'{type(self).__name__}: unknown spyce type {self.spyce_type!r}')

    @abc.abstractmethod
    def content(self):
        raise NotImplemented()

    def __repr__(self):
        return f'{type(self).__name__}({self.section!r}, {self.name!r}, {self.spyce_type!r})'


class PathFlavor(Flavor):
    def __init__(self, path, section=None, name=None, spyce_type=None):
        self.path = Path(path)
        self._check_path()
        super().__init__(section=section, name=name, spyce_type=spyce_type)

    @classmethod
    def parse_data(cls, base_dir, filename, data):
        result = super().parse_data(base_dir, filename, data)
        path = cls._parse_key(data, 'path', (str, Path))
        path = Path(path)
        if not path.is_absolute():
            path = Path(base_dir) / path
        result['path'] = path
        return result

    def _check_path(self):
        if self.path is None:
            raise FlavorError(f'{type(self).__name__}: path not set')

    def _default_name(self):
        return self.path.name

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'


class FileFlavor(PathFlavor):
    def _check_path(self):
        path = self.path
        if not path.is_file():
            raise FlavorError(f'{type(self).__name__}: {path} is not a file')
        super()._check_path()

    @classmethod
    def flavor(cls):
        return 'file'

    def content(self):
        mode = 'r'
        if self.spyce_type == 'bytes':
            mode += 'b'
        with open(self.path, mode) as fh:
            return fh.read()


class SourceFlavor(FileFlavor):
    @classmethod
    def flavor(cls):
        return 'source'

    @classmethod
    def _default_section(cls):
        return 'source'


class DirFlavor(PathFlavor):
    @classmethod
    def flavor(cls):
        return 'dir'

    def _check_path(self):
        path = self.path
        if not path.is_dir():
            raise FlavorError(f'{type(self).__name__}: {path} is not a directory')
        super()._check_name()

    def content(self):
        import io
        import tarfile
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w|gz') as tf:
            tf.add(self.path)
        return bf.getvalue()


class UrlFlavor(Flavor):
    def __init__(self, url, section=None, name=None, spyce_type=None):
        self.url = url
        super().__init__(section=section, name=name, spyce_type=spyce_type)
        self._check_url()

    @classmethod
    def flavor(cls):
        return 'url'

    @classmethod
    def parse_data(cls, base_dir, filename, data):
        result = super().parse_data(base_dir, filename, data)
        url = cls._parse_key(data, 'url', (str,))
        result['url'] = url
        return result

    def _default_name(self):
        if self.url:
            import urllib.parse
            parsed_url = urllib.parse.urlparse(self.url)
            return Path(parsed_url.path).name

    def _check_url(self):
        if self.url is None:
            raise rError(f'{type(self).__name__}: url not set')

    def content(self):
        import urllib.request
        with urllib.request.urlopen(self.url) as response:
            return response.read()

    def __repr__(self):
        return f'{type(self).__name__}({self.url!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'


class ApiFlavor(Flavor):
    def __init__(self, implementation, section=None, name=None, spyce_type=None):
        self.implementation = implementation
        super().__init__(section=section, name=name, spyce_type=spyce_type)
        self._check_implementation()

    @classmethod
    def parse_data(cls, base_dir, filename, data):
        result = super().parse_data(base_dir, filename, data)
        implementation = data.get('implementation', api.default_api_implementation())
        if implementation not in api.get_api_implementations():
            raise FlavorParseError(f'unknown api implementation {implementation!r}')
        result['implementation'] = implementation
        return result

    @classmethod
    def flavor(cls):
        return 'api'

    def _default_section(self):
        return 'source'

    def _default_name(self):
        return 'spyce'

    def _check_implementation(self):
        if self.implementation is None:
            self.implementation = api.default_api_implementation()
        elif self.implementation not in api.get_api_implementations():
            raise FlavorError(f'{type(self).__name__}: api implementation {self.implementation} is not a directory')

    def content(self):
        return api.get_api(self.name, self.implementation)

    def __repr__(self):
        return f'{type(self).__name__}({self.implementation!r}, {self.section!r}, {self.name!r}, {self.spyce_type!r})'
