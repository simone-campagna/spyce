import sys
import termcolor


__all__ = [
    'set_colored',
    'get_colored',
    'colored',
]


COLORED = None


def set_colored(value=None):
    global COLORED
    if value is None:
        value = sys.stdout.isatty()
    COLORED = bool(value)


def get_colored():
    global COLORED
    if COLORED is None:
        set_colored()
    return COLORED


def colored(text, fg_color=None, bg_color=None, attrs=None):
    if get_colored():
        return termcolor.colored(text, fg_color, bg_color, attrs=attrs)
    else:
        return text

