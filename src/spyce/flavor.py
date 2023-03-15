import abc
import inspect

from pathlib import Path
from urllib.parse import urlparse

from .spyce import SpyceError, Spyce
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
    def __init__(self, name=None, spyce_type=None):
        self.name = name
        self.spyce_type = spyce_type

        self._check_name()
        self._check_spyce_type()

    def _default_name(self):
        return None

    @classmethod
    def fix_conf(cls, conf):
        if not conf.get('type', None):
            conf['type'] = cls.default_spyce_type()

    @classmethod
    @abc.abstractmethod
    def flavor(self):
        raise NotImplemented()

    @classmethod
    def flavor_class(cls, flavor):
        if flavor not in cls.__registry__:
            raise SpyceError(f'unknown flavor {flavor}')
        return cls.__registry__[flavor]

    @classmethod
    def parse_conf(cls, base_dir, filename, data):
        result = {}
        if 'type' in data:
            result['spyce_type'] = data['type']
        return result

    def conf(self):
        return {
            'flavor': self.flavor(),
            'type': self.spyce_type,
        }

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
            name=self.name,
            init=self.content(),
            conf=self.conf(),
        )

    @classmethod
    def default_spyce_type(cls):
        return 'bytes'

    def _check_name(self):
        if self.name is None:
            self.name = self._default_name()
        if self.name is None:
            raise FlavorError(f'{type(self).__name__}: spyce name not set')

    def _check_spyce_type(self):
        if self.spyce_type is None:
            self.spyce_type = self.default_spyce_type()
        if self.spyce_type is None:
            self.spyce_type = 'bytes'
        if self.spyce_type not in {'text', 'bytes'}:
            raise FlavorError(f'{type(self).__name__}: unknown spyce type {self.spyce_type!r}')

    @abc.abstractmethod
    def content(self):
        raise NotImplemented()

    def __repr__(self):
        return f'{type(self).__name__}({self.name!r}, {self.spyce_type!r})'


class PathFlavor(Flavor):
    def __init__(self, path, name=None, spyce_type=None):
        self.path = Path(path)
        self._check_path()
        super().__init__(name=name, spyce_type=spyce_type)

    def _default_name(self):
        return self.path.name

    @classmethod
    def parse_conf(cls, base_dir, filename, data):
        result = super().parse_conf(base_dir, filename, data)
        path = cls._parse_key(data, 'path', (str, Path))
        path = Path(path)
        if not path.is_absolute():
            path = Path(base_dir) / path
        result['path'] = path
        return result

    def conf(self):
        result = super().conf()
        result['path'] = str(self.path)
        return result

    def _check_path(self):
        if self.path is None:
            raise FlavorError(f'{type(self).__name__}: path not set')

    def __repr__(self):
        return f'{type(self).__name__}({self.path!r}, {self.name!r}, {self.spyce_type!r})'


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
    def default_spyce_type(cls):
        return 'text'


class DirFlavor(PathFlavor):
    def __init__(self, path, arcname=None, name=None, spyce_type=None):
        super().__init__(path, name=name, spyce_type=spyce_type)
        self.arcname = arcname

    @classmethod
    def flavor(cls):
        return 'dir'

    def _check_path(self):
        path = self.path
        if not path.is_dir():
            raise FlavorError(f'{type(self).__name__}: {path} is not a directory')
        super()._check_path()

    def content(self):
        import gzip
        import io
        import tarfile
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w') as tf:
            tf.add(self.path, arcname=self.arcname)
        return gzip.compress(bf.getvalue(), mtime=0.0)  # make compressed data reproducible!

    @classmethod
    def parse_conf(cls, base_dir, filename, data):
        result = super().parse_conf(base_dir, filename, data)
        arcname = data.get('arcname', None)
        result['arcname'] = arcname
        return result
        
    def conf(self):
        result = super().conf()
        result['arcname'] = self.arcname
        return result


class UrlFlavor(Flavor):
    def __init__(self, url, name=None, spyce_type=None):
        self.url = url
        super().__init__(name=name, spyce_type=spyce_type)
        self._check_url()

    def _default_name(self):
        return Path(urlparse(self.url).path).name

    @classmethod
    def flavor(cls):
        return 'url'

    @classmethod
    def parse_conf(cls, base_dir, filename, data):
        result = super().parse_conf(base_dir, filename, data)
        url = cls._parse_key(data, 'url', (str,))
        result['url'] = url
        return result

    def conf(self):
        result = super().conf()
        result['url'] = str(self.url)
        return result

    def _check_url(self):
        if self.url is None:
            raise rError(f'{type(self).__name__}: url not set')

    def content(self):
        import urllib.request
        with urllib.request.urlopen(self.url) as response:
            return response.read()

    def __repr__(self):
        return f'{type(self).__name__}({self.url!r}, {self.name!r}, {self.spyce_type!r})'


class ApiFlavor(Flavor):
    def __init__(self, implementation, name=None, spyce_type=None):
        self.implementation = implementation
        super().__init__(name=name, spyce_type=spyce_type)
        self._check_implementation()

    def _default_name(self):
        return 'spyce'

    @classmethod
    def default_spyce_type(cls):
        return 'text'

    @classmethod
    def parse_conf(cls, base_dir, filename, data):
        result = super().parse_conf(base_dir, filename, data)
        implementation = data.get('implementation', api.default_api_implementation())
        if implementation not in api.get_api_implementations():
            raise FlavorParseError(f'unknown api implementation {implementation!r}')
        result['implementation'] = implementation
        return result

    def conf(self):
        result = super().conf()
        result['implementation'] = str(self.implementation)
        return result

    @classmethod
    def flavor(cls):
        return 'api'

    def _check_implementation(self):
        if self.implementation is None:
            self.implementation = api.default_api_implementation()
        elif self.implementation not in api.get_api_implementations():
            raise FlavorError(f'{type(self).__name__}: api implementation {self.implementation} is not a directory')

    def content(self):
        return api.get_api(self.name, self.implementation)

    def __repr__(self):
        return f'{type(self).__name__}({self.implementation!r}, {self.name!r}, {self.spyce_type!r})'
