__all__ = [
    'get_spyce',
    'get_api',
]

# spyce: start source/spyce-api
SPYCE_API_VERSION = '0.1.0'

class SpyceApiError(RuntimeError):
    pass


def get_spyce(key, file=__file__):
    import base64
    import re
    re_spyce = re.compile(rf'\# spyce:\s+(?P<action>start|end)\s+{key}(?:\:(?P<type>\S+))?(?:\s+(?P<args>.*))?')
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
    spyce_lines = lines[start+1:end-1]
    if spyce_type is None:
        spyce_type = 'text' if section == 'source' else 'bytes'
    if spyce_type == 'text':
        return ''.join(spyce_lines)
    else:
        prefix = '#|'
        data = ''.join(line[len(prefix):].strip() for line in spyce_lines if line.startswith(prefix))
        return base64.b64decode(data)
# spyce: end source/spyce-api


def get_api():
    return get_spyce('source/spyce-api')
