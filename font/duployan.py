# Copyright 2018-2019 David Corbett
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__all__ = ['Builder']

import collections
import enum
import io
import math
import re
import unicodedata

import fontTools.agl
import fontTools.feaLib.ast
import fontTools.feaLib.builder
import fontTools.feaLib.parser
import fontTools.otlLib.builder
import psMat

BASELINE = 402
DEFAULT_SIDE_BEARING = 85
EPSILON = 1e-5
RADIUS = 50
STROKE_WIDTH = 70
CURSIVE_ANCHOR = 'cursive'
RELATIVE_1_ANCHOR = 'rel1'
RELATIVE_2_ANCHOR = 'rel2'
MIDDLE_ANCHOR = 'mid'
TANGENT_ANCHOR = 'tan'
ABOVE_ANCHOR = 'abv'
BELOW_ANCHOR = 'blw'
CLONE_DEFAULT = object()
WIDTH_MARKER_RADIX = 4
WIDTH_MARKER_PLACES = 7

assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'

class Type(enum.Enum):
    JOINING = enum.auto()
    ORIENTING = enum.auto()
    NON_JOINING = enum.auto()

class Context:
    def __init__(self, angle=None, clockwise=None):
        self.angle = angle
        self.clockwise = clockwise

    def __repr__(self):
        return 'Context({}, {})'.format(self.angle, self.clockwise)

    def __str__(self):
        if self.angle is None:
            return ''
        return '{}{}'.format(
                self.angle,
                '' if self.clockwise is None else 'neg' if self.clockwise else 'pos'
            ).replace('.', '__')

    def __eq__(self, other):
        return self.angle == other.angle and self.clockwise == other.clockwise

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.angle) ^ hash(self.clockwise)

NO_CONTEXT = Context()

def rect(r, theta):
    return (r * math.cos(theta), r * math.sin(theta))

class Shape:
    def clone(self):
        raise NotImplementedError

    def name_is_enough(self):
        return False

    def group(self):
        return str(self)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        raise NotImplementedError

    def context_in(self):
        raise NotImplementedError

    def context_out(self):
        raise NotImplementedError

    def calculate_diacritic_angles(self):
        return {}

class Dummy(Shape):
    def __str__(self):
        return '_'

    def name_is_enough(self):
        return True

class Start(Shape):
    def __str__(self):
        return '_.START'

    def name_is_enough(self):
        return True

class End(Shape):
    def __str__(self):
        return '_.END'

    def name_is_enough(self):
        return True

class Carry(Shape):
    def __init__(self, value):
        self.value = int(value)
        assert self.value == value, value

    def __str__(self):
        return f'_.c.{self.value}'

    def name_is_enough(self):
        return True

class DigitStatus(enum.Enum):
    NORMAL = enum.auto()
    ALMOST_DONE = enum.auto()
    DONE = enum.auto()

class LeftBoundDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''_.{
                "LDX" if self.status == DigitStatus.DONE else "ldx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    def name_is_enough(self):
        return True

class RightBoundDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''_.{
                "RDX" if self.status == DigitStatus.DONE else "rdx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    def name_is_enough(self):
        return True

class CursiveWidthDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''_.{
                "CDX" if self.status == DigitStatus.DONE else "cdx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    def name_is_enough(self):
        return True

class Space(Shape):
    def __init__(self, angle):
        self.angle = angle

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT
    ):
        return Space(self.angle if angle is CLONE_DEFAULT else angle)

    def __str__(self):
        return 'Z.{}'.format(int(self.angle))

    def __call__(self, glyph, pen, size, anchor, joining_type):
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', (size + 2 * DEFAULT_SIDE_BEARING + STROKE_WIDTH), 0)
            glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Step(Shape):
    def __init__(self, sfd_name, angle):
        self.sfd_name = sfd_name
        self.angle = angle

    def clone(
        self,
        *,
        sfd_name=CLONE_DEFAULT,
        angle=CLONE_DEFAULT,
    ):
        return Step(
            self.sfd_name if sfd_name is CLONE_DEFAULT else sfd_name,
            self.angle if angle is CLONE_DEFAULT else angle,
        )

    def __str__(self):
        return self.sfd_name

    def name_is_enough(self):
        return True

    def contextualize(self, context_in, context_out):
        return Space(self.angle)

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Dot(Shape):
    def __str__(self):
        return 'H'

    def clone(self):
        return Dot()

    def __call__(self, glyph, pen, size, anchor, joining_type):
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', STROKE_WIDTH, 'round')
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(0, 0))
        elif joining_type != Type.NON_JOINING:
            x = 2 * DEFAULT_SIDE_BEARING + STROKE_WIDTH
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', -x, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', x, 0)

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Line(Shape):
    def __init__(self, angle, fixed_length=False):
        self.angle = angle
        self.fixed_length = fixed_length

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        fixed_length=CLONE_DEFAULT,
    ):
        return Line(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.fixed_length if fixed_length is CLONE_DEFAULT else fixed_length,
        )

    def __str__(self):
        return 'L.{}'.format(int(self.angle))

    def __call__(self, glyph, pen, size, anchor, joining_type):
        pen.moveTo((0, 0))
        if self.fixed_length:
            length_denominator = 1
        else:
            length_denominator = abs(math.sin(math.radians(self.angle)))
            if length_denominator < EPSILON:
                length_denominator = 1
        length = int(500 * (size or 0.2) / length_denominator)
        pen.lineTo((length, 0))
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(length / 2, 0))
        else:
            if joining_type != Type.NON_JOINING:
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', length, 0)
            if size == 2 and self.angle == 30:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', length / 2 - 2 * STROKE_WIDTH, -STROKE_WIDTH)
                glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', length / 2 + 2 * STROKE_WIDTH, -STROKE_WIDTH)
            else:
                glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', length / 2, STROKE_WIDTH)
                glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', length / 2, -STROKE_WIDTH)
            glyph.addAnchorPoint(MIDDLE_ANCHOR, 'base', length / 2, 0)
            glyph.addAnchorPoint(TANGENT_ANCHOR, 'base', length, 0)
        glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def context_in(self):
        return Context(self.angle)

    def context_out(self):
        return Context(self.angle)

    def rotate_diacritic(self, angle):
        return self.clone(angle=angle)

    def calculate_diacritic_angles(self):
        angle = float(self.angle % 180)
        return {
            RELATIVE_1_ANCHOR: angle,
            RELATIVE_2_ANCHOR: angle,
            MIDDLE_ANCHOR: (angle + 90) % 180,
            TANGENT_ANCHOR: (angle + 90) % 180,
        }

class Curve(Shape):
    def __init__(self, angle_in, angle_out, clockwise, stretch=0, long=False):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.stretch = stretch
        self.long = long

    def clone(
        self,
        *,
        angle_in=CLONE_DEFAULT,
        angle_out=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        stretch=CLONE_DEFAULT,
        long=CLONE_DEFAULT,
    ):
        return Curve(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            self.stretch if stretch is CLONE_DEFAULT else stretch,
            self.long if long is CLONE_DEFAULT else long,
        )

    def __str__(self):
        return 'C.{}.{}.{}'.format(
            int(self.angle_in),
            int(self.angle_out),
            'neg' if self.clockwise else 'pos')

    def group(self):
        return (
            self.angle_in,
            self.angle_out,
            self.clockwise,
            self.stretch,
            self.long,
        )

    def __call__(self, glyph, pen, size, anchor, joining_type):
        assert anchor is None
        angle_out = self.angle_out
        if self.clockwise and angle_out > self.angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < self.angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + self.angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        r = int(RADIUS * size)
        da = a2 - a1
        beziers_needed = int(math.ceil(abs(da) / 90))
        bezier_arc = da / beziers_needed
        cp = r * (4 / 3) * math.tan(math.pi / (2 * beziers_needed * 360 / da))
        cp_distance = math.hypot(cp, r)
        cp_angle = math.asin(cp / cp_distance)
        pen.moveTo(rect(r, math.radians(a1)))
        for i in range(1, beziers_needed + 1):
            theta0 = math.radians(a1 + (i - 1) * bezier_arc)
            p1 = rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = rect(r, theta3)
            p2 = rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        pen.endPath()
        relative_mark_angle = (a1 + a2) / 2
        if joining_type != Type.NON_JOINING:
            x = r * math.cos(math.radians(a1))
            y = r * math.sin(math.radians(a1))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', x, y)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', p3[0], p3[1])
        glyph.addAnchorPoint(MIDDLE_ANCHOR, 'base', *rect(r, math.radians(relative_mark_angle)))
        glyph.addAnchorPoint(TANGENT_ANCHOR, 'base', p3[0], p3[1])
        if joining_type == Type.ORIENTING:
            glyph.addAnchorPoint(ABOVE_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(90)))
            glyph.addAnchorPoint(BELOW_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(270)))
        if self.stretch:
            scale_x = 1.0
            scale_y = 1.0 + self.stretch
            if self.long:
                scale_x, scale_y = scale_y, scale_x
            theta = math.radians(self.angle_in % 180)
            glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', *rect(0, 0))
            glyph.transform(psMat.compose(psMat.rotate(-theta), psMat.compose(psMat.scale(scale_x, scale_y), psMat.rotate(theta))))
            glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', *rect(scale_x * r + 2 * STROKE_WIDTH, math.radians(self.angle_in)))
        else:
            glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base',
                *(rect(0, 0) if abs(da) > 180 else rect(
                    min(STROKE_WIDTH, r - 2 * STROKE_WIDTH),
                    math.radians(relative_mark_angle))))
            glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(relative_mark_angle)))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def contextualize(self, context_in, context_out):
        angle_in = context_in.angle
        angle_out = context_out.angle
        da = self.angle_out - self.angle_in
        if angle_in is None:
            if angle_out is not None:
                angle_in = (angle_out - da) % 360
            else:
                angle_in = self.angle_in
        return Curve(
            angle_in,
            (angle_in + da) % 360,
            (self.clockwise
                if angle_out is None or da != 180
                else (abs(angle_out - angle_in) >= 180) == (angle_out > angle_in)))

    def context_in(self):
        return Context(self.angle_in, self.clockwise)

    def context_out(self):
        return Context(self.angle_out, self.clockwise)

    def calculate_diacritic_angles(self):
        halfway_angle = (self.angle_in + self.angle_out) / 2 % 180
        return {
            RELATIVE_1_ANCHOR: halfway_angle,
            RELATIVE_2_ANCHOR: halfway_angle,
            MIDDLE_ANCHOR: (halfway_angle + 90) % 180,
            TANGENT_ANCHOR: (self.angle_out + 90) % 180,
        }

