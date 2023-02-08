__all__ = [
    'get_spice',
    'get_api',
]

# spice: start source/spice-api
SPYCE_API_VERSION = '0.1.0'

def get_spice(key, file=__file__):
    import base64
    import re
    re_spice = re.compile(rf'\# spice:\s+(?P<action>start|end)\s+{key}(?:\:(?P<type>\S+))?(?:\s+(?P<args>.*))?')
    spice_lines = []
    with open(file, 'r') as fh:
        lines = fh.readlines()
    lst = key.split('/', 1)
    if len(lst) == 1:
        section = 'data'
        name = key
    else:
        section, name = lst
    key = f'{section}/{name}'
    start, end, spice_type = None, None, None
    for line_index, line in enumerate(lines):
        m_obj = re_spice.match(line)
        if m_obj:
            if m_obj['action'] == 'start':
                start = line_index
                spice_type = m_obj['type']
            else:
                end = line_index + 1
    if start is None or end is None:
        raise RuntimeError(f'file {file}: {key!r} not found')
    spice_lines = lines[start+1:end-1]
    if spice_type is None:
        spice_type = 'text' if section == 'source' else 'bytes'
    if spice_type == 'text':
        return ''.join(spice_lines)
    else:
        prefix = '#|'
        data = ''.join(line[len(prefix):].strip() for line in spice_lines if line.startswith(prefix))
        return base64.b64decode(data)
# spice: end source/spice-api


def get_api():
    return get_spice('source/spice-api')
