# Copyright 2018-2019 David Corbett
# Copyright 2019-2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__all__ = ['Builder']

import collections
import enum
import itertools
import io
import math
import re
import unicodedata

import fontforge
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
LIGHT_LINE = 70
SHADED_LINE = 120
MAX_TREE_WIDTH = 2
MAX_TREE_DEPTH = 3
CONTINUING_OVERLAP_CLASS = '_cont'
PARENT_EDGE_CLASS = '_pe'
CHILD_EDGE_CLASSES = [f'_ce{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]
INTER_EDGE_CLASSES = [[f'_edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]
CURSIVE_ANCHOR = 'cursive'
CONTINUING_OVERLAP_ANCHOR = 'cont'
PARENT_EDGE_ANCHOR = 'pe'
CHILD_EDGE_ANCHORS = [[f'ce{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(min(2, MAX_TREE_DEPTH))]
INTER_EDGE_ANCHORS = [[f'edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]
RELATIVE_1_ANCHOR = 'rel1'
RELATIVE_2_ANCHOR = 'rel2'
MIDDLE_ANCHOR = 'mid'
ABOVE_ANCHOR = 'abv'
BELOW_ANCHOR = 'blw'
CLONE_DEFAULT = object()
MAX_GLYPH_NAME_LENGTH = 63 - 2 - 4
WIDTH_MARKER_RADIX = 4
WIDTH_MARKER_PLACES = 7

assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'

def mkmk(anchor):
    return f'mkmk_{anchor}'

class Type(enum.Enum):
    JOINING = enum.auto()
    ORIENTING = enum.auto()
    NON_JOINING = enum.auto()

class Context:
    def __init__(self, angle=None, clockwise=None):
        self.angle = angle
        self.clockwise = clockwise

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
    ):
        return Context(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
        )

    def __repr__(self):
        return 'Context({}, {})'.format(self.angle, self.clockwise)

    def __str__(self):
        if self.angle is None:
            return ''
        return '{}{}'.format(
                self.angle,
                '' if self.clockwise is None else 'neg' if self.clockwise else 'pos'
            )

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

    def name_in_sfd(self):
        return None

    def __str__(self):
        raise NotImplementedError

    def group(self):
        return str(self)

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        raise NotImplementedError

    def can_be_child(self):
        return False

    def max_tree_width(self, size):
        return 0

    def is_shadable(self):
        return False

    def contextualize(self, context_in, context_out):
        raise NotImplementedError

    def context_in(self):
        raise NotImplementedError

    def context_out(self):
        raise NotImplementedError

    def calculate_diacritic_angles(self):
        return {}

    def must_be_mark(self):
        return False

class SFDGlyphWrapper(Shape):
    def __init__(self, sfd_name):
        self.sfd_name = sfd_name

    def clone(
        self,
        *,
        sfd_name=CLONE_DEFAULT,
    ):
        return type(self)(
            self.sfd_name if sfd_name is CLONE_DEFAULT else sfd_name,
        )

    def __str__(self):
        return ''

    def group(self):
        return self.sfd_name

    def name_in_sfd(self):
        return self.sfd_name

class Dummy(Shape):
    def __str__(self):
        return '_'

    def must_be_mark(self):
        return True

class Start(Shape):
    def __str__(self):
        return '_.START'

    def must_be_mark(self):
        return True

class End(Shape):
    def __str__(self):
        return '_.END'

    def must_be_mark(self):
        return True

class VeryEnd(Shape):
    def __str__(self):
        return '_.VERYEND'

class Carry(Shape):
    def __init__(self, value):
        self.value = int(value)
        assert self.value == value, value

    def __str__(self):
        return f'_.c.{self.value}'

    def must_be_mark(self):
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

    def must_be_mark(self):
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

    def must_be_mark(self):
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

    def must_be_mark(self):
        return True

class Space(Shape):
    def __init__(self, angle, with_margin=True):
        self.angle = angle
        self.with_margin = with_margin

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        with_margin=CLONE_DEFAULT,
    ):
        return Space(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.with_margin if with_margin is CLONE_DEFAULT else with_margin,
        )

    def __str__(self):
        return str(int(self.angle))

    def group(self):
        return (
            self.angle,
            self.with_margin,
        )

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', (size + self.with_margin * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class InvalidDTLS(SFDGlyphWrapper):
    def __str__(self):
        return ''

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class ChildEdgeCount(Shape):
    def __init__(self, count):
        self.count = count

    def clone(
        self,
        *,
        count=CLONE_DEFAULT,
    ):
        return ChildEdgeCount(
            self.count if count is CLONE_DEFAULT else count,
        )

    def __str__(self):
        return f'_width.{self.count}'

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        pass

    def must_be_mark(self):
        return True

class ChildEdge(Shape):
    def __init__(self, lineage):
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage=CLONE_DEFAULT,
    ):
        return ChildEdge(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self):
        return f'''{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_' if len(self.lineage) == 1 else '_'.join(str(x[1]) for x in self.lineage[:-1]) if self.lineage else '0'
            }'''

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        layer_index = len(self.lineage) - 1
        child_index = self.lineage[-1][0] - 1
        glyph.addAnchorPoint(CHILD_EDGE_ANCHORS[min(1, layer_index)][child_index], 'mark', 0, 0)
        glyph.addAnchorPoint(INTER_EDGE_ANCHORS[layer_index][child_index], 'basemark', 0, 0)

    def must_be_mark(self):
        return True

class ContinuingOverlap(Shape):
    def clone(self):
        return ContinuingOverlap()

    def __str__(self):
        return ''

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        pass

    def must_be_mark(self):
        return True

class InvalidOverlap(SFDGlyphWrapper):
    def __init__(self, sfd_name, continuing):
        super().__init__(sfd_name)
        self.continuing = continuing

    def clone(
        self,
        *,
        sfd_name=CLONE_DEFAULT,
        continuing=CLONE_DEFAULT,
    ):
        return InvalidOverlap(
            self.sfd_name if sfd_name is CLONE_DEFAULT else sfd_name,
            self.continuing if continuing is CLONE_DEFAULT else continuing,
        )

    def __str__(self):
        return 'fallback'

class ParentEdge(Shape):
    def __init__(self, lineage):
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage=CLONE_DEFAULT,
    ):
        return ParentEdge(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self):
        return f'''_pe.{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_'.join(str(x[1]) for x in self.lineage) if self.lineage else '0'
            }'''

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        if self.lineage:
            layer_index = len(self.lineage) - 1
            child_index = self.lineage[-1][0] - 1
            glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'basemark', 0, 0)
            glyph.addAnchorPoint(INTER_EDGE_ANCHORS[layer_index][child_index], 'mark', 0, 0)

    def must_be_mark(self):
        return True

class InvalidStep(SFDGlyphWrapper):
    def __init__(self, sfd_name, angle):
        super().__init__(sfd_name)
        self.angle = angle

    def clone(
        self,
        *,
        sfd_name=CLONE_DEFAULT,
        angle=CLONE_DEFAULT,
    ):
        return InvalidStep(
            self.sfd_name if sfd_name is CLONE_DEFAULT else sfd_name,
            self.angle if angle is CLONE_DEFAULT else angle,
        )

    def __str__(self):
        return 'fallback'

    def contextualize(self, context_in, context_out):
        return Space(self.angle)

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Dot(Shape):
    def __str__(self):
        return ''

    def clone(self):
        return Dot()

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        assert not child
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', stroke_width, 'round')
        if anchor:
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *rect(0, 0))
            glyph.addAnchorPoint(anchor, 'mark', *rect(0, 0))
        elif joining_type != Type.NON_JOINING:
            x = 2 * DEFAULT_SIDE_BEARING + stroke_width
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', -x, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', x, 0)

    def is_shadable(self):
        return True

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
        return str(int(self.angle))

    def group(self):
        return (
            self.angle,
            self.fixed_length,
        )

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
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
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *rect(length / 2, 0))
            glyph.addAnchorPoint(anchor, 'mark', *rect(length / 2, 0))
        else:
            anchor_name = mkmk if child else lambda a: a
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = length / (max_tree_width + 2)
                for child_index in range(max_tree_width):
                    glyph.addAnchorPoint(
                        CHILD_EDGE_ANCHORS[int(child)][child_index],
                        base,
                        child_interval * (child_index + 2),
                        0,
                    )
                if child:
                    glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'mark', child_interval, 0)
                else:
                    glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'entry', child_interval, 0)
                    glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'exit', child_interval * (max_tree_width + 1), 0)
                    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
                    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', length, 0)
            if size == 2 and self.angle == 45:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, length / 2 - 2 * LIGHT_LINE, -(stroke_width + LIGHT_LINE) / 2)
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, length / 2 + 2 * LIGHT_LINE, -(stroke_width + LIGHT_LINE) / 2)
            else:
                if size == 1 and self.angle == 240:
                    # Special case for U+1BC4F DUPLOYAN LETTER LONG I
                    glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, -(stroke_width + LIGHT_LINE), 0)
                else:
                    glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, length / 2, (stroke_width + LIGHT_LINE) / 2)
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, length / 2, -(stroke_width + LIGHT_LINE) / 2)
            glyph.addAnchorPoint(anchor_name(MIDDLE_ANCHOR), base, length / 2, 0)
        glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))
        glyph.stroke('circular', stroke_width, 'round')

    def can_be_child(self):
        return True

    def max_tree_width(self, size):
        return 2 if size == 2 else 1

    def is_shadable(self):
        return True

    def contextualize(self, context_in, context_out):
        return self if context_in.angle is None else self.clone(angle=context_in.angle)

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
        }

    def reversed(self):
        return self.clone(angle=(self.angle + 180) % 360)

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
        return f'''{
                int(self.angle_in)
            }{
                'n' if self.clockwise else 'p'
            }{
                int(self.angle_out)
            }'''

    def group(self):
        return (
            self.angle_in,
            self.angle_out,
            self.clockwise,
            self.stretch,
            self.long,
        )

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
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
        anchor_name = mkmk if child else lambda a: a
        base = 'basemark' if child else 'base'
        if joining_type != Type.NON_JOINING:
            max_tree_width = self.max_tree_width(size)
            child_interval = da / (max_tree_width + 2)
            for child_index in range(max_tree_width):
                glyph.addAnchorPoint(
                    CHILD_EDGE_ANCHORS[int(child)][child_index],
                    base,
                    *rect(r, math.radians(a1 + child_interval * (child_index + 2))),
                )
            if child:
                glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'mark', *rect(r, math.radians(a1 + child_interval)))
            else:
                glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'entry', *rect(r, math.radians(a1 + child_interval)))
                glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'exit', *rect(r, math.radians(a1 + child_interval * (max_tree_width + 1))))
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', p3[0], p3[1])
        glyph.addAnchorPoint(anchor_name(MIDDLE_ANCHOR), base, *rect(r, math.radians(relative_mark_angle)))
        if joining_type == Type.ORIENTING:
            glyph.addAnchorPoint(anchor_name(ABOVE_ANCHOR), base, *rect(r + stroke_width + LIGHT_LINE, math.radians(90)))
            glyph.addAnchorPoint(anchor_name(BELOW_ANCHOR), base, *rect(r + stroke_width + LIGHT_LINE, math.radians(270)))
        if self.stretch:
            scale_x = 1.0
            scale_y = 1.0 + self.stretch
            if self.long:
                scale_x, scale_y = scale_y, scale_x
            theta = math.radians(self.angle_in % 180)
            glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, *rect(0, 0))
            glyph.transform(psMat.compose(psMat.rotate(-theta), psMat.compose(psMat.scale(scale_x, scale_y), psMat.rotate(theta))))
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(scale_x * r + stroke_width + LIGHT_LINE, math.radians(self.angle_in)))
        else:
            glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base,
                *(rect(0, 0) if abs(da) > 180 else rect(
                    min(stroke_width, r - (stroke_width + LIGHT_LINE)),
                    math.radians(relative_mark_angle))))
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(r + stroke_width + LIGHT_LINE, math.radians(relative_mark_angle)))
        glyph.stroke('circular', stroke_width, 'round')

    def can_be_child(self):
        return True

    def max_tree_width(self, size):
        return 1

    def is_shadable(self):
        return True

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
        }

    def reversed(self):
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
        )

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
        return f'''{
                int(self.angle_in)
            }{
                'n' if self.clockwise else 'p'
            }{
                int(self.angle_out)
            }{
                '.rev' if self.reversed else ''
            }'''

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

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
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
        anchor_name = mkmk if child else lambda a: a
        base = 'basemark' if child else 'base'
        if joining_type != Type.NON_JOINING:
            if child:
                glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'mark', 0, 0)
            else:
                glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'entry', 0, 0)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *rect(r, math.radians(a2)))
        glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, *rect(0, 0))
        scale_x = 1.0 + self.stretch
        if self.stretch:
            scale_y = 1.0
            theta = math.radians(self.angle_in % 180)
            glyph.transform(psMat.compose(psMat.rotate(-theta), psMat.compose(psMat.scale(scale_x, scale_y), psMat.rotate(theta))))
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(scale_x * r + stroke_width + LIGHT_LINE, math.radians(self.angle_in)))
        else:
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(scale_x * r + stroke_width + LIGHT_LINE, math.radians((a1 + a2) / 2)))
        glyph.stroke('circular', stroke_width, 'round')

    def can_be_child(self):
        return True

    def max_tree_width(self, size):
        return 0

    def is_shadable(self):
        return True

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

