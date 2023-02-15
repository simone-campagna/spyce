#!/usr/bin/env python3

import argparse
import fnmatch
import inspect
import sys

from pathlib import Path

from .log import (
    configure_logging,
    set_trace,
    trace_errors,
)
from .spyce import (
    set_max_line_length,
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
from .wok import load_wok, default_wok_filename, find_wok_path
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


def _filtered_keys(spycy_file, key, filters):
    if key is not None:
        if key in spycy_file:
            return [key]
        else:
            raise KeyError(key)

    mp = {}
    for key, spyce in spycy_file.items():
        fq_key = spyce.fq_key
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


def fn_spyce_list(input_file, key, filters, show_lines=False, show_header=True):
    spycy_file = SpycyFile(input_file)
    table = []
    spyces = []
    keys = _filtered_keys(spycy_file, key, filters)
    for key in keys:
        spyce = spycy_file.get_spyce_jar(key)
        num_chars = len(spyce.get_text())
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
                spyce = spycy_file[key]
                for ln, line in enumerate(spyce.get_lines()):
                    line_no = ln + spyce.start + 1
                    print(f'  {line_no:<6d} {line.rstrip()}')



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


def fn_spyce_add(input_file, output_file, flavor_builder, section, name, spyce_type, backup, backup_format, max_line_length):
    if max_line_length is not None:
        set_max_line_length(max_line_length)
    spycy_file = SpycyFile(input_file)
    with spycy_file.refactor(output_file, backup=backup, backup_format=backup_format):
        flavor =flavor_builder(
            section=section,
            name=name,
            spyce_type=spyce_type)
        spyce = flavor()
        spycy_file[spyce.key] = spyce


def fn_spyce_extract(input_file, output_file, key):
    spycy_file = SpycyFile(input_file)
    spyce = spycy_file[key]
    spyce.write_file(output_file)


def fn_spyce_del(input_file, output_file, key, filters, backup, backup_format):
    spycy_file = SpycyFile(input_file)
    keys = _filtered_keys(spycy_file, key, filters)
    with spycy_file.refactor(output_file, backup=backup, backup_format=backup_format):
        for key in keys:
            del spycy_file[key]



def fn_wok_status(input_file):
    wok = load_wok(input_file)
    wok.status()


def fn_wok_fry(input_file):
    wok = load_wok(input_file)
    wok.fry()

    
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


def build_wok_parser(subparsers=None):
    parser = build_parser(
        name='wok',  subparsers=subparsers,
        description=f'''\
wok {get_version()} - add spyces to your python project
'''
    )
    parser.set_defaults(
        function=fn_wok_status,
    )
    parser.add_argument(
        '-i', '--input-file',
        type=Path,
        default=None,
        help='input wok file')
    subparsers = parser.add_subparsers()

    ### status:
    status_parser = build_parser(
        'status', subparsers=subparsers,
        function=fn_wok_status,
        description='show the project status')

    ### fry:
    fry_parser = build_parser(
        'fry', subparsers=subparsers,
        function=fn_wok_fry,
        description='apply the wok recipe')
    return parser


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
    add_parser = build_parser(
        'add', subparsers=subparsers,
        function=fn_spyce_add,
        description='add or replace spyces in python source file')
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
        '-m', '--max-line-length',
        default=None,
        help='set max data line length')

    add_parser.add_argument(
        '-t', '--type',
        dest='spyce_type',
        choices=['text', 'bytes'],
        default=None,
        help="spyce type (default: 'text' for source spyces, else 'bytes')")

    c_group = add_parser.add_argument_group('spyce')
    c_mgrp = add_parser.add_mutually_exclusive_group(required=True)
    c_kwargs = {'dest': 'flavor_builder'}
    api_flavor = FlavorType(ApiFlavor)
    c_mgrp.add_argument(
        '-a', '--api',
        choices=[api_flavor(impl) for impl in api.get_api_implementations()],
        type=FlavorType(ApiFlavor),
        nargs='?', const=FlavorType(ApiFlavor)('memory'),
        **c_kwargs)
    c_mgrp.add_argument(
        '-p', '--py-source',
        type=FlavorType(SourceFlavor),
        **c_kwargs)
    c_mgrp.add_argument(
        '-f', '--file',
        type=FlavorType(FileFlavor),
        **c_kwargs)
    c_mgrp.add_argument(
        '-d', '--dir',
        type=FlavorType(DirFlavor),
        **c_kwargs)
    c_mgrp.add_argument(
        '-u', '--url',
        type=FlavorType(UrlFlavor),
        **c_kwargs)

    ### extract
    extract_parser = build_parser(
        'extract', subparsers=subparsers,
        function=fn_spyce_extract,
        description='extract a spyce object from python source file')
    add_input_argument(extract_parser)
    add_output_argument(extract_parser, optional=False)
    add_key_argument(extract_parser)

    ### del
    del_parser = build_parser(
        'del', subparsers=subparsers,
        function=fn_spyce_del,
        description='remove spyces from python source file')
    add_input_argument(del_parser)
    add_output_argument(del_parser)
    add_backup_argument(del_parser)
    add_key_filters_argument(del_parser, required=True)

    ### wok
    wok_parser = build_wok_parser(subparsers)
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