class Circle(Shape):
    def __init__(self, angle_in, angle_out, clockwise, reversed, stretch=0):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.reversed = reversed
        self.stretch = stretch

    def clone(
        self,
        *,
        angle_in=CLONE_DEFAULT,
        angle_out=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        reversed=CLONE_DEFAULT,
        stretch=CLONE_DEFAULT,
    ):
        return Circle(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            self.reversed if reversed is CLONE_DEFAULT else reversed,
            self.stretch if stretch is CLONE_DEFAULT else stretch,
        )

    def __str__(self):
        return 'O.{}.{}.{}{}'.format(
            int(self.angle_in),
            int(self.angle_out),
            'neg' if self.clockwise else 'pos',
            '.rev' if self.reversed else '')

    def group(self):
        angle_in = self.angle_in
        angle_out = self.angle_out
        clockwise = self.clockwise
        if clockwise and angle_in == angle_out:
            clockwise = False
            angle_in = angle_out = (angle_in + 180) % 360
        return (
            angle_in,
            angle_out,
            clockwise,
            self.stretch,
        )

    def __call__(self, glyph, pen, size, anchor, joining_type):
        assert anchor is None
        angle_out = self.angle_out
        if self.clockwise and self.angle_out > self.angle_in:
            angle_out -= 360
        elif not self.clockwise and self.angle_out < self.angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + self.angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        r = int(RADIUS * size)
        cp = r * (4 / 3) * math.tan(math.pi / 8)
        pen.moveTo((0, r))
        pen.curveTo((cp, r), (r, cp), (r, 0))
        pen.curveTo((r, -cp), (cp, -r), (0, -r))
        pen.curveTo((-cp, -r), (-r, -cp), (-r, 0))
        pen.curveTo((-r, cp), (-cp, r), (0, r))
        pen.endPath()
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *rect(r, math.radians(a2)))
        glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', *rect(0, 0))
        scale_x = 1.0 + self.stretch
        if self.stretch:
            scale_y = 1.0
            theta = math.radians(self.angle_in % 180)
            glyph.transform(psMat.compose(psMat.rotate(-theta), psMat.compose(psMat.scale(scale_x, scale_y), psMat.rotate(theta))))
        glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', *rect(scale_x * r + 2 * STROKE_WIDTH, math.radians(self.angle_in)))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def contextualize(self, context_in, context_out):
        angle_in = context_in.angle
        angle_out = context_out.angle
        if angle_in is None:
            if angle_out is None:
                angle_in = 0
            else:
                angle_in = angle_out
        if angle_out is None:
            angle_out = angle_in
        clockwise_from_adjacent_curve = (
            context_in.clockwise
                if context_in.clockwise is not None
                else context_out.clockwise)
        if angle_in == angle_out:
            return Circle(
                angle_in,
                angle_out,
                clockwise_from_adjacent_curve != self.reversed
                    if clockwise_from_adjacent_curve is not None
                    else self.clockwise,
                self.reversed,
                self.stretch,
            )
        da = abs(angle_out - angle_in)
        clockwise_ignoring_curvature = (da >= 180) != (angle_out > angle_in)
        clockwise_ignoring_reversal = (
            clockwise_from_adjacent_curve
                if clockwise_from_adjacent_curve is not None
                else clockwise_ignoring_curvature)
        clockwise = clockwise_ignoring_reversal != self.reversed
        if clockwise_ignoring_reversal == clockwise_ignoring_curvature:
            if self.reversed:
                if da != 180:
                    return Curve(angle_in, (angle_out + 180) % 360, clockwise, self.stretch, True)
                else:
                    return Circle(angle_in, (angle_out + 180) % 360, clockwise, self.reversed, self.stretch)
            else:
                return Curve(angle_in, angle_out, clockwise, self.stretch, True)
        else:
            if self.reversed:
                if da != 180:
                    return Curve(angle_in, angle_out, clockwise, self.stretch, True)
                else:
                    return Circle(angle_in, (angle_out + 180) % 360, clockwise, self.reversed, self.stretch)
            else:
                if da != 180 and context_in.clockwise != context_out.clockwise:
                    return Circle(angle_in, angle_out, clockwise, self.reversed, self.stretch)
                else:
                    return Curve(angle_in, angle_out, clockwise, self.stretch, True)

    def context_in(self):
        return Context(self.angle_in, self.clockwise)

    def context_out(self):
        return Context(self.angle_out, self.clockwise)

class Style(enum.Enum):
    PERNIN = enum.auto()

