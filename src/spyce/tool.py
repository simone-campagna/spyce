#!/usr/bin/env python3

import argparse
import fnmatch
import inspect
import sys

from pathlib import Path

import yaml

from .log import (
    configure_logging,
    set_trace,
    trace_errors,
)
from .spyce import (
    set_max_line_length,
    SpyceFilter,
    SpycyFile,
    DEFAULT_BACKUP_FORMAT,
)
from .flavor import (
    ApiFlavor,
    FileFlavor,
    SourceFlavor,
    DirFlavor,
    UrlFlavor,
)
from .version import get_version
from .wok import Wok
from . import api


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


def add_filters_argument(parser, required=False):
    parser.add_argument(
        '-f', '--filter',
        dest='filters',
        metavar='FLT',
        type=SpyceFilter.build,
        action='append',
        default=[],
        required=required,
        help="""\
add spyce filter spyces; the format can contain 'name', ':type' and '^flavor',
where all components are optional. The name, section, type and flavor values are patterns,
eventually preceded by ~ to reverse selection. For instance: '^api', '^url *wg*'""")


def add_name_argument(parser, required=False):
    parser.add_argument(
        '-n', '--name',
        required=required,
        help='spyce name')


# REM def fn_spyce_list(input_file, filters, show_lines=False, show_conf=False, show_header=True):
# REM     spycy_file = SpycyFile(input_file)
# REM     table = []
# REM     spyces = []
# REM     names = spycy_file.filter(filters)
# REM     for name in names:
# REM         spyce = spycy_file.get_spyce_jar(name)
# REM         num_chars = len(spyce.get_text())
# REM         flavor = spyce.flavor or ''
# REM         table.append((spyce.name, spyce.spyce_type, flavor, f'{spyce.start+1}:{spyce.end+1}', str(num_chars)))
# REM         spyces.append(spyce)
# REM     if table:
# REM         if show_header:
# REM             names.insert(0, None)
# REM             table.insert(0, ['name', 'type', 'flavor', 'lines', 'size'])
# REM         mlen = [max(len(row[c]) for row in table) for c in range(len(table[0]))]
# REM         if show_header:
# REM             names.insert(1, None)
# REM             table.insert(1, ['-' * ml for ml in mlen])
# REM 
# REM         fmt = ' '.join(f'{{:{ml}s}}' for ml in mlen)
# REM         for name, row in zip(names, table):
# REM             print(fmt.format(*row))
# REM             if name is not None:
# REM                 spyce = spycy_file[name]
# REM                 if show_conf:
# REM                     for line in yaml.dump(spyce.conf).split('\n'):
# REM                         print('  ' + line)
# REM                 if show_lines:
# REM                     spyce_jar = spycy_file.get_spyce_jar(name)
# REM                     for ln, line in enumerate(spyce.get_lines()):
# REM                         line_no = ln + spyce_jar.start + 1
# REM                         print(f'  {line_no:<6d} {line.rstrip()}')
# REM 


class FlavorType:
    class FlavorBuilder:
        def __init__(self, flavor_class, value):
            self.flavor_class = flavor_class
            self.value = value

        def __call__(self, section, name, spyce_type):
            obj = self.flavor_class(self.value, section=section, name=name, spyce_type=spyce_type)
            return obj

        def __str__(self):
            return self.value

        def __repr__(self):
            return self.value
            #return f'{type(self).__name__}({self.flavor_class.__name__}, {self.value})'

    __registry__ = {}

    def __init__(self, flavor_class):
        self.flavor_class = flavor_class

    def __call__(self, value):
        key = (self.flavor_class, value)
        if key not in self.__registry__:
            self.__registry__[key] = self.__class__.FlavorBuilder(*key)
        return self.__registry__[key]


def fn_spyce_mix(input_file, output_file, backup, backup_format, max_line_length):
    if max_line_length is not None:
        set_max_line_length(max_line_length)

    wok = Wok.import_spycy_file(input_file)
    wok.mix(target_path=output_file)


def fn_spyce_extract(input_file, output_file, name):
    spycy_file = SpycyFile(input_file)
    spyce_jar = spycy_file[name]
    spyce = spyce_jar.spyce
    spyce.write_file(output_file)


