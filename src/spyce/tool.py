#!/usr/bin/env python3

import argparse
import fnmatch
import inspect
import sys

from pathlib import Path

from . import api
from .log import (
    configure_logging,
    set_trace,
    trace_errors,
)
from .dish import Dish, DEFAULT_BACKUP_FORMAT
from .dose import (
    ApiDose,
    FileDose,
    DirDose,
    UrlDose,
)
from .version import get_version


def add_input_argument(parser):
    parser.add_argument(
        'input_file',
        metavar='input',
        help='input python file')


def add_output_argument(parser):
    parser.add_argument(
        'output_file',
        metavar='output',
        nargs='?',
        help='do not change input file in-place, write output file instead')


def add_backup_argument(parser):
    parser.add_argument(
        '-b', '--backup',
        default=False,
        action='store_true',
        help="save backup after changes")
    parser.add_argument(
        '-B', '--backup-format',
        default=DEFAULT_BACKUP_FORMAT,
        help=f'set backup format (default: {DEFAULT_BACKUP_FORMAT!r}')


def type_pattern(value):
    negated = False
    if value.startswith('~'):
        value = value[1:]
        negated = True
    lst = value.split('/', 1)
    if len(lst) == 1:
        section = '*'
        rem = value
    else:
        section, rem = lst
    lst = rem.split(':', 1)
    if len(lst) == 1:
        name = rem
        spyce_type = '*'
    else:
        name, spyce_type = lst
    fq_key = f'{section or "*"}/{name or "*"}:{spyce_type or "*"}'
    if negated:
        return lambda lst: [i for i in lst if not fnmatch.fnmatch(i, fq_key)]
    else:
        return lambda lst: fnmatch.filter(lst, fq_key)


def add_filters_argument(parser, required=False):
    parser.add_argument(
        '-f', '--filter',
        dest='filters',
        metavar='[~][section/][name][:type]',
        type=type_pattern,
        action='append',
        default=[],
        required=required,
        help="add pattern to filter spyces, e.g. 'source/api', '~data/x.tgz', ':bytes'")


def _filtered_keys(dish, filters):
    mp = {}
    for key, spyce in dish.items():
        fq_key = spyce.fq_key()
        mp[fq_key] = key
    fq_keys = list(mp)
    for filt in filters:
        fq_keys = filt(fq_keys)
    return [mp[fq_key] for fq_key in fq_keys]


def main_list(input_file, filters, show_lines=False, show_header=True):
    dish = Dish(input_file)
    table = []
    spyces = []
    keys = _filtered_keys(dish, filters)
    for key in keys:
        spyce = dish[key]
        num_chars = len(spyce.get_text(headers=True))
        table.append((spyce.section, spyce.name, spyce.spyce_type, f'{spyce.start+1}:{spyce.end+1}', str(num_chars)))
        spyces.append(spyce)
    if table:
        if show_header:
            keys.insert(0, None)
            table.insert(0, ['section', 'name', 'type', 'lines', 'size'])
        mlen = [max(len(row[c]) for row in table) for c in range(len(table[0]))]
        if show_header:
            keys.insert(1, None)
            table.insert(1, ['-' * ml for ml in mlen])

        fmt = ' '.join(f'{{:{ml}s}}' for ml in mlen)
        for key, row in zip(keys, table):
            print(fmt.format(*row))
            if show_lines and key is not None:
                spyce = dish[key]
                for ln, line in enumerate(spyce.get_lines(headers=True)):
                    line_no = ln + spyce.start + 1
                    print(f'  {line_no:<6d} {line.rstrip()}')


class DoseBuilder:
    def build_dose(self, name, spyce_type):
        raise NotImplementedError()

    @classmethod
    def _check_spyce_type(cls, spyce_type):
        if spyce_type not in {None, 'source', 'data'}:
            raise ValueError(spyce_type)


class ApiDoseBuilder(DoseBuilder):
    def __init__(self, name=None, api_implementation=None):
        if name is not None and not api.is_valid_modulename(name):
            raise ValueError(name)
        self.name = name
        self._implementation = api.default_api_implementation()

    @property
    def implementation(self):
        return self._implementation

    @implementation.setter
    def implementation(self, value):
        if value not in api.get_api_implementations():
            raise ValueError(value)
        self._implementation = value

    def build_dose(self, name, spyce_type):
        self._check_spyce_type(spyce_type)
        return ApiDose(
            implementation=self._implementation,
            section='source', name=name, spyce_type=spyce_type)


class SourceDoseBuilder(DoseBuilder):
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError(path)

    def build_dose(self, name, spyce_type):
        self._check_spyce_type(spyce_type)
        return FileDose(
            self.path,
            section='source', name=name, spyce_type=spyce_type)


class FileDoseBuilder(DoseBuilder):
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError(path)

    def build_dose(self, name, spyce_type):
        self._check_spyce_type(spyce_type)
        return FileDose(
            self.path,
            section='data', name=name, spyce_type=spyce_type)


class DirDoseBuilder(DoseBuilder):
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_dir():
            raise ValueError(path)

    def build_dose(self, name, spyce_type):
        self._check_spyce_type(spyce_type)
        return DirDose(
            self.path,
            section='data', name=name, spyce_type=spyce_type)