class Schema:
    _CHARACTER_NAME_SUBSTITUTIONS = [(re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in [
        (r'^uniEC02$', 'DUPLOYAN LETTER REVERSED P'),
        (r'^uniEC03$', 'DUPLOYAN LETTER REVERSED T'),
        (r'^uniEC04$', 'DUPLOYAN LETTER REVERSED F'),
        (r'^uniEC05$', 'DUPLOYAN LETTER REVERSED K'),
        (r'^uniEC06$', 'DUPLOYAN LETTER REVERSED L'),
        (r'^uniEC19$', 'DUPLOYAN LETTER REVERSED M'),
        (r'^uniEC1B$', 'DUPLOYAN LETTER REVERSED J'),
        (r'^uniEC1C$', 'DUPLOYAN LETTER REVERSED S'),
        (r'^ZERO WIDTH SPACE$', 'ZWSP'),
        (r'^ZERO WIDTH NON-JOINER$', 'ZWNJ'),
        (r'^ZERO WIDTH JOINER$', 'ZWJ'),
        (r'^MEDIUM MATHEMATICAL SPACE$', 'MMSP'),
        (r'^WORD JOINER$', 'WJ'),
        (r'^ZERO WIDTH NO-BREAK SPACE$', 'ZWNBSP'),
        (r'^COMBINING ', ''),
        (r'^DUPLOYAN ((LETTER|AFFIX( ATTACHED)?|SIGN|PUNCTUATION) )?', ''),
        (r'^SHORTHAND FORMAT ', ''),
        (r'\b(QUAD|SPACE)\b', 'SP'),
        (r' (WITH|AND) ', ' '),
        (r'(?<! |-)[A-Z]+', lambda m: m.group(0).lower()),
        (r'[ -]+', ''),
    ]]
    _canonical_names = {}

    def __init__(
            self,
            cp,
            path,
            size,
            joining_type=Type.JOINING,
            side_bearing=DEFAULT_SIDE_BEARING,
            anchor=None,
            marks=None,
            ignored=False,
            styles=None,
            ss_pernin=None,
            context_in=None,
            context_out=None,
            base_angle=None,
            cps=None,
            ss=None,
            _original_shape=None,
    ):
        assert not (marks and anchor), 'A schema has both marks {} and anchor {}'.format(marks, anchor)
        self.cp = cp
        self.path = path
        self.size = size
        self.joining_type = joining_type
        self.side_bearing = side_bearing
        self.anchor = anchor
        self.marks = marks or []
        self.ignored = ignored
        self.styles = frozenset(Style.__dict__.keys() if styles is None else styles)
        self.ss_pernin = ss_pernin
        self.context_in = context_in or NO_CONTEXT
        self.context_out = context_out or NO_CONTEXT
        self.base_angle = base_angle
        self.cps = cps or [cp]
        self.ss = ss
        self._original_shape = _original_shape or type(path)
        self.diacritic_angles = self._calculate_diacritic_angles()
        self.group = self._calculate_group()
        self._glyph_name = None
        self._canonical_schema = self
        self.without_marks = marks and self.clone(cp=-1, marks=None)

    def sort_key(self):
        return (
            self.cp == -1,
            len(self.cps),
            self.ss,
            self._original_shape != type(self.path),
            self.cps,
        )

    def clone(
        self,
        *,
        cp=CLONE_DEFAULT,
        path=CLONE_DEFAULT,
        size=CLONE_DEFAULT,
        joining_type=CLONE_DEFAULT,
        side_bearing=CLONE_DEFAULT,
        anchor=CLONE_DEFAULT,
        marks=CLONE_DEFAULT,
        ignored=CLONE_DEFAULT,
        styles=CLONE_DEFAULT,
        ss_pernin=CLONE_DEFAULT,
        context_in=CLONE_DEFAULT,
        context_out=CLONE_DEFAULT,
        base_angle=CLONE_DEFAULT,
        cps=CLONE_DEFAULT,
        ss=CLONE_DEFAULT,
        _original_shape=CLONE_DEFAULT,
    ):
        return Schema(
            self.cp if cp is CLONE_DEFAULT else cp,
            self.path if path is CLONE_DEFAULT else path,
            self.size if size is CLONE_DEFAULT else size,
            self.joining_type if joining_type is CLONE_DEFAULT else joining_type,
            self.side_bearing if side_bearing is CLONE_DEFAULT else side_bearing,
            self.anchor if anchor is CLONE_DEFAULT else anchor,
            self.marks if marks is CLONE_DEFAULT else marks,
            self.ignored if ignored is CLONE_DEFAULT else ignored,
            self.styles if styles is CLONE_DEFAULT else styles,
            self.ss_pernin if ss_pernin is CLONE_DEFAULT else ss_pernin,
            self.context_in if context_in is CLONE_DEFAULT else context_in,
            self.context_out if context_out is CLONE_DEFAULT else context_out,
            self.base_angle if base_angle is CLONE_DEFAULT else base_angle,
            self.cps if cps is CLONE_DEFAULT else cps,
            self.ss if ss is CLONE_DEFAULT else ss,
            self._original_shape if _original_shape is CLONE_DEFAULT else _original_shape,
        )

    def __repr__(self):
        return '<Schema {}>'.format(', '.join(map(str, [
            (str if self.cp == -1 else hex)(self.cp),
            self.path,
            self.size,
            self.side_bearing,
            self.context_in,
            'ss{:02}'.format(self.ss) if self.ss else '',
            'NJ' if self.joining_type == Type.NON_JOINING else '',
            'mark' if self.anchor else 'base',
            [repr(m) for m in self.marks or []],
        ])))

    def _calculate_diacritic_angles(self):
        return self.path.calculate_diacritic_angles()

    def _calculate_group(self):
        return (
            self.path.group(),
            self.size,
            self.side_bearing,
            self.anchor,
            tuple(m.group for m in self.marks or []),
        )

    def canonical_schema(self, canonical_schema):
        self._canonical_schema = canonical_schema
        self._glyph_name = None

    def calculate_name(self):
        if self.path.name_is_enough():
            return str(self.path)
        def get_names(cp):
            try:
                agl_name = readable_name = fontTools.agl.UV2AGL[cp]
            except KeyError:
                agl_name = '{}{:04X}'.format('uni' if cp <= 0xFFFF else 'u', cp)
                try:
                    readable_name = unicodedata.name(chr(cp))
                except ValueError:
                    readable_name = agl_name
                for regex, repl in self._CHARACTER_NAME_SUBSTITUTIONS:
                    readable_name = regex.sub(repl, readable_name)
            return agl_name, readable_name
        cps = self.cps
        if -1 in cps:
            name = ''
        else:
            agl_name, readable_name = ('_'.join(component) for component in zip(*list(map(get_names, cps))))
            name = agl_name if agl_name == readable_name else '{}.{}'.format(agl_name, readable_name)
        if self.cp == -1:
            name = '{}.{}.{}{}'.format(
                name or 'dupl',
                str(self.path),
                int(self.size),
                ('.' + self.anchor) if self.anchor else '',
            )
        return '{}{}'.format(
            name,
            '.ss{:02}'.format(self.ss) if self.ss else '',
        )

    def __str__(self):
        if self._glyph_name is None:
            canonical = self._canonical_schema
            if self is not canonical:
                self._glyph_name = str(canonical)
            else:
                name = self.calculate_name()
                if name in self._canonical_names:
                    if self not in self._canonical_names[name]:
                        self._canonical_names[name].append(self)
                        name += '._{:X}'.format(len(self._canonical_names[name]) - 1)
                else:
                    self._canonical_names[name] = [self]
                self._glyph_name = name
        return self._glyph_name

    def contextualize(self, context_in, context_out):
        assert self.joining_type == Type.ORIENTING or isinstance(self.path, Step)
        path = self.path.contextualize(context_in, context_out)
        if path is self.path:
            return self
        return self.clone(
            cp=-1,
            path=path,
            anchor=None,
            marks=None,
            context_in=context_in,
            context_out=context_out)

    def rotate_diacritic(self, angle):
        return self.clone(
            cp=-1,
            path=self.path.rotate_diacritic(angle),
            base_angle=angle)

class Hashable:
    def __init__(self, delegate):
        self.delegate = delegate

    def __hash__(self):
        return id(self.delegate)

    def __getattr__(self, attr):
        return getattr(self.delegate, attr)

class OrderedSet(dict):
    def __init__(self, iterable=None):
        super().__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item):
        self[item] = None

    def remove(self, item):
        self.pop(item, None)

class Rule:
    def __init__(self, a1, a2, a3=None, a4=None, lookups=None, x_advances=None):
        def _l(glyphs):
            return [glyphs] if isinstance(glyphs, str) else glyphs
        if a4 is None and lookups is None and x_advances is None:
            assert a3 is None, 'Rule takes 2 or 4 inputs, given 3'
            a4 = a2
            a2 = a1
            a1 = []
            a3 = []
        assert (a4 is not None) + (lookups is not None) + (x_advances is not None) == 1, (
            'Rule can take exactly one of an output glyph/class list, a lookup list, or an x advance list')
        self.contexts_in = _l(a1)
        self.inputs = _l(a2)
        self.contexts_out = _l(a3)
        self.outputs = None
        self.lookups = lookups
        self.x_advances = x_advances
        if lookups is not None:
            assert len(lookups) == len(self.inputs), f'There must be one lookup (or None) per input glyph ({len(lookups)} != {len(self.inputs)})'
        elif x_advances is not None:
            assert len(x_advances) == len(self.inputs), f'There must be one x advance (or None) per input glyph ({len(x_advances)} != {len(self.inputs)})'
        else:
            self.outputs = _l(a4)

    def to_ast(self, class_asts, named_lookup_asts, in_contextual_lookup, in_multiple_lookup, in_reverse_lookup):
        def glyph_to_ast(glyph):
            if isinstance(glyph, str):
                return fontTools.feaLib.ast.GlyphClassName(class_asts[glyph])
            if isinstance(glyph, Schema):
                return fontTools.feaLib.ast.GlyphName(str(glyph))
            return fontTools.feaLib.ast.GlyphName(glyph.glyphname)
        def glyphs_to_ast(glyphs):
            return [glyph_to_ast(glyph) for glyph in glyphs]
        def glyph_to_name(glyph):
            assert not isinstance(glyph, str), 'Glyph classes are not allowed where only glyphs are expected'
            if isinstance(glyph, Schema):
                return str(glyph)
            return glyph.glyphname
        def glyphs_to_names(glyphs):
            return [glyph_to_name(glyph) for glyph in glyphs]
        if self.lookups is not None:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions do not support lookup references'
            return fontTools.feaLib.ast.ChainContextSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                [None if name is None else named_lookup_asts[name] for name in self.lookups])
        elif self.x_advances is not None:
            assert not in_reverse_lookup, 'There is no reverse positioning lookup type'
            assert len(self.inputs) == 1, 'Only single adjustment positioning has been implemented'
            return fontTools.feaLib.ast.SinglePosStatement(
                list(zip(
                    glyphs_to_ast(self.inputs),
                    [fontTools.feaLib.ast.ValueRecord(xAdvance=x_advance) for x_advance in self.x_advances])),
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.contexts_out),
                in_contextual_lookup)
        elif len(self.inputs) == 1:
            if len(self.outputs) == 1 and not in_multiple_lookup:
                if in_reverse_lookup:
                    return fontTools.feaLib.ast.ReverseChainSingleSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs))
                else:
                    return fontTools.feaLib.ast.SingleSubstStatement(
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs),
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        in_contextual_lookup)
            else:
                assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
                return fontTools.feaLib.ast.MultipleSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyph_to_name(self.inputs[0]),
                    glyphs_to_ast(self.contexts_out),
                    glyphs_to_names(self.outputs),
                    in_contextual_lookup)
        else:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
            return fontTools.feaLib.ast.LigatureSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                glyph_to_name(self.outputs[0]),
                in_contextual_lookup)

    def is_contextual(self):
        return bool(self.contexts_in or self.contexts_out)

    def is_multiple(self):
        return len(self.inputs) == 1 and self.outputs is not None and len(self.outputs) != 1