def fn_spyce_del(input_file, output_file, filters, backup, backup_format):
    spycy_file = SpycyFile(input_file)
    names = spycy_file.filter(filters)
    with spycy_file.refactor(output_file, backup=backup, backup_format=backup_format):
        for name in names:
            del spycy_file[name]


def fn_spyce_status(input_file, filters=None, info_level=0):
    wok = Wok.import_spycy_file(input_file)
    wok.status(filters=filters, info_level=info_level)


def fn_spyce_diff(input_file, filters=None, info_level=0):
    wok = Wok.import_spycy_file(input_file)
    wok.diff(filters=filters, info_level=info_level)


def fn_spyce_list(input_file, show_header, show_lines, show_conf, filters):
    wok = Wok.import_spycy_file(input_file)
    wok.list_spyces(
        show_header=show_header,
        show_lines=show_lines,
        show_conf=show_conf,
        filters=filters)


def add_common_arguments(parser):
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


def add_list_arguments(parser):
    parser.add_argument(
        '-c', '--conf',
        dest='show_conf',
        action='store_true',
        default=False,
        help='show spyce conf')
    parser.add_argument(
        '-l', '--lines',
        dest='show_lines',
        action='store_true',
        default=False,
        help='show spyce lines')
    parser.add_argument(
        '-H', '--no-header',
        dest='show_header',
        action='store_false',
        default=True,
        help='do not show table header lines')


def build_parser(name, *, subparsers=None, function=None, **kwargs):
    if subparsers:
        parser = subparsers.add_parser(name, **kwargs)
    else:
        parser = argparse.ArgumentParser(name, **kwargs)
        add_common_arguments(parser)
    if function is None:
        function = parser.print_help
    parser.set_defaults(function=function)
    return parser


class InputFile:
    def __init__(self, file_type, file_name):
        self.file_type = file_type
        self.file_name = Path(file_name)


class InputFileType:
    def __init__(self, file_type):
        self.file_type = file_type

    def __call__(self, file_name):
        return InputFile(file_type=self.file_type, file_name=file_name)


def build_spyce_parser(subparsers=None):
    parser = build_parser(
        name='spyce',  subparsers=subparsers,
        description=f'''\
spyce {get_version()} - add spyces to python source files
'''
    )
    subparsers = parser.add_subparsers()

    ### list
    list_parser = build_parser(
        'list', subparsers=subparsers,
        function=fn_spyce_list,
        description='list spyces in python source file')
    add_input_argument(list_parser)
    add_filters_argument(list_parser)
    add_list_arguments(list_parser)

    ### mix
    mix_parser = build_parser(
        'mix', subparsers=subparsers,
        function=fn_spyce_mix,
        description='mix spyces in python source file')
    add_input_argument(mix_parser)
    add_output_argument(mix_parser)
    add_backup_argument(mix_parser)
    add_filters_argument(mix_parser)
    mix_parser.add_argument(
        '-m', '--max-line-length',
        default=None,
        help='set max data line length')

    ### extract
    extract_parser = build_parser(
        'extract', subparsers=subparsers,
        function=fn_spyce_extract,
        description='extract a spyce object from python source file')
    add_input_argument(extract_parser)
    add_output_argument(extract_parser, optional=False)
    add_name_argument(extract_parser)

    ### del
    del_parser = build_parser(
        'del', subparsers=subparsers,
        function=fn_spyce_del,
        description='remove spyces from python source file')
    add_input_argument(del_parser)
    add_output_argument(del_parser)
    add_backup_argument(del_parser)
    add_filters_argument(del_parser, required=True)

    ### status:
    status_parser = build_parser(
        'status', subparsers=subparsers,
        function=fn_spyce_status,
        description='show the project status')
    add_input_argument(status_parser)
    add_filters_argument(status_parser)

    ### diff:
    diff_parser = build_parser(
        'diff', subparsers=subparsers,
        function=fn_spyce_diff,
        description='show diffs')
    add_input_argument(diff_parser)
    add_filters_argument(diff_parser)

    return parser


def runner(parser):
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


def main_spyce():
    parser = build_spyce_parser()
    runner(parser)


def main_wok():
    parser = build_wok_parser()
    runner(parser)
