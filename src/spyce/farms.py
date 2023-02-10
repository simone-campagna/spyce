from pathlib import Path

from .spyce import Spyce, SpyceFarm, default_spyce_type
from . import api


__all__ = [
    'ApiSpyceFarm',
    'SourceSpyceFarm',
    'FileSpyceFarm',
    'DirSpyceFarm',
    'UrlSpyceFarm',
]


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
