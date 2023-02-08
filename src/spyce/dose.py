import abc
import io
import tarfile

from pathlib import Path

from .api import get_api
from .error import SpiceError


__all__ = [
    'default_spice_type',
    'Dose',
    'ApiDose',
    'FileDose',
    'DirDose',
]


def default_spice_type(section, name, spice_type):
    if spice_type is None:
        spice_type = 'text' if section == 'source' else 'bytes'
    return spice_type


class Dose(abc.ABC):
    def __init__(self, section, name, spice_type=None):
        self.section = section
        self.name = name
        self.spice_type = default_spice_type(section, name, spice_type)

    @abc.abstractmethod
    def content(self):
        raise NotImplementedError()


class ApiDose(Dose):
    def content(self):
        return get_api()


class PathDose(Dose):
    def __init__(self, path, section, name, spice_type=None):
        super().__init__(section, name, spice_type=spice_type)
        self.path = Path(path)
        self.check()

    def check(self):
        pass


class FileDose(PathDose):
    def check(self):
        if not self.path.is_file():
            raise SpiceError(f'{self.path} is not a file')

    def content(self):
        mode = 'r'
        if self.spice_type == 'text':
            mode += 'b'
        with open(self.path, mode) as fh:
            return fh.read()


class DirDose(PathDose):
    def check(self):
        if not self.path.is_dir():
            raise SpiceError(f'{self.path} is not a dir')
        if self.spice_type != 'bytes':
            raise SpiceError(f"dir spice type must be 'bytes'")

    def content(self):
        bf = io.BytesIO()
        with tarfile.open(fileobj=bf, mode='w|gz') as tf:
            tf.add(self.path)
        return bf.getvalue()


class ApiDose(Dose):
    def content(self):
        return get_api()
