__all__ = [
    'get_spyce',
    'get_inline_api',
    'get_tmpfile_api',
    'get_memory_api',
    'get_api',
    'default_api_implementation',
    'get_api_implementations',
]

# spyce: start source/spyce-api
SPYCE_API_VERSION = '0.1.0'

class SpyceApiError(RuntimeError):
    pass


class SpyceObj:
    def __init__(self, lines, start, end):
        self.start = start
        self.end = end
        self._spyce_lines = lines[start+1:end-1]
        self._text = ''.join(self._spyce_lines)
        self._content = self._build_content(self._spyce_lines)

    def _build_content(self, path):
        return self._text

    def _build_path(self, path):
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _file_mode(self):
        return 'w'

    def get_text(self):
        return self._text

    def get_content(self):
        return self._content

    def write_file(self, path):
        path = self._build_path(path)
        with open(path, self._file_mode()) as file:
            file.write(self._content)


class TextSpyceObj(SpyceObj):
    def _file_mode(self):
        return 'w'


class BytesSpyceObj(SpyceObj):
    def _build_content(self, path):
        import base64
        prefix = '#|'
        data = ''.join(line[len(prefix):].strip() for line in self._spyce_lines if line.startswith(prefix))
        return base64.b64decode(data)

    def _file_mode(self):
        return 'wb'

    def untar(self, path, mode='r|*'):
        import io, tarfile
        path = self._build_path(path)
        b_file = io.BytesIO(self._content)
        with tarfile.open(fileobj=b_file, mode=mode) as t_file:
            t_file.extractall(path)


def get_spyce(key, file=None):
    if file is None:
        file = __file__
        # import inspect
        # frame_info = inspect.getouterframes(inspect.currentframe())[1]
        # file = frame_info.filename
    import re, sys
    spyce_lines = []
    with open(file, 'r') as fh:
        lines = fh.readlines()
    lst = key.split('/', 1)
    if len(lst) == 1:
        section = 'data'
        name = key
    else:
        section, name = lst
    key = f'{section}/{name}'
    re_spyce = re.compile(rf'\# spyce:\s+(?P<action>start|end)\s+{key}(?:\:(?P<type>\S+))?\s*')
    start, end, spyce_type = None, None, None
    for line_index, line in enumerate(lines):
        m_obj = re_spyce.match(line)
        if m_obj:
            if m_obj['action'] == 'start':
                start = line_index
                spyce_type = m_obj['type']
            else:
                end = line_index + 1
    if start is None or end is None:
        raise SpyceApiError(f'file {file}: spyce {key!r} not found')
    if spyce_type is None:
        spyce_type = 'text' if section == 'source' else 'bytes'
    if spyce_type == 'text':
        return TextSpyceObj(lines, start, end)
    else:
        return BytesSpyceObj(lines, start, end)
# spyce: end source/spyce-api


def get_inline_api(name):
    source = get_spyce('source/spyce-api').get_content()
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
    return f'''
## spyce api implementation: inline
def _build_spyce_namespace(name, file):
{indented_source}

{name} = _build_spyce_namespace({name!r}, __file__)
'''


def _compress_source(source):
    import base64, gzip
    gz_source = gzip.compress(bytes(source, 'utf-8'))
    data = str(base64.b64encode(gz_source), 'utf-8')
    data_lines = []
    slen = 80
    for idx in range(0, len(data), slen):
        data_lines.append(f'        {data[idx:idx+slen]!r},')
    return '\n'.join(data_lines)


def get_tmpfile_api(name):
    source = get_spyce('source/spyce-api').get_content()
    data = _compress_source(source)
    return f'''
## spyce api implementation: tmpfile
def _load_module_from_tmpfile(name, file):
    import tempfile, gzip, base64, atexit, shutil, sys, importlib.util
    from pathlib import Path
    tmp_path = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, tmp_path)
    tmp_file = tmp_path / (name + '.py')

    source = gzip.decompress(base64.b64decode(''.join([
''' + data + f'''
    ])))
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
    source = get_spyce('source/spyce-api').get_content()
    data = _compress_source(source)
    return '''
## spyce api implementation: memory
def _load_module_from_memory(name, file):
    import base64, gzip, sys, importlib.abc, importlib.util

    class StringLoader(importlib.abc.SourceLoader):
        def __init__(self, data):
            self.data = data

        def get_source(self, fullname):
            return self.data

        def get_data(self, path):
            return self.data

        def get_filename(self, fullname):
            return f'/tmp/fake/{fullname}.py'

    source = gzip.decompress(base64.b64decode(''.join([
''' + data + f'''
    ])))
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
    import re
    regex = re.compile(r'[a-zA-Z0-9_]\w*')
    return bool(regex.match(name))
