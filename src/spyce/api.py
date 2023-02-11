import base64
import gzip
import re

from . import spyce


__all__ = [
#    'get_spyce',
    'get_inline_api',
    'get_tmpfile_api',
    'get_memory_api',
    'get_api',
    'default_api_implementation',
    'get_api_implementations',
]


def get_inline_api(name):
    source = spyce.get_spyce('source/spyce').get_content()
    source += '''
loc = locals()

class SpyceNamespace:
    pass

spyce_namespace = SpyceNamespace
for l_var, l_obj in loc.items():
    setattr(spyce_namespace, l_var, l_obj)

return spyce_namespace
'''
    indent = '    '
    indented_lines = []
    for line in source.split('\n'):
        indented_lines.append(indent + line)
    indented_source = '\n'.join(indented_lines)
    return f'''\
## spyce api implementation: inline
def _build_spyce_namespace(name, file):
{indented_source}

{name} = _build_spyce_namespace({name!r}, __file__)
'''


def _compress_source(source):
    gz_source = gzip.compress(bytes(source, 'utf-8'))
    data = str(base64.b64encode(gz_source), 'utf-8')
    data_lines = ['"""\\']
    slen = spyce.get_max_line_length()
    for idx in range(0, len(data), slen):
        data_lines.append(data[idx:idx+slen])
    data_lines.append('"""')
    return '\n'.join(data_lines)


def get_tmpfile_api(name):
    source = spyce.get_spyce('source/spyce').get_content()
    data = _compress_source(source)
    return f'''\
## spyce api implementation: tmpfile
def _load_module_from_tmpfile(name, file):
    import re, tempfile, gzip, base64, atexit, shutil, sys, importlib.util
    from pathlib import Path
    tmp_path = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, tmp_path)
    tmp_file = tmp_path / (name + '.py')

    r_spc = re.compile(r'\s')
    source = gzip.decompress(base64.b64decode(r_spc.sub('', {data})))
    with open(tmp_file, 'wb') as tmp_f:
        tmp_f.write(source)
    spec = importlib.util.spec_from_file_location(name, str(tmp_file))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = file
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

{name} = _load_module_from_tmpfile("{name}", __file__)
'''


def get_memory_api(name):
    source = spyce.get_spyce('source/spyce').get_content()
    data = _compress_source(source)
    return f'''\
## spyce api implementation: memory
def _load_module_from_memory(name, file):
    import re, base64, gzip, sys, importlib.abc, importlib.util

    class StringLoader(importlib.abc.SourceLoader):
        def __init__(self, data):
            self.data = data

        def get_source(self, fullname):
            return self.data

        def get_data(self, path):
            return self.data

        def get_filename(self, fullname):
            return f'/tmp/fake/{{fullname}}.py'

    r_spc = re.compile(r'\s')
    source = gzip.decompress(base64.b64decode(r_spc.sub('', {data})))
    spec = importlib.util.spec_from_loader(name, loader=StringLoader(source), origin='built-in')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.__file__ = file
    return module

{name} = _load_module_from_memory("{name}", __file__)
'''

API_IMPLEMENTATION = {
    'inline': get_inline_api,
    'tmpfile': get_tmpfile_api,
    'memory': get_memory_api,
}


DEFAULT_API_IMPLEMENTATION = 'memory'

def get_api(name=None, implementation=None):
    if name is None:
        name = 'spyce'
    if not is_valid_modulename(name):
        raise ValueError(name)
    if implementation is None:
        implementation = DEFAULT_API_IMPLEMENTATION
    # print('-->', name, implementation)
    return API_IMPLEMENTATION[implementation](name)


def default_api_implementation():
    return DEFAULT_API_IMPLEMENTATION


def get_api_implementations():
    return list(API_IMPLEMENTATION)


def is_valid_modulename(name):
    regex = re.compile(r'[a-zA-Z0-9_]\w*')
    return bool(regex.match(name))