class Lookup:
    def __init__(
            self,
            feature,
            script,
            language,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            mark_filtering_set=None,
            reversed=False,
    ):
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        if mark_filtering_set:
             flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        self.feature = feature
        self.script = script
        self.language = language
        self.flags = flags
        self.mark_filtering_set = mark_filtering_set
        self.reversed = reversed
        self.rules = []
        assert (feature is None) == (script is None) == (language is None), 'Not clear whether this is a named or a normal lookup'
        if script == 'dupl':
            self.required = feature in [
                'frac',
                'numr',
                'dnom',
                'locl',
                'ccmp',
                'nukt',
                'akhn',
                'rphf',
                'pref',
                'rkrf',
                'abvf',
                'blwf',
                'half',
                'pstf',
                'vatu',
                'cjct',
                'isol',
                'init',
                'medi',
                'fina',
                'abvs',
                'blws',
                'calt',
                'clig',
                'haln',
                'pres',
                'psts',
                'rclt',
                'rlig',
                'curs',
                'dist',
                'mark',
                'abvm',
                'blwm',
                'mkmk',
            ]
        elif script is None:
            self.required = False
        else:
            raise ValueError("Unrecognized script tag: '{}'".format(self.script))

    def to_ast(self, class_asts, named_lookup_asts, name=None):
        assert named_lookup_asts is None or name is None, 'A named lookup cannot use named lookups'
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        if name:
            ast = fontTools.feaLib.ast.LookupBlock(name)
        else:
            ast = fontTools.feaLib.ast.FeatureBlock(self.feature)
            ast.statements.append(fontTools.feaLib.ast.ScriptStatement(self.script))
            ast.statements.append(fontTools.feaLib.ast.LanguageStatement(self.language))
        ast.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
            self.flags,
            markFilteringSet=fontTools.feaLib.ast.GlyphClassName(class_asts[self.mark_filtering_set])
                if self.mark_filtering_set
                else None))
        ast.statements.extend(r.to_ast(class_asts, named_lookup_asts, contextual, multiple, self.reversed) for r in self.rules)
        return ast

    def append(self, rule):
        self.rules.append(rule)

    def extend(self, other):
        assert self.feature == other.feature, "Incompatible features: '{}', '{}'".format(self.feature, other.feature)
        assert self.script == other.script, "Incompatible scripts: '{}', '{}'".format(self.script, other.script)
        assert self.language == other.language, "Incompatible languages: '{}', '{}'".format(self.language, other.language)
        for rule in other.rules:
            self.append(rule)

def dont_ignore_default_ignorables(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup_1 = Lookup('ccmp', 'dupl', 'dflt')
    lookup_2 = Lookup('ccmp', 'dupl', 'dflt')
    for schema in schemas:
        if schema.ignored:
            add_rule(lookup_1, Rule([schema], [schema, schema]))
            add_rule(lookup_2, Rule([schema, schema], [schema]))
    return [lookup_1, lookup_2]

def ligate_pernin_r(schemas, new_schemas, classes, named_lookups, add_rule):
    liga = Lookup('liga', 'dupl', 'dflt')
    dlig = Lookup('dlig', 'dupl', 'dflt')
    vowels = []
    zwj = None
    r = None
    for schema in schemas:
        if schema.cps == [0x200D]:
            assert zwj is None, 'Multiple ZWJs found'
            zwj = schema
        elif schema.cps == [0x1BC06]:
            assert r is None, 'Multiple Pernin Rs found'
            r = schema
        elif (schema in new_schemas
                and isinstance(schema.path, Circle)
                and not schema.path.reversed
                and Style.PERNIN in schema.styles):
            classes['ll_vowel'].append(schema)
            vowels.append(schema)
    assert classes['ll_vowel'], 'No Pernin circle vowels found'
    if vowels:
        add_rule(liga, Rule([], 'll_vowel', [zwj, r, 'll_vowel'], 'll_vowel'))
        add_rule(dlig, Rule([], 'll_vowel', [r, 'll_vowel'], 'll_vowel'))
    for vowel in vowels:
        reversed_vowel = vowel.clone(
            cp=-1,
            path=vowel.path.clone(clockwise=not vowel.path.clockwise, reversed=True),
            cps=vowel.cps + zwj.cps + r.cps,
        )
        add_rule(liga, Rule([vowel, zwj, r], [reversed_vowel]))
        add_rule(dlig, Rule([vowel, r], [reversed_vowel]))
    return [liga, dlig]

def decompose(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('abvs', 'dupl', 'dflt')
    for schema in schemas:
        if schema.marks and schema in new_schemas:
            add_rule(lookup, Rule([schema], [schema.without_marks] + schema.marks))
    return [lookup]

def join_with_next_step(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt', reversed=True)
    old_input_count = len(classes['js_i'])
    for schema in new_schemas:
        if isinstance(schema.path, Step):
            classes['js_i'].append(schema)
        if (schema.joining_type != Type.NON_JOINING
            and not schema.anchor
            and not isinstance(schema.path, Step)
        ):
            classes['js_c'].append(schema)
    new_context = 'js_o' not in classes
    for i, target_schema in enumerate(classes['js_i']):
        if new_context or i >= old_input_count:
            output_schema = target_schema.contextualize(NO_CONTEXT, NO_CONTEXT)
            classes['js_o'].append(output_schema)
    if new_context:
        add_rule(lookup, Rule([], 'js_i', 'js_c', 'js_o'))
    return [lookup]

def ss_pernin(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('ss01', 'dupl', 'dflt')
    for schema in schemas:
        if schema in new_schemas and schema.ss_pernin:
            add_rule(lookup, Rule([schema], [schema.clone(cp=-1, ss_pernin=None, ss=1, **schema.ss_pernin)]))
    return [lookup]

def join_with_previous(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt', reversed=True)
    contexts_in = OrderedSet()
    new_contexts_in = set()
    old_input_count = len(classes['jp_i'])
    for schema in schemas:
        if not schema.anchor:
            if (schema.joining_type == Type.ORIENTING
                    and schema.context_in == NO_CONTEXT
                    and schema in new_schemas):
                classes['jp_i'].append(schema)
            if schema.joining_type != Type.NON_JOINING:
                context_in = schema.path.context_out()
                if context_in != NO_CONTEXT:
                    contexts_in.add(context_in)
                    context_in_class = classes['jp_c_' + str(context_in)]
                    if schema not in context_in_class:
                        if not context_in_class:
                            new_contexts_in.add(context_in)
                        context_in_class.append(schema)
    for context_in in contexts_in:
        output_class_name = 'jp_o_' + str(context_in)
        new_context = context_in in new_contexts_in
        for i, target_schema in enumerate(classes['jp_i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(context_in, NO_CONTEXT)
                classes[output_class_name].append(output_schema)
        if new_context:
            add_rule(lookup, Rule('jp_c_' + str(context_in), 'jp_i', [], output_class_name))
    return [lookup]

def join_with_next(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt')
    contexts_out = OrderedSet()
    new_contexts_out = set()
    old_input_count = len(classes['jn_i'])
    for schema in schemas:
        if not schema.anchor:
            if (schema.joining_type == Type.ORIENTING
                    and schema.context_out == NO_CONTEXT
                    and schema in new_schemas):
                classes['jn_i'].append(schema)
            if schema.joining_type != Type.NON_JOINING:
                context_out = schema.path.context_in()
                if context_out != NO_CONTEXT:
                    contexts_out.add(context_out)
                    context_out_class = classes['jn_c_' + str(context_out)]
                    if schema not in context_out_class:
                        if not context_out_class:
                            new_contexts_out.add(context_out)
                        context_out_class.append(schema)
    for context_out in contexts_out:
        output_class_name = 'jn_o_' + str(context_out)
        new_context = context_out in new_contexts_out
        for i, target_schema in enumerate(classes['jn_i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(target_schema.context_in, context_out)
                classes[output_class_name].append(output_schema)
        if new_context:
            add_rule(lookup, Rule([], 'jn_i', 'jn_c_' + str(context_out), output_class_name))
    return [lookup]

def rotate_diacritics(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt', 0, reversed=True)
    base_contexts = OrderedSet()
    new_base_contexts = set()
    for schema in schemas:
        if schema.anchor:
            if (schema.joining_type == Type.ORIENTING
                    and schema.base_angle is None
                    and schema in new_schemas):
                classes['rd_i_' + str(schema.anchor)].append(schema)
        else:
            for base_context in schema.diacritic_angles.items():
                base_contexts.add(base_context)
                base_context_class = classes['rd_c_{}_{}'.format(*base_context).replace('.', '__')]
                if schema not in base_context_class:
                    if not base_context_class:
                        new_base_contexts.add(base_context)
                    base_context_class.append(schema)
    for base_context in base_contexts:
        if base_context in new_base_contexts:
            anchor, angle = base_context
            for target_schema in classes['rd_i_' + str(anchor)]:
                if anchor == target_schema.anchor:
                    output_schema = target_schema.rotate_diacritic(angle)
                    add_rule(lookup, Rule('rd_c_{}_{}'.format(anchor, angle).replace('.', '__'), 'rd_i_' + str(anchor), [], [output_schema]))
    return [lookup]

def add_width_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup('psts', 'dupl', 'dflt')
    carry_0_schema = Schema(-1, Carry(0), 0)
    left_bound_markers = {}
    right_bound_markers = {}
    cursive_width_markers = {}
    start = Schema(-1, Start(), 0)
    end = Schema(-1, End(), 0)
    for glyph in new_glyphs:
        if glyph.glyphclass == 'baseligature':
            for anchor_class_name, type, x, _ in glyph.anchorPoints:
                if anchor_class_name == CURSIVE_ANCHOR:
                    if type == 'entry':
                        entry = x
                    elif type == 'exit':
                        exit = x
            cursive_width = exit - entry
            bounding_box = glyph.boundingBox()
            if bounding_box == (0, 0, 0, 0):
                left_bound = 0
                right_bound = cursive_width
            else:
                left_bound = bounding_box[0] - entry
                right_bound = bounding_box[2] - entry
            digits = []
            for width, digit_path, width_markers in [
                (left_bound, LeftBoundDigit, left_bound_markers),
                (right_bound, RightBoundDigit, right_bound_markers),
                (cursive_width, CursiveWidthDigit, cursive_width_markers),
            ]:
                assert (width < WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                    if width >= 0
                    else width >= -WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                    ), f'Glyph {glyph.glyphname} is too wide: {width} units'
                digits_base = len(digits)
                digits += [carry_0_schema] * WIDTH_MARKER_PLACES * 2
                quotient = round(width)
                for i in range(WIDTH_MARKER_PLACES):
                    quotient, remainder = divmod(quotient, WIDTH_MARKER_RADIX)
                    args = (i, remainder)
                    if args not in width_markers:
                        width_markers[args] = Schema(-1, digit_path(*args), 0)
                    digits[digits_base + i * 2 + 1] = width_markers[args]
            if digits:
                add_rule(lookup, Rule([glyph], [start, glyph, end, *digits]))
    return [lookup]

def sum_width_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'sw',
    )
    carry_schemas = {}
    dummied_carry_schemas = set()
    original_carry_schemas = []
    left_digit_schemas = {}
    original_left_digit_schemas = []
    right_digit_schemas = {}
    original_right_digit_schemas = []
    cursive_digit_schemas = {}
    original_cursive_digit_schemas = []
    dummy = None
    for schema in glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, Carry):
            carry_schemas[schema.path.value] = schema
            original_carry_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
        elif isinstance(schema.path, LeftBoundDigit):
            left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_left_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
        elif isinstance(schema.path, RightBoundDigit):
            right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_right_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
        elif isinstance(schema.path, CursiveWidthDigit):
            cursive_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_cursive_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
        elif isinstance(schema.path, Dummy):
            dummy = schema
    for augend_schema in original_cursive_digit_schemas:
        augend_is_new = augend_schema in new_glyphs
        place = augend_schema.path.place
        augend = augend_schema.path.digit
        for (
            skip,
            original_digit_schemas,
            digit_schemas,
            digit_path,
        ) in [(
            6 * WIDTH_MARKER_PLACES - 2,
            original_cursive_digit_schemas,
            cursive_digit_schemas,
            CursiveWidthDigit,
        ), (
            2 * WIDTH_MARKER_PLACES - 2,
            original_left_digit_schemas,
            left_digit_schemas,
            LeftBoundDigit,
        ), (
            4 * WIDTH_MARKER_PLACES - 2,
            original_right_digit_schemas,
            right_digit_schemas,
            RightBoundDigit,
        )]:
            for carry_in_schema in original_carry_schemas:
                carry_in = carry_in_schema.path.value
                carry_in_is_new = carry_in_schema in new_glyphs
                if carry_in_is_new and carry_in_schema.path.value not in dummied_carry_schemas:
                    dummied_carry_schemas.add(carry_in_schema.path.value)
                    if dummy is None:
                        dummy = Schema(-1, Dummy(), 0)
                    add_rule(lookup, Rule([carry_in_schema], [carry_schemas[0]], [], [dummy]))
                contexts_in = [augend_schema, *['sw'] * skip, carry_in_schema]
                for addend_schema in original_digit_schemas:
                    if place != addend_schema.path.place:
                        continue
                    if not (carry_in_is_new or augend_is_new or addend_schema in new_glyphs):
                        continue
                    addend = addend_schema.path.digit
                    carry_out, sum_digit = divmod(carry_in + augend + addend, WIDTH_MARKER_RADIX)
                    if carry_out != 0 or sum_digit != addend:
                        if carry_out in carry_schemas:
                            carry_out_schema = carry_schemas[carry_out]
                        else:
                            carry_out_schema = Schema(-1, Carry(carry_out), 0)
                            carry_schemas[carry_out] = carry_out_schema
                        sum_index = place * WIDTH_MARKER_RADIX + sum_digit
                        if sum_index in digit_schemas:
                            sum_digit_schema = digit_schemas[sum_index]
                        else:
                            sum_digit_schema = Schema(-1, digit_path(place, sum_digit), 0)
                            digit_schemas[sum_index] = sum_digit_schema
                        outputs = ([sum_digit_schema]
                            if place == WIDTH_MARKER_PLACES - 1
                            else [sum_digit_schema, carry_out_schema])
                        add_rule(lookup, Rule(contexts_in, [addend_schema], [], outputs))
    return [lookup]

def calculate_bound_extrema(glyphs, new_glyphs, classes, named_lookups, add_rule):
    left_lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'ml',
    )
    named_lookups['ml_copy'] = Lookup(
        None,
        None,
        None,
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'ml',
    )
    left_digit_schemas = {}
    right_lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'mr',
    )
    named_lookups['mr_copy'] = Lookup(
        None,
        None,
        None,
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'mr',
    )
    right_digit_schemas = {}
    for schema in glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, LeftBoundDigit):
            left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            if schema in new_glyphs:
                classes['ml'].append(schema)
        elif isinstance(schema.path, RightBoundDigit):
            right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            if schema in new_glyphs:
                classes['mr'].append(schema)
    for place in range(WIDTH_MARKER_PLACES - 1, -1, -1):
        for i in range(0, WIDTH_MARKER_RADIX):
            left_schema_i = left_digit_schemas.get(place * WIDTH_MARKER_RADIX + i)
            right_schema_i = right_digit_schemas.get(place * WIDTH_MARKER_RADIX + i)
            i_signed = i if place != WIDTH_MARKER_PLACES - 1 or i < WIDTH_MARKER_RADIX / 2 else i - WIDTH_MARKER_RADIX
            if left_schema_i is None and right_schema_i is None:
                continue
            for j in range(0, WIDTH_MARKER_RADIX):
                if i == j:
                    continue
                j_signed = j if place != WIDTH_MARKER_PLACES - 1 or j < WIDTH_MARKER_RADIX / 2 else j - WIDTH_MARKER_RADIX
                for schema_i, digit_schemas, lookup, marker_class, copy_lookup_name, compare in [
                    (left_schema_i, left_digit_schemas, left_lookup, 'ml', 'ml_copy', int.__gt__),
                    (right_schema_i, right_digit_schemas, right_lookup, 'mr', 'mr_copy', int.__lt__),
                ]:
                    schema_j = digit_schemas.get(place * WIDTH_MARKER_RADIX + j)
                    if schema_j is None:
                        continue
                    add_rule(lookup, Rule(
                        [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - schema_i.path.place - 1)],
                        [*[marker_class] * schema_j.path.place, schema_j],
                        [],
                        lookups=[None if compare(i_signed, j_signed) else copy_lookup_name] * (schema_j.path.place + 1)))
                    add_rule(named_lookups[copy_lookup_name], Rule(
                        [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - 1)],
                        [schema_j],
                        [],
                        [schema_i]))
    return [left_lookup, right_lookup]

def remove_false_start_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'fs',
        True,
    )
    dummy = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, Dummy))
    start = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, Start))
    classes['fs'].append(start)
    add_rule(lookup, Rule([start], [start], [], [dummy]))
    return [lookup]

