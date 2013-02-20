
from warnings import warn

from .dimension import Dimension
from .hyphenator import Hyphenator
from .flowable import Flowable, FlowableStyle
from .layout import DownExpandingContainer, EndOfContainer
from .reference import LateEval, Footnote
from .text import Character, Space, Box, ControlCharacter, Newline, Tab, Spacer
from .text import TextStyle, SingleStyledText, MixedStyledText
from .dimension import PT


# Text justification
LEFT = 'left'
RIGHT = 'right'
CENTER = 'center'
BOTH = 'justify'


# Line spacing
STANDARD = 1.2
SINGLE = 1.0
DOUBLE = 2.0

# TODO: LineSpacing class (leading, proportional, exact, at-least, ...)?
##class LineSpacing(object):
##    def __self__(self, leading, proportional, ...):



# TODO: look at Word/OpenOffice for more options
class ParagraphStyle(TextStyle, FlowableStyle):
    attributes = {'indent_left': 0*PT,
                  'indent_right': 0*PT,
                  'indent_first': 0*PT,
                  'line_spacing': STANDARD,
                  'justify': BOTH,
                  'tab_stops': []}

    def __init__(self, base=None, **attributes):
        super().__init__(base=base, **attributes)


class TabStop(object):
    def __init__(self, position, align=LEFT, fill=None):
        self._position = position
        self.align = align
        self.fill = fill

    def get_position(self, width):
        if isinstance(self._position, Dimension):
            return float(self._position)
        else:
            return width * self._position


class EndOfLine(Exception):
    def __init__(self, hyphenation_remainder=None):
        self.hyphenation_remainder = hyphenation_remainder


class Line(list):
    def __init__(self, paragraph, width, indent=0.0):
        super().__init__()
        self.paragraph = paragraph
        self.width = width - indent
        self.indent = indent
        self.text_width = 0
        self._in_tab = None

    def _find_tab_stop(self, cursor):
        for tab_stop in self.paragraph.get_style('tab_stops'):
            tab_position = tab_stop.get_position(self.width)
            if cursor < tab_position:
                return tab_stop, tab_position
        else:
            return None, None

    def append(self, item):
        width = item.width
        if not self and isinstance(item, Space):
            return
        elif isinstance(item, Tab):
            cursor = self.text_width
            tab_stop, tab_position = self._find_tab_stop(cursor)
            if tab_stop:
                item.tab_stop = tab_stop
                width = item.tab_width = tab_position - cursor
                if tab_stop.align in (RIGHT, CENTER):
                    self._in_tab = item
                else:
                    self._in_tab = None
        elif self._in_tab and self._in_tab.tab_stop.align == RIGHT:
            if self._in_tab.tab_width <= width:
                for first, second in item.hyphenate():
                    first_width = first.width
                    if self._in_tab.tab_width >= first_width:
                        self._in_tab.tab_width -= first_width
                        super().append(first)
                        raise EndOfLine(second)
                raise EndOfLine
            else:
                self._in_tab.tab_width -= width
                self.text_width -= width
        elif self._in_tab and self._in_tab.tab_stop.align == CENTER:
            if self._in_tab.tab_width <= width:
                for first, second in item.hyphenate():
                    first_width = first.width
                    if self._in_tab.tab_width >= first_width / 2:
                        self._in_tab.tab_width -= first_width / 2
                        super().append(first)
                        raise EndOfLine(second)
                raise EndOfLine
            else:
                self._in_tab.tab_width -= width / 2
                self.text_width -= width / 2
        elif self.text_width + width > self.width:
            if len(self) == 0:
                warn('item too long to fit on line')
                # TODO: print source location (and repeat for diff. occurences)
            else:
                for first, second in item.hyphenate():
                    if self.text_width + first.width < self.width:
                        self.append(first)
                        raise EndOfLine(second)
                raise EndOfLine

        self.text_width += width
        super().append(item)

    def typeset(self, container, last_line=False):
        """Typeset words at the current coordinates"""
        max_font_size = 0
        justify = self.paragraph.get_style('justify')
        if Tab in map(type, self) or justify == BOTH and last_line:
            justification = LEFT
        else:
            justification = justify

        # drop spaces at the end of the line
        try:
            while isinstance(self[-1], Space):
                self.pop()
        except IndexError:
            return 0

        # replace tabs with spacers or fillers
        # TODO: encapsulate (Tab.expand method)
        i = 0
        while i < len(self):
            if isinstance(self[i], Tab):
                tab = self.pop(i)
                try:
                    fill_char = SingleStyledText(tab.tab_stop.fill)
                    fill_char.parent = tab.parent
                    number, rest = divmod(tab.tab_width, fill_char.width)
                    spacer = Spacer(rest)
                    spacer.parent = tab.parent
                    self.insert(i, spacer)
                    fill_text = SingleStyledText(tab.tab_stop.fill * int(number))
                    fill_text.parent = tab.parent
                    self.insert(i + 1, fill_text)
                    i += 1
                except (AttributeError, TypeError):
                    spacer = Spacer(tab.tab_width)
                    spacer.parent = tab.parent
                    self.insert(i, spacer)
            i += 1

        line_width = sum(item.width for item in self)
        max_font_size = max(float(item.height) for item in self)
        extra_space = self.width - line_width

        def _is_scalable_space(item):
            return isinstance(item, Space) and not item.fixed_width

        # horizontal displacement
        x = self.indent
        add_to_spaces = 0.0
        if justification == CENTER:
            x += extra_space / 2.0
        elif justification == RIGHT:
            x += extra_space
        elif justification == BOTH:
            number_of_spaces = list(map(_is_scalable_space, self)).count(True)
            if number_of_spaces:
                add_to_spaces = extra_space / number_of_spaces
                # TODO: padding added to spaces should be prop. to font size

        # position cursor
        container.advance(max_font_size)

        def render_span(item, font_style, glyphs, widths):
            font, size, y_offset = font_style
            y = container.cursor - y_offset
            container.canvas.show_glyphs(x, y, font, size, glyphs, widths)
            total_width = sum(widths)
            del glyphs[:]
            del widths[:]
            return total_width

        # typeset spans
        prev_item = None
        glyphs = []
        widths = []
        prev_font_style = None
        for item in self:
            font_style = item.font, float(item.height), item.y_offset
            if isinstance(item, Box):
                if prev_item:
                    x += render_span(prev_item, prev_font_style, glyphs, widths)
                    prev_item = None
                    prev_font_style = None
                x += item.render(container.canvas, x,
                                 self.paragraph.container.cursor)
                continue
            if _is_scalable_space(item):
                item_widths = [item.widths[0] + add_to_spaces]
            else:
                item_widths = item.widths
            if prev_item and font_style != prev_font_style:
                x += render_span(prev_item, prev_font_style, glyphs, widths)
            widths += item_widths
            glyphs += item.glyphs()
            prev_item = item
            prev_font_style = font_style
        if prev_item:
            x += render_span(prev_item, prev_font_style, glyphs, widths)

        return max_font_size


