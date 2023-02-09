import abc
import io
import tarfile
import urllib.parse
import urllib.request

from pathlib import Path

from .api import get_api
from .error import SpyceError


__all__ = [
    'default_spyce_type',
    'Dose',
    'ApiDose',
    'FileDose',
    'DirDose',
    'UrlDose',
]


def default_spyce_type(section, name, spyce_type):
    if spyce_type is None:
        spyce_type = 'text' if section == 'source' else 'bytes'
    return spyce_type


class Dose(abc.ABC):
    def __init__(self, section, name, spyce_type=None):
        self.section = section
        if not isinstance(name, str):
            raise TypeError(name)
        invalid_chars = set('/:').intersection(name)
        if invalid_chars:
            chs = ''.join(invalid_chars)
            raise SpyceError(f'invalid spyce name {name} - the following chars are not allowed: {chs!r}')
        self.name = name
        self.spyce_type = default_spyce_type(section, name, spyce_type)
        self.check()

    def check(self):
        pass

    @abc.abstractmethod
    def content(self):
        raise NotImplementedError()


class PathDose(Dose):
    def __init__(self, path, section, name=None, spyce_type=None):
        path = Path(path)
        if name is None:
            name = path.name
        self.path = path
        super().__init__(section, name, spyce_type=spyce_type)


class FileDose(PathDose):
    def check(self):
        super().check()
        if not self.path.is_file():
            raise SpyceError(f'{self.path} is not a file')

    def content(self):
        mode = 'r'
        if self.spyce_type == 'bytes':
            mode += 'b'
        with open(self.path, mode) as fh:
            return fh.read()


class DirDose(PathDose):
    def check(self):
        super().check()
        if not self.path.is_dir():
            raise SpyceError(f'{self.path} is not a dir')
        if self.spyce_type != 'bytes':
            raise SpyceError(f"dir spyce type must be 'bytes'")

    def content(self):
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w|gz') as tf:
            tf.add(self.path)
        return bf.getvalue()


class UrlDose(Dose):
    def __init__(self, url, section, name=None, spyce_type=None):
        self.url = url
        self.parsed_url = urllib.parse.urlparse(self.url)
        if name is None:
            name = Path(self.parsed_url.path).name
        super().__init__(section, name, spyce_type=spyce_type)

    def check(self):
        super().check()

    def content(self):
        with urllib.request.urlopen(self.url) as response:
            return response.read()


class ApiDose(Dose):
    def __init__(self, section, name=None, spyce_type=None):
        if name is None:
            name = 'spyce-api'
        super().__init__(section, name, spyce_type=spyce_type)

    def content(self):
        return get_api()


class ObfuscatedApiDose(Dose):
    def __init__(self, section, name=None, spyce_type=None):
        if name is None:
            name = 'spyce-api'
        super().__init__(section, name, spyce_type=spyce_type)

    def content(self):
        return get_obfuscated_api()