class Complex(Shape):
    def __init__(
        self,
        instructions,
        *,
        hook=False,
        _all_circles=None
    ):
        self.instructions = instructions
        self.hook = hook
        if _all_circles is None:
            self._all_circles = all(not callable(op) and isinstance(op[1], Circle) for op in self.instructions)
        else:
            self._all_circles = _all_circles
        assert not (self.hook and self._all_circles)

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
        hook=CLONE_DEFAULT,
        _all_circles=CLONE_DEFAULT,
    ):
        return Complex(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            hook=self.hook if hook is CLONE_DEFAULT else hook,
            _all_circles=self._all_circles if _all_circles is CLONE_DEFAULT else _all_circles,
        )

    def __str__(self):
        return next(str(op[1]) for op in self.instructions if not callable(op))

    def group(self):
        return (
            *((op[0], op[1].group()) for op in self.instructions if not callable(op)),
            self._all_circles,
        )

    class Proxy:
        def __init__(self):
            self.anchor_points = collections.defaultdict(list)
            self.contour = fontforge.contour()

        def addAnchorPoint(self, anchor_class_name, anchor_type, x, y):
            self.anchor_points[(anchor_class_name, anchor_type)].append((x, y))

        def stroke(self, *args):
            pass

        def transform(self, matrix, *args):
            for anchor, points in self.anchor_points.items():
                for i, x_y in enumerate(points):
                    new_point = fontforge.point(*x_y).transform(matrix)
                    self.anchor_points[anchor][i] = (new_point.x, new_point.y)
            self.contour.transform(matrix)

        def moveTo(self, x_y):
            self.contour.moveTo(*x_y)

        def lineTo(self, x_y):
            self.contour.lineTo(*x_y)

        def curveTo(self, cp1, cp2, x_y):
            self.contour.cubicTo(cp1, cp2, x_y)

        def endPath(self):
            pass

        def get_crossing_point(self, component):
            entry_list = self.anchor_points[(CURSIVE_ANCHOR, 'entry')]
            assert len(entry_list) == 1
            if component.angle_in == component.angle_out:
                return entry_list[0]
            exit_list = self.anchor_points[(CURSIVE_ANCHOR, 'exit')]
            assert len(exit_list) == 1
            if isinstance(component, Circle):
                rel1_list = self.anchor_points[(RELATIVE_1_ANCHOR, 'base')]
                assert len(rel1_list) == 1
                rel2_list = self.anchor_points[(RELATIVE_2_ANCHOR, 'base')]
                assert len(rel2_list) == 1
                r = math.hypot(entry_list[0][1] - rel1_list[0][1], entry_list[0][0] - rel1_list[0][0])
                theta = math.atan2(rel2_list[0][1] - rel1_list[0][1], rel2_list[0][0] - rel1_list[0][0])
                return rect(r, theta)
            asx = entry_list[0][0]
            asy = entry_list[0][1]
            bsx = exit_list[0][0]
            bsy = exit_list[0][1]
            adx = math.cos(math.radians(component.angle_in))
            ady = math.sin(math.radians(component.angle_in))
            bdx = math.cos(math.radians(component.angle_out))
            bdy = math.sin(math.radians(component.angle_out))
            dx = bsx - asx
            dy = bsy - asy
            det = bdx * ady - bdy * adx
            if abs(det) < EPSILON:
                return 0, 0
            u = (dy * bdx - dx * bdy) / det
            v = (dy * adx - dx * ady) / det
            px = asx + adx * u
            py = asy + ady * u
            return px, py

    def __call__(self, glyph, pen, stroke_width, size, anchor, joining_type, child):
        first_entry = None
        last_exit = None
        last_rel1 = None
        last_crossing_point = False
        for op in self.instructions:
            if callable(op):
                continue
            scalar, component = op
            proxy = Complex.Proxy()
            component(proxy, proxy, stroke_width, scalar * size, anchor, Type.JOINING, False)
            entry_list = proxy.anchor_points[(CURSIVE_ANCHOR, 'entry')]
            assert len(entry_list) == 1
            if self._all_circles and last_crossing_point is not None:
                this_point = proxy.get_crossing_point(component)
                if first_entry is None:
                    first_entry = entry_list[0]
                else:
                    proxy.transform(psMat.translate(
                        last_crossing_point[0] - this_point[0],
                        last_crossing_point[1] - this_point[1],
                    ))
            else:
                this_point = entry_list[0]
                if first_entry is None:
                    first_entry = this_point
                else:
                    proxy.transform(psMat.translate(
                        last_exit[0] - this_point[0],
                        last_exit[1] - this_point[1],
                    ))
            proxy.contour.draw(pen)
            rel1_list = proxy.anchor_points[(RELATIVE_1_ANCHOR, 'base')]
            assert len(rel1_list) <= 1
            if rel1_list:
                last_rel1 = rel1_list[0]
            exit_list = proxy.anchor_points[(CURSIVE_ANCHOR, 'exit')]
            assert len(exit_list) == 1
            if self._all_circles:
                last_crossing_point = this_point
                if last_exit is None:
                    last_exit = exit_list[0]
            else:
                last_exit = exit_list[0]
                last_crossing_point = None
        glyph.stroke('circular', stroke_width, 'round')
        glyph.removeOverlap()
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *first_entry)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *last_exit)
        glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', *last_rel1)
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        glyph.addAnchorPoint(ABOVE_ANCHOR, 'base', (x_max + x_min) / 2, y_max + stroke_width + LIGHT_LINE)
        glyph.addAnchorPoint(BELOW_ANCHOR, 'base', (x_max + x_min) / 2, y_min - stroke_width + LIGHT_LINE)

    def can_be_child(self):
        #return not callable(self.instructions[0]) and self.instructions[0][1].can_be_child()
        return False

    def max_tree_width(self, size):
        #return min(op[1].max_tree_width(size) for op in self.instructions if not callable(op))
        return 0

    def is_shadable(self):
        return all(callable(op) or op[1].is_shadable() for op in self.instructions)

    def contextualize(self, context_in, context_out):
        instructions = []
        initial_hook = context_in == NO_CONTEXT and self.hook
        if self._all_circles:
            for scalar, component in self.instructions:
                component = component.contextualize(context_in, context_out)
                instructions.append((scalar, component))
        else:
            forced_context = None
            for i, op in enumerate(self.instructions):
                if callable(op):
                    forced_context = op(forced_context or (context_out if initial_hook else context_in))
                    instructions.append(op)
                else:
                    scalar, component = op
                    component = component.contextualize(context_in, context_out)
                    if i and initial_hook:
                        component = component.reversed()
                    if forced_context is not None:
                        if isinstance(component, Line):
                            if forced_context.angle is not None:
                                component = component.clone(angle=forced_context.angle)
                        else:
                            if forced_context.clockwise is not None and forced_context.clockwise != component.clockwise:
                                component = component.reversed()
                            if forced_context.angle is not None and forced_context.angle != (component.angle_out if initial_hook else component.angle_in):
                                angle_out = component.angle_out
                                if component.clockwise and angle_out > component.angle_in:
                                    angle_out -= 360
                                elif not component.clockwise and angle_out < component.angle_in:
                                    angle_out += 360
                                da = angle_out - component.angle_in
                                if initial_hook:
                                    component = component.clone(
                                        angle_in=(forced_context.angle - da) % 360,
                                        angle_out=forced_context.angle,
                                    )
                                else:
                                    component = component.clone(
                                        angle_in=forced_context.angle,
                                        angle_out=(forced_context.angle + da) % 360,
                                    )
                    instructions.append((scalar, component))
                    if initial_hook:
                        context_out = component.context_in()
                    else:
                        context_in = component.context_out()
                    if forced_context is not None:
                        if initial_hook:
                            assert component.context_out() == forced_context, f'{component.context_out()} != {forced_context}'
                        else:
                            assert component.context_in() == forced_context, f'{component.context_in()} != {forced_context}'
                        forced_context = None
            if initial_hook:
                instructions.reverse()
        return self.clone(instructions=instructions)

    def context_in(self):
        return next(op for op in self.instructions if not callable(op))[1].context_in()

    def context_out(self):
        return self.instructions[-1][1].context_out()

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
        (r'^uniEC1A$', 'DUPLOYAN LETTER REVERSED N'),
        (r'^uniEC1B$', 'DUPLOYAN LETTER REVERSED J'),
        (r'^uniEC1C$', 'DUPLOYAN LETTER REVERSED S'),
        (r'^ZERO WIDTH SPACE$', 'ZWSP'),
        (r'^ZERO WIDTH NON-JOINER$', 'ZWNJ'),
        (r'^ZERO WIDTH JOINER$', 'ZWJ'),
        (r'^NARROW NO-BREAK SPACE$', 'NNBSP'),
        (r'^MEDIUM MATHEMATICAL SPACE$', 'MMSP'),
        (r'^WORD JOINER$', 'WJ'),
        (r'^ZERO WIDTH NO-BREAK SPACE$', 'ZWNBSP'),
        (r'^DUPLOYAN THICK LETTER SELECTOR$', 'DTLS'),
        (r'^COMBINING ', ''),
        (r'^DUPLOYAN ((LETTER|AFFIX( ATTACHED)?|SIGN|PUNCTUATION) )?', ''),
        (r'^SHORTHAND FORMAT ', ''),
        (r'\bACCENT\b', ''),
        (r'\bDIAERESIS\b', 'DIERESIS'),
        (r'\bDOTS INSIDE AND ABOVE\b', 'DOTS'),
        (r'\bFULL STOP\b', 'PERIOD'),
        (r' MARK$', ''),
        (r'\bQUAD\b', 'SPACE'),
        (r' (WITH|AND) ', ' '),
        (r'.+', lambda m: m.group(0).lower()),
        (r'[ -]+', '_'),
    ]]
    _SEQUENCE_NAME_SUBSTITUTIONS = [(re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in [
        (r'__zwj__', '___'),
        (r'((?:[a-z]+_)+)_dtls(?=__|$)', lambda m: m.group(1)[:-1].upper()),
    ]]
    _canonical_names = {}

    def __init__(
            self,
            cp,
            path,
            size,
            joining_type=Type.JOINING,
            side_bearing=DEFAULT_SIDE_BEARING,
            child=False,
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
        self.child = child
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
        self.glyph_class = self._calculate_glyph_class()
        self.group = self._calculate_group()
        self._glyph_name = None
        self._canonical_schema = self
        self.without_marks = marks and self.clone(cp=-1, marks=None)

    def sort_key(self):
        return (
            self.cp == -1,
            -1 in self.cps,
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
        child=CLONE_DEFAULT,
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
            self.child if child is CLONE_DEFAULT else child,
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

    def _calculate_glyph_class(self):
        return (
            'mark'
                if self.anchor or self.child or self.path.must_be_mark()
                else 'baseglyph'
                if self.joining_type == Type.NON_JOINING
                else 'baseligature'
        )

    def _calculate_group(self):
        return (
            type(self.path),
            self.path.group(),
            self.cps[-1] == 0x1BC9D,
            self.size,
            self.side_bearing,
            self.child,
            self.anchor,
            tuple(m.group for m in self.marks or []),
        )

    def canonical_schema(self, canonical_schema):
        self._canonical_schema = canonical_schema
        self._glyph_name = None

    def _calculate_name(self):
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
            agl_name, readable_name = zip(*[*map(get_names, cps)])
            joined_agl_name = '_'.join(agl_name)
            if agl_name == readable_name:
                name = joined_agl_name
            else:
                joined_readable_name = '__'.join(readable_name)
                for regex, repl in self._SEQUENCE_NAME_SUBSTITUTIONS:
                    joined_readable_name = regex.sub(repl, joined_readable_name)
                name = f'{joined_agl_name}.{joined_readable_name}'
        if self.cp == -1:
            if not name:
                name_from_path = str(self.path)
                if name_from_path.startswith('_'):
                    name = name_from_path
                else:
                    name = f'dupl.{type(self.path).__name__}'
                    if name_from_path:
                        name += f'.{name_from_path}'
                if self.anchor:
                    name += f'.{self.anchor}'
            elif self.joining_type == Type.ORIENTING or isinstance(self.path, ChildEdge):
                name += f'.{self.path}'
            if self.child:
                name += '.blws'
        if self.path.name_in_sfd():
            name_from_path = str(self.path)
            if name_from_path:
                name += f'.{name_from_path}'
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
                name = self._calculate_name()
                while len(name) > MAX_GLYPH_NAME_LENGTH:
                    name = name.rsplit('.', 1)[0]
                if name in self._canonical_names:
                    if self not in self._canonical_names[name]:
                        self._canonical_names[name].append(self)
                        name += '._{:X}'.format(len(self._canonical_names[name]) - 1)
                else:
                    self._canonical_names[name] = [self]
                self._glyph_name = name
        return self._glyph_name

    def contextualize(self, context_in, context_out):
        assert self.joining_type == Type.ORIENTING or isinstance(self.path, InvalidStep)
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
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
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
            assert feature not in [
                'rtlm',
                'frac',
                'numr',
                'dnom',
                'rand',
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
            ], f"The feature '{feature}' is not simple enough for the phase system to handle"
            self.required = feature in [
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
    lookup_1 = Lookup('abvs', 'dupl', 'dflt')
    lookup_2 = Lookup('abvs', 'dupl', 'dflt')
    for schema in schemas:
        if schema.ignored:
            add_rule(lookup_1, Rule([schema], [schema, schema]))
            add_rule(lookup_2, Rule([schema, schema], [schema]))
    return [lookup_1, lookup_2]

def validate_overlap_controls(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt')
    new_classes = {}
    global_max_tree_width = 0
    for schema in new_schemas:
        if isinstance(schema.path, ChildEdge):
            return [lookup]
        if isinstance(schema.path, InvalidOverlap):
            if schema.path.continuing:
                continuing_overlap = schema
            else:
                letter_overlap = schema
        elif not schema.anchor:
            max_tree_width = schema.path.max_tree_width(schema.size)
            if max_tree_width:
                if max_tree_width > global_max_tree_width:
                    global_max_tree_width = max_tree_width
                classes['vv_base'].append(schema)
                new_class = f'vv_base_{max_tree_width}'
                classes[new_class].append(schema)
                new_classes[max_tree_width] = new_class
    assert global_max_tree_width == MAX_TREE_WIDTH
    classes['vv_invalid'].append(letter_overlap)
    classes['vv_invalid'].append(continuing_overlap)
    valid_letter_overlap = letter_overlap.clone(cp=-1, path=ChildEdge(lineage=[(1, 0)]))
    valid_continuing_overlap = continuing_overlap.clone(cp=-1, path=ContinuingOverlap())
    classes['vv_valid'].append(valid_letter_overlap)
    classes['vv_valid'].append(valid_continuing_overlap)
    add_rule(lookup, Rule('vv_invalid', 'vv_invalid', [], 'vv_invalid'))
    add_rule(lookup, Rule('vv_valid', 'vv_invalid', [], 'vv_valid'))
    for i in range(global_max_tree_width - 2):
        add_rule(lookup, Rule([], [letter_overlap], [*[letter_overlap] * i, continuing_overlap, 'vv_invalid'], [letter_overlap]))
    if global_max_tree_width > 1:
        add_rule(lookup, Rule([], [continuing_overlap], 'vv_invalid', [continuing_overlap]))
    for max_tree_width, new_class in new_classes.items():
        add_rule(lookup, Rule([new_class], 'vv_invalid', ['vv_invalid'] * max_tree_width, 'vv_invalid'))
    add_rule(lookup, Rule(['vv_base'], [letter_overlap], [], [valid_letter_overlap]))
    classes['vv_base'].append(valid_letter_overlap)
    add_rule(lookup, Rule(['vv_base'], [continuing_overlap], [], [valid_continuing_overlap]))
    classes['vv_base'].append(valid_continuing_overlap)
    classes[CHILD_EDGE_CLASSES[0]].append(valid_letter_overlap)
    classes[INTER_EDGE_CLASSES[0][0]].append(valid_letter_overlap)
    classes[CONTINUING_OVERLAP_CLASS].append(valid_continuing_overlap)
    return [lookup]

def count_letter_overlaps(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt', 0)
    letter_overlap = next(s for s in new_schemas if isinstance(s.path, ChildEdge))
    for count in range(MAX_TREE_WIDTH, 0, -1):
        add_rule(lookup, Rule(
            [],
            [letter_overlap],
            [letter_overlap] * (count - 1),
            [Schema(-1, ChildEdgeCount(count), 0, Type.NON_JOINING, 0), letter_overlap]
        ))
    return [lookup]

def add_parent_edges(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('blws', 'dupl', 'dflt')
    root_parent_edge = Schema(-1, ParentEdge([]), 0, Type.NON_JOINING, 0)
    for child_index in range(MAX_TREE_WIDTH):
        if CHILD_EDGE_CLASSES[child_index] not in classes:
            classes[CHILD_EDGE_CLASSES[child_index]].append(root_parent_edge)
        for layer_index in range(MAX_TREE_DEPTH):
            if INTER_EDGE_CLASSES[layer_index][child_index] not in classes:
                classes[INTER_EDGE_CLASSES[layer_index][child_index]].append(root_parent_edge)
    for schema in new_schemas:
        if schema.joining_type != Type.NON_JOINING and not schema.anchor:
            add_rule(lookup, Rule([schema], [root_parent_edge, schema]))
    return [lookup]

def make_trees(node, edge, maximum_depth, *, top_widths=None, prefix_depth=None):
    if maximum_depth <= 0:
        return []
    trees = []
    if prefix_depth is None:
        subtrees = make_trees(node, edge, maximum_depth - 1)
        widths = range(MAX_TREE_WIDTH + 1) if top_widths is None else top_widths
        for width in widths:
            for index_set in itertools.product(range(len(subtrees)), repeat=width):
                tree = [node, *[edge] * width] if top_widths is None else []
                for i in index_set:
                    tree.extend(subtrees[i])
                trees.append(tree)
    elif prefix_depth == 1:
        trees.append([])
    else:
        shallow_subtrees = make_trees(node, edge, maximum_depth - 2)
        deep_subtrees = make_trees(node, edge, maximum_depth - 1, prefix_depth=prefix_depth - 1)
        widths = range(1, MAX_TREE_WIDTH + 1) if top_widths is None else top_widths
        for width in widths:
            for shallow_index_set in itertools.product(range(len(shallow_subtrees)), repeat=width - 1):
                for deep_subtree in deep_subtrees:
                    for edge_count in [width] if prefix_depth == 2 else range(width, MAX_TREE_WIDTH + 1):
                        tree = [node, *[edge] * edge_count] if top_widths is None else []
                        for i in shallow_index_set:
                            tree.extend(shallow_subtrees[i])
                        tree.extend(deep_subtree)
                        trees.append(tree)
    return trees

def invalidate_overlap_controls(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup(
        'rclt',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'iv',
        True,
    )
    for schema in new_schemas:
        if isinstance(schema.path, ParentEdge):
            node = schema
            classes['iv'].append(schema)
        elif isinstance(schema.path, ChildEdge):
            valid_letter_overlap = schema
            classes['iv'].append(schema)
        elif isinstance(schema.path, ContinuingOverlap):
            valid_continuing_overlap = schema
            classes['iv'].append(schema)
        elif isinstance(schema.path, InvalidOverlap):
            if schema.path.continuing:
                invalid_continuing_overlap = schema
            else:
                invalid_letter_overlap = schema
            classes['iv'].append(schema)
    classes['iv_valid'].append(valid_letter_overlap)
    classes['iv_valid'].append(valid_continuing_overlap)
    classes['iv_invalid'].append(invalid_letter_overlap)
    classes['iv_invalid'].append(invalid_continuing_overlap)
    add_rule(lookup, Rule([], 'iv_valid', 'iv_invalid', 'iv_invalid'))
    for older_sibling_count in range(MAX_TREE_WIDTH - 1, -1, -1):
        # A continuing overlap not at the top level must be licensed by an
        # ancestral continuing overlap.
        # TODO: Optimization: All but the youngest child can use
        # `valid_letter_overlap` instead of `'iv_valid'`.
        for subtrees in make_trees(node, 'iv_valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count]):
            for older_sibling_count_of_continuing_overlap in range(MAX_TREE_WIDTH):
                add_rule(lookup, Rule(
                    [valid_letter_overlap] * older_sibling_count,
                    [valid_letter_overlap],
                    [*subtrees, node, *[valid_letter_overlap] * older_sibling_count_of_continuing_overlap, valid_continuing_overlap],
                    [invalid_letter_overlap]
                ))
        # Trees have a maximum depth of `MAX_TREE_DEPTH` letters.
        # TODO: Optimization: Why use a nested `for` loop? Can a combination of
        # `top_width` and `prefix_depth` work?
        for subtrees in make_trees(node, valid_letter_overlap, MAX_TREE_DEPTH, top_widths=range(older_sibling_count + 1)):
            for deep_subtree in make_trees(node, 'iv_valid', MAX_TREE_DEPTH, prefix_depth=MAX_TREE_DEPTH):
                add_rule(lookup, Rule(
                    [valid_letter_overlap] * older_sibling_count,
                    'iv_valid',
                    [*subtrees, *deep_subtree],
                    'iv_invalid',
                ))
        # Anything valid needs to be explicitly kept valid, since there might
        # not be enough context to tell that an invalid overlap is invalid.
        # TODO: Optimization: The last subtree can just be one node instead of
        # the full subtree.
        for subtrees in make_trees(node, 'iv_valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count + 1]):
            add_rule(lookup, Rule(
                [valid_letter_overlap] * older_sibling_count if older_sibling_count else [node],
                'iv_valid',
                subtrees,
                'iv_valid',
            ))
    # If an overlap gets here without being kept valid, it is invalid.
    # FIXME: This should be just one rule, without context, but `add_rule`
    # is broken: it does not take into account what rules precede it in the
    # lookup when determining the possible output schemas.
    add_rule(lookup, Rule([], 'iv_valid', 'iv_valid', 'iv_valid'))
    add_rule(lookup, Rule([node], 'iv_valid', [], 'iv_invalid'))
    add_rule(lookup, Rule('iv_valid', 'iv_valid', [], 'iv_invalid'))
    return [lookup]

def categorize_edges(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup(
        'blws',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'ce',
    )
    old_groups = [s.path.group() for s in classes['ce']]
    child_edges = {}
    parent_edges = {}
    def get_child_edge(lineage):
        lineage = tuple(lineage)
        child_edge = child_edges.get(lineage)
        if child_edge is None:
            child_edge = default_child_edge.clone(cp=-1, path=default_child_edge.path.clone(lineage=lineage))
            child_edges[lineage] = child_edge
        return child_edge
    def get_parent_edge(lineage):
        lineage = tuple(lineage)
        parent_edge = parent_edges.get(lineage)
        if parent_edge is None:
            parent_edge = default_parent_edge.clone(cp=-1, path=default_parent_edge.path.clone(lineage=lineage))
            parent_edges[lineage] = parent_edge
        return parent_edge
    for schema in schemas:
        if isinstance(schema.path, ChildEdge):
            child_edges[tuple(schema.path.lineage)] = schema
            if (len(schema.path.lineage) == 1
                and schema.path.lineage[0][0] == 1
            ):
                default_child_edge = schema
        elif isinstance(schema.path, ParentEdge):
            parent_edges[tuple(schema.path.lineage)] = schema
            if not schema.path.lineage:
                default_parent_edge = schema
    for schema in new_schemas:
        if isinstance(schema.path, ChildEdge):
            classes['ce'].append(schema)
        elif isinstance(schema.path, ParentEdge):
            classes['ce'].append(schema)
    for edge in new_schemas:
        if edge.path.group() not in old_groups:
            if isinstance(edge.path, ChildEdge):
                lineage = list(edge.path.lineage)
                lineage[-1] = (lineage[-1][0] + 1, 0)
                if lineage[-1][0] <= MAX_TREE_WIDTH:
                    new_child_edge = get_child_edge(lineage)
                    classes[CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                    classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                    add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                lineage = list(edge.path.lineage)
                lineage[-1] = (1, lineage[-1][0])
                new_parent_edge = get_parent_edge(lineage)
                classes[PARENT_EDGE_CLASS].append(new_parent_edge)
                classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
            elif isinstance(edge.path, ParentEdge) and edge.path.lineage:
                lineage = list(edge.path.lineage)
                if len(lineage) < MAX_TREE_DEPTH:
                    lineage.append((1, lineage[-1][0]))
                    new_child_edge = get_child_edge(lineage)
                    classes[CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                    classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                    add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                lineage = list(edge.path.lineage)
                while lineage and lineage[-1][0] == lineage[-1][1]:
                    lineage.pop()
                if lineage:
                    lineage[-1] = (lineage[-1][0] + 1, lineage[-1][1])
                    if lineage[-1][0] <= MAX_TREE_WIDTH:
                        new_parent_edge = get_parent_edge(lineage)
                        classes[PARENT_EDGE_CLASS].append(new_parent_edge)
                        classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                        add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
    return [lookup]

def make_mark_variants_of_children(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('blws', 'dupl', 'dflt', 0)
    children_to_be = []
    for schema in new_schemas:
        if isinstance(schema.path, ParentEdge) and schema.path.lineage:
            classes['mv'].append(schema)
        elif (schema.joining_type != Type.NON_JOINING
            and not schema.anchor
            and not schema.child
            and schema.path.can_be_child()
        ):
            children_to_be.append(schema)
    for child_to_be in children_to_be:
        child = child_to_be.clone(cp=-1, child=True)
        classes[PARENT_EDGE_CLASS].append(child)
        for child_index in range(MAX_TREE_WIDTH):
            classes[CHILD_EDGE_CLASSES[child_index]].append(child)
        add_rule(lookup, Rule('mv', [child_to_be], [], [child]))
    return [lookup]

def ligate_pernin_r(schemas, new_schemas, classes, named_lookups, add_rule):
    liga = Lookup('liga', 'dupl', 'dflt')
    dlig = Lookup('dlig', 'dupl', 'dflt')
    vowels = []
    zwj = None
    r = None
    for schema in schemas:
        if schema.child:
            continue
        if schema.cps == [0x200D]:
            assert zwj is None, 'Multiple ZWJs found'
            zwj = schema
        elif schema.cps == [0x1BC06]:
            assert r is None, 'Multiple Pernin Rs found'
            r = schema
        elif (schema in new_schemas
            and isinstance(schema.path, Circle)
            and not schema.path.reversed
            and Style.PERNIN in schema.styles
            and len(schema.cps) == 1
        ):
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

def shade(schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup('rlig', 'dupl', 'dflt', 0)
    dtls = next(s for s in schemas if s.cps == [0x1BC9D])
    for schema in new_schemas:
        if not schema.anchor and len(schema.cps) == 1 and schema.path.is_shadable():
            add_rule(lookup, Rule(
                [schema, dtls],
                [schema.clone(cp=-1, cps=[*schema.cps, 0x1BC9D])]))
    return [lookup]

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
        if isinstance(schema.path, InvalidStep):
            classes['js_i'].append(schema)
        if (schema.joining_type != Type.NON_JOINING
            and not schema.anchor
            and not isinstance(schema.path, InvalidStep)
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
    lookup = Lookup(
        'rclt',
        'dupl',
        'dflt',
        0,
        mark_filtering_set=CONTINUING_OVERLAP_CLASS,
        reversed=True,
    )
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
                base_context_class = classes['rd_c_{}_{}'.format(*base_context)]
                if schema not in base_context_class:
                    if not base_context_class:
                        new_base_contexts.add(base_context)
                    base_context_class.append(schema)
    for base_context in base_contexts:
        if base_context in new_base_contexts:
            anchor, angle = base_context
            output_class_name = f'rd_o_{anchor}_{angle}'
            for target_schema in classes['rd_i_' + str(anchor)]:
                if anchor == target_schema.anchor:
                    output_schema = target_schema.rotate_diacritic(angle)
                    classes[output_class_name].append(output_schema)
            add_rule(lookup, Rule(f'rd_c_{anchor}_{angle}', f'rd_i_{anchor}', [], output_class_name))
    return [lookup]

def classify_marks_for_trees(schemas, new_schemas, classes, named_lookups, add_rule):
    for schema in schemas:
        for anchor in [
            RELATIVE_1_ANCHOR,
            RELATIVE_2_ANCHOR,
            MIDDLE_ANCHOR,
            ABOVE_ANCHOR,
            BELOW_ANCHOR,
        ]:
            if schema.child or schema.anchor == anchor:
                classes[f'_{mkmk(anchor)}'].append(schema)
    return []

def add_width_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookups_per_position = 12
    lookups_before = [Lookup('psts', 'dupl', 'dflt') for _ in range(lookups_per_position)]
    lookups_main = [Lookup('psts', 'dupl', 'dflt') for _ in range(lookups_per_position)]
    lookups_after = [Lookup('psts', 'dupl', 'dflt') for _ in range(lookups_per_position)]
    rule_count_before = 0
    rule_count_main = 0
    rule_count_after = 0
    carry_0_schema = Schema(-1, Carry(0), 0)
    left_bound_markers = {}
    right_bound_markers = {}
    cursive_width_markers = {}
    start = Schema(-1, Start(), 0)
    end = Schema(-1, End(), 0)
    very_end = Schema(-1, VeryEnd(), 0, Type.NON_JOINING)
    for glyph in new_glyphs:
        if isinstance(glyph, Schema):
            continue
        if glyph.glyphclass == 'baseligature':
            overlap_entry = None
            overlap_exit = None
            for anchor_class_name, type, x, _ in glyph.anchorPoints:
                if anchor_class_name == CURSIVE_ANCHOR:
                    if type == 'entry':
                        entry = x
                    elif type == 'exit':
                        exit = x
                elif anchor_class_name == CONTINUING_OVERLAP_ANCHOR:
                    if type == 'entry':
                        overlap_entry = x
                    elif type == 'exit':
                        overlap_exit = x
            if overlap_entry is None:
                overlap_entry = entry
            if overlap_exit is None:
                overlap_exit = exit
            x_min, _, x_max, _ = glyph.boundingBox()
            if x_min == x_max == 0:
                x_min = entry
                x_max = exit
            for segment_exit, segment_entry, peripheral, look_behind in [
                (overlap_entry, entry, True, True),
                (overlap_exit, overlap_entry, False, False),
                (exit, overlap_exit, True, False),
            ]:
                left_bound = x_min - segment_entry
                right_bound = x_max - segment_entry if not look_behind else 0
                cursive_width = segment_exit - segment_entry
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
                    if peripheral:
                        outputs = [glyph, *digits]
                        if look_behind:
                            lookup = lookups_before[rule_count_before % lookups_per_position]
                            rule_count_before += 1
                        else:
                            outputs.append(very_end)
                            lookup = lookups_after[rule_count_after % lookups_per_position]
                            rule_count_after += 1
                    else:
                        outputs = [start, glyph, end, *digits]
                        lookup = lookups_main[rule_count_main % lookups_per_position]
                        rule_count_main += 1
                    add_rule(lookup, Rule([glyph], outputs))
    return [*lookups_after, *lookups_main, *lookups_before]

def add_very_end_markers_for_marks(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup('psts', 'dupl', 'dflt', 0)
    very_end = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, VeryEnd))
    for glyph in new_glyphs:
        if (not isinstance(glyph, Schema)
            and glyph.glyphclass == 'mark'
            and not glyph.glyphname.startswith('_')
        ):
            add_rule(lookup, Rule([glyph], [glyph, very_end]))
    return [lookup]

def remove_false_very_end_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'fv',
    )
    if 'fv' in classes:
        return [lookup]
    dummy = Schema(-1, Dummy(), 0)
    very_end = next(s for s in new_glyphs if isinstance(s, Schema) and isinstance(s.path, VeryEnd))
    classes['fv'].append(very_end)
    add_rule(lookup, Rule([], [very_end], [very_end], [dummy]))
    return [lookup]

def clear_peripheral_width_markers(glyphs, new_glyphs, classes, named_lookups, add_rule):
    lookup = Lookup(
        'psts',
        'dupl',
        'dflt',
        fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        'zp',
    )
    zeros = [None] * WIDTH_MARKER_PLACES
    if 'zp_zero' not in named_lookups:
        named_lookups['zp_zero'] = Lookup(None, None, None)
    for glyph in glyphs:
        if isinstance(glyph, Schema):
            if isinstance(glyph.path, CursiveWidthDigit):
                classes['zp'].append(glyph)
                classes[f'zp_{glyph.path.place}'].append(glyph)
                if glyph.path.digit == 0:
                    zeros[glyph.path.place] = glyph
        else:
            # FIXME: Relying on glyph names is brittle.
            if glyph.glyphname.startswith('u1BCA1.'):
                classes['zp'].append(glyph)
                continuing_overlap = glyph
    for schema in new_glyphs:
        if isinstance(schema, Schema) and isinstance(schema.path, CursiveWidthDigit) and schema.path.digit != 0:
            add_rule(named_lookups['zp_zero'], Rule([schema], [zeros[schema.path.place]]))
    add_rule(lookup, Rule(
        [continuing_overlap],
        [f'zp_{place}' for place in range(WIDTH_MARKER_PLACES)],
        [],
        lookups=['zp_zero'] * WIDTH_MARKER_PLACES,
    ))
    add_rule(lookup, Rule(
        [],
        [f'zp_{place}' for place in range(WIDTH_MARKER_PLACES)],
        [continuing_overlap],
        lookups=['zp_zero'] * WIDTH_MARKER_PLACES,
    ))
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
    for schema in glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, Carry):
            carry_schemas[schema.path.value] = schema
            original_carry_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
                classes['sw_c'].append(schema)
        elif isinstance(schema.path, LeftBoundDigit):
            left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_left_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
                classes[f'sw_ldx_{schema.path.place}'].append(schema)
        elif isinstance(schema.path, RightBoundDigit):
            right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_right_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
                classes[f'sw_rdx_{schema.path.place}'].append(schema)
        elif isinstance(schema.path, CursiveWidthDigit):
            cursive_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
            original_cursive_digit_schemas.append(schema)
            if schema in new_glyphs:
                classes['sw'].append(schema)
                classes[f'sw_cdx_{schema.path.place}'].append(schema)
        elif isinstance(schema.path, Dummy):
            dummy = schema
    for augend_schema in original_cursive_digit_schemas:
        augend_is_new = augend_schema in new_glyphs
        place = augend_schema.path.place
        augend = augend_schema.path.digit
        for (
            skip_left,
            skip_right,
            original_digit_schemas,
            digit_schemas,
            digit_path,
        ) in [(
            True,
            True,
            original_cursive_digit_schemas,
            cursive_digit_schemas,
            CursiveWidthDigit,
        ), (
            False,
            False,
            original_left_digit_schemas,
            left_digit_schemas,
            LeftBoundDigit,
        ), (
            True,
            False,
            original_right_digit_schemas,
            right_digit_schemas,
            RightBoundDigit,
        )]:
            for carry_in_schema in original_carry_schemas:
                carry_in = carry_in_schema.path.value
                carry_in_is_new = carry_in_schema in new_glyphs
                if carry_in_is_new and carry_in_schema.path.value not in dummied_carry_schemas:
                    dummied_carry_schemas.add(carry_in_schema.path.value)
                    add_rule(lookup, Rule([carry_in_schema], [carry_schemas[0]], [], [dummy]))
                contexts_in = [augend_schema]
                for cursive_place in range(augend_schema.path.place + 1, WIDTH_MARKER_PLACES):
                    contexts_in.append('sw_c')
                    contexts_in.append(f'sw_cdx_{cursive_place}')
                for left_place in range(0, WIDTH_MARKER_PLACES if skip_left else augend_schema.path.place):
                    contexts_in.append('sw_c')
                    contexts_in.append(f'sw_ldx_{left_place}')
                if skip_left:
                    for right_place in range(0, WIDTH_MARKER_PLACES if skip_right else augend_schema.path.place):
                        contexts_in.append('sw_c')
                        contexts_in.append(f'sw_rdx_{right_place}')
                if skip_right:
                    for cursive_place in range(0, augend_schema.path.place):
                        contexts_in.append('sw_c')
                        contexts_in.append(f'sw_cdx_{cursive_place}')
                contexts_in.append(carry_in_schema)
                for addend_schema in original_digit_schemas:
                    if place != addend_schema.path.place:
                        continue
                    if not (carry_in_is_new or augend_is_new or addend_schema in new_glyphs):
                        continue
                    addend = addend_schema.path.digit
                    carry_out, sum_digit = divmod(carry_in + augend + addend, WIDTH_MARKER_RADIX)
                    if (carry_out != 0 and place != WIDTH_MARKER_PLACES - 1) or sum_digit != addend:
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
                        sum_lookup_name = f'sw_{sum_digit}'
                        if sum_lookup_name not in named_lookups:
                            named_lookups[sum_lookup_name] = Lookup(None, None, None, 0)
                        add_rule(lookup, Rule(contexts_in, [addend_schema], [], lookups=[sum_lookup_name]))
                        add_rule(named_lookups[sum_lookup_name], Rule([addend_schema], outputs))
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
    cursive_lookup = Lookup('psts', 'dupl', 'dflt', 0, 'tc', True)
    new_left_bounds = []
    new_right_bounds = []
    new_cursive_widths = []
    for schema in new_glyphs:
        if not isinstance(schema, Schema):
            continue
        if isinstance(schema.path, End):
            end = schema
            if end not in classes['tl']:
                classes['tl'].append(end)
            if end not in classes['tr']:
                classes['tr'].append(end)
            if end not in classes['tc']:
                classes['tc'].append(end)
        elif isinstance(schema.path, LeftBoundDigit) and schema.path.status == DigitStatus.NORMAL:
            classes['tl'].append(schema)
            new_left_bounds.append(schema)
        elif isinstance(schema.path, RightBoundDigit) and schema.path.status == DigitStatus.NORMAL:
            classes['tr'].append(schema)
            new_right_bounds.append(schema)
        elif isinstance(schema.path, CursiveWidthDigit) and schema.path.status == DigitStatus.NORMAL:
            classes['tc'].append(schema)
            new_cursive_widths.append(schema)
    for new_digits, lookup, class_name, digit_path, status in [
        (new_left_bounds, left_lookup, 'tl', LeftBoundDigit, DigitStatus.ALMOST_DONE),
        (new_right_bounds, right_lookup, 'tr', RightBoundDigit, DigitStatus.DONE),
        (new_cursive_widths, cursive_lookup, 'tc', CursiveWidthDigit, DigitStatus.DONE),
    ]:
        for schema in new_digits:
            skipped_schemas = [class_name] * schema.path.place
            add_rule(lookup, Rule(
                [end, *[class_name] * (WIDTH_MARKER_PLACES + schema.path.place)],
                [schema],
                [],
                [Schema(-1, digit_path(schema.path.place, schema.path.digit, status), 0)]))
    return [left_lookup, right_lookup, cursive_lookup]

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
        if total.path.digit != 0:
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

def add_rule(autochthonous_schemas, output_schemas, classes, named_lookups, lookup, rule):
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

    def register_output_schemas(rule):
        if rule.outputs is not None:
            for output in rule.outputs:
                if isinstance(output, str):
                    for o in classes[output]:
                        output_schemas.add(o)
                else:
                    output_schemas.add(output)
        elif rule.lookups is not None:
            for lookup in rule.lookups:
                if lookup is not None:
                    for rule in named_lookups[lookup].rules:
                        register_output_schemas(rule)

    register_output_schemas(rule)

def run_phases(all_input_schemas, phases):
    all_schemas = OrderedSet(all_input_schemas)
    all_input_schemas = OrderedSet(all_input_schemas)
    all_lookups = []
    all_classes = collections.defaultdict(list)
    all_named_lookups = {}
    for phase in phases:
        all_output_schemas = OrderedSet()
        autochthonous_schemas = OrderedSet()
        new_input_schemas = OrderedSet(all_input_schemas)
        output_schemas = OrderedSet(all_input_schemas)
        classes = collections.defaultdict(list)
        named_lookups = {}
        lookups = None
        while new_input_schemas:
            output_lookups = phase(
                all_input_schemas,
                new_input_schemas,
                classes,
                named_lookups,
                lambda lookup, rule: add_rule(
                    autochthonous_schemas,
                    output_schemas,
                    classes,
                    named_lookups,
                    lookup,
                    rule,
                 ),
             )
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
        for class_name, schemas in classes.items():
            all_classes[class_name].extend(schemas)
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
    shade,
    decompose,
    validate_overlap_controls,
    count_letter_overlaps,
    add_parent_edges,
    invalidate_overlap_controls,
    categorize_edges,
    make_mark_variants_of_children,
    ligate_pernin_r,
    join_with_next_step,
    #ss_pernin,
    join_with_previous,
    join_with_next,
    rotate_diacritics,
    classify_marks_for_trees,
]

GLYPH_PHASES = [
    add_width_markers,
    add_very_end_markers_for_marks,
    remove_false_very_end_markers,
    clear_peripheral_width_markers,
    sum_width_markers,
    calculate_bound_extrema,
    remove_false_start_markers,
    remove_false_end_markers,
    expand_start_markers,
    mark_maximum_bounds,
    copy_maximum_left_bound_to_start,
    dist,
]

SPACE = Space(0)
H = Dot()
X = Complex([(0.288, Line(73, True)), (0.168, Line(152, True)), (0.288, Line(73, True))])
P = Line(270)
P_REVERSE = Line(90)
T = Line(0)
T_REVERSE = Line(180)
F = Line(300)
F_REVERSE = Line(120)
K = Line(240)
K_REVERSE = Line(60)
L = Line(45)
L_REVERSE = Line(225)
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
S_T = Curve(270, 0, False)
S_P = Curve(270, 180, True)
T_S = Curve(0, 270, True)
W = Curve(180, 270, False)
S_N = Curve(0, 90, False)
K_R_S = Curve(90, 180, False)
S_K = Curve(90, 0, True)
J_N = Complex([(1, S_K), (1, N)])
J_N_S = Complex([(3, S_K), (4, N_S)])
O = Circle(0, 0, False, False)
O_REVERSE = Circle(0, 0, True, True)
YE = Complex([(0.47, T), (0.385, Line(242, True)), (0.47, T), (0.385, Line(242, True)), (0.47, T), (0.385, Line(242, True)), (0.47, T)])
U_N = Curve(90, 180, True)
LONG_U = Curve(225, 45, False, 4, True)
ROMANIAN_U = Complex([(4, Curve(180, 0, False)), lambda c: c, (2, Curve(0, 180, False))], hook=True)
UH = Circle(45, 45, False, False, 2)
OU = Complex([(4, Circle(180, 145, False, False)), lambda c: c, (5 / 3, Curve(145, 270, False, False))], hook=True)
WA = Complex([(4, Circle(180, 180, False, False)), (2, Circle(180, 180, False, False))])
WO = Complex([(4, Circle(180, 180, False, False)), (2.5, Circle(180, 180, False, False))])
WI = Complex([(4, Circle(180, 180, False, False)), lambda c: c, (5 / 3, M)])
WEI = Complex([(4, Circle(180, 180, False, False)), lambda c: c, (1, M), lambda c: c.clone(clockwise=not c.clockwise), (1, N)])
RTL_SECANT = Line(240, True)
LTR_SECANT = Line(330, True)
TANGENT = Complex([lambda c: Context(None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360), (0.25, Line(270, True)), lambda c: Context((c.angle + 180) % 360), (0.5, Line(90, True))], hook=True)
TAIL = Complex([(0.4, T), (6, N_REVERSE)])
TANGENT_HOOK = Complex([(1, Curve(180, 270, False)), lambda c: Context((c.angle + 180) % 360, None if c.clockwise is None else not c.clockwise), (1, Curve(90, 270, True))])
HIGH_ACUTE = Complex([(333, Space(90)), (0.5, Line(45, True))])
HIGH_TIGHT_ACUTE = Complex([(82, Space(90)), (0.5, Line(45, True))])
HIGH_GRAVE = Complex([(333, Space(90)), (0.5, Line(135, True))])
HIGH_LONG_GRAVE = Complex([(333, Space(90)), (0.75, Line(180, True)), (0.4, Line(120, True))])
HIGH_DOT = Complex([(333, Space(90)), (0.5, O)])
HIGH_CIRCLE = Complex([(333, Space(90)), (2, O)])
HIGH_LINE = Complex([(333, Space(90)), (0.5, Line(180, True))])
HIGH_WAVE = Complex([(333, Space(90)), (2, Curve(270, 45, False)), (RADIUS * math.sqrt(2) / 500, Line(45, True)), (2, Curve(45, 270, True))])
HIGH_VERTICAL = Complex([(333, Space(90)), (0.5, Line(90, True))])
LOW_ACUTE = Complex([(333, Space(270)), (0.5, Line(45, True))])
LOW_TIGHT_ACUTE = Complex([(82, Space(270)), (0.5, Line(45, True))])
LOW_GRAVE = Complex([(333, Space(270)), (0.5, Line(135, True))])
LOW_LONG_GRAVE = Complex([(333, Space(270)), (0.75, Line(180, True)), (0.4, Line(120, True))])
LOW_DOT = Complex([(333, Space(270)), (0.5, O)])
LOW_CIRCLE = Complex([(333, Space(270)), (2, O)])
LOW_LINE = Complex([(333, Space(270)), (0.5, Line(180, True))])
LOW_WAVE = Complex([(333, Space(270)), (2, Curve(270, 45, False)), (RADIUS * math.sqrt(2) / 500, Line(45, True)), (2, Curve(45, 270, True))])
LOW_VERTICAL = Complex([(333, Space(270)), (0.5, Line(90, True))])
LOW_ARROW = Complex([(333, Space(270)), (0.4, Line(0, True)), (0.4, Line(240, True))])
LIKALISTI = Complex([(5, O), (375, Space(90, False)), (0.5, P), (math.hypot(125, 125), Space(135, False)), (0.5, Line(0, True))])
DTLS = InvalidDTLS('u1BC9D')
CHINOOK_PERIOD = Complex([(1, Line(11, True)), (179, Space(90, False)), (1, Line(191, True))])
OVERLAP = InvalidOverlap('u1BCA0', False)
CONTINUING_OVERLAP = InvalidOverlap('u1BCA1', True)
DOWN_STEP = InvalidStep('u1BCA2', 270)
UP_STEP = InvalidStep('u1BCA3', 90)
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
    Schema(0xEC1A, N_REVERSE, 6),
    Schema(0xEC1B, J_REVERSE, 6),
    Schema(0xEC1C, S_REVERSE, 6),
    Schema(0xFEFF, SPACE, 0, side_bearing=0, ignored=True),
    Schema(0x1BC00, H, 1),
    Schema(0x1BC01, X, 1, Type.NON_JOINING),
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
    Schema(0x1BC31, J_N_S, 2),
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
    Schema(0x1BC4F, K, 1, marks=[DOT_1]),
    Schema(0x1BC50, YE, 1),
    Schema(0x1BC51, S_T, 2, Type.ORIENTING),
    Schema(0x1BC52, S_P, 2, Type.ORIENTING),
    Schema(0x1BC53, S_T, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC54, U_N, 4),
    Schema(0x1BC55, LONG_U, 2),
    Schema(0x1BC56, ROMANIAN_U, 1, Type.ORIENTING),
    Schema(0x1BC57, UH, 2, Type.ORIENTING),
    Schema(0x1BC58, UH, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC59, UH, 2, Type.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC5A, O, 4, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC5B, OU, 1, Type.ORIENTING),
    Schema(0x1BC5C, WA, 1, Type.ORIENTING),
    Schema(0x1BC5D, WO, 1, Type.ORIENTING),
    Schema(0x1BC5E, WI, 1, Type.ORIENTING),
    Schema(0x1BC5F, WEI, 1, Type.ORIENTING),
    Schema(0x1BC60, WO, 1, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC61, S_T, 2, Type.ORIENTING),
    Schema(0x1BC62, S_N, 2, Type.ORIENTING),
    Schema(0x1BC63, T_S, 2, Type.ORIENTING),
    Schema(0x1BC64, S_K, 2, Type.ORIENTING),
    Schema(0x1BC65, S_P, 2, Type.ORIENTING),
    Schema(0x1BC66, W, 2, Type.ORIENTING),
    Schema(0x1BC67, S_T, 2, Type.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC68, S_T, 2, Type.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC69, S_K, 2, Type.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC6A, S_K, 2),
    Schema(0x1BC70, T, 2, Type.NON_JOINING),
    Schema(0x1BC71, T, 2, Type.NON_JOINING),
    Schema(0x1BC72, T, 2, Type.NON_JOINING),
    Schema(0x1BC73, P, 2, Type.NON_JOINING),
    Schema(0x1BC74, P, 2, Type.NON_JOINING),
    Schema(0x1BC75, P, 2, Type.NON_JOINING),
    Schema(0x1BC76, RTL_SECANT, 1, Type.NON_JOINING),
    Schema(0x1BC77, LTR_SECANT, 1, Type.NON_JOINING),
    Schema(0x1BC78, TANGENT, 0.5, Type.ORIENTING),
    Schema(0x1BC79, TAIL, 1),
    Schema(0x1BC7A, J, 2),
    Schema(0x1BC7B, M, 2),
    Schema(0x1BC7C, TANGENT_HOOK, 2),
    Schema(0x1BC80, HIGH_ACUTE, 1, Type.NON_JOINING),
    Schema(0x1BC81, HIGH_TIGHT_ACUTE, 1, Type.NON_JOINING),
    Schema(0x1BC82, HIGH_GRAVE, 1, Type.NON_JOINING),
    Schema(0x1BC83, HIGH_LONG_GRAVE, 1, Type.NON_JOINING),
    Schema(0x1BC84, HIGH_DOT, 1, Type.NON_JOINING),
    Schema(0x1BC85, HIGH_CIRCLE, 1, Type.NON_JOINING),
    Schema(0x1BC86, HIGH_LINE, 1, Type.NON_JOINING),
    Schema(0x1BC87, HIGH_WAVE, 1, Type.NON_JOINING),
    Schema(0x1BC88, HIGH_VERTICAL, 1, Type.NON_JOINING),
    Schema(0x1BC90, LOW_ACUTE, 1, Type.NON_JOINING),
    Schema(0x1BC91, LOW_TIGHT_ACUTE, 1, Type.NON_JOINING),
    Schema(0x1BC92, LOW_GRAVE, 1, Type.NON_JOINING),
    Schema(0x1BC93, LOW_LONG_GRAVE, 1, Type.NON_JOINING),
    Schema(0x1BC94, LOW_DOT, 1, Type.NON_JOINING),
    Schema(0x1BC95, LOW_CIRCLE, 1, Type.NON_JOINING),
    Schema(0x1BC96, LOW_LINE, 1, Type.NON_JOINING),
    Schema(0x1BC97, LOW_WAVE, 1, Type.NON_JOINING),
    Schema(0x1BC98, LOW_VERTICAL, 1, Type.NON_JOINING),
    Schema(0x1BC99, LOW_ARROW, 1, Type.NON_JOINING),
    Schema(0x1BC9C, LIKALISTI, 1, Type.NON_JOINING),
    Schema(0x1BC9D, DTLS, 0, Type.NON_JOINING),
    Schema(0x1BC9E, LINE, 0.45, Type.ORIENTING, anchor=MIDDLE_ANCHOR),
    Schema(0x1BC9F, CHINOOK_PERIOD, 1, Type.NON_JOINING),
    Schema(0x1BCA0, OVERLAP, 0, Type.NON_JOINING, 0, ignored=True),
    Schema(0x1BCA1, CONTINUING_OVERLAP, 0, Type.NON_JOINING, 0, ignored=True),
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
        for glyph in font.selection.all().byGlyphs:
            if glyph.unicode != -1 and glyph.unicode not in code_points:
                self._schemas.append(Schema(glyph.unicode, SFDGlyphWrapper(glyph.glyphname), 0, Type.NON_JOINING))
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    '
            + '\n    '.join(map(hex, sorted(code_points.keys()))))

    def _add_lookup(
        self,
        feature_tag,
        anchor_class_name,
        flags=0,
        mark_filtering_set=None,
    ):
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
             flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        lookup = fontTools.feaLib.ast.LookupBlock(anchor_class_name)
        if flags:
            lookup.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
                flags,
                markFilteringSet=fontTools.feaLib.ast.GlyphClassName(mark_filtering_set)
                    if mark_filtering_set
                    else None,
                ))
        self._fea.statements.append(lookup)
        self._anchors[anchor_class_name] = lookup
        feature = fontTools.feaLib.ast.FeatureBlock(feature_tag)
        feature.statements.append(fontTools.feaLib.ast.ScriptStatement('dupl'))
        feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
        feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts):
        parent_edge_lookup = None
        child_edge_lookups = [None] * MAX_TREE_WIDTH
        self._add_lookup(
                'abvm',
                PARENT_EDGE_ANCHOR,
                0,
                class_asts[PARENT_EDGE_CLASS],
            )
        for layer_index in range(MAX_TREE_DEPTH):
            if layer_index < 2:
                for child_index in range(MAX_TREE_WIDTH):
                    self._add_lookup(
                            'blwm',
                            CHILD_EDGE_ANCHORS[layer_index][child_index],
                            0,
                            class_asts[CHILD_EDGE_CLASSES[child_index]],
                        )
            for child_index in range(MAX_TREE_WIDTH):
                self._add_lookup(
                    'mkmk',
                    INTER_EDGE_ANCHORS[layer_index][child_index],
                    fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                    class_asts[INTER_EDGE_CLASSES[layer_index][child_index]],
                )
        self._add_lookup('curs', CONTINUING_OVERLAP_ANCHOR, fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS)
        self._add_lookup('curs', CURSIVE_ANCHOR, 0, class_asts[CONTINUING_OVERLAP_CLASS])
        for feature, is_mkmk in [
            ('mark', False),
            ('mkmk', True),
        ]:
            for anchor in [
                RELATIVE_1_ANCHOR,
                RELATIVE_2_ANCHOR,
                MIDDLE_ANCHOR,
                ABOVE_ANCHOR,
                BELOW_ANCHOR,
            ]:
                self._add_lookup(
                    feature,
                    mkmk(anchor) if is_mkmk else anchor,
                    mark_filtering_set=class_asts[f'_{mkmk(anchor)}'] if is_mkmk else None,
                )

    def _add_altuni(self, cp, glyph_name):
        glyph = self.font[glyph_name]
        if cp != -1:
            if glyph.unicode == -1:
                glyph.unicode = cp
            else:
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
        glyph.addReference(base_glyph)
        base_anchors = {p[0]: p for p in self.font[base_glyph].anchorPoints if p[1] == 'base'}
        for mark_glyph in mark_glyphs:
            mark_anchors = [p for p in self.font[mark_glyph].anchorPoints if p[1] == 'mark']
            assert len(mark_anchors) == 1 or len(mark_anchors) == 2 and mark_anchors[1][0].startswith(mkmk(mark_anchors[0][0]))
            mark_anchor = mark_anchors[0]
            base_anchor = base_anchors[mark_anchor[0]]
            glyph.addReference(mark_glyph, psMat.translate(
                base_anchor[2] - mark_anchor[2],
                base_anchor[3] - mark_anchor[3]))
        return glyph

    def _draw_base_glyph(self, schema, glyph_name):
        glyph = self.font.createChar(schema.cp, glyph_name)
        pen = glyph.glyphPen()
        schema.path(
            glyph,
            pen,
            SHADED_LINE if schema.cps[-1] == 0x1BC9D else LIGHT_LINE,
            schema.size,
            schema.anchor,
            schema.joining_type,
            schema.child,
        )
        return glyph

    def _draw_glyph(self, schema):
        glyph_name = str(schema)
        if schema.path.name_in_sfd():
            return self.font[schema.path.name_in_sfd()]
        if glyph_name in self.font:
            return self._add_altuni(schema.cp, glyph_name)
        if schema.marks:
            glyph = self._draw_glyph_with_marks(schema, glyph_name)
        else:
            glyph = self._draw_base_glyph(schema, glyph_name)
        glyph.glyphclass = schema.glyph_class
        if schema.joining_type == Type.NON_JOINING:
            glyph.left_side_bearing = schema.side_bearing
            glyph.right_side_bearing = schema.side_bearing
        else:
            bbox = glyph.boundingBox()
            center_y = (bbox[3] - bbox[1]) / 2 + bbox[1]
            entry_x = next((x for _, type, x, _ in glyph.anchorPoints if type == 'entry'), 0)
            glyph.transform(psMat.translate(-entry_x, BASELINE - center_y))
            glyph.width = 0
        return glyph

    def _complete_gpos(self):
        mark_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        base_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        basemark_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
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
                elif type == 'basemark':
                    basemark_positions[anchor_class_name][(x, y)].append(glyph_name)
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
            for x_y, glyph_class in basemark_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.MarkMarkPosStatement(
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
        glyph.glyphclass = schema.glyph_class
        glyph.width = 0
        if isinstance(schema.path, VeryEnd):
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)

    def augment(self):
        schemas, lookups, classes, named_lookups = run_phases(self._schemas, self._phases)
        assert not named_lookups, 'Named lookups have not been implemented for pre-merge phases'
        merge_schemas(schemas, lookups, classes)
        for schema in schemas:
            self._draw_glyph(schema)
        for schema in schemas:
            name_in_sfd = schema.path.name_in_sfd()
            if name_in_sfd:
                self.font[name_in_sfd].glyphname = str(schema)
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
                fontTools.feaLib.ast.GlyphClass([str(s) if isinstance(s, Schema) else s.glyphname for s in schemas]))
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        for name, lookup in named_lookups.items():
            named_lookup_ast = lookup.to_ast(class_asts, None, name=name)
            self._fea.statements.append(named_lookup_ast)
            named_lookup_asts[name] = named_lookup_ast
        self._fea.statements.extend(l.to_ast(class_asts, named_lookup_asts) for l in lookups)
        self._add_lookups(class_asts)

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