def remove_false_end_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'fe',
    )
    dummy = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, Dummy))
    end = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, End))
    classes['fe'].append(end)
    add_rule(lookup, Rule([], [end], [end], [dummy]))
    return [lookup]

def expand_start_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup('psts', 'dupl', 'dflt', 0)
    start = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, Start))
    add_rule(lookup, Rule([start], [
        start,
        *(Schema(-1, LeftBoundDigit(place, 0, DigitStatus.DONE), 0) for place in range(WIDTH_MARKER_PLACES)),
    ]))
    return [lookup]

def mark_maximum_bounds(glyphs, new_glyphs, classes, named_lookups, add_rule):
    left_lookup = Lookup('psts', 'dupl', 'dflt', 0, 'tl', True)
    right_lookup = Lookup('psts', 'dupl', 'dflt', 0, 'tr', True)
    new_left_bounds = []
    new_right_bounds = []
    for schema in new_glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, End):
            end = schema
            if end not in classes['tl']:
                classes['tl'].append(end)
            if end not in classes['tr']:
                classes['tr'].append(end)
        elif isinstance(schema.path, LeftBoundDigit) and schema.path.status == DigitStatus.NORMAL:
            classes['tl'].append(schema)
            new_left_bounds.append(schema)
        elif isinstance(schema.path, RightBoundDigit) and schema.path.status == DigitStatus.NORMAL:
            classes['tr'].append(schema)
            new_right_bounds.append(schema)
    for new_digits, lookup, class_name, after_end, digit_path, status in [
        (new_left_bounds, left_lookup, 'tl', True, LeftBoundDigit, DigitStatus.ALMOST_DONE),
        (new_right_bounds, right_lookup, 'tr', True, RightBoundDigit, DigitStatus.DONE),
    ]:
        for schema in new_digits:
            skipped_schemas = [class_name] * schema.path.place
            add_rule(lookup, Rule(
                [end, *[class_name] * schema.path.place] if after_end else [],
                [schema],
                [] if after_end else [*[class_name] * (WIDTH_MARKER_PLACES - 1 - schema.path.place), end],
                [Schema(-1, digit_path(schema.path.place, schema.path.digit, status), 0)]))
    return [left_lookup, right_lookup]

def copy_penultimate_cursive_width_to_end(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup_1 = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'cp',
    )
    lookup_2 = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'cp',
    )
    cursive_digit_schemas = {}
    done_cursive_digit_schemas = {}
    for schema in glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, End):
            end = schema
            if end not in classes['cp']:
                classes['cp'].append(end)
        elif isinstance(schema.path, CursiveWidthDigit):
            if schema.path.status == DigitStatus.NORMAL and (schema in new_glyphs or schema.path.digit == 0):
                cursive_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            elif schema.path.status == DigitStatus.DONE:
                done_cursive_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            if schema in new_glyphs:
                classes['cp'].append(schema)
    for key, schema in cursive_digit_schemas.items():
        if schema not in new_glyphs:
            continue
        zero_schema = cursive_digit_schemas[key - schema.path.digit]
        if schema.path.digit != 0:
            add_rule(lookup_1, Rule(
                [end, *['cp'] * schema.path.place],
                [schema],
                [],
                [zero_schema]))
        done_key = schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit
        if done_key not in done_cursive_digit_schemas:
            done_schema = Schema(-1, CursiveWidthDigit(schema.path.place, schema.path.digit, DigitStatus.DONE), 0)
            classes['cp'].append(done_schema)
            done_cursive_digit_schemas[done_key] = done_schema
        add_rule(lookup_2, Rule(
            [schema, *['cp'] * (WIDTH_MARKER_PLACES - schema.path.place - 1), end, *['cp'] * schema.path.place],
            [zero_schema],
            [],
            [done_cursive_digit_schemas[done_key]]))
    return [lookup_1, lookup_2]