class UrlDoseBuilder(DoseBuilder):
    def __init__(self, url):
        self.url = url

    def build_dose(self, name, spyce_type):
        self._check_spyce_type(spyce_type)
        return UrlDose(
            self.url,
            section='data', name=name, spyce_type=spyce_type)


def main_add(input_file, output_file, dose_builder, api_implementation, name, spyce_type, backup, backup_format):
    if isinstance(dose_builder, str):
        dose_builder = ApiDoseBuilder(dose_builder)
    if api_implementation is not None:
        if not isinstance(dose_builder, ApiDoseBuilder):
            raise RuntimeError(f'-A/--api-implementation applies only to -a/--api')
        dose_builder.implementation = api_implementation
    dish = Dish(input_file)
    with dish.refactor(output_file, backup=backup, backup_format=backup_format):
        dose = dose_builder.build_dose(
            name=name,
            spyce_type=spyce_type)
        dish[name] = dose


def main_del(input_file, output_file, filters, backup, backup_format):
    dish = Dish(input_file)
    keys = _filtered_keys(dish, filters)
    with dish.refactor(output_file, backup=backup, backup_format=backup_format):
        for key in keys:
            del dish[key]


def type_api():
    return (ApiDose, None)


def type_source(value):
    return (SourceDose, value)


def type_file(value):
    return (FileDose, value)


def type_dir(value):
    return (DirDose, value)


def main():
    parser = argparse.ArgumentParser(
        description=f'''\
spyce {get_version()} - add spyces to python source files
''',
    )
    parser.add_argument(
        '--trace',
        action='store_true',
        default=False,
        help=argparse.SUPPRESS)
    v_mgrp = parser.add_mutually_exclusive_group()
    v_kwargs = {'dest': 'verbose_level', 'default': 1}
    v_mgrp.add_argument(
        '-v', '--verbose',
        action='count',
        help='increase verbose level',
        **v_kwargs)
    parser.add_argument(
        '-q', '--quiet',
        action='store_const',
        const=0,
        help='suppress warnings',
        **v_kwargs)
    subparsers = parser.add_subparsers()

    ### list
    list_parser = subparsers.add_parser(
        'list',
        description='list spyces in python source file')
    list_parser.set_defaults(function=main_list)
    add_input_argument(list_parser)
    add_filters_argument(list_parser)
    list_parser.add_argument(
        '-l', '--lines',
        dest='show_lines',
        action='store_true',
        default=False,
        help='show spyce')
    list_parser.add_argument(
        '-H', '--no-header',
        dest='show_header',
        action='store_false',
        default=True,
        help='do not show table header lines')

    ### add
    add_parser = subparsers.add_parser(
        'add',
        description='add or replace spyces in python source file')
    add_parser.set_defaults(function=main_add)
    add_input_argument(add_parser)
    add_output_argument(add_parser)
    add_backup_argument(add_parser)

    add_parser.add_argument(
        '-n', '--name',
        default=None,
        help='spyce name')

    add_parser.add_argument(
        '-t', '--type',
        dest='spyce_type',
        choices=['text', 'bytes'],
        default=None,
        help="spyce type (default: 'text' for source spyces, else 'bytes')")

    add_parser.add_argument(
        '-A', '--api-implementation',
        choices=['inline', 'tmpfile', 'memory'],
        default=None,
        help='(advanced) set api implementation')

    c_group = add_parser.add_argument_group('dose')
    c_mgrp = add_parser.add_mutually_exclusive_group(required=True)
    c_kwargs = {'dest': 'dose_builder'}
    c_mgrp.add_argument(
        '-a', '--api',
        action='store_const', const=ApiDoseBuilder(),
        **c_kwargs)
    c_mgrp.add_argument(
        '-s', '--source',
        type=SourceDoseBuilder,
        **c_kwargs)
    c_mgrp.add_argument(
        '-f', '--file',
        type=FileDoseBuilder,
        **c_kwargs)
    c_mgrp.add_argument(
        '-d', '--dir',
        type=DirDoseBuilder,
        **c_kwargs)
    c_mgrp.add_argument(
        '-u', '--url',
        type=UrlDoseBuilder,
        **c_kwargs)

    ### del
    del_parser = subparsers.add_parser(
        'del',
        description='remove spyces from python source file')
    del_parser.set_defaults(function=main_del)
    add_input_argument(del_parser)
    add_output_argument(del_parser)
    add_backup_argument(del_parser)
    add_filters_argument(del_parser, required=True)


    ### parsing:
    ns = parser.parse_args()
    set_trace(ns.trace)
    configure_logging(ns.verbose_level)

    ns_vars = vars(ns)

    function = ns.function
    f_args = {}
    for p_name, p_obj in inspect.signature(function).parameters.items():
        if p_name in ns_vars:
            f_args[p_name] = ns_vars[p_name]
        elif p_obj.default is p_obj.empty:
            raise RuntimeError(f'internal error: {function.__name__}: missing argument {p_name}')
    with trace_errors(function.__name__, on_error='exit'):
        result = function(**f_args)
    if not result:
        sys.exit(0)
    sys.exit(1)
