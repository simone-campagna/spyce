__all__ = [
    'Spyce',
    'TextSpyce',
    'BytesSpyce',
]

import abc
import base64
import inspect

from pathlib import Path

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

    def __init__(self, dish, section, name, start, end, args=None):
        self.dish = dish
        self.section = section
        self.name = name
        self.key = self.spyce_key(section, name)
        self.start = start
        self.end = end
        self.args = args

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
        return f'{type(self).__name__}({self.dish!r}, {self.section!r}, {self.name!r}, {self.start!r}, {self.end!r}, {self.args!r})'


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
