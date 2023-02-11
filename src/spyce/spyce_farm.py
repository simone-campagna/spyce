import abc
from pathlib import Path

from .spyce import Spyce, default_spyce_type
from . import api


__all__ = [
    'SpyceFarm',
    'ApiSpyceFarm',
    'SourceSpyceFarm',
    'FileSpyceFarm',
    'DirSpyceFarm',
    'UrlSpyceFarm',
]


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
        super().__init__(section=section, name=name, spyce_type=spyce_type)

    def _check_path(self):
        if self.path is None:
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
        super()._check_path()

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
        import io
        import tarfile
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w|gz') as tf:
            tf.add(self.path)
        return bf.getvalue()


class UrlSpyceFarm(SpyceFarm):
    def __init__(self, url, section=None, name=None, spyce_type=None):
        self.url = url
        super().__init__(section=section, name=name, spyce_type=spyce_type)
        self._check_url()

    def _default_name(self):
        if self.url:
            import urllib.parse
            parsed_url = urllib.parse.urlparse(self.url)
            return Path(parsed_url.path).name

    def _check_url(self):
        if self.url is None:
            raise RuntimeError(f'{type(self).__name__}: url not set')

    def content(self):
        import urllib.request
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
