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
    get_max_line_length,
    set_max_line_length,
    SpyceFilter,
    SpycyFile,
)
from .flavor import (
    ApiFlavor,
    FileFlavor,
    SourceFlavor,
    DirFlavor,
    UrlFlavor,
)
from .version import get_version
from .wok import (
    Before, After, Begin, End,
    Wok,
    DEFAULT_BACKUP_FORMAT,
)
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
where all components are optional. The name, type and flavor values are patterns,
eventually preceded by ~ to reverse selection. For instance: '^api', '^url *wg*'""")


def add_name_argument(parser, required=False):
    parser.add_argument(
        '-n', '--name',
        required=required,
        help='spyce name')


class FlavorType:
    class FlavorBuilder:
        def __init__(self, flavor_class, value):
            self.flavor_class = flavor_class
            self.value = value

        def __call__(self, name, spyce_type=None):
            obj = self.flavor_class(self.value, name=name, spyce_type=spyce_type)
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


def fn_spyce_mix(input_file, output_file, max_line_length):
    if max_line_length is not None:
        set_max_line_length(max_line_length)

    wok = Wok(input_file)
    wok.mix(output_file=output_file)


def fn_spyce_extract(input_file, output_file, name):
    spycy_file = SpycyFile(input_file)
    spyce_jar = spycy_file[name]
    spyce = spyce_jar.spyce
    spyce.write_file(output_file)


def fn_spyce_set(input_file, output_file, flavor_builder, name, spyce_type, max_line_length, replace, position, empty=False):
    if max_line_length is not None:
        set_max_line_length(max_line_length)
    flavor = flavor_builder(
        name=name,
        spyce_type=spyce_type)
    wok = Wok(input_file)
    wok.set_flavor(flavor, output_file=output_file,
                   replace=replace, position=position, empty=empty)


def fn_spyce_del(input_file, output_file, filters, content_only=False):
    wok = Wok(input_file)
    wok.del_spyces(output_file=output_file, filters=filters, content_only=content_only)


def fn_spyce_status(input_file, filters=None, info_level=0):
    wok = Wok(input_file)
    wok.status(filters=filters, info_level=info_level)


def fn_spyce_diff(input_file, filters=None, binary=True, info_level=0):
    wok = Wok(input_file)
    wok.diff(filters=filters, info_level=info_level, binary=binary)


def fn_spyce_list(input_file, show_header, filters):
    wok = Wok(input_file)
    wok.list_spyces(
        show_header=show_header,
        filters=filters)


def fn_spyce_show(input_file, show_target, filters):
    wok = Wok(input_file)
    if show_target == 'lines':
        function = wok.show_spyce_lines
    elif show_target == 'conf':
        function = wok.show_spyce_conf
    else:
        return
    function(filters=filters)


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

    list_parser.add_argument(
        '-H', '--no-header',
        dest='show_header',
        action='store_false',
        default=True,
        help='do not show table header lines')

    ### show
    show_parser = build_parser(
        'show', subparsers=subparsers,
        function=fn_spyce_show,
        description='show spyces in python source file')
    add_input_argument(show_parser)
    add_filters_argument(show_parser)

    target_mgrp = show_parser.add_mutually_exclusive_group()
    target_kwargs = {'dest': 'show_target', 'default': 'conf'}
    target_mgrp.add_argument(
        '-c', '--conf',
        action='store_const', const='conf',
        help='show spyce conf',
        **target_kwargs)
    target_mgrp.add_argument(
        '-l', '--lines',
        action='store_const', const='lines',
        help='show spyce lines',
        **target_kwargs)

    ### mix
    mix_parser = build_parser(
        'mix', subparsers=subparsers,
        function=fn_spyce_mix,
        description='mix spyces in python source file')
    add_input_argument(mix_parser)
    add_output_argument(mix_parser)
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

    ### add
    set_parser = build_parser(
        'set', subparsers=subparsers,
        function=fn_spyce_set,
        description='set spyces in python source file')
    add_input_argument(set_parser)
    add_output_argument(set_parser)

    set_parser.add_argument(
        '-n', '--name',
        default=None,
        help='spyce name')

    set_parser.add_argument(
        '-m', '--max-line-length',
        metavar='LEN',
        default=None,
        help=f'set max data line length (default: {get_max_line_length()})')

    set_parser.add_argument(
        '-t', '--type',
        dest='spyce_type',
        choices=['text', 'bytes'],
        default=None,
        help="spyce type (default: 'text' for source spyces, else 'bytes')")

    pos_group = set_parser.add_argument_group('position')
    pos_kwargs = {'dest': 'position', 'default': None}
    pos_group.add_argument(
        '-B', '--before',
        type=Before.build,
        help='add before spyces',
        **pos_kwargs)
    pos_group.add_argument(
        '-A', '--after',
        type=After.build,
        help='add after spyces',
        **pos_kwargs)
    pos_group.add_argument(
        '-b', '--begin',
        action='store_const', const=Begin(),
        help='add at the beginning of the file',
        **pos_kwargs)
    pos_group.add_argument(
        '-e', '--end',
        action='store_const', const=End(),
        help='add at the end of the file',
        **pos_kwargs)

    set_parser.add_argument(
        '-E', '--empty',
        action='store_true', default=False,
        help='add empty spyce (no contents)')

    c_group = set_parser.add_argument_group('spyce')
    c_mgrp = set_parser.add_mutually_exclusive_group(required=True)
    c_kwargs = {'dest': 'flavor_builder'}
    api_flavor = FlavorType(ApiFlavor)
    c_mgrp.add_argument(
        '-a', '--api',
        choices=[api_flavor(impl) for impl in api.get_api_implementations()],
        type=FlavorType(ApiFlavor),
        nargs='?', const=FlavorType(ApiFlavor)('memory'),
        help='add spyce api (default implementation: "memory")',
        **c_kwargs)
    c_mgrp.add_argument(
        '-p', '--py-source',
        metavar='PY_SOURCE',
        type=FlavorType(SourceFlavor),
        help='add python source file',
        **c_kwargs)
    c_mgrp.add_argument(
        '-f', '--file',
        metavar='FILE',
        type=FlavorType(FileFlavor),
        help='add file',
        **c_kwargs)
    c_mgrp.add_argument(
        '-d', '--dir',
        metavar='DIR',
        type=FlavorType(DirFlavor),
        help='add directory',
        **c_kwargs)
    c_mgrp.add_argument(
        '-u', '--url',
        metavar='URL',
        type=FlavorType(UrlFlavor),
        help='add url',
        **c_kwargs)
    set_parser.add_argument(
        '-r', '--replace',
        action='store_true', default=False,
        help='replace existing spyce with the same name')

    ### del
    del_parser = build_parser(
        'del', subparsers=subparsers,
        function=fn_spyce_del,
        description='remove spyces from python source file')
    add_input_argument(del_parser)
    add_output_argument(del_parser)
    add_filters_argument(del_parser, required=True)
    del_parser.add_argument(
        '-c', '--content-only',
        action='store_true', default=False,
        help='remove only spyce content')

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
    diff_parser.add_argument(
        '-b', '--binary',
        action='store_true', default=False,
        help='show diff in encoded binary spyces')

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