def copy_maximum_left_bound_to_start(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'ct',
    )
    new_left_totals = []
    new_left_start_totals = [None] * WIDTH_MARKER_PLACES
    start = next(s for s in glyphs if isinstance(s, Schema) and isinstance(s.path, Start))
    if start not in classes['ct']:
        classes['ct'].append(start)
    for schema in new_glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, LeftBoundDigit):
            if schema.path.status == DigitStatus.ALMOST_DONE:
                new_left_totals.append(schema)
            elif schema.path.status == DigitStatus.DONE and schema.path.digit == 0:
                new_left_start_totals[schema.path.place] = schema
    for total in new_left_totals:
        classes['ct'].append(total)
        if total.path.digit == 0:
            done = new_left_start_totals[total.path.place]
        else:
            done = Schema(-1, LeftBoundDigit(total.path.place, total.path.digit, DigitStatus.DONE), 0)
        classes['ct'].append(done)
        add_rule(lookup, Rule(
            [start, *['ct'] * total.path.place],
            [new_left_start_totals[total.path.place]],
            [*['ct'] * (WIDTH_MARKER_PLACES - 1), total],
            [done]))
    return [lookup]

def dist(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup('dist', 'dupl', 'dflt', 0)
    for schema in new_glyphs:
        if not isinstance(schema, Schema):
            continue
        if ((isinstance(schema.path, LeftBoundDigit)
                or isinstance(schema.path, RightBoundDigit)
                or isinstance(schema.path, CursiveWidthDigit))
                and schema.path.status == DigitStatus.DONE):
            digit = schema.path.digit
            if schema.path.place == WIDTH_MARKER_PLACES - 1 and digit >= WIDTH_MARKER_RADIX / 2:
                digit -= WIDTH_MARKER_RADIX
            x_advance = digit * WIDTH_MARKER_RADIX ** schema.path.place
            if not isinstance(schema.path, RightBoundDigit):
                x_advance = -x_advance
            if schema.path.place == 0 and not isinstance(schema.path, CursiveWidthDigit):
                x_advance += DEFAULT_SIDE_BEARING
            if x_advance:
                add_rule(lookup, Rule([], [schema], [], x_advances=[x_advance]))
    return [lookup]

def add_rule(autochthonous_schemas, output_schemas, classes, lookup, rule):
    for input in rule.inputs:
        if isinstance(input, str):
            if all(s in autochthonous_schemas for s in classes[input]):
                return
        elif input in autochthonous_schemas:
            return
    lookup.append(rule)
    if lookup.required and not rule.contexts_in and not rule.contexts_out and len(rule.inputs) == 1:
        input = rule.inputs[0]
        if isinstance(input, str):
            for i in classes[input]:
                output_schemas.remove(i)
        else:
            output_schemas.remove(input)
    if rule.outputs is not None:
        for output in rule.outputs:
            if isinstance(output, str):
                for o in classes[output]:
                    output_schemas.add(o)
            else:
                output_schemas.add(output)

def run_phases(all_input_schemas, phases):
    all_schemas = OrderedSet(all_input_schemas)
    all_input_schemas = OrderedSet(all_input_schemas)
    all_lookups = []
    all_classes = {}
    all_named_lookups = {}
    for phase in phases:
        all_output_schemas = OrderedSet()
        autochthonous_schemas = OrderedSet()
        new_input_schemas = OrderedSet(all_input_schemas)
        output_schemas = OrderedSet(all_input_schemas)
        classes = collections.defaultdict(list)
        named_lookups = collections.defaultdict(list)
        lookups = None
        while new_input_schemas:
            output_lookups = phase(
                all_input_schemas,
                new_input_schemas,
                classes,
                named_lookups,
                lambda lookup, rule: add_rule(autochthonous_schemas, output_schemas, classes, lookup, rule))
            if lookups is None:
                lookups = output_lookups
            else:
                assert len(lookups) == len(output_lookups), 'Incompatible lookup counts for phase {}'.format(phase)
                for i, lookup in enumerate(lookups):
                    lookup.extend(output_lookups[i])
            if len(output_lookups) == 1:
                might_have_feedback = False
                lookup = output_lookups[0]
                for rule in lookup.rules:
                    if rule.contexts_out if lookup.reversed else rule.contexts_in:
                        might_have_feedback = True
                        break
            else:
                might_have_feedback = True
            for output_schema in output_schemas:
                if isinstance(output_schema, Schema):
                    all_output_schemas.add(output_schema)
            new_input_schemas = OrderedSet()
            if might_have_feedback:
                for output_schema in output_schemas:
                    if output_schema not in all_input_schemas:
                        all_input_schemas.add(output_schema)
                        autochthonous_schemas.add(output_schema)
                        new_input_schemas.add(output_schema)
        all_input_schemas = all_output_schemas
        all_schemas.update(all_input_schemas)
        all_lookups.extend(lookups)
        all_classes.update(classes)
        all_named_lookups.update(named_lookups)
    return all_schemas, all_lookups, all_classes, all_named_lookups

class Grouper:
    def __init__(self, groups):
        self._groups = []
        self._inverted = {}
        for group in groups:
            if len(group) > 1:
                self.add(group)

    def groups(self):
        return list(self._groups)

    def group_of(self, item):
        return self._inverted.get(item)

    def add(self, group):
        self._groups.append(group)
        for item in group:
            self._inverted[item] = group

    def remove(self, group):
        self._groups.remove(group)
        for item in group:
            del self._inverted[item]

    def remove_item(self, group, item):
        group.remove(item)
        del self._inverted[item]

    def remove_items(self, minuend, subtrahend):
        for item in subtrahend:
            try:
                self.remove_item(minuend, item)
            except ValueError:
                pass

def group_schemas(schemas):
    group_dict = collections.defaultdict(list)
    for schema in schemas:
        group_dict[schema.group].append(schema)
    return Grouper(group_dict.values())

def sift_groups(grouper, rule, target_part, classes):
    for s in target_part:
        if isinstance(s, str):
            cls = classes[s]
            cls_intersection = set(cls).intersection
            for group in grouper.groups():
                intersection_set = cls_intersection(group)
                overlap = len(intersection_set)
                if overlap:
                    if overlap == len(group):
                        intersection = group
                    else:
                        grouper.remove_items(group, intersection_set)
                        if len(group) == 1:
                            grouper.remove(group)
                        if overlap != 1:
                            intersection = [x for x in cls if x in intersection_set]
                            grouper.add(intersection)
                    if overlap != 1 and target_part is rule.inputs and len(target_part) == 1:
                        if len(rule.outputs) == 1:
                            # a single substitution, or a (chaining) contextual substitution that
                            # calls a single substitution
                            output = rule.outputs[0]
                            if isinstance(output, str):
                                output = classes[output]
                                if len(output) != 1:
                                    # non-singleton glyph class
                                    grouper.remove(intersection)
                                    new_groups = collections.defaultdict(list)
                                    for input_schema, output_schema in zip(cls, output):
                                        if input_schema in intersection_set:
                                            key = id(grouper.group_of(output_schema) or output_schema)
                                            new_groups[key].append(input_schema)
                                    for new_group in new_groups.values():
                                        if len(new_group) != 1:
                                            grouper.add(new_group)
                        # Not implemented:
                        # chaining subsitution, general form
                        #   substitute $class' lookup $lookup ...;
                        # reverse chaining subsitution, general form
                        #   reversesub $class' lookup $lookup ...;
                        # reverse chaining substitution, inline form, singleton glyph class
                        #   reversesub $backtrack $class' $lookahead by $singleton;
                        # reverse chaining substitution, inline form, non-singleton glyph class
                        #   reversesub $backtrack $class' $lookahead by $class;
        else:
            for group in grouper.groups():
                if s in group:
                    if len(group) == 2:
                        grouper.remove(group)
                    else:
                        grouper.remove_item(group, s)
                    break

def rename_schemas(groups):
    for group in groups:
        group.sort(key=Schema.sort_key)
        group = iter(group)
        canonical_schema = next(group)
        for schema in group:
            schema.canonical_schema(canonical_schema)

def merge_schemas(schemas, lookups, classes):
    grouper = group_schemas(schemas)
    for lookup in reversed(lookups):
        for rule in lookup.rules:
            sift_groups(grouper, rule, rule.contexts_in, classes)
            sift_groups(grouper, rule, rule.contexts_out, classes)
            sift_groups(grouper, rule, rule.inputs, classes)
    rename_schemas(grouper.groups())

def chord_to_radius(c, theta):
    return c / math.sin(math.radians(theta) / 2)

PHASES = [
    dont_ignore_default_ignorables,
    ligate_pernin_r,
    decompose,
    join_with_next_step,
    ss_pernin,
    join_with_previous,
    join_with_next,
    rotate_diacritics,
]

GLYPH_PHASES = [
    add_width_markers,
    sum_width_markers,
    calculate_bound_extrema,
    remove_false_start_markers,
    remove_false_end_markers,
    expand_start_markers,
    mark_maximum_bounds,
    copy_penultimate_cursive_width_to_end,
    copy_maximum_left_bound_to_start,
    dist,
]

SPACE = Space(0)
H = Dot()
P = Line(270)
P_REVERSE = Line(90)
T = Line(0)
T_REVERSE = Line(180)
F = Line(315)
F_REVERSE = Line(135)
K = Line(240)
K_REVERSE = Line(60)
L = Line(30)
L_REVERSE = Line(210)
L_SHALLOW = Line(25)
M = Curve(180, 0, False, 0.2)
M_REVERSE = Curve(180, 0, True, 0.2)
N = Curve(0, 180, True, 0.2)
N_REVERSE = Curve(0, 180, False, 0.2)
N_SHALLOW = Curve(295, 245, True)
J = Curve(90, 270, True, 0.2)
J_REVERSE = Curve(90, 270, False, 0.2)
J_SHALLOW = Curve(25, 335, True)
S = Curve(270, 90, False, 0.2)
S_REVERSE = Curve(270, 90, True, 0.2)
S_SHALLOW = Curve(335, 25, False)
M_S = Curve(180, 0, False, 0.8)
N_S = Curve(0, 180, True, 0.8)
J_S = Curve(90, 270, True, 0.8)
S_S = Curve(270, 90, False, 0.8)
J_N = Curve(90, 180, True)
S_T = Curve(270, 0, False)
S_P = Curve(270, 180, True)
T_S = Curve(0, 270, True)
W = Curve(180, 270, False)
S_N = Curve(0, 90, False)
K_R_S = Curve(90, 180, False)
S_K = Curve(90, 0, True)
O = Circle(0, 0, False, False)
O_REVERSE = Circle(0, 0, True, True)
LONG_U = Curve(225, 45, False, 4, True)
UH = Circle(45, 45, False, False, 2)
DOWN_STEP = Step('u1BCA2', 270)
UP_STEP = Step('u1BCA3', 90)
LINE = Line(90, True)

DOT_1 = Schema(-1, H, 1, anchor=RELATIVE_1_ANCHOR)
DOT_2 = Schema(-1, H, 1, anchor=RELATIVE_2_ANCHOR)
LINE_2 = Schema(-1, LINE, 0.35, Type.ORIENTING, anchor=RELATIVE_2_ANCHOR)
LINE_MIDDLE = Schema(-1, LINE, 0.45, Type.ORIENTING, anchor=MIDDLE_ANCHOR)

SCHEMAS = [
    Schema(0x0020, SPACE, 260, Type.NON_JOINING, 260),
    Schema(0x00A0, SPACE, 260, Type.NON_JOINING, 260),
    Schema(0x0304, T, 0, anchor=ABOVE_ANCHOR),
    Schema(0x0307, H, 1, anchor=ABOVE_ANCHOR),
    Schema(0x0323, H, 1, anchor=BELOW_ANCHOR),
    Schema(0x2000, SPACE, 500, side_bearing=500),
    Schema(0x2001, SPACE, 1000, side_bearing=1000),
    Schema(0x2002, SPACE, 500, side_bearing=500),
    Schema(0x2003, SPACE, 1000, side_bearing=1000),
    Schema(0x2004, SPACE, 333, side_bearing=333),
    Schema(0x2005, SPACE, 250, side_bearing=250),
    Schema(0x2006, SPACE, 167, side_bearing=167),
    Schema(0x2007, SPACE, 572, side_bearing=572),
    Schema(0x2008, SPACE, 268, side_bearing=268),
    Schema(0x2009, SPACE, 200, side_bearing=200),
    Schema(0x200A, SPACE, 100, side_bearing=100),
    Schema(0x200B, SPACE, 0, side_bearing=0, ignored=True),
    Schema(0x200C, SPACE, 0, Type.NON_JOINING, 0, ignored=True),
    Schema(0x200D, SPACE, 0, Type.NON_JOINING, 0),
    Schema(0x202F, SPACE, 200, side_bearing=200),
    Schema(0x205F, SPACE, 222, side_bearing=222),
    Schema(0x2060, SPACE, 0, side_bearing=0, ignored=True),
    Schema(0xEC02, P_REVERSE, 1),
    Schema(0xEC03, T_REVERSE, 1),
    Schema(0xEC04, F_REVERSE, 1),
    Schema(0xEC05, K_REVERSE, 1),
    Schema(0xEC06, L_REVERSE, 1),
    Schema(0xEC19, M_REVERSE, 6),
    Schema(0xEC1B, J_REVERSE, 6),
    Schema(0xEC1C, S_REVERSE, 6),
    Schema(0xFEFF, SPACE, 0, side_bearing=0, ignored=True),
    Schema(0x1BC00, H, 1),
    Schema(0x1BC02, P, 1),
    Schema(0x1BC03, T, 1),
    Schema(0x1BC04, F, 1),
    Schema(0x1BC05, K, 1),
    Schema(0x1BC06, L, 1, ss_pernin={'path': L_SHALLOW}),
    Schema(0x1BC07, P, 2),
    Schema(0x1BC08, T, 2),
    Schema(0x1BC09, F, 2),
    Schema(0x1BC0A, K, 2),
    Schema(0x1BC0B, L, 2, ss_pernin={'path': L_SHALLOW}),
    Schema(0x1BC0C, P, 3),
    Schema(0x1BC0D, T, 3),
    Schema(0x1BC0E, F, 3),
    Schema(0x1BC0F, K, 3),
    Schema(0x1BC10, L, 3, ss_pernin={'path': L_SHALLOW}),
    Schema(0x1BC11, T, 1, marks=[DOT_1]),
    Schema(0x1BC12, T, 1, marks=[DOT_2]),
    Schema(0x1BC13, T, 2, marks=[DOT_1]),
    Schema(0x1BC14, K, 1, marks=[DOT_2]),
    Schema(0x1BC15, K, 2, marks=[DOT_1]),
    Schema(0x1BC16, L, 1, marks=[DOT_1]),
    Schema(0x1BC17, L, 1, marks=[DOT_2]),
    Schema(0x1BC18, L, 2, marks=[DOT_1, DOT_2]),
    Schema(0x1BC19, M, 6),
    Schema(0x1BC1A, N, 6, ss_pernin={'path': N_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC1B, J, 6, ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC1C, S, 6, ss_pernin={'path': S_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC1D, M, 6, marks=[LINE_MIDDLE]),
    Schema(0x1BC1E, N, 6, marks=[LINE_MIDDLE]),
    Schema(0x1BC1F, J, 6, marks=[LINE_MIDDLE]),
    Schema(0x1BC20, S, 6, marks=[LINE_MIDDLE]),
    Schema(0x1BC21, M, 6, marks=[DOT_1]),
    Schema(0x1BC22, N, 6, marks=[DOT_1]),
    Schema(0x1BC23, J, 6, marks=[DOT_1], ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC24, J, 6, marks=[DOT_1, DOT_2]),
    Schema(0x1BC25, S, 6, marks=[DOT_1], ss_pernin={'path': S_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC26, S, 6, marks=[DOT_2]),
    Schema(0x1BC27, M_S, 8),
    Schema(0x1BC28, N_S, 8),
    Schema(0x1BC29, J_S, 8, ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(8, 50)}),
    Schema(0x1BC2A, S_S, 8),
    Schema(0x1BC2B, M_S, 8, marks=[LINE_MIDDLE]),
    Schema(0x1BC2C, N_S, 8, marks=[LINE_MIDDLE]),
    Schema(0x1BC2D, J_S, 8, marks=[LINE_MIDDLE]),
    Schema(0x1BC2E, S_S, 8, marks=[LINE_MIDDLE]),
    Schema(0x1BC2F, J_S, 8, marks=[DOT_1], ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(8, 50)}),
    Schema(0x1BC30, J_N, 6),
    Schema(0x1BC32, S_T, 4),
    Schema(0x1BC33, S_T, 6),
    Schema(0x1BC34, S_P, 4),
    Schema(0x1BC35, S_P, 6),
    Schema(0x1BC36, T_S, 4),
    Schema(0x1BC37, T_S, 6),
    Schema(0x1BC38, W, 4),
    Schema(0x1BC39, W, 4, marks=[DOT_1]),
    Schema(0x1BC3A, W, 6),
    Schema(0x1BC3B, S_N, 4),
    Schema(0x1BC3C, S_N, 6),
    Schema(0x1BC3D, K_R_S, 4),
    Schema(0x1BC3E, K_R_S, 6),
    Schema(0x1BC3F, S_K, 4),
    Schema(0x1BC40, S_K, 6),
    Schema(0x1BC41, O, 2, Type.ORIENTING, styles=[Style.PERNIN]),
    Schema(0x1BC42, O_REVERSE, 2, Type.ORIENTING),
    Schema(0x1BC43, O, 3, Type.ORIENTING, styles=[Style.PERNIN]),
    Schema(0x1BC44, O, 4, Type.ORIENTING, styles=[Style.PERNIN]),
    Schema(0x1BC45, O, 5, Type.ORIENTING),
    Schema(0x1BC46, M, 2, Type.ORIENTING),
    Schema(0x1BC47, S, 2, Type.ORIENTING),
    Schema(0x1BC48, M, 2),
    Schema(0x1BC49, N, 2),
    Schema(0x1BC4A, J, 2),
    Schema(0x1BC4B, S, 2),
    Schema(0x1BC4C, S, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC4D, S, 2, Type.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC4E, S, 2, Type.ORIENTING, marks=[LINE_2]),
    Schema(0x1BC51, S_T, 2, Type.ORIENTING),
    Schema(0x1BC53, S_T, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC54, J_N, 4),
    Schema(0x1BC55, LONG_U, 2),
    Schema(0x1BC57, UH, 2, Type.ORIENTING),
    Schema(0x1BC58, UH, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC59, UH, 2, Type.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC5A, O, 4, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC65, S_P, 2, Type.ORIENTING),
    Schema(0x1BC66, W, 2, Type.ORIENTING),
    Schema(0x1BC78, LINE, 0.5, Type.ORIENTING, anchor=TANGENT_ANCHOR),
    Schema(0x1BC79, N_REVERSE, 6),
    Schema(0x1BCA2, DOWN_STEP, 800, side_bearing=0, ignored=True),
    Schema(0x1BCA3, UP_STEP, 800, side_bearing=0, ignored=True),
]

class Builder:
    def __init__(self, font, schemas=SCHEMAS, phases=PHASES):
        self.font = font
        self._schemas = schemas
        self._phases = phases
        self._fea = fontTools.feaLib.ast.FeatureFile()
        self._anchors = {}
        code_points = collections.defaultdict(int)
        for schema in schemas:
            if schema.cp != -1:
                code_points[schema.cp] += 1
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    '
            + '\n    '.join(map(hex, sorted(code_points.keys()))))

    def _add_lookup(self, feature_tag, anchor_class_name, lookup_flags=0):
        lookup = fontTools.feaLib.ast.LookupBlock(anchor_class_name)
        if lookup_flags:
            lookup.statements.append(fontTools.feaLib.ast.LookupFlagStatement(lookup_flags))
        self._fea.statements.append(lookup)
        self._anchors[anchor_class_name] = lookup
        feature = fontTools.feaLib.ast.FeatureBlock(feature_tag)
        feature.statements.append(fontTools.feaLib.ast.ScriptStatement('dupl'))
        feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
        feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self):
        self._add_lookup('curs', CURSIVE_ANCHOR, fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS)
        self._add_lookup('mark', RELATIVE_1_ANCHOR)
        self._add_lookup('mark', RELATIVE_2_ANCHOR)
        self._add_lookup('mark', MIDDLE_ANCHOR)
        self._add_lookup('mark', TANGENT_ANCHOR)
        self._add_lookup('mark', ABOVE_ANCHOR)
        self._add_lookup('mark', BELOW_ANCHOR)

    def _add_altuni(self, cp, glyph_name):
        glyph = self.font.temporary[glyph_name]
        if cp != -1:
            new_altuni = ((cp, -1, 0),)
            if glyph.altuni is None:
                glyph.altuni = new_altuni
            else:
                glyph.altuni += new_altuni
        return glyph

    def _draw_glyph_with_marks(self, schema, glyph_name):
        base_glyph = self._draw_glyph(schema.without_marks).glyphname
        mark_glyphs = []
        for mark in schema.marks:
            mark_glyphs.append(self._draw_glyph(mark).glyphname)
        glyph = self.font.createChar(schema.cp, glyph_name)
        self.font.temporary[glyph_name] = glyph
        glyph.glyphclass = 'baseligature'
        glyph.addReference(base_glyph)
        base_anchors = {p[0]: p for p in self.font[base_glyph].anchorPoints if p[1] == 'base'}
        for mark_glyph in mark_glyphs:
            mark_anchors = [p for p in self.font[mark_glyph].anchorPoints if p[1] == 'mark']
            assert len(mark_anchors) == 1
            mark_anchor = mark_anchors[0]
            base_anchor = base_anchors[mark_anchor[0]]
            glyph.addReference(mark_glyph, psMat.translate(
                base_anchor[2] - mark_anchor[2],
                base_anchor[3] - mark_anchor[3]))
        return glyph

    def _draw_base_glyph(self, schema, glyph_name):
        glyph = self.font.createChar(schema.cp, glyph_name)
        self.font.temporary[glyph_name] = glyph
        glyph.glyphclass = ('mark' if schema.anchor
            else 'baseglyph' if schema.joining_type == Type.NON_JOINING
            else 'baseligature')
        pen = glyph.glyphPen()
        schema.path(glyph, pen, schema.size, schema.anchor, schema.joining_type)
        return glyph

    def _draw_glyph(self, schema):
        glyph_name = str(schema)
        if glyph_name in self.font.temporary:
            return self._add_altuni(schema.cp, glyph_name)
        if glyph_name in self.font:
            return self.font[glyph_name]
        assert not schema.path.name_is_enough(), f'The SFD has no glyph named {glyph_name}'
        if schema.marks:
            glyph = self._draw_glyph_with_marks(schema, glyph_name)
        else:
            glyph = self._draw_base_glyph(schema, glyph_name)
        if schema.joining_type == Type.NON_JOINING:
            glyph.left_side_bearing = schema.side_bearing
            glyph.right_side_bearing = schema.side_bearing
        bbox = glyph.boundingBox()
        center_y = (bbox[3] - bbox[1]) / 2 + bbox[1]
        entry_x = next((x for _, type, x, _ in glyph.anchorPoints if type == 'entry'), 0)
        glyph.transform(psMat.translate(-entry_x, BASELINE - center_y))
        glyph.width = 0
        return glyph

    def _complete_gpos(self):
        mark_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        base_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        cursive_positions = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))
        for glyph in self.font.glyphs():
            for anchor_class_name, type, x, y in glyph.anchorPoints:
                x = round(x)
                y = round(y)
                glyph_name = glyph.glyphname
                if type == 'mark':
                    mark_positions[anchor_class_name][(x, y)].append(glyph_name)
                elif type == 'base':
                    base_positions[anchor_class_name][(x, y)].append(glyph_name)
                elif type == 'entry':
                    cursive_positions[anchor_class_name][glyph_name][0] = fontTools.feaLib.ast.Anchor(x, y)
                elif type == 'exit':
                    cursive_positions[anchor_class_name][glyph_name][1] = fontTools.feaLib.ast.Anchor(x, y)
                else:
                    raise RuntimeError('Unknown anchor type: {}'.format(type))
        for anchor_class_name, lookup in self._anchors.items():
            mark_class = fontTools.feaLib.ast.MarkClass(anchor_class_name)
            for x_y, glyph_class in mark_positions[anchor_class_name].items():
                mark_class_definition = fontTools.feaLib.ast.MarkClassDefinition(
                    mark_class,
                    fontTools.feaLib.ast.Anchor(*x_y),
                    glyph_class)
                mark_class.addDefinition(mark_class_definition)
                lookup.statements.append(mark_class_definition)
            for x_y, glyph_class in base_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.MarkBasePosStatement(
                    glyph_class,
                    [(fontTools.feaLib.ast.Anchor(*x_y), mark_class)]))
            for glyph_name, entry_exit in cursive_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.CursivePosStatement(
                    fontTools.feaLib.ast.GlyphName(glyph_name),
                    *entry_exit))

    def _recreate_gdef(self):
        bases = []
        marks = []
        ligatures = []
        for glyph in self.font.glyphs():
            glyph_class = glyph.glyphclass
            if glyph_class == 'baseglyph':
                bases.append(glyph.glyphname)
            elif glyph_class == 'mark':
                marks.append(glyph.glyphname)
            elif glyph_class == 'baseligature':
                ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            fontTools.feaLib.ast.GlyphClass(bases),
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    def _create_marker(self, schema):
        assert schema.cp == -1, f'A marker has the code point U+{schema.cp:X}'
        glyph = self.font.createChar(schema.cp, str(schema))
        glyph.glyphclass = 'mark'
        glyph.width = 0

    def augment(self):
        self._add_lookups()
        self.font.temporary = {}
        schemas, lookups, classes, named_lookups = run_phases(self._schemas, self._phases)
        assert not named_lookups, 'Named lookups have not been implemented for pre-merge phases'
        merge_schemas(schemas, lookups, classes)
        for schema in schemas:
            self._draw_glyph(schema)
        schemas, more_lookups, more_classes, more_named_lookups = run_phases([Hashable(g) for g in self.font.glyphs()], GLYPH_PHASES)
        lookups += more_lookups
        classes.update(more_classes)
        named_lookups.update(more_named_lookups)
        for schema in schemas:
            if isinstance(schema, Schema):
                self._create_marker(schema)
        class_asts = {}
        named_lookup_asts = {}
        for name, schemas in classes.items():
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                name,
                fontTools.feaLib.ast.GlyphClass([str(s) for s in schemas]))
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        for name, lookup in named_lookups.items():
            named_lookup_ast = lookup.to_ast(class_asts, None, name=name)
            self._fea.statements.append(named_lookup_ast)
            named_lookup_asts[name] = named_lookup_ast
        self._fea.statements.extend(l.to_ast(class_asts, named_lookup_asts) for l in lookups)

    def merge_features(self, tt_font, old_fea):
        self._fea.statements.extend(
            fontTools.feaLib.parser.Parser(
                io.StringIO(old_fea),
                tt_font.getReverseGlyphMap())
            .parse().statements)
        self._complete_gpos()
        self._recreate_gdef()
        fontTools.feaLib.builder.addOpenTypeFeatures(
                tt_font,
                self._fea,
                ['GDEF', 'GPOS', 'GSUB'])

