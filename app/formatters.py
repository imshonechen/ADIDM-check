import re


def format_filesize(value):
    size_bytes = parse_filesize_bytes(value)
    if size_bytes is None:
        return str(value or '')
    if size_bytes < 1024:
        return f'{size_bytes} B'
    if size_bytes < 1024 ** 2:
        return f'{size_bytes / 1024:.2f} KB'
    if size_bytes < 1024 ** 3:
        return f'{size_bytes / (1024 ** 2):.2f} MB'
    return f'{size_bytes / (1024 ** 3):.2f} GB'


def parse_filesize_bytes(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    match = re.search(r'([\d.]+)\s*(B|BYTE|BYTES|KB|KIB|MB|MIB|GB|GIB)?', text, re.IGNORECASE)
    if not match:
        return None

    number = float(match.group(1))
    unit = (match.group(2) or 'B').upper()
    if unit in ('B', 'BYTE', 'BYTES'):
        return int(number)
    if unit in ('KB', 'KIB'):
        return int(number * 1024)
    if unit in ('MB', 'MIB'):
        return int(number * 1024 ** 2)
    if unit in ('GB', 'GIB'):
        return int(number * 1024 ** 3)
    return int(number)
