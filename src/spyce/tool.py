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
from .spyce import (
    Curry,
    DEFAULT_BACKUP_FORMAT,
)
from .farms import (
    ApiSpyceFarm,
    FileSpyceFarm,
    SourceSpyceFarm,
    DirSpyceFarm,
    UrlSpyceFarm,
)
from .version import get_version


def add_input_argument(parser):
    parser.add_argument(
        'input_file',
        metavar='input',
        help='input python file')


def add_output_argument(parser, optional=True):
    kwargs = {}
    if optional:
        kwargs['nargs'] = '?'
    parser.add_argument(
        'output_file',
        metavar='output',
        help='do not change input file in-place, write output file instead',
        **kwargs)


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


def filter_pattern(value):
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
        type=filter_pattern,
        action='append',
        default=[],
        required=required,
        help="add pattern to filter spyces, e.g. 'source/api', '~data/x.tgz', ':bytes'")


def _filtered_keys(curry, key, filters):
    if key is not None:
        if key in curry:
            return [key]
        else:
            raise KeyError(key)

    mp = {}
    for key, spyce in curry.items():
        fq_key = spyce.fq_key()
        mp[fq_key] = key
    fq_keys = list(mp)
    for filt in filters:
        fq_keys = filt(fq_keys)
    return [mp[fq_key] for fq_key in fq_keys]


def add_key_argument(parser, required=False):
    parser.add_argument(
        '-k', '--key',
        required=required,
        help='spyce key (section/name)')


def add_key_filters_argument(parser, required=False):
    kf_group = parser.add_argument_group('key/filter')
    kf_mgrp = kf_group.add_mutually_exclusive_group(required=required)
    add_key_argument(kf_mgrp, required=False)
    add_filters_argument(kf_mgrp, required=False)


def main_list(input_file, key, filters, show_lines=False, show_header=True):
    curry = Curry(input_file)
    table = []
    spyces = []
    keys = _filtered_keys(curry, key, filters)
    for key in keys:
        spyce = curry[key]
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
                spyce = curry[key]
                for ln, line in enumerate(spyce.get_lines(headers=True)):
                    line_no = ln + spyce.start + 1
                    print(f'  {line_no:<6d} {line.rstrip()}')



class SpyceFarmType:
    class SpyceFarmBuilder:
        def __init__(self, spyce_farm_class, value):
            self.spyce_farm_class = spyce_farm_class
            self.value = value

        def __call__(self, section, name, spyce_type):
            obj = self.spyce_farm_class(self.value, section=section, name=name, spyce_type=spyce_type)
            return obj

        def __str__(self):
            return self.value

        def __repr__(self):
            return self.value
            #return f'{type(self).__name__}({self.spyce_farm_class.__name__}, {self.value})'

    __registry__ = {}

    def __init__(self, spyce_farm_class):
        self.spyce_farm_class = spyce_farm_class

    def __call__(self, value):
        key = (self.spyce_farm_class, value)
        if key not in self.__registry__:
            self.__registry__[key] = self.__class__.SpyceFarmBuilder(*key)
        return self.__registry__[key]


def main_add(input_file, output_file, spyce_farm_builder, section, name, spyce_type, backup, backup_format):
    curry = Curry(input_file)
    with curry.refactor(output_file, backup=backup, backup_format=backup_format):
        spyce_farm =spyce_farm_builder(
            section=section,
            name=name,
            spyce_type=spyce_type)
        curry[name] = spyce_farm


def main_extract(input_file, output_file, key):
    curry = Curry(input_file)
    spyce = curry[key]
    spyce.write_file(output_file)


def main_del(input_file, output_file, key, filters, backup, backup_format):
    curry = Curry(input_file)
    keys = _filtered_keys(curry, key, filters)
    with curry.refactor(output_file, backup=backup, backup_format=backup_format):
        for key in keys:
            del curry[key]


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
    add_key_filters_argument(list_parser)
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
        '-s', '--section',
        default=None,
        help='spyce section')

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

    c_group = add_parser.add_argument_group('spyce')
    c_mgrp = add_parser.add_mutually_exclusive_group(required=True)
    c_kwargs = {'dest': 'spyce_farm_builder'}
    c_mgrp.add_argument(
        '-a', '--api',
        choices=[SpyceFarmType(ApiSpyceFarm)('inline'),
                 SpyceFarmType(ApiSpyceFarm)('tmpfile'),
                 SpyceFarmType(ApiSpyceFarm)('memory')],
        type=SpyceFarmType(ApiSpyceFarm),
        nargs='?', const=SpyceFarmType(ApiSpyceFarm)('memory'),
        **c_kwargs)
    c_mgrp.add_argument(
        '-p', '--py-source',
        type=SpyceFarmType(SourceSpyceFarm),
        **c_kwargs)
    c_mgrp.add_argument(
        '-f', '--file',
        type=SpyceFarmType(FileSpyceFarm),
        **c_kwargs)
    c_mgrp.add_argument(
        '-d', '--dir',
        type=SpyceFarmType(DirSpyceFarm),
        **c_kwargs)
    c_mgrp.add_argument(
        '-u', '--url',
        type=SpyceFarmType(UrlSpyceFarm),
        **c_kwargs)

    ### extract
    extract_parser = subparsers.add_parser(
        'extract',
        description='extract a spyce object from python source file')
    extract_parser.set_defaults(function=main_extract)
    add_input_argument(extract_parser)
    add_output_argument(extract_parser, optional=False)
    add_key_argument(extract_parser)

    ### del
    del_parser = subparsers.add_parser(
        'del',
        description='remove spyces from python source file')
    del_parser.set_defaults(function=main_del)
    add_input_argument(del_parser)
    add_output_argument(del_parser)
    add_backup_argument(del_parser)
    add_key_filters_argument(del_parser, required=True)


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