class Paragraph(MixedStyledText, Flowable):
    style_class = ParagraphStyle

    def __init__(self, items, style=None):
        super().__init__(items, style=style)
        # TODO: move to TextStyle
        #self.char_spacing = 0.0

        self._words = []
        self._init_state()

    def _init_state(self):
        self.word_pointer = 0
        self.field_pointer = None
        self.first_line = True

    def _split_words(self, spans):
        join = False
        words = []
        for span in spans:
            try:
                words += span.split()
            except AttributeError:
                words.append(span)
        return words

    def render(self, container):
        return self.typeset(container)

    def typeset(self, container):
        if not self._words:
            self._words = self._split_words(self.spans())

        canvas = container.canvas
        start_offset = container.cursor

        indent_left = float(self.get_style('indent_left'))
        indent_right = float(self.get_style('indent_right'))
        indent_first = float(self.get_style('indent_first'))
        line_width = float(container.width - indent_right)

        self._last_font_style = None
        line_pointers = self.word_pointer, self.field_pointer
        if self.first_line:
            line = Line(self, line_width, indent_left + indent_first)
        else:
            line = Line(self, line_width, indent_left)

        while self.word_pointer < len(self._words):
            word = self._words[self.word_pointer]
            if isinstance(word, LateEval):
                if self.field_pointer is None:
                    self._field_words = self._split_words(word.spans(container))
                    self.field_pointer = 0
                else:
                    self.field_pointer += 1
                if self._field_words:
                    word = self._field_words[self.field_pointer]
                if self.field_pointer >= len(self._field_words) - 1:
                    self.field_pointer = None
                    self.word_pointer += 1
                if not self._field_words:
                    continue
            else:
                self.word_pointer += 1

            if isinstance(word, (Newline, Flowable)):
                line_pointers = self.typeset_line(container, line,
                                                  line_pointers, last_line=True)
                if isinstance(word, Flowable):
                    self.word_pointer -= 1
                    child_container = DownExpandingContainer(container,
                                        left=self.get_style('indent_left'),
                                        top=container.cursor*PT)
                    container.advance(word.flow(child_container))
                    self.word_pointer += 1
                line = Line(self, line_width, indent_left)
            else:
                try:
                    line.append(word)
                except EndOfLine as eol:
                    line_pointers = self.typeset_line(container, line,
                                                      line_pointers)
                    line = Line(self, line_width, indent_left)
                    if eol.hyphenation_remainder:
                        line.append(eol.hyphenation_remainder)
                    else:
                        line.append(word)

        # the last line
        if len(line) != 0:
            self.typeset_line(container, line, line_pointers, last_line=True)

        self._init_state()
        return container.cursor - start_offset

    def _line_spacing(self, line_height):
        line_spacing = self.get_style('line_spacing')
        if isinstance(line_spacing, Dimension):
            return float(line_spacing)
        else:
            return line_spacing * line_height

    def typeset_line(self, container, line, line_pointers, last_line=False):
        try:
            line_height = line.typeset(container, last_line)
            container.advance(self._line_spacing(line_height) - line_height)
            try:
                line_pointers = (self.word_pointer - 1, self.field_pointer - 1)
            except TypeError:
                line_pointers = (self.word_pointer - 1, self.field_pointer)
        except EndOfContainer:
            self.word_pointer, self.field_pointer = line_pointers
            raise
        self.first_line = False
        return line_pointers
