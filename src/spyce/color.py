import re
import sys


__all__ = [
    'set_colored',
    'get_colored',
    'AnsiColor',
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


class AnsiColor:
    __colors__ = {
        'black': 30,  # 'grey' in termcolor
        'red': 31,
        'green': 32,
        'yellow': 33,
        'blue': 34,
        'magenta': 35,
        'cyan': 36,
        'white': 37,
        'bright-black': 90,
        'bright-red': 91,
        'bright-green': 92,
        'bright-yellow': 93,
        'bright-blue': 94,
        'bright-magenta': 95,
        'bright-cyan': 96,
        'bright-white': 97,
    }
    __background_offset__ = 10
    __styles__ = {
        'bold': 1,
        'light': 2,  # 'dark' in termcolor
        'italic': 3,
        'underline': 4,
        'slow-blink': 5,
        'blink': 5,
        'fast-blink': 6,
        'reverse': 7,
        'concealed': 8,
        'strike': 9,
    }
    __ansi_format__ = '\033[{code}m'
    __reset__ = __ansi_format__.format(code=0)
    __regex_uncolor__ = __ansi_format__.format(code=r'\d+')


    def _rendered(self, code):
        return self.__ansi_format__.format(code=code)

    def rendered_fg_color(self, name):
        return self._rendered(self.__colors__[name])

    def rendered_bg_color(self, name):
        return self._rendered(self.__colors__[name] + self.__background_offset__)

    def rendered_styles(self, styles):
        rendered_styles = []
        for style in styles:
            rendered_styles.append(self._rendered(self.__styles__[style]))
        return ''.join(rendered_styles)

    def color(self, text, fg_color=None, bg_color=None, styles=None):
        text = str(text)
        if not get_colored():
            return text
        tokens = []
        if fg_color:
            tokens.append(self.rendered_fg_color(fg_color))
        if bg_color:
            tokens.append(self.rendered_bg_color(bg_color))
        if styles:
            tokens.append(self.rendered_styles(styles))
        if tokens:
            tokens.append(text)
            tokens.append(self.__reset__)
            return ''.join(tokens)
        else:
            return text

    def uncolor(self, text):
        return self.__re_uncolor__.sub('', text)

    def __call__(self, text, fg_color=None, bg_color=None, styles=None):
        return self.color(text, fg_color=fg_color, bg_color=bg_color, styles=styles)


ANSI_COLOR = AnsiColor()


colored = ANSI_COLOR.color
