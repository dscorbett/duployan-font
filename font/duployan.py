# Copyright 2018-2019 David Corbett
# Copyright 2019-2021 Google LLC
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
import functools
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
import fontTools.misc.transform
import fontTools.otlLib.builder

DEFAULT_SIDE_BEARING = 85
EPSILON = 1e-5
RADIUS = 50
SHADING_FACTOR = 12 / 7
MINIMUM_STROKE_GAP = 70
STRIKEOUT_POSITION = 258
MAX_HUB_PRIORITY = 2
MAX_DOUBLE_MARKS = 3
MAX_TREE_WIDTH = 2
MAX_TREE_DEPTH = 3
CONTINUING_OVERLAP_CLASS = 'global..cont'
HUB_CLASS = 'global..hub'
CONTINUING_OVERLAP_OR_HUB_CLASS = 'global..cont_or_hub'
PARENT_EDGE_CLASS = 'global..pe'
CHILD_EDGE_CLASSES = [f'global..ce{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]
INTER_EDGE_CLASSES = [[f'global..edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]
PARENT_EDGE_ANCHOR = 'pe'
CHILD_EDGE_ANCHORS = [[f'ce{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(min(2, MAX_TREE_DEPTH))]
INTER_EDGE_ANCHORS = [[f'edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]
RELATIVE_1_ANCHOR = 'rel1'
RELATIVE_2_ANCHOR = 'rel2'
MIDDLE_ANCHOR = 'mid'
ABOVE_ANCHOR = 'abv'
BELOW_ANCHOR = 'blw'
SECANT_ANCHOR = 'sec'
MKMK_ANCHORS = [
    RELATIVE_1_ANCHOR,
    RELATIVE_2_ANCHOR,
    MIDDLE_ANCHOR,
    ABOVE_ANCHOR,
    BELOW_ANCHOR,
]
MARK_ANCHORS = MKMK_ANCHORS + [
    SECANT_ANCHOR,
]
PRE_HUB_CONTINUING_OVERLAP_ANCHOR = 'hub1cont'
POST_HUB_CONTINUING_OVERLAP_ANCHOR = 'hub2cont'
CONTINUING_OVERLAP_ANCHOR = 'cont'
PRE_HUB_CURSIVE_ANCHOR = 'hub1cursive'
POST_HUB_CURSIVE_ANCHOR = 'hub2cursive'
CURSIVE_ANCHOR = 'cursive'
CURSIVE_ANCHORS = [
    # The hub cursive anchors are intentionally skipped here: they are
    # duplicates of the standard cursive anchors used only to finagle the
    # baseline glyph into the root of the cursive attachment tree.
    CONTINUING_OVERLAP_ANCHOR,
    CURSIVE_ANCHOR,
]
ALL_ANCHORS = MARK_ANCHORS + CURSIVE_ANCHORS
CLONE_DEFAULT = object()
MAX_GLYPH_NAME_LENGTH = 63 - 2 - 4
WIDTH_MARKER_RADIX = 4
WIDTH_MARKER_PLACES = 7
NO_PHASE_INDEX = -1
CURVE_OFFSET = 75

assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'

def mkmk(anchor):
    return f'mkmk_{anchor}'

class GlyphClass:
    BLOCKER = 'baseglyph'
    JOINER = 'baseligature'
    MARK = 'mark'

class Type(enum.Enum):
    JOINING = enum.auto()
    ORIENTING = enum.auto()
    NON_JOINING = enum.auto()

class Context:
    def __init__(
        self,
        angle=None,
        clockwise=None,
        *,
        minor=False,
        ignorable_for_topography=False,
        diphthong_start=False,
        diphthong_end=False,
    ):
        assert clockwise is not None or not ignorable_for_topography
        self.angle = float(angle) if angle is not None else None
        self.clockwise = clockwise
        self.minor = minor
        self.ignorable_for_topography = ignorable_for_topography
        self.diphthong_start = diphthong_start
        self.diphthong_end = diphthong_end

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        minor=CLONE_DEFAULT,
        ignorable_for_topography=CLONE_DEFAULT,
        diphthong_start=CLONE_DEFAULT,
        diphthong_end=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            ignorable_for_topography=self.ignorable_for_topography if ignorable_for_topography is CLONE_DEFAULT else ignorable_for_topography,
            diphthong_start=self.diphthong_start if diphthong_start is CLONE_DEFAULT else diphthong_start,
            diphthong_end=self.diphthong_end if diphthong_end is CLONE_DEFAULT else diphthong_end,
        )

    def __repr__(self):
        return f'''Context({
                self.angle
            }, {
                self.clockwise
            }, minor={
                self.minor
            }, ignorable_for_topography={
                self.ignorable_for_topography
            }, diphthong_start={
                self.diphthong_start
            }, diphthong_end={
                self.diphthong_end
            })'''

    def __str__(self):
        if self.angle is None:
            return ''
        return f'''{
            self.angle
        }{
            '' if self.clockwise is None else 'neg' if self.clockwise else 'pos'
        }{
            '.minor' if self.minor else ''
        }{
            '.ori' if self.ignorable_for_topography else ''
        }{
            '.diph' if self.diphthong_start or self.diphthong_end else ''
        }{
            '1' if self.diphthong_start else ''
        }{
            '2' if self.diphthong_end else ''
        }'''

    def __eq__(self, other):
        return (
            self.angle == other.angle
            and self.clockwise == other.clockwise
            and self.minor == other.minor
            and self.ignorable_for_topography == other.ignorable_for_topography
            and self.diphthong_start == other.diphthong_start
            and self.diphthong_end == other.diphthong_end
        )

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return (
            hash(self.angle)
            ^ hash(self.clockwise)
            ^ hash(self.minor)
            ^ hash(self.ignorable_for_topography)
            ^ hash(self.diphthong_start)
            ^ hash(self.diphthong_end)
        )

    def reversed(self):
        return self.clone(
            angle=None if self.angle is None else (self.angle + 180) % 360,
            clockwise=None if self.clockwise is None else not self.clockwise,
        )

    def has_clockwise_loop_to(self, other):
        if self.angle is None or other.angle is None:
            return False
        angle_in = self.angle
        angle_out = other.angle
        if self.clockwise:
            angle_in += CURVE_OFFSET
        elif self.clockwise == False:
            angle_in -= CURVE_OFFSET
        if other.clockwise:
            angle_out -= CURVE_OFFSET
        elif other.clockwise == False:
            angle_out += CURVE_OFFSET
        da = abs(angle_out - angle_in)
        return da % 180 != 0 and (da >= 180) != (angle_out > angle_in)

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

    @staticmethod
    def name_implies_type():
        return False

    def group(self):
        return str(self)

    def invisible(self):
        return False

    @staticmethod
    def can_take_secant():
        return False

    def hub_priority(self, size):
        return 0 if self.invisible() else -1

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        if not self.invisible():
            raise NotImplementedError

    def can_be_child(self, size):
        return False

    def max_tree_width(self, size):
        return 0

    def max_double_marks(self, size, joining_type, marks):
        return 0

    def is_pseudo_cursive(self, size):
        return False

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

    @staticmethod
    def guaranteed_glyph_class():
        return None

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

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class ContextMarker(Shape):
    def __init__(
        self,
        is_context_in,
        context,
    ):
        self.is_context_in = is_context_in
        self.context = context

    def clone(
        self,
        *,
        is_context_in=CLONE_DEFAULT,
        context=CLONE_DEFAULT,
    ):
        return type(self)(
            self.is_context_in if is_context_in is CLONE_DEFAULT else is_context_in,
            self.context if context is CLONE_DEFAULT else context,
        )

    def __str__(self):
        return f'''{
                'in' if self.is_context_in else 'out'
            }.{
                self.context
            }'''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class Dummy(Shape):
    def __str__(self):
        return ''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class Start(Shape):
    def __str__(self):
        return 'START'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class Hub(Shape):
    def __init__(
        self,
        priority,
        *,
        initial_secant=False,
    ):
        self.priority = priority
        self.initial_secant = initial_secant

    def clone(
        self,
        *,
        priority=CLONE_DEFAULT,
        initial_secant=CLONE_DEFAULT,
    ):
        return type(self)(
            priority=self.priority if priority is CLONE_DEFAULT else priority,
            initial_secant=self.initial_secant if initial_secant is CLONE_DEFAULT else initial_secant,
        )

    def __str__(self):
        return f'HUB.{self.priority}{"s" if self.initial_secant else ""}'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        if self.initial_secant:
            glyph.addAnchorPoint(PRE_HUB_CONTINUING_OVERLAP_ANCHOR, 'entry', 0, 0)
            glyph.addAnchorPoint(POST_HUB_CONTINUING_OVERLAP_ANCHOR, 'exit', 0, 0)
        else:
            glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'entry', 0, 0)
            glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'exit', 0, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class End(Shape):
    def __str__(self):
        return 'END'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class Carry(Shape):
    def __str__(self):
        return 'c'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class DigitStatus(enum.Enum):
    NORMAL = enum.auto()
    ALMOST_DONE = enum.auto()
    DONE = enum.auto()

class EntryWidthDigit(Shape):
    def __init__(self, place, digit):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit

    def __str__(self):
        return f'idx.{self.digit}e{self.place}'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class LeftBoundDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''{
                "LDX" if self.status == DigitStatus.DONE else "ldx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class RightBoundDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''{
                "RDX" if self.status == DigitStatus.DONE else "rdx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class AnchorWidthDigit(Shape):
    def __init__(self, place, digit, status=DigitStatus.NORMAL):
        self.place = int(place)
        self.digit = int(digit)
        assert self.place == place, place
        assert self.digit == digit, digit
        self.status = status

    def __str__(self):
        return f'''{
                "ADX" if self.status == DigitStatus.DONE else "adx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class WidthNumber(Shape):
    def __init__(self, digit_path, width):
        self.digit_path = digit_path
        self.width = width

    def __str__(self):
        return f'''{
                'ilra'[[EntryWidthDigit, LeftBoundDigit, RightBoundDigit, AnchorWidthDigit].index(self.digit_path)]
            }dx.{self.width}'''.replace('-', 'n')

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

    def to_digits(self, register_width_marker):
        digits = [None] * WIDTH_MARKER_PLACES
        quotient = self.width
        for i in range(WIDTH_MARKER_PLACES):
            quotient, remainder = divmod(quotient, WIDTH_MARKER_RADIX)
            digits[i] = register_width_marker(self.digit_path, i, remainder)
        return digits

class MarkAnchorSelector(Shape):
    def __init__(self, index):
        self.index = index

    def __str__(self):
        return f'anchor.{MARK_ANCHORS[self.index]}'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class GlyphClassSelector(Shape):
    def __init__(self, glyph_class):
        self.glyph_class = glyph_class

    def __str__(self):
        return f'gc.{self.glyph_class}'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class InitialSecantMarker(Shape):
    def __str__(self):
        return 'SECANT'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class Notdef(Shape):
    def clone(self):
        return self

    def __str__(self):
        return 'notdef'

    @staticmethod
    def name_implies_type():
        return True

    def group(self):
        return ()

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        stroke_width = 51
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class Space(Shape):
    def __init__(
        self,
        angle,
        *,
        margins=True,
    ):
        self.angle = angle
        self.margins = margins

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        margins=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.margins if margins is CLONE_DEFAULT else margins,
        )

    def __str__(self):
        return str(int(self.angle))

    def group(self):
        return (
            self.angle,
            self.margins,
        )

    def invisible(self):
        return True

    def hub_priority(self, size):
        return 0 if self.angle % 180 == 90 else -1

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'entry', 0, 0)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            glyph.transform(
                fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
                ('round',),
            )

    def can_be_child(self, size):
        return size == 0 and self.angle == 0 and not self.margins

    def is_pseudo_cursive(self, size):
        return size and self.hub_priority(size) == -1

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Bound(Shape):
    def clone(self):
        return self

    def __str__(self):
        return ''

    def group(self):
        return ()

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        stroke_width = 75
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        pen.moveTo((stroke_width / 2, 639 + stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class ValidDTLS(Shape):
    def __str__(self):
        return 'dtls'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class ChildEdge(Shape):
    def __init__(self, lineage):
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage=CLONE_DEFAULT,
    ):
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self):
        return f'''{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_' if len(self.lineage) == 1 else '_'.join(str(x[1]) for x in self.lineage[:-1]) if self.lineage else '0'
            }'''

    def invisible(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        layer_index = len(self.lineage) - 1
        child_index = self.lineage[-1][0] - 1
        glyph.addAnchorPoint(CHILD_EDGE_ANCHORS[min(1, layer_index)][child_index], 'mark', 0, 0)
        glyph.addAnchorPoint(INTER_EDGE_ANCHORS[layer_index][child_index], 'basemark', 0, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class ContinuingOverlapS(Shape):
    def clone(self):
        return type(self)()

    def __str__(self):
        return ''

    def invisible(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        pass

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class ContinuingOverlap(ContinuingOverlapS):
    pass

class ParentEdge(Shape):
    def __init__(self, lineage):
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage=CLONE_DEFAULT,
    ):
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self):
        return f'''pe.{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_'.join(str(x[1]) for x in self.lineage) if self.lineage else '0'
            }'''

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        if self.lineage:
            layer_index = len(self.lineage) - 1
            child_index = self.lineage[-1][0] - 1
            glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'basemark', 0, 0)
            glyph.addAnchorPoint(INTER_EDGE_ANCHORS[layer_index][child_index], 'mark', 0, 0)

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class RootOnlyParentEdge(Shape):
    def __str__(self):
        return 'pe'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK

class Dot(Shape):
    def __init__(
        self,
        *,
        centered=False,
    ):
        self.centered = centered

    def clone(
        self,
        *,
        centered=CLONE_DEFAULT,
    ):
        return Dot(
            centered=self.centered if centered is CLONE_DEFAULT else centered,
        )

    def __str__(self):
        return ''

    def group(self):
        return self.centered

    def hub_priority(self, size):
        return -1

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        assert not child
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', stroke_width, 'round')
        if anchor:
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *rect(0, 0))
            glyph.addAnchorPoint(anchor, 'mark', *rect(0, 0))
        elif joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', 0, 0 if self.centered else -(stroke_width / 2))

    def is_pseudo_cursive(self, size):
        return True

    def is_shadable(self):
        return True

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Line(Shape):
    def __init__(
        self,
        angle,
        *,
        minor=False,
        stretchy=True,
        secant=None,
        secant_curvature_offset=45,
        dots=None,
        final_tick=False,
        original_angle=None,
    ):
        self.angle = angle
        self.minor = minor
        self.stretchy = stretchy
        self.secant = secant
        self.secant_curvature_offset = secant_curvature_offset
        self.dots = dots
        self.final_tick = final_tick
        self.original_angle = original_angle

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        minor=CLONE_DEFAULT,
        stretchy=CLONE_DEFAULT,
        secant=CLONE_DEFAULT,
        secant_curvature_offset=CLONE_DEFAULT,
        dots=CLONE_DEFAULT,
        final_tick=CLONE_DEFAULT,
        original_angle=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            stretchy=self.stretchy if stretchy is CLONE_DEFAULT else stretchy,
            secant=self.secant if secant is CLONE_DEFAULT else secant,
            secant_curvature_offset=self.secant_curvature_offset if secant_curvature_offset is CLONE_DEFAULT else secant_curvature_offset,
            dots=self.dots if dots is CLONE_DEFAULT else dots,
            final_tick=self.final_tick if final_tick is CLONE_DEFAULT else final_tick,
            original_angle=self.original_angle if original_angle is CLONE_DEFAULT else original_angle,
        )

    def __str__(self):
        if self.final_tick:
            s = 'tick'
        elif self.dots or not self.stretchy:
            s = str(int(self.angle))
            if self.dots:
                s += '.dotted'
        else:
            s = ''
        return s

    def group(self):
        return (
            self.angle,
            self.stretchy,
            self.secant,
            self.secant_curvature_offset,
            self.dots,
            self.final_tick,
            self.original_angle if self.original_angle != self.angle else None,
        )

    @staticmethod
    def can_take_secant():
        return True

    def hub_priority(self, size):
        if self.dots:
            return 0
        if self.secant:
            return -1
        if self.angle % 180 == 0:
            return 2
        if size >= 1:
            return 0
        return -1

    def _get_length(self, size):
        if self.stretchy:
            length_denominator = abs(math.sin(math.radians(self.angle if self.original_angle is None else self.original_angle)))
            if length_denominator < EPSILON:
                length_denominator = 1
        else:
            length_denominator = 1
        return int(500 * size / length_denominator)

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        end_y = 0
        length = self._get_length(size)
        pen.moveTo((0, 0))
        if self.dots:
            dot_interval = length / (self.dots - 1)
            for dot_index in range(1, self.dots):
                pen.endPath()
                pen.moveTo((dot_interval * dot_index, 0))
        else:
            pen.lineTo((length, 0))
            if self.final_tick:
                end_y = 100 if 90 < self.angle <= 270 else -100
                pen.lineTo((length, end_y))
        if anchor:
            if (joining_type == Type.ORIENTING
                or self.angle % 180 == 0
                or anchor not in [ABOVE_ANCHOR, BELOW_ANCHOR]
            ):
                length *= self.secant or 0.5
            elif (anchor == ABOVE_ANCHOR) == (self.angle < 180):
                length = 0
            glyph.addAnchorPoint(anchor, 'mark', length, end_y)
            glyph.addAnchorPoint(mkmk(anchor), 'mark', length, end_y)
        elif self.secant:
            glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'exit', length * self.secant, end_y)
            glyph.addAnchorPoint(PRE_HUB_CONTINUING_OVERLAP_ANCHOR, 'exit', length * self.secant, end_y)
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
                    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', length, end_y)
                    glyph.addAnchorPoint(POST_HUB_CONTINUING_OVERLAP_ANCHOR, 'entry', child_interval, 0)
                    if self.hub_priority(size) != -1:
                        glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'entry', 0, 0)
                    if self.hub_priority(size) != 0:
                        glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', length, end_y)
                    glyph.addAnchorPoint(anchor_name(SECANT_ANCHOR), base, child_interval * (max_tree_width + 1), 0)
            if size == 2 and 0 < self.angle <= 45:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, length / 2 - (light_line + stroke_gap), -(stroke_width + light_line) / 2)
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, length / 2 + light_line + stroke_gap, -(stroke_width + light_line) / 2)
            else:
                glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, length / 2, (stroke_width + light_line) / 2)
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, length / 2, -(stroke_width + light_line) / 2)
            glyph.addAnchorPoint(anchor_name(MIDDLE_ANCHOR), base, length / 2, 0)
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
            ('round',)
        )
        glyph.stroke('circular', stroke_width, 'round')
        if not anchor and not self.secant:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchor_name(ABOVE_ANCHOR), base, x_center, y_max + stroke_width / 2 + 2 * stroke_gap + light_line / 2)
            glyph.addAnchorPoint(anchor_name(BELOW_ANCHOR), base, x_center, y_min - (stroke_width / 2 + 2 * stroke_gap + light_line / 2))

    def can_be_child(self, size):
        return not (self.secant or self.dots)

    def max_tree_width(self, size):
        return 2 if size == 2 and not self.secant else 1

    def max_double_marks(self, size, joining_type, marks):
        return (0
            if self.secant or self.dots or any(
                m.anchor in [RELATIVE_1_ANCHOR, RELATIVE_2_ANCHOR, MIDDLE_ANCHOR]
                    for m in marks
            ) else int(self._get_length(size) // (250 * 0.45)) - 1)

    def is_shadable(self):
        return not self.dots

    def contextualize(self, context_in, context_out):
        if self.secant:
            if context_out != NO_CONTEXT:
                return self.rotate_diacritic(context_out)
        else:
            if self.stretchy:
                if context_out == Context(self.angle):
                    return self.clone(final_tick=True)
            elif context_in != NO_CONTEXT:
                return self.clone(angle=context_in.angle)
        return self

    def context_in(self):
        # FIXME: This should use the current angle, not the original angle.
        return Context(self.angle if self.original_angle is None else self.original_angle, minor=self.minor)

    def context_out(self):
        # FIXME: This should use the current angle, not the original angle.
        return Context(self.angle if self.original_angle is None else self.original_angle, minor=self.minor)

    def rotate_diacritic(self, context):
        angle = context.angle
        if self.secant:
            clockwise = context.clockwise
            if clockwise is None:
                minimum_da = 30
            else:
                minimum_da = 0 if context.ignorable_for_topography else 45
                angle -= self.secant_curvature_offset * (1 if clockwise else -1)
            da = (self.angle % 180) - (angle % 180)
            if da > 90:
                da -= 180
            elif da < -90:
                da += 180
            if abs(da) >= minimum_da:
                return self
            if da > 0:
                new_da = minimum_da - da
            else:
                new_da = -minimum_da - da
            ltr = 90 < self.angle % 180
            rtl = self.angle % 180 < 90
            new_ltr = 90 < (self.angle + new_da) % 180
            new_rtl = (self.angle + new_da) % 180 < 90
            if ltr != new_ltr and rtl != new_rtl:
                if da > 0:
                    new_da = -minimum_da
                else:
                    new_da = minimum_da
            angle = (self.angle + new_da) % 360
        return self.clone(angle=angle)

    def calculate_diacritic_angles(self):
        angle = float(self.angle % 180)
        return {
            RELATIVE_1_ANCHOR: angle,
            RELATIVE_2_ANCHOR: angle,
            MIDDLE_ANCHOR: (angle + 90) % 180,
            SECANT_ANCHOR: angle,
        }

    def reversed(self):
        return self.clone(angle=(self.angle + 180) % 360)

class Curve(Shape):
    def __init__(
        self,
        angle_in,
        angle_out,
        *,
        clockwise,
        stretch=0,
        long=False,
        relative_stretch=True,
        hook=False,
        reversed_circle=False,
        overlap_angle=None,
        secondary=None,
    ):
        assert overlap_angle is None or abs(angle_out - angle_in) == 180, 'Only a semicircle may have an overlap angle'
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.stretch = stretch
        self.long = long
        self.relative_stretch = relative_stretch
        self.hook = hook
        self.reversed_circle = reversed_circle
        self.overlap_angle = overlap_angle if overlap_angle is None else overlap_angle % 180
        self.secondary = clockwise if secondary is None else secondary

    def clone(
        self,
        *,
        angle_in=CLONE_DEFAULT,
        angle_out=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        stretch=CLONE_DEFAULT,
        long=CLONE_DEFAULT,
        relative_stretch=CLONE_DEFAULT,
        hook=CLONE_DEFAULT,
        reversed_circle=CLONE_DEFAULT,
        overlap_angle=CLONE_DEFAULT,
        secondary=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            clockwise=self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            stretch=self.stretch if stretch is CLONE_DEFAULT else stretch,
            long=self.long if long is CLONE_DEFAULT else long,
            relative_stretch=self.relative_stretch if relative_stretch is CLONE_DEFAULT else relative_stretch,
            hook=self.hook if hook is CLONE_DEFAULT else hook,
            reversed_circle=self.reversed_circle if reversed_circle is CLONE_DEFAULT else reversed_circle,
            overlap_angle=self.overlap_angle if overlap_angle is CLONE_DEFAULT else overlap_angle,
            secondary=self.secondary if secondary is CLONE_DEFAULT else secondary,
        )

    def __str__(self):
        return f'''{
                int(self.angle_in)
            }{
                'n' if self.clockwise else 'p'
            }{
                int(self.angle_out)
            }{
                'r' if self.reversed_circle else ''
            }'''

    def group(self):
        return (
            self.angle_in,
            self.angle_out,
            self.clockwise,
            self.stretch,
            self.long,
            self.relative_stretch,
            self.reversed_circle,
            self.overlap_angle,
        )

    @staticmethod
    def can_take_secant():
        return True

    def hub_priority(self, size):
        return 0 if size >= 6 else 1

    def _get_normalized_angles(self, diphthong_1=False, diphthong_2=False):
        angle_in = self.angle_in
        angle_out = self.angle_out
        if diphthong_1:
            angle_out = (angle_out + 90 * (1 if self.clockwise else -1)) % 360
        if diphthong_2:
            angle_in = (angle_in - 90 * (1 if self.clockwise else -1)) % 360
        if self.clockwise and angle_out > angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        return a1, a2

    def _get_angle_to_overlap_point(self, a1, a2, *, is_entry):
        angle_to_overlap_point = self.overlap_angle
        angle_at_overlap_point = (angle_to_overlap_point - (90 if self.clockwise else -90))
        if (not self.in_degree_range(
                angle_at_overlap_point % 360,
                self.angle_in,
                self.angle_out,
                self.clockwise,
            )
            or is_entry and self.in_degree_range(
                (angle_at_overlap_point + 180) % 360,
                self.angle_in,
                self.angle_out,
                self.clockwise,
            ) and self.in_degree_range(
                (angle_at_overlap_point + 180) % 360,
                self.angle_in - 90,
                self.angle_in + 90,
                False,
            )
        ):
            angle_to_overlap_point += 180
        angle_at_overlap_point = (angle_to_overlap_point - (90 if self.clockwise else -90)) % 180
        exclusivity_zone = 30
        if self.in_degree_range(
            angle_to_overlap_point,
            ((a1 if is_entry else a2) - exclusivity_zone) % 360,
            ((a1 if is_entry else a2) + exclusivity_zone) % 360,
            False,
        ):
            delta = abs(angle_to_overlap_point - self.overlap_angle - (180 if is_entry else 0)) - exclusivity_zone
            if is_entry != self.clockwise:
                delta = -delta
            angle_to_overlap_point += delta
        return angle_to_overlap_point % 360

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        a1, a2 = self._get_normalized_angles(diphthong_1, diphthong_2)
        if final_circle_diphthong:
            a2 = a1
        elif initial_circle_diphthong:
            a1 = a2
        da = a2 - a1 or 360
        r = int(RADIUS * size)
        beziers_needed = int(math.ceil(abs(da) / 90))
        bezier_arc = da / beziers_needed
        cp = r * (4 / 3) * math.tan(math.pi / (2 * beziers_needed * 360 / da))
        cp_distance = math.hypot(cp, r)
        cp_angle = math.asin(cp / cp_distance)
        p0 = rect(r, math.radians(a1))
        if diphthong_2:
            entry = rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (p0[0] + entry[0], p0[1] + entry[1])
            pen.moveTo(entry)
            pen.lineTo(p0)
        else:
            entry = p0
            pen.moveTo(entry)
        for i in range(1, beziers_needed + 1):
            theta0 = math.radians(a1 + (i - 1) * bezier_arc)
            p1 = rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = rect(r, theta3)
            p2 = rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        if self.reversed_circle and not diphthong_1 and not diphthong_2:
            swash_angle = (360 - abs(da)) / 2
            swash_length = math.sin(math.radians(swash_angle)) * r / math.sin(math.radians(90 - swash_angle))
            swash_endpoint = rect(abs(swash_length), math.radians(self.angle_out))
            swash_endpoint = (p3[0] + swash_endpoint[0], p3[1] + swash_endpoint[1])
            pen.lineTo(swash_endpoint)
            exit = rect(min(r, abs(swash_length)), math.radians(self.angle_out))
            exit = (p3[0] + exit[0], p3[1] + exit[1])
        else:
            exit = p3
        if diphthong_1:
            exit_delta = rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
        pen.endPath()
        relative_mark_angle = (a1 + a2) / 2
        anchor_name = mkmk if child else lambda a: a
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(r, math.radians(relative_mark_angle)))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *rect(r, math.radians(relative_mark_angle)))
        else:
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = da / (max_tree_width + 2)
                if self.overlap_angle is None:
                    for child_index in range(max_tree_width):
                        glyph.addAnchorPoint(
                            CHILD_EDGE_ANCHORS[int(child)][child_index],
                            base,
                            *rect(r, math.radians(a1 + child_interval * (child_index + 2))),
                        )
                else:
                    overlap_exit_angle = self._get_angle_to_overlap_point(a1, a2, is_entry=False)
                    glyph.addAnchorPoint(
                        CHILD_EDGE_ANCHORS[int(child)][0],
                        base,
                        *rect(r, math.radians(overlap_exit_angle)),
                    )
                overlap_entry_angle = (a1 + child_interval
                    if self.overlap_angle is None
                    else self._get_angle_to_overlap_point(a1, a2, is_entry=True))
                if child:
                    glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'mark', *rect(r, math.radians(overlap_entry_angle)))
                else:
                    glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'entry', *rect(r, math.radians(overlap_entry_angle)))
                    glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'exit', *rect(r, math.radians(
                        a1 + child_interval * (max_tree_width + 1)
                            if self.overlap_angle is None
                            else overlap_exit_angle)))
                    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *entry)
                    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *exit)
                    glyph.addAnchorPoint(POST_HUB_CONTINUING_OVERLAP_ANCHOR, 'entry', *rect(r, math.radians(overlap_entry_angle)))
                    if self.hub_priority(size) != -1:
                        glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
                    if self.hub_priority(size) != 0:
                        glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', *exit)
                    glyph.addAnchorPoint(
                        anchor_name(SECANT_ANCHOR),
                        base,
                        *rect(0,0)
                            if abs(da) > 180
                            else rect(r, math.radians(a1 + child_interval * (max_tree_width + 1))),
                    )
            glyph.addAnchorPoint(anchor_name(MIDDLE_ANCHOR), base, *rect(r, math.radians(relative_mark_angle)))
        if not anchor:
            if self.stretch:
                scale_x = 1.0
                scale_y = 1.0 + self.stretch
                if self.long:
                    scale_x, scale_y = scale_y, scale_x
                theta = self.relative_stretch and math.radians(self.angle_in % 180)
                glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, *rect(0, 0))
                glyph.transform(
                    fontTools.misc.transform.Identity
                        .rotate(theta)
                        .scale(scale_x, scale_y)
                        .rotate(-theta),
                )
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(scale_x * r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(self.angle_in)))
            else:
                glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base,
                    *(rect(0, 0) if abs(da) > 180 else rect(
                        min(stroke_width, r - (stroke_width / 2 + stroke_gap + light_line / 2)),
                        math.radians(relative_mark_angle))))
                glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(relative_mark_angle)))
        glyph.stroke('circular', stroke_width, 'round')
        if not anchor:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchor_name(ABOVE_ANCHOR), base, x_center, y_max + stroke_gap)
            glyph.addAnchorPoint(anchor_name(BELOW_ANCHOR), base, x_center, y_min - stroke_gap)

    def can_be_child(self, size):
        a1, a2 = self._get_normalized_angles()
        return abs(a2 - a1) <= 180

    def max_tree_width(self, size):
        return 1

    def max_double_marks(self, size, joining_type, marks):
        if any(m.anchor == MIDDLE_ANCHOR for m in marks):
            return 0
        a1, a2 = self._get_normalized_angles()
        return min(3, int(abs(a1 - a2) / 360 * size))

    def is_shadable(self):
        return True

    @staticmethod
    def in_degree_range(key, start, stop, clockwise):
        if clockwise:
            start, stop = stop, start
        if start <= stop:
            return start <= key <= stop
        return start <= key or key <= stop

    def contextualize(self, context_in, context_out):
        angle_in = context_in.angle
        angle_out = context_out.angle
        da = self.angle_out - self.angle_in
        if angle_in is None:
            if angle_out is None:
                angle_in = self.angle_in
            else:
                angle_in = (angle_out - da) % 360
        if angle_out is None:
            angle_out = (angle_in + da) % 360
        def flip():
            nonlocal candidate_clockwise
            nonlocal candidate_angle_in
            nonlocal candidate_angle_out
            candidate_clockwise = not candidate_clockwise
            if context_in == NO_CONTEXT:
                candidate_angle_in = (2 * candidate_angle_out - candidate_angle_in) % 360
            else:
                candidate_angle_out = (2 * candidate_angle_in - candidate_angle_out) % 360
        if self.hook:
            candidate_angle_in = self.angle_in
            candidate_angle_out = self.angle_out
            candidate_clockwise = self.clockwise
            if context_in == NO_CONTEXT:
                if candidate_angle_out == context_out.angle:
                    candidate_clockwise = not candidate_clockwise
                    candidate_angle_out = (candidate_angle_out + 180) % 360
                    candidate_angle_in = (candidate_angle_out - da) % 360
            else:
                if candidate_angle_in == context_in.angle:
                    candidate_clockwise = not candidate_clockwise
                    candidate_angle_in = (candidate_angle_in + 180) % 360
                    candidate_angle_out = (candidate_angle_in + da) % 360
        else:
            candidate_angle_in = angle_in
            candidate_angle_out = (candidate_angle_in + da) % 360
            candidate_clockwise = self.clockwise
            if candidate_clockwise != (context_in == NO_CONTEXT):
                flip()
            clockwise_from_adjacent_curve = (
                context_in.clockwise
                    if context_in != NO_CONTEXT
                    else context_out.clockwise
            )
            if self.secondary != (clockwise_from_adjacent_curve not in [None, candidate_clockwise]):
                flip()
        if self.hook or (context_in != NO_CONTEXT != context_out):
            final_hook = self.hook and context_in != NO_CONTEXT
            if final_hook:
                flip()
                context_out = context_in.reversed()
                context_in = NO_CONTEXT
                angle_in, angle_out = (angle_out + 180) % 360, (angle_in + 180) % 360
            context_clockwises = (context_in.clockwise, context_out.clockwise)
            curve_offset = 0 if context_clockwises in [(None, None), (True, False), (False, True)] else CURVE_OFFSET
            if False in context_clockwises:
                curve_offset = -curve_offset
            a1, a2 = self._get_normalized_angles()
            slight_overlap_offset = abs(a1 - a2) / 4 * (1 if candidate_clockwise else -1)
            if final_hook != (
                not ((abs(slight_overlap_offset) + abs(curve_offset) >= abs(a1 - a2)
                        and math.copysign(1, slight_overlap_offset) != math.copysign(1, curve_offset))
                    or self.in_degree_range(
                        (angle_out + 180) % 360,
                        (candidate_angle_out + slight_overlap_offset) % 360,
                        (candidate_angle_in + curve_offset) % 360,
                        candidate_clockwise,
                    )
                )
            ):
                flip()
            if (context_out.clockwise == context_in.clockwise == candidate_clockwise
                and (self.in_degree_range(
                    angle_out,
                    (angle_in + 180) % 360,
                    (angle_in + 180 + curve_offset) % 360,
                    not candidate_clockwise,
                ) or self.in_degree_range(
                    (angle_out - curve_offset) % 360,
                    (angle_in + 180) % 360,
                    (angle_in + 180 + curve_offset) % 360,
                    not candidate_clockwise,
                ))
            ):
                flip()
        if context_in.diphthong_start or context_out.diphthong_end:
            candidate_angle_in = (candidate_angle_in - 180) % 360
            candidate_angle_out = (candidate_angle_out - 180) % 360
        return self.clone(
            angle_in=candidate_angle_in,
            angle_out=candidate_angle_out,
            clockwise=candidate_clockwise,
        )

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
            SECANT_ANCHOR: self.angle_out % 180,
        }

    def reversed(self):
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
        )

class CircleRole(enum.Enum):
    INDEPENDENT = enum.auto()
    LEADER = enum.auto()
    DEPENDENT = enum.auto()

class Circle(Shape):
    def __init__(
        self,
        angle_in,
        angle_out,
        *,
        clockwise,
        reversed=False,
        pinned=False,
        stretch=0,
        long=False,
        role=CircleRole.INDEPENDENT,
    ):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.reversed = reversed
        self.pinned = pinned
        self.stretch = stretch
        self.long = long
        self.role = role

    def clone(
        self,
        *,
        angle_in=CLONE_DEFAULT,
        angle_out=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        reversed=CLONE_DEFAULT,
        pinned=CLONE_DEFAULT,
        stretch=CLONE_DEFAULT,
        long=CLONE_DEFAULT,
        role=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            clockwise=self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            reversed=self.reversed if reversed is CLONE_DEFAULT else reversed,
            pinned=self.pinned if pinned is CLONE_DEFAULT else pinned,
            stretch=self.stretch if stretch is CLONE_DEFAULT else stretch,
            long=self.long if long is CLONE_DEFAULT else long,
            role=self.role if role is CLONE_DEFAULT else role,
        )

    def __str__(self):
        return f'''{
                int(self.angle_in)
            }{
                'n' if self.clockwise else 'p'
            }{
                int(self.angle_out)
            }{
                'r' if self.reversed else ''
            }'''

    def group(self):
        angle_in = self.angle_in
        angle_out = self.angle_out
        if self.clockwise:
            angle_in = (angle_in + 180) % 360
            angle_out = (angle_out + 180) % 360
        return (
            angle_in,
            angle_out,
            self.stretch,
            self.long,
        )

    @staticmethod
    def can_take_secant():
        return True

    def hub_priority(self, size):
        return 0 if size >= 6 else 1

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        angle_in = self.angle_in
        angle_out = self.angle_out
        if (diphthong_1 or diphthong_2) and angle_in == angle_out:
            Curve(
                    angle_in,
                    angle_out,
                    clockwise=self.clockwise,
                    stretch=self.stretch,
                    long=True,
                    reversed_circle=self.reversed,
                ).draw(
                    glyph,
                    pen,
                    stroke_width,
                    light_line,
                    stroke_gap,
                    size,
                    anchor,
                    joining_type,
                    child,
                    initial_circle_diphthong,
                    final_circle_diphthong,
                    diphthong_1,
                    diphthong_2,
                )
            return
        if diphthong_1:
            angle_out = (angle_out + 90 * (1 if self.clockwise else -1)) % 360
        if diphthong_2:
            angle_in = (angle_in - 90 * (1 if self.clockwise else -1)) % 360
        if self.clockwise and angle_out > angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        r = int(RADIUS * size)
        cp = r * (4 / 3) * math.tan(math.pi / 8)
        entry = rect(r, math.radians(a1))
        if diphthong_2:
            pen.moveTo(entry)
            entry_delta = rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (entry[0] + entry_delta[0], entry[1] + entry_delta[1])
            pen.lineTo(entry)
            pen.endPath()
        pen.moveTo((0, r))
        pen.curveTo((cp, r), (r, cp), (r, 0))
        pen.curveTo((r, -cp), (cp, -r), (0, -r))
        pen.curveTo((-cp, -r), (-r, -cp), (-r, 0))
        pen.curveTo((-r, cp), (-cp, r), (0, r))
        pen.endPath()
        exit = rect(r, math.radians(a2))
        if diphthong_1:
            pen.moveTo(exit)
            exit_delta = rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
            pen.endPath()
        anchor_name = mkmk if child else lambda a: a
        base = 'basemark' if child else 'base'
        if joining_type != Type.NON_JOINING:
            if child:
                glyph.addAnchorPoint(PARENT_EDGE_ANCHOR, 'mark', 0, 0)
            else:
                glyph.addAnchorPoint(CONTINUING_OVERLAP_ANCHOR, 'entry', 0, 0)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *entry)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *exit)
                glyph.addAnchorPoint(POST_HUB_CONTINUING_OVERLAP_ANCHOR, 'entry', 0, 0)
                if self.hub_priority(size) != -1:
                    glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'entry', *entry)
                if self.hub_priority(size) != 0:
                    glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', *exit)
                glyph.addAnchorPoint(anchor_name(SECANT_ANCHOR), base, 0, 0)
        glyph.addAnchorPoint(anchor_name(RELATIVE_1_ANCHOR), base, *rect(0, 0))
        if anchor:
            glyph.addAnchorPoint(MIDDLE_ANCHOR, 'mark', 0, 0)
        if self.stretch:
            scale_x = 1.0 + self.stretch
            scale_y = 1.0
            if self.long:
                scale_x, scale_y = scale_y, scale_x
            theta = math.radians(angle_in % 180)
            glyph.transform(
                fontTools.misc.transform.Identity
                    .rotate(theta)
                    .scale(scale_x, scale_y)
                    .rotate(-theta),
            )
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(scale_x * r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(angle_in)))
        else:
            glyph.addAnchorPoint(anchor_name(RELATIVE_2_ANCHOR), base, *rect(r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians((a1 + a2) / 2)))
        glyph.stroke('circular', stroke_width, 'round')
        if diphthong_1 or diphthong_2:
            glyph.removeOverlap()
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        glyph.addAnchorPoint(anchor_name(ABOVE_ANCHOR), base, x_center, y_max + stroke_gap)
        glyph.addAnchorPoint(anchor_name(BELOW_ANCHOR), base, x_center, y_min - stroke_gap)

    def can_be_child(self, size):
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
                else None
                if context_in.angle == context_out.angle
                else context_out.clockwise)
        def flop():
            nonlocal clockwise
            nonlocal angle_in
            nonlocal angle_out
            if (context_in.ignorable_for_topography and (context_in.clockwise == clockwise) != context_in.diphthong_start
                or context_out.ignorable_for_topography and (context_out.clockwise == clockwise) != context_out.diphthong_end
            ):
                clockwise = not clockwise
            if context_in.ignorable_for_topography and context_out == NO_CONTEXT:
                angle_out = angle_in if context_in.diphthong_start else (angle_in + 180) % 360
            elif context_out.ignorable_for_topography and context_in == NO_CONTEXT:
                angle_in = angle_out if context_out.diphthong_end else (angle_out + 180) % 360
            if context_in.diphthong_start:
                angle_in = (angle_in - 180) % 360
                if context_out == NO_CONTEXT:
                    angle_out = (angle_out - 180) % 360
            elif context_out.diphthong_end:
                angle_in = (angle_in - 180) % 360
                angle_out = (angle_out - 180) % 360
        if angle_in == angle_out:
            clockwise = (clockwise_from_adjacent_curve != self.reversed
                if clockwise_from_adjacent_curve is not None
                else self.clockwise
            )
            flop()
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_out,
                clockwise=clockwise,
            )
        da = abs(angle_out - angle_in)
        clockwise_ignoring_curvature = (da >= 180) != (angle_out > angle_in)
        forms_loop_next_to_curve = context_in.has_clockwise_loop_to(context_out) == clockwise_from_adjacent_curve
        clockwise_ignoring_reversal = (
            clockwise_from_adjacent_curve
                if forms_loop_next_to_curve and clockwise_from_adjacent_curve is not None
                else clockwise_ignoring_curvature)
        clockwise = clockwise_ignoring_reversal != self.reversed
        flop()
        if angle_in == angle_out:
            clockwise = (clockwise_from_adjacent_curve != self.reversed
                if clockwise_from_adjacent_curve is not None
                else self.clockwise
            )
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_out,
                clockwise=clockwise,
            )
        if self.role != CircleRole.INDEPENDENT and (self.pinned or not self.reversed):
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_in if self.role == CircleRole.LEADER else angle_out,
                clockwise=clockwise,
            )
        elif clockwise_ignoring_reversal == clockwise_ignoring_curvature:
            if self.reversed:
                if da != 180:
                    return Curve(
                        angle_in,
                        (angle_out + 180) % 360,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=True,
                    )
                else:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=(angle_out + 180) % 360,
                        clockwise=clockwise,
                    )
            else:
                return Curve(
                    angle_in,
                    angle_out,
                    clockwise=clockwise,
                    stretch=self.stretch,
                    long=True,
                )
        else:
            if self.reversed:
                if da != 180:
                    return Curve(
                        angle_in,
                        angle_out,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=True,
                    )
                else:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=(angle_out + 180) % 360,
                        clockwise=clockwise,
                    )
            else:
                if da != 180 and not forms_loop_next_to_curve:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=angle_out,
                        clockwise=clockwise,
                    )
                else:
                    return Curve(
                        angle_in,
                        angle_out,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                    )

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
        maximum_tree_width=0,
        _final_rotation=0,
    ):
        self.instructions = instructions
        self.hook = hook
        self.maximum_tree_width = maximum_tree_width
        self._final_rotation = _final_rotation

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
        hook=CLONE_DEFAULT,
        maximum_tree_width=CLONE_DEFAULT,
        _final_rotation=CLONE_DEFAULT,
    ):
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            hook=self.hook if hook is CLONE_DEFAULT else hook,
            maximum_tree_width=self.maximum_tree_width if maximum_tree_width is CLONE_DEFAULT else maximum_tree_width,
            _final_rotation=self._final_rotation if _final_rotation is CLONE_DEFAULT else _final_rotation,
        )

    def __str__(self):
        if self._final_rotation:
            return str(int(self._final_rotation))
        non_callables = filter(lambda op: not callable(op), self.instructions)
        op = next(non_callables)
        if isinstance(op[1], Circle):
            op = next(non_callables)
        return str(op[1])

    def group(self):
        return (
            *(op if callable(op) else (op[0], op[1].group(), op[2:]) for op in self.instructions),
            self._final_rotation,
        )

    def hub_priority(self, size):
        first_scalar, first_component, *_ = next(op for op in self.instructions if not (callable(op) or op[1].invisible()))
        return first_component.hub_priority(first_scalar * size)

    class Proxy:
        def __init__(self):
            self.anchor_points = collections.defaultdict(list)
            self.contour = fontforge.contour()

        def addAnchorPoint(self, anchor_class_name, anchor_type, x, y):
            self.anchor_points[(anchor_class_name, anchor_type)].append((x, y))

        def stroke(self, *args):
            pass

        def boundingBox(self):
            return self.contour.boundingBox()

        def transform(self, matrix, *args):
            for anchor, points in self.anchor_points.items():
                for i, x_y in enumerate(points):
                    new_point = fontforge.point(*x_y).transform(matrix)
                    self.anchor_points[anchor][i] = (new_point.x, new_point.y)
            self.contour.transform(matrix)

        def moveTo(self, x_y):
            if not self.contour:
                self.contour.moveTo(*x_y)

        def lineTo(self, x_y):
            self.contour.lineTo(*x_y)

        def curveTo(self, cp1, cp2, x_y):
            self.contour.cubicTo(cp1, cp2, x_y)

        def endPath(self):
            pass

        def removeOverlap(self):
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

    def draw_to_proxy(self, pen, stroke_width, light_line, stroke_gap, size):
        first_is_invisible = None
        singular_anchor_points = collections.defaultdict(list)
        for op in self.instructions:
            if callable(op):
                continue
            scalar, component, *skip_drawing = op
            proxy = Complex.Proxy()
            component.draw(
                proxy,
                proxy,
                stroke_width,
                light_line,
                stroke_gap,
                scalar * size,
                None,
                Type.JOINING,
                False,
                False,
                False,
                False,
                False,
            )
            if first_is_invisible is None:
                first_is_invisible = component.invisible()
            this_entry_list = proxy.anchor_points[(CURSIVE_ANCHOR, 'entry')]
            assert len(this_entry_list) == 1
            this_x, this_y = this_entry_list[0]
            if exit_list := singular_anchor_points.get((CURSIVE_ANCHOR, 'exit')):
                last_x, last_y = exit_list[-1]
                proxy.transform(fontTools.misc.transform.Offset(
                    last_x - this_x,
                    last_y - this_y,
                ))
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1:
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not (skip_drawing and skip_drawing[0]):
                proxy.contour.draw(pen)
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    @staticmethod
    def _remove_bad_contours(glyph):
        if not hasattr(glyph, 'foreground'):
            # This `Complex` is nested within another `Complex`. The outermost one
            # will remove all the bad contours.
            return
        bad_indices = []
        foreground = glyph.foreground
        for contour_index, contour in enumerate(foreground):
            if not contour.closed and len(contour) == 2 and contour[0] == contour[1]:
                bad_indices.append(contour_index)
        if bad_indices:
            for bad_index in reversed(bad_indices):
                del foreground[bad_index]
            glyph.foreground = foreground

    def enter_on_first_path(self):
        return True

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        (
            first_is_invisible,
            singular_anchor_points,
        ) = self.draw_to_proxy(pen, stroke_width, light_line, stroke_gap, size)
        glyph.stroke('circular', stroke_width, 'round')
        glyph.removeOverlap()
        self._remove_bad_contours(glyph)
        if not (anchor or child or joining_type == Type.NON_JOINING):
            entry = singular_anchor_points[(CURSIVE_ANCHOR, 'entry')][0 if self.enter_on_first_path() else -1]
            exit = singular_anchor_points[(CURSIVE_ANCHOR, 'exit')][-1]
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *entry)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *exit)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(POST_HUB_CURSIVE_ANCHOR, 'entry', *entry)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(PRE_HUB_CURSIVE_ANCHOR, 'exit', *exit)
        anchor_name = mkmk if anchor or child else lambda a: a
        base = 'basemark' if anchor or child else 'base'
        if anchor is None:
            for (singular_anchor, type), points in singular_anchor_points.items():
                if singular_anchor in MARK_ANCHORS or (
                    self.maximum_tree_width and (
                        singular_anchor == CONTINUING_OVERLAP_ANCHOR
                        or any(map(lambda l: singular_anchor in l, CHILD_EDGE_ANCHORS))
                    )
                ):
                    glyph.addAnchorPoint(singular_anchor, type, *points[-1])
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self._final_rotation)),
            ('round',),
        )
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        y_center = (y_max + y_min) / 2
        if anchor == MIDDLE_ANCHOR:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_center)
        elif anchor == ABOVE_ANCHOR:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_min + stroke_width / 2)
        elif anchor == BELOW_ANCHOR:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_max - stroke_width / 2)
        elif anchor is None:
            glyph.addAnchorPoint(MIDDLE_ANCHOR, 'base', x_center, y_center)
            glyph.addAnchorPoint(ABOVE_ANCHOR, 'base', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
            glyph.addAnchorPoint(BELOW_ANCHOR, 'base', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
        return first_is_invisible

    def can_be_child(self, size):
        #return not callable(self.instructions[0]) and self.instructions[0][1].can_be_child(size)
        return False

    def max_tree_width(self, size):
        return self.maximum_tree_width

    def is_shadable(self):
        return all(callable(op) or op[1].is_shadable() for op in self.instructions)

    def contextualize(self, context_in, context_out):
        instructions = []
        initial_hook = context_in == NO_CONTEXT and self.hook
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
                        if forced_context != NO_CONTEXT:
                            component = component.clone(angle=forced_context.angle)
                    else:
                        if forced_context.clockwise is not None and forced_context.clockwise != component.clockwise:
                            component = component.reversed()
                        if forced_context != NO_CONTEXT and forced_context.angle != (component.angle_out if initial_hook else component.angle_in):
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
        return next(op for op in reversed(self.instructions) if not callable(op))[1].context_out()

    def rotate_diacritic(self, context):
        return self.clone(_final_rotation=context.angle)

class InvalidDTLS(Complex):
    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class InvalidOverlap(Complex):
    def __init__(
        self,
        *,
        continuing,
        instructions,
    ):
        super().__init__(instructions)
        self.continuing = continuing

    def clone(
        self,
        *,
        continuing=CLONE_DEFAULT,
        instructions=CLONE_DEFAULT,
    ):
        return type(self)(
            continuing=self.continuing if continuing is CLONE_DEFAULT else continuing,
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER

class InvalidStep(Complex):
    def __init__(self, angle, instructions):
        super().__init__(instructions)
        self.angle = angle

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        instructions=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    def contextualize(self, context_in, context_out):
        return Space(self.angle)

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class RomanianU(Complex):
    def draw_to_proxy(self, pen, stroke_width, light_line, stroke_gap, size):
        (
            first_is_invisible,
            singular_anchor_points,
        ) = super().draw_to_proxy(pen, stroke_width, light_line, stroke_gap, size)
        singular_anchor_points[(RELATIVE_1_ANCHOR, 'base')] = singular_anchor_points[(CURSIVE_ANCHOR, 'exit')]
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    def contextualize(self, context_in, context_out):
        if context_in == NO_CONTEXT or context_out == NO_CONTEXT:
            return super().contextualize(context_in, context_out)
        return Circle(0, 0, clockwise=False).contextualize(context_in, context_out)

class Ou(Complex):
    def __init__(
        self,
        instructions,
        role=CircleRole.INDEPENDENT,
        _initial=False,
        _isolated=True,
    ):
        super().__init__(instructions, hook=True)
        self.role = role
        self._initial = _initial
        self._isolated = _isolated

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
        role=CLONE_DEFAULT,
        _initial=CLONE_DEFAULT,
        _isolated=CLONE_DEFAULT,
    ):
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            self.role if role is CLONE_DEFAULT else role,
            self._initial if _initial is CLONE_DEFAULT else _initial,
            self._isolated if _isolated is CLONE_DEFAULT else _isolated,
        )

    def __str__(self):
        rv = str(self.instructions[2 if self._initial and self.role == CircleRole.LEADER else 0][1])
        if self.role == CircleRole.LEADER and not self._isolated:
            rv += '.open'
        return rv

    def group(self):
        leader = self.role == CircleRole.LEADER and not self._isolated
        return (
            super().group(),
            leader,
            leader and self._initial,
        )

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        if self.role != CircleRole.LEADER or self._isolated:
            drawer = super()
        else:
            circle_op = self.instructions[2 if self._initial else 0]
            circle_path = circle_op[1]
            clockwise = circle_path.clockwise
            curve_op = self.instructions[0 if self._initial else 2]
            curve_path = curve_op[1]
            curve_da = curve_path.angle_out - curve_path.angle_in
            if self._initial:
                angle_out = circle_path.angle_out
                intermediate_angle = (angle_out + curve_da) % 360
                instructions = [
                    (curve_op[0], curve_path.clone(
                        angle_in=angle_out,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (circle_op[0], Curve(
                        angle_in=intermediate_angle,
                        angle_out=angle_out,
                        clockwise=clockwise,
                    )),
                ]
            else:
                angle_in = circle_path.angle_in
                intermediate_angle = (angle_in - curve_da) % 360
                instructions = [
                    (circle_op[0], Curve(
                        angle_in=angle_in,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (curve_op[0], curve_path.clone(
                        angle_in=intermediate_angle,
                        angle_out=angle_in,
                        clockwise=clockwise,
                    )),
                ]
            drawer = Complex(instructions=instructions)
        drawer.draw(
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )

    def contextualize(self, context_in, context_out):
        return super().contextualize(context_in, context_out).clone(
            _initial=self._initial or context_in == NO_CONTEXT,
            _isolated=False,
        )

    def context_in(self):
        if self._initial:
            rv = super().context_out()
            return rv.clone(angle=(rv.angle + 180) % 360)
        else:
            return super().context_in()

    def context_out(self):
        if self._isolated:
            return super().context_out()
        else:
            rv = self.context_in()
            return rv.clone(angle=(rv.angle + 180) % 360)

class Wa(Complex):
    def __init__(
        self,
        instructions,
    ):
        super().__init__(instructions)

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
    ):
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    def draw_to_proxy(self, pen, stroke_width, light_line, stroke_gap, size):
        first_is_invisible = None
        last_crossing_point = None
        singular_anchor_points = collections.defaultdict(list)
        for op in self.instructions:
            scalar, component, *skip_drawing = op
            proxy = Complex.Proxy()
            component.draw(
                proxy,
                proxy,
                stroke_width,
                light_line,
                stroke_gap,
                scalar
                *
                size,
                None,
                Type.JOINING,
                False,
                False,
                False,
                False,
                False,
            )
            if first_is_invisible is None:
                first_is_invisible = component.invisible()
            this_crossing_point = proxy.get_crossing_point(component)
            if last_crossing_point is not None:
                proxy.transform(fontTools.misc.transform.Offset(
                    last_crossing_point[0] - this_crossing_point[0],
                    last_crossing_point[1] - this_crossing_point[1],
                ))
            last_crossing_point = this_crossing_point
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1:
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not (skip_drawing and skip_drawing[0]):
                proxy.contour.draw(pen)
        first_entry = singular_anchor_points[(CURSIVE_ANCHOR, 'entry')][0]
        last_entry = singular_anchor_points[(CURSIVE_ANCHOR, 'entry')][-1]
        if math.hypot(first_entry[0] - last_entry[0], first_entry[1] - last_entry[1]) >= 10:
            proxy = Complex.Proxy()
            # FIXME: Using the anchor points unmodified, FontForge gets stuck in
            # `font.generate`. If some but not all the points are offset by 0.01,
            # the stroking code produces buggy results for some glyphs.
            proxy.moveTo((first_entry[0], first_entry[1] + 0.01))
            proxy.lineTo((last_entry[0], last_entry[1] + 0.01))
            proxy.contour.draw(pen)
        first_exit = singular_anchor_points[(CURSIVE_ANCHOR, 'exit')][0]
        last_exit = singular_anchor_points[(CURSIVE_ANCHOR, 'exit')][-1]
        if math.hypot(first_exit[0] - last_exit[0], first_exit[1] - last_exit[1]) >= 10:
            proxy = Complex.Proxy()
            proxy.moveTo((first_exit[0], first_exit[1] + 0.01))
            proxy.lineTo((last_exit[0], last_exit[1] + 0.01))
            proxy.contour.draw(pen)
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    def enter_on_first_path(self):
        return False

    def contextualize(self, context_in, context_out):
        instructions = []
        for scalar, component in self.instructions:
            component = component.contextualize(context_in, context_out)
            instructions.append((scalar, component))
        outer_circle_path = instructions[0][1]
        if isinstance(outer_circle_path, Curve):
            assert context_in != NO_CONTEXT and context_out != NO_CONTEXT
            a1, a2 = outer_circle_path._get_normalized_angles()
            if abs(a2 - a1) < 180:
                return Complex(instructions=[
                    (
                        instructions[0][0],
                        self.instructions[0][1].clone(
                            angle_in=instructions[-1][1].angle_in,
                            angle_out=instructions[-1][1].angle_in,
                            clockwise=instructions[-1][1].clockwise,
                        ),
                        *instructions[0][2:]
                    ),
                    *instructions[1:],
                ])
        return self.clone(instructions=instructions)

class Wi(Complex):
    def contextualize(self, context_in, context_out):
        if context_in != NO_CONTEXT or context_out == NO_CONTEXT:
            curve_index = next(i for i, op in enumerate(self.instructions) if not callable(op) and not isinstance(op[1], Circle))
            if curve_index == 0:
                return super().contextualize(context_in, context_out)
            curve_path = self.clone(instructions=self.instructions[curve_index:]).contextualize(context_in, context_out)
            circle_path = self.instructions[0][1].clone(
                angle_in=curve_path.instructions[0][1].angle_in,
                angle_out=curve_path.instructions[0][1].angle_in,
                clockwise=curve_path.instructions[0][1].clockwise,
            )
            return self.clone(instructions=[(self.instructions[0][0], circle_path), *curve_path.instructions])
        if Curve.in_degree_range(
            context_out.angle,
            self.instructions[-1][1].angle_out,
            (self.instructions[-1][1].angle_out + 180 - EPSILON * (-1 if self.instructions[-1][1].clockwise else 1)) % 360,
            self.instructions[-1][1].clockwise,
        ):
            return self.clone(
                instructions=[
                    op
                        if callable(op)
                        else (
                            op[0],
                            op[1].clone(
                                    angle_in=(op[1].angle_in + 180) % 360,
                                    angle_out=(op[1].angle_out + 180) % 360,
                                    clockwise=not op[1].clockwise,
                                ) if isinstance(op[1], (Circle, Curve))
                                else op[1]
                            *op[2:],
                        ) for op in self.instructions
                ],
            )
        return self

class TangentHook(Complex):
    def __init__(
        self,
        instructions,
        *,
        _initial=False,
    ):
        while callable(instructions[0]):
            instructions = instructions[1:]
        super().__init__([self.override_initial_context if _initial else self.override_noninitial_context, *instructions], hook=True)
        self._initial = _initial

    @staticmethod
    def override_noninitial_context(c):
        return Context(
            None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else  (c.angle + 90) % 360,
            not (90 < c.angle < 315),
        )

    @staticmethod
    def override_initial_context(c):
        return Context(
            None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else  (c.angle + 90) % 360,
            90 < c.angle < 315,
        )

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
        _initial=CLONE_DEFAULT,
    ):
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            _initial=self._initial if _initial is CLONE_DEFAULT else _initial,
        )

    def contextualize(self, context_in, context_out):
        if context_in == NO_CONTEXT != context_out and not self._initial:
            shape = self.clone(instructions=[
                self.instructions[0],
                (self.instructions[1][0], self.instructions[1][1].clone(
                    angle_in=self.instructions[1][1].angle_in,
                    angle_out=(self.instructions[1][1].angle_out + 180) % 360,
                    clockwise=not self.instructions[1][1].clockwise,
                )),
                self.instructions[2],
                (self.instructions[3][0], self.instructions[3][1].clone(
                    angle_in=self.instructions[3][1].angle_out,
                    angle_out=(self.instructions[3][1].angle_out + 180) % 360,
                    clockwise=not self.instructions[3][1].clockwise,
                )),
            ], _initial=True)
        else:
            shape = super()
        return shape.contextualize(context_in, context_out)

class XShape(Complex):
    def hub_priority(self, size):
        return 1

    def draw(
            self,
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
    ):
        super().draw(
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        for anchor_class_name, type, x, y in glyph.anchorPoints:
            if anchor_class_name == CURSIVE_ANCHOR:
                if type == 'entry':
                    entry = x, y
                elif type == 'exit':
                    exit = x, y
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != CURSIVE_ANCHOR]
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_avg = (x_min + x_max) / 2
        y_avg = (y_min + y_max) / 2
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', x_avg, y_avg)
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', x_avg, y_avg)

    def is_pseudo_cursive(self, size):
        return True

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Ignorability(enum.Enum):
    DEFAULT_NO = enum.auto()
    DEFAULT_YES = enum.auto()
    OVERRIDDEN_NO = enum.auto()

class Schema:
    _CHARACTER_NAME_SUBSTITUTIONS = [(re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in [
        # Custom PUA names
        (r'^uniE000$', 'BOUND'),
        (r'^uniEC02$', 'DUPLOYAN LETTER REVERSED P'),
        (r'^uniEC03$', 'DUPLOYAN LETTER REVERSED T'),
        (r'^uniEC04$', 'DUPLOYAN LETTER REVERSED F'),
        (r'^uniEC05$', 'DUPLOYAN LETTER REVERSED K'),
        (r'^uniEC06$', 'DUPLOYAN LETTER REVERSED L'),
        (r'^uniEC19$', 'DUPLOYAN LETTER REVERSED M'),
        (r'^uniEC1A$', 'DUPLOYAN LETTER REVERSED N'),
        (r'^uniEC1B$', 'DUPLOYAN LETTER REVERSED J'),
        (r'^uniEC1C$', 'DUPLOYAN LETTER REVERSED S'),
        (r'^uniEC44$', 'DUPLOYAN LETTER REVERSED O'),
        (r'^uniEC5A$', 'DUPLOYAN LETTER REVERSED OW'),
        (r'^uniEC5B$', 'DUPLOYAN LETTER REVERSED OU'),
        # Unicode name aliases
        (r'^ZERO WIDTH SPACE$', 'ZWSP'),
        (r'^ZERO WIDTH NON-JOINER$', 'ZWNJ'),
        (r'^ZERO WIDTH JOINER$', 'ZWJ'),
        (r'^NARROW NO-BREAK SPACE$', 'NNBSP'),
        (r'^MEDIUM MATHEMATICAL SPACE$', 'MMSP'),
        (r'^WORD JOINER$', 'WJ'),
        (r'^ZERO WIDTH NO-BREAK SPACE$', 'ZWNBSP'),
        # Custom name aliases
        (r'^DUPLOYAN THICK LETTER SELECTOR$', 'DTLS'),
        # Familiar vocabulary choices from AGLFN
        (r'\bFULL STOP\b', 'PERIOD'),
        (r'\bQUOTATION MARK\b', 'QUOTE'),
        (r'\bSOLIDUS\b', 'SLASH'),
        (r'(?<=ER|SS)[- ]THAN\b', ''),
        # Unnecessary words
        (r'\bDOTS INSIDE AND ABOVE\b', 'DOTS'),
        (r' ACCENT\b', ''),
        (r' (AND|WITH) ', ' '),
        (r'\bCOMBINING ', ''),
        (r'\bDIGIT ', ''),
        (r'^DUPLOYAN ((AFFIX( ATTACHED)?|LETTER|PUNCTUATION|SIGN) )?', ''),
        (r' (MARK|SIGN)$', ''),
        (r'[- ]POINTING\b', ''),
        (r'^SHORTHAND FORMAT ', ''),
        # Final munging
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
            cmap,
            path,
            size,
            joining_type=Type.JOINING,
            *,
            side_bearing=DEFAULT_SIDE_BEARING,
            child=False,
            can_lead_orienting_sequence=None,
            ignored_for_topography=False,
            anchor=None,
            widthless=None,
            marks=None,
            ignorability=Ignorability.DEFAULT_NO,
            encirclable=False,
            shading_allowed=True,
            context_in=None,
            context_out=None,
            diphthong_1=False,
            diphthong_2=False,
            base_angle=None,
            cps=None,
            original_shape=None,
    ):
        assert not (marks and anchor), 'A schema has both marks {} and anchor {}'.format(marks, anchor)
        assert not widthless or anchor, f'A widthless schema has anchor {anchor}'
        self.cmap = cmap
        self.path = path
        self.size = size
        self.joining_type = joining_type
        self.side_bearing = side_bearing
        self.child = child
        self.can_lead_orienting_sequence = can_lead_orienting_sequence if can_lead_orienting_sequence is not None else joining_type == Type.ORIENTING
        self.ignored_for_topography = ignored_for_topography
        self.anchor = anchor
        self.widthless = widthless
        self.marks = marks or []
        self.ignorability = ignorability
        self.encirclable = encirclable
        self.shading_allowed = shading_allowed
        self.context_in = context_in or NO_CONTEXT
        self.context_out = context_out or NO_CONTEXT
        self.diphthong_1 = diphthong_1
        self.diphthong_2 = diphthong_2
        self.base_angle = base_angle
        self.cps = cps or ([] if cmap is None else [cmap])
        self.original_shape = original_shape or type(path)
        self.phase_index = CURRENT_PHASE_INDEX
        self._glyph_name = None
        self._canonical_schema = self
        self._lookalike_group = [self]
        self.glyph = None

    def sort_key(self):
        cmap_string = '' if self.cmap is None else chr(self.cmap)
        return (
            bool(self.cps) and any(unicodedata.category(chr(cp)) == 'Co' for cp in self.cps),
            self.phase_index,
            self.cmap is None,
            not unicodedata.is_normalized('NFD', cmap_string),
            not self.cps,
            len(self.cps),
            self.original_shape != type(self.path),
            self.cps,
            len(self._calculate_name()),
        )

    def clone(
        self,
        *,
        cmap=CLONE_DEFAULT,
        path=CLONE_DEFAULT,
        size=CLONE_DEFAULT,
        joining_type=CLONE_DEFAULT,
        side_bearing=CLONE_DEFAULT,
        child=CLONE_DEFAULT,
        can_lead_orienting_sequence=CLONE_DEFAULT,
        ignored_for_topography=CLONE_DEFAULT,
        anchor=CLONE_DEFAULT,
        widthless=CLONE_DEFAULT,
        marks=CLONE_DEFAULT,
        ignorability=CLONE_DEFAULT,
        encirclable=CLONE_DEFAULT,
        shading_allowed=CLONE_DEFAULT,
        context_in=CLONE_DEFAULT,
        context_out=CLONE_DEFAULT,
        diphthong_1=CLONE_DEFAULT,
        diphthong_2=CLONE_DEFAULT,
        base_angle=CLONE_DEFAULT,
        cps=CLONE_DEFAULT,
        original_shape=CLONE_DEFAULT,
    ):
        return type(self)(
            self.cmap if cmap is CLONE_DEFAULT else cmap,
            self.path if path is CLONE_DEFAULT else path,
            self.size if size is CLONE_DEFAULT else size,
            self.joining_type if joining_type is CLONE_DEFAULT else joining_type,
            side_bearing=self.side_bearing if side_bearing is CLONE_DEFAULT else side_bearing,
            child=self.child if child is CLONE_DEFAULT else child,
            can_lead_orienting_sequence=self.can_lead_orienting_sequence if can_lead_orienting_sequence is CLONE_DEFAULT else can_lead_orienting_sequence,
            ignored_for_topography=self.ignored_for_topography if ignored_for_topography is CLONE_DEFAULT else ignored_for_topography,
            anchor=self.anchor if anchor is CLONE_DEFAULT else anchor,
            widthless=self.widthless if widthless is CLONE_DEFAULT else widthless,
            marks=self.marks if marks is CLONE_DEFAULT else marks,
            ignorability=self.ignorability if ignorability is CLONE_DEFAULT else ignorability,
            encirclable=self.encirclable if encirclable is CLONE_DEFAULT else encirclable,
            shading_allowed=self.shading_allowed if shading_allowed is CLONE_DEFAULT else shading_allowed,
            context_in=self.context_in if context_in is CLONE_DEFAULT else context_in,
            context_out=self.context_out if context_out is CLONE_DEFAULT else context_out,
            diphthong_1=self.diphthong_1 if diphthong_1 is CLONE_DEFAULT else diphthong_1,
            diphthong_2=self.diphthong_2 if diphthong_2 is CLONE_DEFAULT else diphthong_2,
            base_angle=self.base_angle if base_angle is CLONE_DEFAULT else base_angle,
            cps=self.cps if cps is CLONE_DEFAULT else cps,
            original_shape=self.original_shape if original_shape is CLONE_DEFAULT else original_shape,
        )

    def __repr__(self):
        return '<Schema {}>'.format(', '.join(map(str, [
            self._calculate_name(),
            self.cmap and f'{self.cmap:04X}',
            self.path,
            self.size,
            self.side_bearing,
            self.context_in,
            'NJ' if self.joining_type == Type.NON_JOINING else '',
            'mark' if self.anchor else 'base',
            [repr(m) for m in self.marks or []],
        ])))

    @functools.cached_property
    def diacritic_angles(self):
        return self.path.calculate_diacritic_angles()

    @functools.cached_property
    def without_marks(self):
        return self.marks and self.clone(cmap=None, marks=None)

    @functools.cached_property
    def glyph_class(self):
        return self.path.guaranteed_glyph_class() or (
            GlyphClass.MARK
                if self.anchor or self.child or self.ignored_for_topography
                else GlyphClass.BLOCKER
                if self.joining_type == Type.NON_JOINING
                else GlyphClass.JOINER
        )

    @functools.cached_property
    def might_need_width_markers(self):
        return not (
                self.ignored_for_topography or self.widthless
            ) and (
                self.glyph_class == GlyphClass.JOINER
                or self.glyph_class == GlyphClass.MARK
            )

    @functools.cached_property
    def group(self):
        if self.ignored_for_topography:
            return (
                self.ignorability == Ignorability.DEFAULT_YES,
                self.side_bearing,
            )
        if isinstance(self.path, Circle) and (self.diphthong_1 or self.diphthong_2):
            path_group = (
                self.path.angle_in,
                self.path.angle_out,
                self.path.clockwise,
                self.path.stretch,
                self.path.long,
            )
        else:
            path_group = self.path.group()
        return (
            self.ignorability == Ignorability.DEFAULT_YES,
            type(self.path),
            path_group,
            self.path.invisible() or self.cmap is not None or self.cps[-1:] != [0x1BC9D],
            self.size,
            self.joining_type,
            self.side_bearing,
            self.child,
            self.anchor,
            self.widthless,
            tuple(m.group for m in self.marks or []),
            self.glyph_class,
            self.context_in == NO_CONTEXT and not self.diphthong_1,
            self.context_out == NO_CONTEXT and not self.diphthong_2,
            self.context_in == NO_CONTEXT and self.diphthong_1,
            self.context_out == NO_CONTEXT and self.diphthong_2,
            self.diphthong_1,
            self.diphthong_2,
        )

    @property
    def canonical_schema(self):
        return self._canonical_schema

    @canonical_schema.setter
    def canonical_schema(self, canonical_schema):
        assert self._canonical_schema is self
        self._canonical_schema = canonical_schema
        self._glyph_name = None

    @canonical_schema.deleter
    def canonical_schema(self):
        del self._canonical_schema

    @property
    def lookalike_group(self):
        return self._lookalike_group

    @lookalike_group.setter
    def lookalike_group(self, lookalike_group):
        assert len(self._lookalike_group) == 1 and self._lookalike_group[0] is self
        self._lookalike_group = lookalike_group

    @lookalike_group.deleter
    def lookalike_group(self):
        del self._lookalike_group

    @staticmethod
    def _agl_name(cp):
        return fontTools.agl.UV2AGL[cp] if cp <= 0x7F else None

    @staticmethod
    def _u_name(cp):
        return '{}{:04X}'.format('uni' if cp <= 0xFFFF else 'u', cp)

    @classmethod
    def _readable_name(cls, cp):
        try:
            name = unicodedata.name(chr(cp))
        except ValueError:
            name = cls._u_name(cp)
        for regex, repl in cls._CHARACTER_NAME_SUBSTITUTIONS:
            name = regex.sub(repl, name)
        return name

    def _calculate_name(self):
        cps = self.cps
        if cps:
            first_component_implies_type = False
            try:
                name = '_'.join(map(self._agl_name, cps))
            except:
                name = '_'.join(map(self._u_name, cps))
                readable_name = '__'.join(map(self._readable_name, cps))
                for regex, repl in self._SEQUENCE_NAME_SUBSTITUTIONS:
                    readable_name = regex.sub(repl, readable_name)
                if name != readable_name.replace('__', '_'):
                    name = f'{name}.{readable_name}'
        else:
            first_component_implies_type = self.path.name_implies_type()
            if first_component_implies_type:
                name = ''
            else:
                name = f'dupl.{type(self.path).__name__}'
        if first_component_implies_type or self.path.name_in_sfd() or (
            self.cmap is None
            and (
                self.joining_type == Type.ORIENTING
                or isinstance(self.path, ChildEdge)
                or isinstance(self.path, Line) and self.path.dots
            )
        ):
            if name_from_path := str(self.path):
                if name:
                    name += '.'
                name += name_from_path
        if not cps and isinstance(self.path, Space):
            name += f'''.{
                    int(self.size * math.cos(math.radians(self.path.angle)))
                }.{
                    int(self.size * math.sin(math.radians(self.path.angle)))
                }'''.replace('-', 'n')
        if not cps and self.anchor:
            name += f'.{self.anchor}'
        if self.diphthong_1 or self.diphthong_2:
            name += '.diph'
            if self.diphthong_1:
                name += '1'
            if self.diphthong_2:
                name += '2'
        if self.child:
            name += '.sub'
        if isinstance(self.path, Curve) and self.path.overlap_angle is not None:
            name += f'.{int(self.path.overlap_angle)}'
        if self.widthless:
            name += '.psts'
        if self.ignored_for_topography:
            name += '.dependent'
        if (isinstance(self.path, Circle)
            and self.path.role != CircleRole.INDEPENDENT
            and self.path.angle_in != self.path.angle_out
        ):
            name += '.circle'
        if first_component_implies_type or self.cmap is None and self.path.invisible():
            if name and first_component_implies_type:
                name = f'.{name}'
            if not isinstance(self.path, Notdef):
                if name.startswith('dupl.'):
                    name = name.removeprefix('dupl')
                name = f'_{name}'
        agl_string = fontTools.agl.toUnicode(name)
        agl_cps = [*map(ord, agl_string)]
        assert cps == agl_cps, f'''The glyph name "{
                name
            }" corresponds to <{
                ', '.join(f'U+{cp:04X}' for cp in agl_cps)
            }> but its glyph corresponds to <{
                ', '.join(f'U+{cp:04X}' for cp in cps)
            }>'''
        return name

    def __str__(self):
        if self._glyph_name is None:
            if self is not (canonical := self._canonical_schema):
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

    def max_double_marks(self):
        return (0
            if self.glyph_class != GlyphClass.JOINER
            else max(0, min(MAX_DOUBLE_MARKS, self.path.max_double_marks(self.size, self.joining_type, self.marks))))

    @functools.cached_property
    def pseudo_cursive(self):
        return self.glyph_class == GlyphClass.JOINER and self.path.is_pseudo_cursive(self.size)

    @functools.cached_property
    def is_primary(self):
        return not (self.path.reversed if isinstance(self.path, Circle) else self.path.secondary or self.path.reversed_circle)

    @functools.cached_property
    def can_become_part_of_diphthong(self):
        return not (self.diphthong_1
            or self.diphthong_2
            or (self.glyph_class != GlyphClass.JOINER and not self.ignored_for_topography)
            or self.joining_type != Type.ORIENTING
            or isinstance(self.path, Ou)
            or not self.can_be_ignored_for_topography()
            or isinstance(self.path, Curve) and not self.path.reversed_circle and (self.path.hook or (self.path.angle_out - self.path.angle_in) % 180 != 0)
            # TODO: Remove the following restriction.
            or self.path.stretch
        )

    def can_be_ignored_for_topography(self):
        return (isinstance(self.path, (Circle, Ou))
            or isinstance(self.path, Curve) and not self.path.hook
        )

    def contextualize(
        self,
        context_in,
        context_out,
        *,
        ignore_dependent_schemas=True,
    ):
        assert self.joining_type == Type.ORIENTING or isinstance(self.path, InvalidStep)
        ignored_for_topography = (
            ignore_dependent_schemas
            and context_out == NO_CONTEXT
            and self.can_be_ignored_for_topography()
            and context_in.ignorable_for_topography
        )
        if ignored_for_topography:
            if isinstance(self.path, Circle):
                path = self.path.clone(role=CircleRole.DEPENDENT)
            else:
                path = self.path
        else:
            if not ignore_dependent_schemas and (self.diphthong_1 or self.diphthong_2):
                context_in = context_in.clone(diphthong_start=self.diphthong_2)
                context_out = context_out.clone(diphthong_end=self.diphthong_1)
            path = self.path.contextualize(context_in, context_out)
            if path is self.path:
                return self
        return self.clone(
            cmap=None,
            path=path,
            ignored_for_topography=ignored_for_topography,
            anchor=None,
            marks=None,
            context_in=None if ignored_for_topography else context_in,
            context_out=None if ignored_for_topography else context_out,
        )

    def path_context_in(self):
        context_in = self.path.context_in()
        ignorable_for_topography = (
                self.glyph_class == GlyphClass.JOINER
                and self.can_lead_orienting_sequence
                and (isinstance(self.path, Ou) or self.can_be_ignored_for_topography())
            ) or CLONE_DEFAULT
        return context_in.clone(
            ignorable_for_topography=ignorable_for_topography,
            diphthong_start=self.diphthong_1,
            diphthong_end=self.diphthong_2,
        )

    def path_context_out(self):
        context_out = self.path.context_out()
        ignorable_for_topography = (
            self.glyph_class == GlyphClass.JOINER
                and self.can_lead_orienting_sequence
                and (isinstance(self.path, Ou) or self.can_be_ignored_for_topography())
            ) or CLONE_DEFAULT
        return context_out.clone(
            ignorable_for_topography=ignorable_for_topography,
            diphthong_start=self.diphthong_1,
            diphthong_end=self.diphthong_2,
        )

    def rotate_diacritic(self, context):
        return self.clone(
            cmap=None,
            path=self.path.rotate_diacritic(context),
            base_angle=context.angle,
        )

    @functools.cached_property
    def hub_priority(self):
        if self.glyph_class != GlyphClass.JOINER:
            return -1
        priority = self.path.hub_priority(self.size)
        assert -1 <= priority <= MAX_HUB_PRIORITY, f'Invalid hub priority for {self._calculate_name()}: {priority}'
        return priority

class FreezableList:
    def __init__(self):
        self._delegate = []

    def freeze(self):
        self._delegate = tuple(self._delegate)

    def __iter__(self):
        return iter(self._delegate)

    def __len__(self):
        return len(self._delegate)

    def insert(self, index, object, /):
        try:
            self._delegate.insert(index, object)
        except AttributeError:
            raise ValueError('Inserting into a frozen list') from None

    def append(self, object, /):
        try:
            self._delegate.append(object)
        except AttributeError:
            raise ValueError('Appending to a frozen list') from None

    def extend(self, iterable, /):
        try:
            self._delegate.extend(iterable)
        except AttributeError:
            raise ValueError('Extending a frozen list') from None

class OrderedSet(dict):
    def __init__(self, iterable=None, /):
        super().__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item, /):
        self[item] = None

    def remove(self, item, /):
        self.pop(item, None)

    def sorted(self, /, *, key=None, reverse=False):
        return sorted(self.keys(), key=key, reverse=reverse)

class AlwaysTrueList(list):
    def __bool__(self):
        return True

class Rule:
    def __init__(
        self,
        a1,
        a2,
        a3=None,
        a4=None,
        /,
        *,
        lookups=None,
        x_placements=None,
        x_advances=None,
    ):
        def _l(glyphs):
            return [glyphs] if isinstance(glyphs, str) else glyphs
        if a4 is None and lookups is None and x_advances is None:
            assert a3 is None, 'Rule takes 2 or 4 inputs, given 3'
            a4 = a2
            a2 = a1
            a1 = []
            a3 = []
        assert (a4 is not None) + (lookups is not None) + (x_placements is not None or x_advances is not None) == 1, (
            'Rule can take exactly one of an output glyph/class list, a lookup list, or a position list')
        self.contexts_in = _l(a1)
        self.inputs = _l(a2)
        self.contexts_out = _l(a3)
        self.outputs = None
        self.lookups = lookups
        self.x_placements = x_placements
        self.x_advances = x_advances
        if lookups is not None:
            assert len(lookups) == len(self.inputs), f'There must be one lookup (or None) per input glyph ({len(lookups)} != {len(self.inputs)})'
        elif a4 is not None:
            self.outputs = _l(a4)
        else:
            if x_placements is not None:
                assert len(x_placements) == len(self.inputs), f'There must be one x placement (or None) per input glyph ({len(x_placements)} != {len(self.inputs)})'
            if x_advances is not None:
                assert len(x_advances) == len(self.inputs), f'There must be one x advance (or None) per input glyph ({len(x_advances)} != {len(self.inputs)})'

    def to_asts(self, class_asts, named_lookup_asts, in_contextual_lookup, in_multiple_lookup, in_reverse_lookup):
        def glyph_to_ast(glyph, unrolling_index=None):
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return fontTools.feaLib.ast.GlyphName(class_asts[glyph].glyphs.glyphs[unrolling_index])
                else:
                    return fontTools.feaLib.ast.GlyphClassName(class_asts[glyph])
            return fontTools.feaLib.ast.GlyphName(str(glyph))
        def glyphs_to_ast(glyphs, unrolling_index=None):
            return [glyph_to_ast(glyph, unrolling_index) for glyph in glyphs]
        def glyph_to_name(glyph, unrolling_index=None):
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return class_asts[glyph].glyphs.glyphs[unrolling_index]
                else:
                    assert not isinstance(glyph, str), f'Glyph classes are not allowed where only glyphs are expected: @{glyph}'
            return str(glyph)
        def glyphs_to_names(glyphs, unrolling_index=None):
            return [glyph_to_name(glyph, unrolling_index) for glyph in glyphs]
        if self.lookups is not None:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions do not support lookup references'
            return [fontTools.feaLib.ast.ChainContextSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                [None if name is None else named_lookup_asts[name] for name in self.lookups],
            )]
        elif self.x_placements is not None or self.x_advances is not None:
            assert not in_reverse_lookup, 'There is no reverse positioning lookup type'
            assert len(self.inputs) == 1, 'Only single adjustment positioning has been implemented'
            return [fontTools.feaLib.ast.SinglePosStatement(
                list(zip(
                    glyphs_to_ast(self.inputs),
                    [
                        fontTools.feaLib.ast.ValueRecord(x_placement, xAdvance=x_advance)
                            for x_placement, x_advance in itertools.zip_longest(
                                self.x_placements or [None] * len(self.inputs),
                                self.x_advances or [None] * len(self.inputs),
                            )
                    ],
                )),
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.contexts_out),
                in_contextual_lookup,
            )]
        elif len(self.inputs) == 1:
            if len(self.outputs) == 1 and not in_multiple_lookup:
                if in_reverse_lookup:
                    return [fontTools.feaLib.ast.ReverseChainSingleSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs),
                    )]
                else:
                    return [fontTools.feaLib.ast.SingleSubstStatement(
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs),
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        in_contextual_lookup,
                    )]
            else:
                assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
                input = self.inputs[0]
                if isinstance(input, str) and any(isinstance(output, str) for output in self.outputs):
                    # Allow classes in multiple substitution output by unrolling all uses of
                    # the class in parallel with the input class.
                    asts = []
                    for i, glyph_name in enumerate(class_asts[input].glyphs.glyphs):
                        asts.append(fontTools.feaLib.ast.MultipleSubstStatement(
                            glyphs_to_ast(self.contexts_in),
                            glyph_name,
                            glyphs_to_ast(self.contexts_out),
                            glyphs_to_names(self.outputs, i),
                            in_contextual_lookup,
                        ))
                    return asts
                else:
                    return [fontTools.feaLib.ast.MultipleSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        glyph_to_name(input),
                        glyphs_to_ast(self.contexts_out),
                        glyphs_to_names(self.outputs),
                        in_contextual_lookup,
                    )]
        else:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
            output = self.outputs[0]
            if isinstance(output, str):
                # Allow a class in ligature substitution output that is the same length
                # as the only class in the input by unrolling all uses of the classes in
                # parallel.
                input_class = None
                input_class_index = -1
                for i, input in enumerate(self.inputs):
                    if isinstance(input, str):
                        assert input_class is None, 'A ligature substitution with a glyph class output may only have one glyph class input'
                        assert len(class_asts[input].glyphs.glyphs) == len(class_asts[output].glyphs.glyphs), (
                            'Parallel glyph classes must have the same length')
                        input_class = input
                        input_class_index = i
                assert input_class is not None, 'A ligature substitution with a glyph class output must have a glyph class input'
                asts = []
                for input_glyph_name, output_glyph_name in zip(class_asts[input_class].glyphs.glyphs, class_asts[output].glyphs.glyphs):
                    asts.append(fontTools.feaLib.ast.LigatureSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        [
                            *glyphs_to_ast(self.inputs[:input_class_index]),
                            fontTools.feaLib.ast.GlyphName(input_glyph_name),
                            *glyphs_to_ast(self.inputs[input_class_index + 1:]),
                        ],
                        glyphs_to_ast(self.contexts_out),
                        glyph_to_name(fontTools.feaLib.ast.GlyphName(output_glyph_name)),
                        in_contextual_lookup,
                    ))
                return asts
            else:
                return [fontTools.feaLib.ast.LigatureSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyphs_to_ast(self.inputs),
                    glyphs_to_ast(self.contexts_out),
                    glyph_to_name(output),
                    in_contextual_lookup,
                )]

    def is_contextual(self):
        return bool(self.contexts_in or self.contexts_out)

    def is_multiple(self):
        return len(self.inputs) == 1 and self.outputs is not None and len(self.outputs) != 1

class Lookup:
    _DISCRETIONARY_FEATURES = {
        'afrc',
        'calt',
        'clig',
        'cswh',
        *{f'cv{x:02}' for x in range(1, 100)},
        'dlig',
        'hist',
        'hlig',
        'kern',
        'liga',
        'lnum',
        'onum',
        'ordn',
        'pnum',
        'salt',
        'sinf',
        *{f'ss{x:02}' for x in range(1, 21)},
        'subs',
        'sups',
        'swsh',
        'titl',
        'tnum',
        'zero',
    }
    _REQUIRED_SCRIPT_FEATURES = {
        'DFLT': {
            'abvm',
            'blwm',
            'curs',
            'dist',
            'locl',
            'mark',
            'mkmk',
            'rclt',
            'rlig',
        },
        'dupl': {
            'abvm',
            'abvs',
            'blwm',
            'blws',
            'curs',
            'dist',
            'haln',
            'mark',
            'mkmk',
            'pres',
            'psts',
            'rclt',
            'rlig',
        },
    }
    KNOWN_SCRIPTS = sorted(_REQUIRED_SCRIPT_FEATURES)

    def __init__(
            self,
            feature,
            scripts,
            language,
            *,
            flags=0,
            mark_filtering_set=None,
            reversed=False,
            prepending=False,
    ):
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
             flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        self.feature = feature
        if scripts is not None:
            scripts = [scripts] if isinstance(scripts, str) else sorted(scripts)
            self.required = set()
        else:
            scripts = []
            self.required = {False}
        self.scripts = scripts
        self.language = language
        for script in self.scripts:
            assert len(script) == 4, f"Script tag must be 4 characters long: '{script}'"
        assert language is None or len(language) == 4, f"Language tag must be 4 characters long: '{language}'"
        assert feature is None or len(feature) == 4, f"Feature tag must be 4 characters long: '{feature}'"
        self.flags = flags
        self.mark_filtering_set = mark_filtering_set
        self.reversed = reversed
        self.prepending = prepending
        self.rules = FreezableList()
        assert (feature is None) == (not scripts) == (language is None), 'Not clear whether this is a named or a normal lookup'
        for script in scripts:
            if feature in self._DISCRETIONARY_FEATURES:
                required = False
            else:
                try:
                    script_features = self._REQUIRED_SCRIPT_FEATURES[script]
                except KeyError:
                    raise ValueError(f"Unrecognized script tag: '{script}'")
                assert feature in script_features, f"The phase system does not support the feature '{feature}' for the script '{script}'"
                required = True
            self.required.add(required)
        assert len(self.required) == 1, f"""Scripts {{{
                ', '.join("'{script}'" for script in scripts)
            }}} disagree about whether the feature '{feature}' is required"""
        self.required = next(iter(self.required))

    def to_asts(self, class_asts, named_lookup_asts, name):
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        if isinstance(name, str):
            lookup_block = fontTools.feaLib.ast.LookupBlock(name)
            asts = [lookup_block]
        else:
            lookup_block = fontTools.feaLib.ast.LookupBlock(f'lookup_{name}')
            feature_block = fontTools.feaLib.ast.FeatureBlock(self.feature)
            for script in self.scripts:
                feature_block.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
                feature_block.statements.append(fontTools.feaLib.ast.LanguageStatement(self.language))
                feature_block.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup_block))
            asts = [lookup_block, feature_block]
        lookup_block.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
            self.flags,
            markFilteringSet=fontTools.feaLib.ast.GlyphClassName(class_asts[self.mark_filtering_set])
                if self.mark_filtering_set
                else None))
        lookup_block.statements.extend({
                ast.asFea(): ast
                    for r in self.rules
                    for ast in r.to_asts(class_asts, named_lookup_asts, contextual, multiple, self.reversed)
            }.values())
        return asts

    def freeze(self):
        self.rules.freeze()

    def append(self, rule):
        self.rules.append(rule)

    def extend(self, other):
        assert self.feature == other.feature, f"Incompatible features: '{self.feature}' != '{other.feature}'"
        assert self.scripts == other.scripts, f'''Incompatible script sets: {{{
                ', '.join(f"'{script}'" for script in self.scripts)
            }}} != {{{
                ', '.join(f"'{script}'" for script in other.scripts)
            }}}'''
        assert self.language == other.language, f"Incompatible languages: '{self.language}' != '{other.language}'"
        assert self.prepending == other.prepending, f'Incompatible prepending values: {self.prepending} != {other.prepending}'
        if self.prepending:
            for rule in other.rules:
                self.rules.insert(0, rule)
        else:
            for rule in other.rules:
                self.append(rule)

def make_trees(node, edge, maximum_depth, *, top_widths=None, prefix_depth=None):
    if maximum_depth <= 0:
        return []
    trees = []
    if prefix_depth is None:
        subtrees = make_trees(node, edge, maximum_depth - 1)
        for width in range(MAX_TREE_WIDTH + 1) if top_widths is None else top_widths:
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
        for width in range(1, MAX_TREE_WIDTH + 1) if top_widths is None else top_widths:
            for shallow_index_set in itertools.product(range(len(shallow_subtrees)), repeat=width - 1):
                for deep_subtree in deep_subtrees:
                    for edge_count in [width] if prefix_depth == 2 else range(width, MAX_TREE_WIDTH + 1):
                        tree = [node, *[edge] * edge_count] if top_widths is None else []
                        for i in shallow_index_set:
                            tree.extend(shallow_subtrees[i])
                        tree.extend(deep_subtree)
                        trees.append(tree)
    return trees

def add_rule(autochthonous_schemas, output_schemas, classes, named_lookups, lookup, rule, track_possible_outputs=True):
    def ignored(schema):
        glyph_class = schema.glyph_class
        return (
            glyph_class == GlyphClass.BLOCKER and lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_BASE_GLYPHS
            or glyph_class == GlyphClass.JOINER and lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES
            or glyph_class == GlyphClass.MARK and (
                lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS
                or lookup.mark_filtering_set and schema not in classes[lookup.mark_filtering_set]
            )
        )

    def check_ignored(target_part):
        for s in target_part:
            if isinstance(s, str):
                ignored_schema = next(filter(ignored, classes[s]), None)
                assert ignored_schema is None, f'''At least one glyph in @{s} ({
                        ignored_schema
                    }) appears in a substitution where it is ignored'''
            else:
                assert not ignored(s), f'{s} appears in a substitution where it is ignored'

    check_ignored(rule.contexts_in)
    if lookup.feature is None:
        # The first item in a named lookup’s input sequence is immune to that
        # named lookup’s lookup flags. It is guaranteed to (try to) match the
        # glyph at the targeted position in the rule that references the named
        # lookup.
        inputs = iter(rule.inputs)
        next(inputs)
        check_ignored(inputs)
    else:
        check_ignored(rule.inputs)
    check_ignored(rule.contexts_out)

    for input in rule.inputs:
        if isinstance(input, str):
            if all(s in autochthonous_schemas for s in classes[input]):
                classes[input].freeze()
                return
        elif input in autochthonous_schemas:
            return

    def is_prefix(maybe_prefix, full):
        return len(maybe_prefix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(maybe_prefix, full)))
    def is_suffix(maybe_suffix, full):
        return len(maybe_suffix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(reversed(maybe_suffix), reversed(full))))
    if not lookup.prepending and any(r.is_contextual() for r in lookup.rules):
        # TODO: Check prepending lookups too.
        for i, previous_rule in enumerate(lookup.rules):
            if lookup.prepending:
                previous_rule, rule = rule, previous_rule
            if (previous_rule.inputs == rule.inputs
                and is_suffix(previous_rule.contexts_in, rule.contexts_in)
                and is_prefix(previous_rule.contexts_out, rule.contexts_out)
                and (previous_rule.contexts_in != rule.contexts_in or previous_rule.contexts_out != rule.contexts_out)
            ):
                return
    lookup.append(rule)

    # FIXME: `track_possible_outputs` is a manual workaround for this function’s
    # inability to track possible outputs between rules in the same lookup.
    if (track_possible_outputs
        and lookup.required
        and not rule.contexts_in
        and not rule.contexts_out
        and len(rule.inputs) == 1
    ):
        input = rule.inputs[0]
        if isinstance(input, str):
            for i in classes[input]:
                output_schemas.remove(i)
        else:
            output_schemas.remove(input)

    registered_lookups = {None}
    def register_output_schemas(rule):
        if rule.outputs is not None:
            froze = False
            for output in rule.outputs:
                if isinstance(output, str):
                    must_freeze = False
                    for o in classes[output]:
                        if o not in output_schemas:
                            must_freeze = True
                            output_schemas.add(o)
                    if must_freeze:
                        classes[output].freeze()
                        froze = True
                else:
                    output_schemas.add(output)
            return froze
        elif rule.lookups is not None:
            for lookup in rule.lookups:
                if lookup not in registered_lookups:
                    registered_lookups.add(lookup)
                    froze = False
                    for rule in named_lookups[lookup].rules:
                        if register_output_schemas(rule):
                            froze = True
                    if froze:
                        named_lookups[lookup].freeze()
            return False

    register_output_schemas(rule)

class PrefixView:
    def __init__(self, source, delegate):
        self.prefix = f'{source.__name__}..'
        self._delegate = delegate

    def _prefixed(self, key):
        is_global = key.startswith('global..')
        assert len(key.split('..')) == 1 + is_global, f'Invalid key: {key!r}'
        return key if is_global else self.prefix + key

    def __getitem__(self, key, /):
        return self._delegate[self._prefixed(key)]

    def __setitem__(self, key, value, /):
        self._delegate[self._prefixed(key)] = value

    def __contains__(self, item, /):
        return self._prefixed(item) in self._delegate

    def keys(self):
        return self._delegate.keys()

    def items(self):
        return self._delegate.items()

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
        if len(group) == 1:
            self.remove(group)

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
                if overlap := len(intersection_set):
                    if overlap == len(group):
                        intersection = group
                    else:
                        grouper.remove_items(group, intersection_set)
                        if overlap != 1:
                            intersection = [*dict.fromkeys(x for x in cls if x in intersection_set)]
                            grouper.add(intersection)
                    if overlap != 1 and target_part is rule.inputs:
                        if rule.outputs is not None:
                            for output in rule.outputs:
                                if isinstance(output, str) and len(output := classes[output]) != 1:
                                    grouper.remove(intersection)
                                    new_groups = collections.defaultdict(list)
                                    for input_schema, output_schema in zip(cls, output):
                                        if input_schema in intersection_set:
                                            key = id(grouper.group_of(output_schema) or output_schema)
                                            new_groups[key].append(input_schema)
                                    new_intersection = None
                                    for schema in intersection:
                                        new_group = new_groups.get(id(schema))
                                        if new_group and schema in new_group:
                                            if new_intersection is None:
                                                new_intersection = new_group
                                            else:
                                                new_intersection += new_group
                                                new_group *= 0
                                    for new_group in new_groups.values():
                                        if len(new_group) > 1:
                                            grouper.add([*dict.fromkeys(new_group)])
                        elif rule.lookups is not None and not all(lookup is None for lookup in rule.lookups):
                            # TODO: Optimization: Check named lookups instead of assuming the group
                            # must be removed.
                            grouper.remove(intersection)
        else:
            for group in grouper.groups():
                if s in group:
                    grouper.remove_item(group, s)
                    break

def rename_schemas(grouper, phase_index):
    for group in grouper.groups():
        if not any(map(lambda s: s.phase_index >= phase_index, group)):
            continue
        group.sort(key=Schema.sort_key)
        canonical_schema = next(filter(lambda s: s.phase_index < phase_index, group), None)
        if canonical_schema is None:
            canonical_schema = group[0]
        for schema in list(group):
            if schema.phase_index >= phase_index:
                schema.canonical_schema = canonical_schema
                if grouper.group_of(schema):
                    grouper.remove_item(group, schema)

CURRENT_PHASE_INDEX = NO_PHASE_INDEX

class Builder:
    def __init__(self, font, bold, noto):
        self.font = font
        self._fea = fontTools.feaLib.ast.FeatureFile()
        self._anchors = {}
        self._initialize_phases()
        self.light_line = 101 if bold else 70
        self.shaded_line = SHADING_FACTOR * self.light_line
        self.stroke_gap = max(MINIMUM_STROKE_GAP, self.light_line)
        code_points = collections.defaultdict(int)
        self._initialize_schemas(noto, self.light_line, self.stroke_gap)
        for schema in self._schemas:
            if schema.cmap is not None:
                code_points[schema.cmap] += 1
        for glyph in font.glyphs():
            if glyph.unicode != -1 and glyph.unicode not in code_points:
                self._schemas.append(Schema(glyph.unicode, SFDGlyphWrapper(glyph.glyphname), 0, Type.NON_JOINING))
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    '
            + '\n    '.join(map(hex, sorted(code_points.keys()))))

    def _initialize_phases(self):
        self._phases = [
            self._dont_ignore_default_ignorables,
            self._validate_shading,
            self._validate_double_marks,
            self._decompose,
            self._expand_secants,
            self._validate_overlap_controls,
            self._add_parent_edges,
            self._invalidate_overlap_controls,
            self._add_secant_guidelines,
            self._add_placeholders_for_missing_children,
            self._categorize_edges,
            self._promote_final_letter_overlap_to_continuing_overlap,
            self._reposition_chinook_jargon_overlap_points,
            self._make_mark_variants_of_children,
            self._reposition_stenographic_period,
            self._disjoin_equals_sign,
            self._join_with_next_step,
            self._separate_subantiparallel_lines,
            self._prepare_for_secondary_diphthong_ligature,
            self._join_with_previous,
            self._unignore_last_orienting_glyph_in_initial_sequence,
            self._ignore_first_orienting_glyph_in_initial_sequence,
            self._tag_main_glyph_in_orienting_sequence,
            self._join_with_next,
            self._join_circle_with_adjacent_nonorienting_glyph,
            self._ligate_diphthongs,
            self._unignore_noninitial_orienting_sequences,
            self._unignore_initial_orienting_sequences,
            self._join_double_marks,
            self._rotate_diacritics,
            self._shade,
            self._make_widthless_variants_of_marks,
            self._classify_marks_for_trees,
        ]

        self._middle_phases = [
            self._merge_lookalikes,
        ]

        self._marker_phases = [
            self._add_shims_for_pseudo_cursive,
            self._shrink_wrap_enclosing_circle,
            self._add_width_markers,
            self._add_end_markers_for_marks,
            self._remove_false_end_markers,
            self._clear_entry_width_markers,
            self._sum_width_markers,
            self._calculate_bound_extrema,
            self._remove_false_start_markers,
            self._mark_hubs_after_initial_secants,
            self._find_real_hub,
            self._expand_start_markers,
            self._mark_maximum_bounds,
            self._copy_maximum_left_bound_to_start,
            self._dist,
        ]

    def _initialize_schemas(self, noto, light_line, stroke_gap):
        notdef = Notdef()
        space = Space(0)
        h = Dot()
        exclamation = Complex([(1, h), (201, Space(90, margins=False)), (1.109, Line(90, stretchy=False))])
        dollar = Complex([(2.58, Curve(180 - 18, 180 + 26, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (2.88, Curve(180 + 26, 360 - 8, clockwise=False, stretch=0.5, long=True, relative_stretch=False)), (0.0995, Line(360 - 8, stretchy=False)), (2.88, Curve(360 - 8, 180 + 26, clockwise=True, stretch=0.5, long=True, relative_stretch=False)), (2.58, Curve(180 + 26, 180 - 18, clockwise=True, stretch=2.058, long=True, relative_stretch=False)), (151.739, Space(328.952, margins=False)), (1.484, Line(90, stretchy=False)), (140, Space(0, margins=False)), (1.484, Line(270, stretchy=False))])
        asterisk = Complex([(310, Space(90, margins=False)), (0.467, Line(90, stretchy=False)), (0.467, Line(198, stretchy=False)), (0.467, Line(18, stretchy=False), False), (0.467, Line(126, stretchy=False)), (0.467, Line(306, stretchy=False), False), (0.467, Line(54, stretchy=False)), (0.467, Line(234, stretchy=False), False), (0.467, Line(342, stretchy=False))])
        plus = Complex([(146, Space(90, margins=False)), (0.828, Line(90, stretchy=False)), (0.414, Line(270, stretchy=False)), (0.414, Line(180, stretchy=False)), (0.828, Line(0, stretchy=False))])
        comma = Complex([(35, Space(0, margins=False)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True))])
        slash = Complex([(0, Space(0, margins=False)), (0.364, Line(240, stretchy=False)), (2.378, Line(60, stretchy=False))])
        zero = Circle(180, 180, clockwise=False, stretch=132 / 193, long=True)
        one = Complex([(1.288, Line(90, stretchy=False)), (0.416, Line(218, stretchy=False))])
        two = Complex([(3.528, Curve(42, 25, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232, stretchy=False)), (0.7, Line(0, stretchy=False))])
        three = Complex([(3, Curve(36, 0, clockwise=True, stretch=0.2, long=True)), (3, Curve(0, 180, clockwise=True, stretch=0.2, long=True)), (0.15, Line(180, stretchy=False)), (0.15, Line(0, stretchy=False)), (3.36, Curve(0, 180, clockwise=True, stretch=0.375, long=True)), (3.42, Curve(180, 155, clockwise=True, stretch=0.937, long=True))])
        four = Complex([(1.296, Line(90, stretchy=False)), (1.173, Line(235, stretchy=False)), (0.922, Line(0, stretchy=False))])
        five = Complex([(3.72, Curve(330, 0, clockwise=False, stretch=0.196, long=True)), (3.72, Curve(0, 180, clockwise=False, stretch=13 / 93, long=True)), (3.72, Curve(180, 210, clockwise=False, stretch=0.196, long=True)), (0.565, Line(86.145, stretchy=False)), (0.572, Line(0, stretchy=False))])
        six = Complex([(3.88, Circle(90, 90, clockwise=True)), (19.5, Curve(90, 70, clockwise=True, stretch=0.45)), (4, Curve(65, 355, clockwise=True))])
        seven = Complex([(0.818, Line(0, stretchy=False)), (1.36, Line(246, stretchy=False))])
        eight = Complex([(2.88, Curve(180, 90, clockwise=True)), (2.88, Curve(90, 270, clockwise=True)), (2.88, Curve(270, 180, clockwise=True)), (3.16, Curve(180, 270, clockwise=False)), (3.16, Curve(270, 90, clockwise=False)), (3.16, Curve(90, 180, clockwise=False))])
        nine = Complex([(3.5, Circle(270, 270, clockwise=True)), (35.1, Curve(270, 260, clockwise=True, stretch=0.45)), (4, Curve(255, 175, clockwise=True))])
        colon = Complex([(1, h), (509, Space(90, margins=False)), (1, h)])
        semicolon = Complex([(0, Space(0, margins=False)), (1, comma), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False)), (416, Space(90, margins=False)), (1, h)])
        question = Complex([(1, h), (201, Space(90, margins=False)), (4.162, Curve(90, 45, clockwise=True)), (0.16, Line(45, stretchy=False)), (4.013, Curve(45, 210, clockwise=False))])
        less_than = Complex([(1, Line(153, stretchy=False)), (1, Line(27, stretchy=False))])
        equal = Complex([(305, Space(90, margins=False)), (1, Line(0, stretchy=False)), (180, Space(90, margins=False)), (1, Line(180, stretchy=False)), (90, Space(270, margins=False)), (1, Line(0, stretchy=False), True)], maximum_tree_width=1)
        greater_than = Complex([(1, Line(27, stretchy=False)), (1, Line(153, stretchy=False))])
        left_bracket = Complex([(0, Space(0, margins=False)), (0.315, Line(270, stretchy=False), False), (0.45, Line(0, stretchy=False), False), (0.45, Line(180, stretchy=False)), (2.059, Line(90, stretchy=False)), (0.45, Line(0, stretchy=False))])
        right_bracket = Complex([(0, Space(0, margins=False)), (0.315, Line(270, stretchy=False), False), (0.45, Line(180, stretchy=False), False), (0.45, Line(0, stretchy=False)), (2.059, Line(90, stretchy=False)), (0.45, Line(180, stretchy=False))])
        guillemet_vertical_space = (75, Space(90, margins=False))
        guillemet_horizontal_space = (200, Space(0, margins=False))
        left_guillemet = [(0.524, Line(129.89, stretchy=False)), (0.524, Line(50.11, stretchy=False))]
        right_guillemet = [*reversed(left_guillemet)]
        left_guillemet += [(op[0], op[1].reversed(), True) for op in left_guillemet]
        right_guillemet += [(op[0], op[1].reversed(), True) for op in right_guillemet]
        left_double_guillemet = Complex([guillemet_vertical_space, *left_guillemet, guillemet_horizontal_space, *left_guillemet])
        right_double_guillemet = Complex([guillemet_vertical_space, *right_guillemet, guillemet_horizontal_space, *right_guillemet])
        left_single_guillemet = Complex([guillemet_vertical_space, *left_guillemet])
        right_single_guillemet = Complex([guillemet_vertical_space, *right_guillemet])
        enclosing_circle = Circle(180, 180, clockwise=False)
        degree = Complex([(683, Space(90, margins=False)), (2.3, Circle(180, 180, clockwise=False))])
        masculine_ordinal_indicator = Complex([(625.5, Space(90, margins=False)), (2.3, Circle(180, 180, clockwise=False, stretch=0.078125, long=True)), (370, Space(270, margins=False)), (105, Space(180, margins=False)), (0.42, Line(0, stretchy=False))])
        multiplication = Complex([(1, Line(315, stretchy=False)), (0.5, Line(135, stretchy=False), False), (0.5, Line(225, stretchy=False)), (1, Line(45, stretchy=False))])
        greater_than_overlapping_less_than = Complex([(1, greater_than), (math.hypot(500 * math.cos(math.radians(27)), 1000 * math.sin(math.radians(27))), Space(360 - math.degrees(math.atan2(2 * math.sin(math.radians(27)), math.cos(math.radians(27)))), margins=False)), (1, less_than)])
        grave = Line(150, stretchy=False)
        acute = Line(45, stretchy=False)
        circumflex = Complex([(1, Line(25, stretchy=False)), (1, Line(335, stretchy=False))])
        macron = Line(0, stretchy=False)
        breve = Curve(270, 90, clockwise=False, stretch=0.2)
        diaeresis = Line(0, stretchy=False, dots=2)
        caron = Complex([(1, Line(335, stretchy=False)), (1, Line(25, stretchy=False))])
        inverted_breve = Curve(90, 270, clockwise=False, stretch=0.2)
        en_dash = Complex([(395, Space(90, margins=False)), (1, Line(0, stretchy=False))])
        high_left_quote = Complex([(755, Space(90, margins=False)), (3, Curve(221, 281, clockwise=False)), (0.5, Circle(281, 281, clockwise=False)), (160, Space(0, margins=False)), (0.5, Circle(101, 101, clockwise=True)), (3, Curve(101, 41, clockwise=True))])
        high_right_quote = Complex([(742, Space(90, margins=False)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0, margins=False)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        low_right_quote = Complex([(35, Space(0, margins=False)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0, margins=False)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        ellipsis = Complex([(1, h), (148, Space(0, margins=False)), (1, h), (148, Space(0, margins=False)), (1, h)])
        nnbsp = Space(0, margins=False)
        dotted_circle = Complex([(33, Space(90, margins=False)), (1, h), (446, Space(90, margins=False)), (1, h), (223, Space(270, margins=False)), (223, Space(60, margins=False)), (1, h), (446, Space(240, margins=False)), (1, h), (223, Space(60, margins=False)), (223, Space(30, margins=False)), (1, h), (446, Space(210, margins=False)), (1, h), (223, Space(30, margins=False)), (223, Space(0, margins=False)), (1, h), (446, Space(180, margins=False)), (1, h), (223, Space(0, margins=False)), (223, Space(330, margins=False)), (1, h), (446, Space(150, margins=False)), (1, h), (223, Space(330, margins=False)), (223, Space(300, margins=False)), (1, h), (446, Space(120, margins=False)), (1, h)])
        stenographic_period = Complex([(0.5, Line(135, stretchy=False)), *multiplication.instructions])
        double_hyphen = Complex([(305, Space(90, margins=False)), (0.5, Line(0, stretchy=False)), (179, Space(90, margins=False)), (0.5, Line(180, stretchy=False))])
        bound = Bound()
        x = XShape([(2, Curve(30, 130, clockwise=False)), (2, Curve(130, 30, clockwise=True))])
        p = Line(270)
        p_reverse = Line(90)
        t = Line(0)
        t_reverse = Line(180)
        f = Line(300)
        f_reverse = Line(120)
        k = Line(240)
        k_reverse = Line(60)
        l = Line(45)
        l_reverse = Line(225)
        m = Curve(180, 0, clockwise=False, stretch=0.2)
        m_reverse = Curve(180, 0, clockwise=True, stretch=0.2)
        n = Curve(0, 180, clockwise=True, stretch=0.2)
        n_reverse = Curve(0, 180, clockwise=False, stretch=0.2)
        j = Curve(90, 270, clockwise=True, stretch=0.2)
        j_reverse = Curve(90, 270, clockwise=False, stretch=0.2)
        s = Curve(270, 90, clockwise=False, stretch=0.2)
        s_reverse = Curve(270, 90, clockwise=True, stretch=0.2)
        m_s = Curve(180, 0, clockwise=False, stretch=0.8)
        n_s = Curve(0, 180, clockwise=True, stretch=0.8)
        j_s = Curve(90, 270, clockwise=True, stretch=0.8)
        s_s = Curve(270, 90, clockwise=False, stretch=0.8)
        s_t = Curve(270, 0, clockwise=False)
        s_p = Curve(270, 180, clockwise=True)
        t_s = Curve(0, 270, clockwise=True)
        w = Curve(180, 270, clockwise=False)
        s_n = Curve(0, 90, clockwise=False, secondary=True)
        k_r_s = Curve(90, 180, clockwise=False)
        s_k = Curve(90, 0, clockwise=True, secondary=False)
        j_n = Complex([(1, s_k), (1, n)], maximum_tree_width=1)
        j_n_s = Complex([(3, s_k), (4, n_s)], maximum_tree_width=1)
        o = Circle(90, 90, clockwise=False)
        o_reverse = Circle(270, 270, clockwise=True, reversed=True)
        ie = Curve(180, 0, clockwise=False)
        short_i = Curve(0, 180, clockwise=True)
        ui = Curve(90, 270, clockwise=True)
        ee = Curve(270, 90, clockwise=False, secondary=True)
        ye = Complex([(0.47, Line(0, minor=True)), (0.385, Line(242, stretchy=False)), (0.47, t), (0.385, Line(242, stretchy=False)), (0.47, t), (0.385, Line(242, stretchy=False)), (0.47, t)])
        u_n = Curve(90, 180, clockwise=True)
        long_u = Curve(225, 45, clockwise=False, stretch=4, long=True)
        romanian_u = RomanianU([(1, Curve(180, 0, clockwise=False)), lambda c: c, (0.5, Curve(0, 180, clockwise=False))], hook=True)
        uh = Circle(45, 45, clockwise=False, reversed=False, stretch=2)
        ou = Ou([(1, Circle(180, 145, clockwise=False)), lambda c: c, (5 / 9, Curve(145, 270, clockwise=False))])
        ou_reverse = Ou([(1, Circle(0, 35, clockwise=True)), lambda c: c, (5 / 9, Curve(35, 270, clockwise=True))])
        wa = Wa([(4, Circle(180, 180, clockwise=False)), (2, Circle(180, 180, clockwise=False))])
        wo = Wa([(4, Circle(180, 180, clockwise=False)), (2.5, Circle(180, 180, clockwise=False))])
        wi = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (5 / 3, m)])
        wei = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (1, m), lambda c: c.clone(clockwise=not c.clockwise), (1, n)])
        left_horizontal_secant = Line(0, stretchy=False, secant=2 / 3)
        mid_horizontal_secant = Line(0, stretchy=False, secant=0.5)
        right_horizontal_secant = Line(0, stretchy=False, secant=1 / 3)
        low_vertical_secant = Line(90, stretchy=False, secant=2 / 3)
        mid_vertical_secant = Line(90, stretchy=False, secant=0.5)
        high_vertical_secant = Line(90, stretchy=False, secant=1 / 3)
        rtl_secant = Line(240, stretchy=False, secant=0.5, secant_curvature_offset=55)
        ltr_secant = Line(310, stretchy=False, secant=0.5, secant_curvature_offset=55)
        tangent = Complex([lambda c: Context(None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360), (0.25, Line(270, stretchy=False)), lambda c: Context((c.angle + 180) % 360), (0.5, Line(90, stretchy=False))], hook=True)
        e_hook = Curve(90, 270, clockwise=True, hook=True)
        i_hook = Curve(180, 0, clockwise=False, hook=True)
        tangent_hook = TangentHook([(1, Curve(180, 270, clockwise=False)), Context.reversed, (1, Curve(90, 270, clockwise=True))])
        separate_affix_guideline = [(250 - light_line / 2, Space(90, margins=False)), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (0.25, Line(0), True), (1, Dot()), (1.5, Line(180), True)]
        high_acute = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.25, Line(0), True), (0.5, Line(45, stretchy=False))])
        high_tight_acute = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (1, Line(0), True), (0.5, Line(45, stretchy=False))])
        high_grave = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (1, Line(0), True), (0.5, Line(135, stretchy=False))])
        high_long_grave = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (1.25, Line(0), True), (0.75, Line(180, stretchy=False)), (0.4, Line(120, stretchy=False))])
        high_dot = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.75, Line(0), True), (1, Dot(centered=True))])
        high_circle = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.75, Line(0), True), (2, Circle(0, 0, clockwise=False))])
        high_line = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.5, Line(0), True), (0.5, Line(0, stretchy=False))])
        high_wave = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.375, Line(0), True), (2, Curve(90, 315, clockwise=True)), (RADIUS * math.sqrt(2) / 500, Line(315, stretchy=False)), (2, Curve(315, 90, clockwise=False))])
        high_vertical = Complex(separate_affix_guideline + [(1.5 * stroke_gap + light_line, Space(90, margins=False)), (0.75, Line(0), True), (0.5, Line(90, stretchy=False))])
        low_acute = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.25, Line(0), True), (math.sin(math.radians(45)) * 0.5, Line(270), True), (0.5, Line(45, stretchy=False))])
        low_tight_acute = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (1, Line(0), True), (math.sin(math.radians(45)) * 0.5, Line(270), True), (0.5, Line(45, stretchy=False))])
        low_grave = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (1, Line(0), True), (math.sin(math.radians(135)) * 0.5, Line(270), True), (0.5, Line(135, stretchy=False))])
        low_long_grave = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (1.25, Line(0), True), (math.sin(math.radians(120)) * 0.5, Line(270), True), (0.75, Line(180, stretchy=False)), (0.4, Line(120, stretchy=False))])
        low_dot = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.75, Line(0), True), (1, Dot(centered=True))])
        low_circle = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.75, Line(0), True), (2, Circle(180, 180, clockwise=False))])
        low_line = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.5, Line(0), True), (0.5, Line(0, stretchy=False))])
        low_wave = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.375, Line(0), True), (100, Space(180, margins=False)), (2, Curve(180, 90, clockwise=False), True), (2, Curve(90, 315, clockwise=True)), (RADIUS * math.sqrt(2) / 500, Line(315, stretchy=False)), (2, Curve(315, 90, clockwise=False))])
        low_vertical = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.75, Line(0), True), (0.5, Line(270, stretchy=False))])
        low_arrow = Complex(separate_affix_guideline + [(1.5 * stroke_gap, Space(270, margins=False)), (0.55, Line(0), True), (0.4, Line(0, stretchy=False)), (0.4, Line(240, stretchy=False))])
        likalisti = Complex([(5, Circle(0, 0, clockwise=False)), (375, Space(90, margins=False)), (0.5, p), (math.hypot(125, 125), Space(135, margins=False)), (0.5, Line(0, stretchy=False))])
        dotted_square = [(152, Space(270, margins=False)), (0.26 - light_line / 1000, Line(90, stretchy=False)), (58 + light_line, Space(90, margins=False)), (0.264 - light_line / 500, Line(90, stretchy=False)), (58 + light_line, Space(90, margins=False)), (0.264 - light_line / 500, Line(90, stretchy=False)), (58 + light_line, Space(90, margins=False)), (0.264 - light_line / 500, Line(90, stretchy=False)), (58 + light_line, Space(90, margins=False)), (0.26 - light_line / 1000, Line(90, stretchy=False)), (0.26 - light_line / 1000, Line(0, stretchy=False)), (58 + light_line, Space(0, margins=False)), (0.264 - light_line / 500, Line(0, stretchy=False)), (58 + light_line, Space(0, margins=False)), (0.264 - light_line / 500, Line(0, stretchy=False)), (58 + light_line, Space(0, margins=False)), (0.264 - light_line / 500, Line(0, stretchy=False)), (58 + light_line, Space(0, margins=False)), (0.26 - light_line / 1000, Line(0, stretchy=False)), (0.26 - light_line / 1000, Line(270, stretchy=False)), (58 + light_line, Space(270, margins=False)), (0.264 - light_line / 500, Line(270, stretchy=False)), (58 + light_line, Space(270, margins=False)), (0.264 - light_line / 500, Line(270, stretchy=False)), (58 + light_line, Space(270, margins=False)), (0.264 - light_line / 500, Line(270, stretchy=False)), (58 + light_line, Space(270, margins=False)), (0.26 - light_line / 1000, Line(270, stretchy=False)), (0.26 - light_line / 1000, Line(180, stretchy=False)), (58 + light_line, Space(180, margins=False)), (0.264 - light_line / 500, Line(180, stretchy=False)), (58 + light_line, Space(180, margins=False)), (0.264 - light_line / 500, Line(180, stretchy=False)), (58 + light_line, Space(180, margins=False)), (0.264 - light_line / 500, Line(180, stretchy=False)), (58 + light_line, Space(180, margins=False)), (0.26 - light_line / 1000, Line(180, stretchy=False))]
        dtls = InvalidDTLS(instructions=dotted_square + [(341, Space(0, margins=False)), (173, Space(90, margins=False)), (0.238, Line(180, stretchy=False)), (0.412, Line(90, stretchy=False)), (130, Space(90, margins=False)), (0.412, Line(90, stretchy=False)), (0.18, Line(0, stretchy=False)), (2.06, Curve(0, 180, clockwise=True, stretch=-27 / 115, long=True, relative_stretch=False)), (0.18, Line(180, stretchy=False)), (369, Space(0, margins=False)), (0.412, Line(90, stretchy=False)), (0.148, Line(180, stretchy=False), True), (0.296, Line(0, stretchy=False)), (341, Space(270, margins=False)), (14.5, Space(180, margins=False)), (.345 * 2.58, Curve(164, 196, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (.345 * 2.88, Curve(196, 341, clockwise=False, stretch=0.25, long=True, relative_stretch=False)), (.345 *0.224, Line(341, stretchy=False)), (.345 * 2.88, Curve(341, 196, clockwise=True, stretch=0.25, long=True, relative_stretch=False)), (.345 * 2.58, Curve(196, 164, clockwise=True, stretch=2.058, long=True, relative_stretch=False))])
        chinook_period = Complex([(100, Space(90, margins=False)), (1, Line(0, stretchy=False)), (179, Space(90, margins=False)), (1, Line(180, stretchy=False))])
        overlap = InvalidOverlap(continuing=False, instructions=dotted_square + [(162.5, Space(0, margins=False)), (397, Space(90, margins=False)), (0.192, Line(90, stretchy=False)), (0.096, Line(270, stretchy=False), True), (1.134, Line(0, stretchy=False)), (0.32, Line(140, stretchy=False)), (0.32, Line(320, stretchy=False), True), (0.32, Line(220, stretchy=False)), (170, Space(180, margins=False)), (0.4116, Line(90, stretchy=False))])
        continuing_overlap = InvalidOverlap(continuing=True, instructions=dotted_square + [(189, Space(0, margins=False)), (522, Space(90, margins=False)), (0.192, Line(90, stretchy=False)), (0.096, Line(270, stretchy=False), True), (0.726, Line(0, stretchy=False)), (124, Space(180, margins=False)), (145, Space(90, margins=False)), (0.852, Line(270, stretchy=False)), (0.552, Line(0, stretchy=False)), (0.32, Line(140, stretchy=False)), (0.32, Line(320, stretchy=False), True), (0.32, Line(220, stretchy=False))])
        down_step = InvalidStep(270, dotted_square + [(444, Space(0, margins=False)), (749, Space(90, margins=False)), (1.184, Line(270, stretchy=False)), (0.32, Line(130, stretchy=False)), (0.32, Line(310, stretchy=False), True), (0.32, Line(50, stretchy=False))])
        up_step = InvalidStep(90, dotted_square + [(444, Space(0, margins=False)), (157, Space(90, margins=False)), (1.184, Line(90, stretchy=False)), (0.32, Line(230, stretchy=False)), (0.32, Line(50, stretchy=False), True), (0.32, Line(310, stretchy=False))])
        line = Line(0, stretchy=False)

        dot_1 = Schema(None, h, 1, anchor=RELATIVE_1_ANCHOR)
        dot_2 = Schema(None, h, 1, anchor=RELATIVE_2_ANCHOR)
        line_2 = Schema(None, line, 0.35, Type.ORIENTING, anchor=RELATIVE_2_ANCHOR)
        line_middle = Schema(None, line, 0.45, Type.ORIENTING, anchor=MIDDLE_ANCHOR)

        self._schemas = [
            Schema(None, notdef, 1, Type.NON_JOINING, side_bearing=95),
            Schema(0x0020, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x0021, exclamation, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x0024, dollar, 7 / 8, Type.NON_JOINING),
            Schema(0x002A, asterisk, 1, Type.NON_JOINING),
            Schema(0x002B, plus, 1, Type.NON_JOINING),
            Schema(0x002C, comma, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x002E, h, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x002F, slash, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0030, zero, 3.882, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0031, one, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0032, two, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0033, three, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0034, four, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0035, five, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0036, six, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0037, seven, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0038, eight, 1.064, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0039, nine, 1.021, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003A, colon, 0.856, Type.NON_JOINING, encirclable=True, shading_allowed=False),
            Schema(0x003B, semicolon, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x003C, less_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003D, equal, 1),
            Schema(0x003E, greater_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003F, question, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x005B, left_bracket, 1, Type.NON_JOINING),
            Schema(0x005D, right_bracket, 1, Type.NON_JOINING),
            Schema(0x00A0, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x00AB, left_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00B0, degree, 1, Type.NON_JOINING),
            Schema(0x00BA, masculine_ordinal_indicator, 1, Type.NON_JOINING),
            Schema(0x00BB, right_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00D7, multiplication, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0300, grave, 0.2, anchor=ABOVE_ANCHOR),
            Schema(0x0301, acute, 0.2, anchor=ABOVE_ANCHOR),
            Schema(0x0302, circumflex, 0.2, Type.NON_JOINING, anchor=ABOVE_ANCHOR),
            Schema(0x0304, macron, 0.2, anchor=ABOVE_ANCHOR),
            Schema(0x0306, breve, 1, anchor=ABOVE_ANCHOR),
            Schema(0x0307, h, 1, anchor=ABOVE_ANCHOR),
            Schema(0x0308, diaeresis, 0.2, anchor=ABOVE_ANCHOR),
            Schema(0x030C, caron, 0.2, Type.NON_JOINING, anchor=ABOVE_ANCHOR),
            Schema(0x0316, grave, 0.2, anchor=BELOW_ANCHOR),
            Schema(0x0317, acute, 0.2, anchor=BELOW_ANCHOR),
            Schema(0x0323, h, 1, anchor=BELOW_ANCHOR),
            Schema(0x0324, diaeresis, 0.2, anchor=BELOW_ANCHOR),
            Schema(0x032F, inverted_breve, 1, anchor=BELOW_ANCHOR),
            Schema(0x0331, macron, 0.2, anchor=BELOW_ANCHOR),
            Schema(0x2001, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x2003, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x200C, space, 0, Type.NON_JOINING, side_bearing=0, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x2013, en_dash, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x201C, high_left_quote, 1, Type.NON_JOINING),
            Schema(0x201D, high_right_quote, 1, Type.NON_JOINING),
            Schema(0x201E, low_right_quote, 1, Type.NON_JOINING),
            Schema(0x2026, ellipsis, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x202F, nnbsp, 200 - 2 * DEFAULT_SIDE_BEARING, side_bearing=200 - 2 * DEFAULT_SIDE_BEARING),
            Schema(0x2039, left_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x203A, right_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x20DD, enclosing_circle, 10, anchor=MIDDLE_ANCHOR),
            Schema(0x25CC, dotted_circle, 1, Type.NON_JOINING),
            Schema(0x2AA4, greater_than_overlapping_less_than, 2, Type.NON_JOINING),
            Schema(0x2E3C, stenographic_period, 0.5, Type.NON_JOINING, shading_allowed=False),
            Schema(0x2E40, double_hyphen, 1, Type.NON_JOINING),
            Schema(0x1BC00, h, 1, shading_allowed=False),
            Schema(0x1BC01, x, 0.75, shading_allowed=False),
            Schema(0x1BC02, p, 1, Type.ORIENTING),
            Schema(0x1BC03, t, 1, Type.ORIENTING),
            Schema(0x1BC04, f, 1, Type.ORIENTING),
            Schema(0x1BC05, k, 1, Type.ORIENTING),
            Schema(0x1BC06, l, 1, Type.ORIENTING),
            Schema(0x1BC07, p, 2, Type.ORIENTING),
            Schema(0x1BC08, t, 2, Type.ORIENTING),
            Schema(0x1BC09, f, 2, Type.ORIENTING),
            Schema(0x1BC0A, k, 2, Type.ORIENTING),
            Schema(0x1BC0B, l, 2, Type.ORIENTING),
            Schema(0x1BC0C, p, 3, Type.ORIENTING),
            Schema(0x1BC0D, t, 3, Type.ORIENTING),
            Schema(0x1BC0E, f, 3, Type.ORIENTING),
            Schema(0x1BC0F, k, 3, Type.ORIENTING),
            Schema(0x1BC10, l, 3, Type.ORIENTING),
            Schema(0x1BC11, t, 1, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC12, t, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC13, t, 2, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC14, k, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC15, k, 2, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC16, l, 1, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC17, l, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC18, l, 2, Type.ORIENTING, marks=[dot_1, dot_2]),
            Schema(0x1BC19, m, 6),
            Schema(0x1BC1A, n, 6),
            Schema(0x1BC1B, j, 6),
            Schema(0x1BC1C, s, 6),
            Schema(0x1BC1D, m, 6, marks=[line_middle]),
            Schema(0x1BC1E, n, 6, marks=[line_middle]),
            Schema(0x1BC1F, j, 6, marks=[line_middle]),
            Schema(0x1BC20, s, 6, marks=[line_middle]),
            Schema(0x1BC21, m, 6, marks=[dot_1]),
            Schema(0x1BC22, n, 6, marks=[dot_1]),
            Schema(0x1BC23, j, 6, marks=[dot_1]),
            Schema(0x1BC24, j, 6, marks=[dot_1, dot_2]),
            Schema(0x1BC25, s, 6, marks=[dot_1]),
            Schema(0x1BC26, s, 6, marks=[dot_2]),
            Schema(0x1BC27, m_s, 8),
            Schema(0x1BC28, n_s, 8),
            Schema(0x1BC29, j_s, 8),
            Schema(0x1BC2A, s_s, 8),
            Schema(0x1BC2B, m_s, 8, marks=[line_middle]),
            Schema(0x1BC2C, n_s, 8, marks=[line_middle]),
            Schema(0x1BC2D, j_s, 8, marks=[line_middle]),
            Schema(0x1BC2E, s_s, 8, marks=[line_middle]),
            Schema(0x1BC2F, j_s, 8, marks=[dot_1]),
            Schema(0x1BC30, j_n, 6, shading_allowed=False),
            Schema(0x1BC31, j_n_s, 2, shading_allowed=False),
            Schema(0x1BC32, s_t, 8),
            Schema(0x1BC33, s_t, 12),
            Schema(0x1BC34, s_p, 8),
            Schema(0x1BC35, s_p, 12),
            Schema(0x1BC36, t_s, 8),
            Schema(0x1BC37, t_s, 12),
            Schema(0x1BC38, w, 8),
            Schema(0x1BC39, w, 8, marks=[dot_1]),
            Schema(0x1BC3A, w, 12),
            Schema(0x1BC3B, s_n, 8),
            Schema(0x1BC3C, s_n, 12),
            Schema(0x1BC3D, k_r_s, 8, shading_allowed=False),
            Schema(0x1BC3E, k_r_s, 12, shading_allowed=False),
            Schema(0x1BC3F, s_k, 8),
            Schema(0x1BC40, s_k, 12),
            Schema(0x1BC41, o, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC42, o_reverse, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC43, o, 2.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC44, o, 3, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC45, o, 3.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC46, ie, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC47, ee, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC48, ie, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC49, short_i, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4A, ui, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4B, ee, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4C, ee, 2, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC4D, ee, 2, Type.ORIENTING, marks=[dot_2], shading_allowed=False),
            Schema(0x1BC4E, ee, 2, Type.ORIENTING, marks=[line_2], shading_allowed=False),
            Schema(0x1BC4F, k, 0.5, Type.ORIENTING),
            Schema(0x1BC50, ye, 1, shading_allowed=False),
            Schema(0x1BC51, s_t, 6, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC52, s_p, 6, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC53, s_t, 6, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC54, u_n, 3, shading_allowed=False),
            Schema(0x1BC55, long_u, 2, shading_allowed=False),
            Schema(0x1BC56, romanian_u, 3, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC57, uh, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC58, uh, 2, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC59, uh, 2, Type.ORIENTING, marks=[dot_2], shading_allowed=False),
            Schema(0x1BC5A, o, 3, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC5B, ou, 3, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC5C, wa, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5D, wo, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5E, wi, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5F, wei, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC60, wo, 1, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC61, s_t, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC62, s_n, 3.2, Type.ORIENTING),
            Schema(0x1BC63, t_s, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC64, s_k, 3.2, Type.ORIENTING),
            Schema(0x1BC65, s_p, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC66, w, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC67, s_t, 3.2, can_lead_orienting_sequence=True, marks=[dot_1]),
            Schema(0x1BC68, s_t, 3.2, can_lead_orienting_sequence=True, marks=[dot_2]),
            Schema(0x1BC69, s_k, 3.2, can_lead_orienting_sequence=True, marks=[dot_2]),
            Schema(0x1BC6A, s_k, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC70, left_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC71, mid_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC72, right_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC73, low_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC74, mid_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC75, high_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC76, rtl_secant, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC77, ltr_secant, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC78, tangent, 0.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC79, n_reverse, 6, shading_allowed=False),
            Schema(0x1BC7A, e_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC7B, i_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True),
            Schema(0x1BC7C, tangent_hook, 2, Type.ORIENTING, shading_allowed=False, can_lead_orienting_sequence=True),
            Schema(0x1BC80, high_acute, 1, Type.NON_JOINING),
            Schema(0x1BC81, high_tight_acute, 1, Type.NON_JOINING),
            Schema(0x1BC82, high_grave, 1, Type.NON_JOINING),
            Schema(0x1BC83, high_long_grave, 1, Type.NON_JOINING),
            Schema(0x1BC84, high_dot, 1, Type.NON_JOINING),
            Schema(0x1BC85, high_circle, 1, Type.NON_JOINING),
            Schema(0x1BC86, high_line, 1, Type.NON_JOINING),
            Schema(0x1BC87, high_wave, 1, Type.NON_JOINING),
            Schema(0x1BC88, high_vertical, 1, Type.NON_JOINING),
            Schema(0x1BC90, low_acute, 1, Type.NON_JOINING),
            Schema(0x1BC91, low_tight_acute, 1, Type.NON_JOINING),
            Schema(0x1BC92, low_grave, 1, Type.NON_JOINING),
            Schema(0x1BC93, low_long_grave, 1, Type.NON_JOINING),
            Schema(0x1BC94, low_dot, 1, Type.NON_JOINING),
            Schema(0x1BC95, low_circle, 1, Type.NON_JOINING),
            Schema(0x1BC96, low_line, 1, Type.NON_JOINING),
            Schema(0x1BC97, low_wave, 1, Type.NON_JOINING),
            Schema(0x1BC98, low_vertical, 1, Type.NON_JOINING),
            Schema(0x1BC99, low_arrow, 1, Type.NON_JOINING),
            Schema(0x1BC9C, likalisti, 1, Type.NON_JOINING),
            Schema(0x1BC9D, dtls, 1, Type.NON_JOINING),
            Schema(0x1BC9E, line, 0.45, Type.ORIENTING, anchor=MIDDLE_ANCHOR),
            Schema(0x1BC9F, chinook_period, 1, Type.NON_JOINING),
            Schema(0x1BCA0, overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA1, continuing_overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA2, down_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA3, up_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
        ]
        if not noto:
            self._schemas += [
                Schema(0xE000, bound, 1, Type.NON_JOINING, side_bearing=0),
                Schema(0xEC02, p_reverse, 1, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC03, t_reverse, 1, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC04, f_reverse, 1, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC05, k_reverse, 1, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC06, l_reverse, 1, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC19, m_reverse, 6, shading_allowed=False),
                Schema(0xEC1A, n_reverse, 6, shading_allowed=False),
                Schema(0xEC1B, j_reverse, 6, shading_allowed=False),
                Schema(0xEC1C, s_reverse, 6, shading_allowed=False),
                Schema(0xEC44, o_reverse, 3, Type.ORIENTING, shading_allowed=False),
                Schema(0xEC5A, o_reverse, 3, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
                Schema(0xEC5B, ou_reverse, 3, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            ]

    def _dont_ignore_default_ignorables(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup('abvm', {'DFLT', 'dupl'}, 'dflt')
        lookup_2 = Lookup('abvm', {'DFLT', 'dupl'}, 'dflt')
        for schema in schemas:
            if schema.ignorability == Ignorability.OVERRIDDEN_NO:
                add_rule(lookup_1, Rule([schema], [schema, schema]))
                add_rule(lookup_2, Rule([schema, schema], [schema]))
        return [lookup_1, lookup_2]

    def _validate_shading(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            'dupl',
            'dflt',
            mark_filtering_set='independent_mark',
            reversed=True,
        )
        if len(new_schemas) == len(schemas):
            invalid_dtls = next(s for s in schemas if isinstance(s.path, InvalidDTLS))
            valid_dtls = invalid_dtls.clone(cmap=None, path=ValidDTLS())
            for schema in new_schemas:
                if schema.anchor:
                    if schema.cmap is not None:
                        classes['independent_mark'].append(schema)
                elif schema.shading_allowed and schema.path.is_shadable():
                    classes['c'].append(schema)
            add_rule(lookup, Rule(['c'], [invalid_dtls], [], [valid_dtls]))
        return [lookup]

    def _validate_double_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            'dupl',
            'dflt',
            mark_filtering_set='double_mark',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        double_mark = next(s for s in original_schemas if s.cps == [0x1BC9E])
        classes['double_mark'].append(double_mark)
        new_maximums = set()
        for schema in new_schemas:
            maximum = schema.max_double_marks()
            new_maximums.add(maximum)
            classes[str(maximum)].append(schema)
        for maximum in sorted(new_maximums, reverse=True):
            for i in range(0, maximum):
                add_rule(lookup, Rule([str(maximum)] + [double_mark] * i, [double_mark], [], lookups=[None]))
        guideline = Schema(None, Line(0, dots=7), 1.5, Type.NON_JOINING)
        add_rule(lookup, Rule([double_mark], [guideline, double_mark]))
        return [lookup]

    def _decompose(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('abvs', 'dupl', 'dflt')
        for schema in schemas:
            if schema.marks and schema in new_schemas:
                add_rule(lookup, Rule([schema], [schema.without_marks] + schema.marks))
        return [lookup]

    def _expand_secants(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'abvs',
            'dupl',
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
        named_lookups['non_initial_secant'] = Lookup(None, None, None)
        for schema in new_schemas:
            if isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.JOINER:
                add_rule(named_lookups['non_initial_secant'], Rule(
                    [schema],
                    [schema.clone(
                        cmap=None,
                        path=schema.path.clone(secant_curvature_offset=-schema.path.secant_curvature_offset),
                        anchor=SECANT_ANCHOR,
                        widthless=False,
                    )],
                ))
                classes['secant'].append(schema)
            elif schema.glyph_class == GlyphClass.JOINER and schema.path.can_take_secant():
                classes['base'].append(schema)
        add_rule(lookup, Rule('base', 'secant', [], lookups=['non_initial_secant']))
        initial_secant_marker = Schema(None, InitialSecantMarker(), 0, side_bearing=0)
        add_rule(lookup, Rule(
            ['secant'],
            ['secant', continuing_overlap, initial_secant_marker],
        ))
        return [lookup]

    def _validate_overlap_controls(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='overlap',
        )
        new_classes = {}
        global_max_tree_width = 0
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                return [lookup]
            if isinstance(schema.path, InvalidOverlap):
                classes['overlap'].append(schema)
                if schema.path.continuing:
                    continuing_overlap = schema
                else:
                    letter_overlap = schema
            elif not schema.anchor:
                if max_tree_width := schema.path.max_tree_width(schema.size):
                    if max_tree_width > global_max_tree_width:
                        global_max_tree_width = max_tree_width
                    classes['base'].append(schema)
                    new_class = f'base_{max_tree_width}'
                    classes[new_class].append(schema)
                    new_classes[max_tree_width] = new_class
        assert global_max_tree_width == MAX_TREE_WIDTH
        classes['invalid'].append(letter_overlap)
        classes['invalid'].append(continuing_overlap)
        valid_letter_overlap = letter_overlap.clone(cmap=None, path=ChildEdge(lineage=((1, 0),)), side_bearing=0)
        valid_continuing_overlap = continuing_overlap.clone(cmap=None, path=ContinuingOverlap(), side_bearing=0)
        classes['valid'].append(valid_letter_overlap)
        classes['valid'].append(valid_continuing_overlap)
        classes['overlap'].append(valid_letter_overlap)
        classes['overlap'].append(valid_continuing_overlap)
        add_rule(lookup, Rule('invalid', 'invalid', [], lookups=[None]))
        add_rule(lookup, Rule('valid', 'invalid', [], 'valid'))
        for i in range(global_max_tree_width - 2):
            add_rule(lookup, Rule([], [letter_overlap], [*[letter_overlap] * i, continuing_overlap, 'invalid'], lookups=[None]))
        if global_max_tree_width > 1:
            add_rule(lookup, Rule([], [continuing_overlap], 'invalid', lookups=[None]))
        for max_tree_width, new_class in new_classes.items():
            add_rule(lookup, Rule([new_class], 'invalid', ['invalid'] * max_tree_width, lookups=[None]))
        add_rule(lookup, Rule(['base'], [letter_overlap], [], [valid_letter_overlap]))
        classes['base'].append(valid_letter_overlap)
        add_rule(lookup, Rule(['base'], [continuing_overlap], [], [valid_continuing_overlap]))
        classes['base'].append(valid_continuing_overlap)
        classes[CHILD_EDGE_CLASSES[0]].append(valid_letter_overlap)
        classes[INTER_EDGE_CLASSES[0][0]].append(valid_letter_overlap)
        classes[CONTINUING_OVERLAP_CLASS].append(valid_continuing_overlap)
        classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(valid_continuing_overlap)
        return [lookup]

    def _add_parent_edges(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('blwm', {'DFLT', 'dupl'}, 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        root_parent_edge = Schema(None, ParentEdge([]), 0, Type.NON_JOINING, side_bearing=0)
        root_only_parent_edge = Schema(None, RootOnlyParentEdge(), 0, Type.NON_JOINING, side_bearing=0)
        for child_index in range(MAX_TREE_WIDTH):
            if root_parent_edge not in classes[CHILD_EDGE_CLASSES[child_index]]:
                classes[CHILD_EDGE_CLASSES[child_index]].append(root_parent_edge)
            for layer_index in range(MAX_TREE_DEPTH):
                if root_parent_edge not in classes[INTER_EDGE_CLASSES[layer_index][child_index]]:
                    classes[INTER_EDGE_CLASSES[layer_index][child_index]].append(root_parent_edge)
        for schema in new_schemas:
            if schema.glyph_class == GlyphClass.JOINER:
                classes['root' if schema.path.can_be_child(schema.size) else 'root_only'].append(schema)
        add_rule(lookup, Rule(['root'], [root_parent_edge, 'root']))
        add_rule(lookup, Rule(['root_only'], [root_only_parent_edge, root_parent_edge, 'root_only']))
        return [lookup]

    def _invalidate_overlap_controls(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
            reversed=True,
        )
        for schema in new_schemas:
            if isinstance(schema.path, ParentEdge):
                node = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, RootOnlyParentEdge):
                root_only_parent_edge = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, ChildEdge):
                valid_letter_overlap = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                valid_continuing_overlap = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, InvalidOverlap):
                if schema.path.continuing:
                    invalid_continuing_overlap = schema
                else:
                    invalid_letter_overlap = schema
        classes['valid'].append(valid_letter_overlap)
        classes['valid'].append(valid_continuing_overlap)
        classes['invalid'].append(invalid_letter_overlap)
        classes['invalid'].append(invalid_continuing_overlap)
        add_rule(lookup, Rule([], 'valid', 'invalid', 'invalid'))
        for older_sibling_count in range(MAX_TREE_WIDTH - 1, -1, -1):
            # A continuing overlap not at the top level must be licensed by an
            # ancestral continuing overlap.
            # TODO: Optimization: All but the youngest child can use
            # `valid_letter_overlap` instead of `'valid'`.
            for subtrees in make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count]):
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
                for deep_subtree in make_trees(node, 'valid', MAX_TREE_DEPTH, prefix_depth=MAX_TREE_DEPTH):
                    add_rule(lookup, Rule(
                        [valid_letter_overlap] * older_sibling_count,
                        'valid',
                        [*subtrees, *deep_subtree],
                        'invalid',
                    ))
            # Anything valid needs to be explicitly kept valid, since there might
            # not be enough context to tell that an invalid overlap is invalid.
            # TODO: Optimization: The last subtree can just be one node instead of
            # the full subtree.
            for subtrees in make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count + 1]):
                add_rule(lookup, Rule(
                    [valid_letter_overlap] * older_sibling_count if older_sibling_count else [node],
                    'valid',
                    subtrees,
                    'valid',
                ))
        # If an overlap gets here without being kept valid, it is invalid.
        # FIXME: This should be just one rule, without context, but `add_rule`
        # is broken: it does not take into account what rules precede it in the
        # lookup when determining the possible output schemas.
        add_rule(lookup, Rule([], 'valid', 'valid', 'valid'))
        add_rule(lookup, Rule([node], 'valid', [], 'invalid'))
        add_rule(lookup, Rule('valid', 'valid', [], 'invalid'))
        return [lookup]

    def _add_secant_guidelines(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('abvs', 'dupl', 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        invalid_continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
        valid_continuing_overlap = next(s for s in schemas if isinstance(s.path, ContinuingOverlap))
        dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
        initial_secant_marker = next(s for s in schemas if isinstance(s.path, InitialSecantMarker))
        named_lookups['prepend_zwnj'] = Lookup(None, None, None)
        for schema in new_schemas:
            if (isinstance(schema.path, Line)
                and schema.path.secant
                and schema.glyph_class == GlyphClass.JOINER
                and schema in original_schemas
            ):
                classes['secant'].append(schema)
                zwnj = Schema(None, Space(0), 0, Type.NON_JOINING, side_bearing=0)
                guideline_angle = 270 if 45 <= (schema.path.angle + 90) % 180 < 135 else 0
                guideline = Schema(None, Line(guideline_angle, dots=7), 1.5)
                add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [initial_secant_marker, dtls], [dtls, valid_continuing_overlap, guideline]))
                add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [], [valid_continuing_overlap, guideline]))
        add_rule(named_lookups['prepend_zwnj'], Rule('secant', [zwnj, 'secant']))
        add_rule(lookup, Rule([], 'secant', [], lookups=['prepend_zwnj']))
        return [lookup]

    def _add_placeholders_for_missing_children(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='valid_final_overlap',
        )
        lookup_2 = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='valid_final_overlap',
        )
        if len(original_schemas) != len(schemas):
            return [lookup_1, lookup_2]
        base_classes = {}
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                valid_letter_overlap = schema
                classes['valid_final_overlap'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                valid_continuing_overlap = schema
                classes['valid_final_overlap'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and (max_tree_width := schema.path.max_tree_width(schema.size)) > 1
            ):
                new_class = f'base_{max_tree_width}'
                classes[new_class].append(schema)
                base_classes[max_tree_width] = new_class
        root_parent_edge = next(s for s in schemas if isinstance(s.path, ParentEdge))
        placeholder = Schema(None, Space(0, margins=False), 0, Type.JOINING, side_bearing=0, child=True)
        for max_tree_width, base_class in base_classes.items():
            add_rule(lookup_1, Rule(
                [base_class],
                [valid_letter_overlap],
                [valid_letter_overlap] * (max_tree_width - 2) + ['valid_final_overlap'],
                lookups=[None],
            ))
            add_rule(lookup_2, Rule(
                [],
                [base_class],
                [valid_letter_overlap] * (max_tree_width - 1) + ['valid_final_overlap'],
                lookups=[None],
            ))
            for sibling_count in range(max_tree_width - 1, 0, -1):
                input_1 = 'valid_final_overlap' if sibling_count > 1 else valid_letter_overlap
                add_rule(lookup_1, Rule(
                    [base_class] + [valid_letter_overlap] * (sibling_count - 1),
                    [input_1],
                    [],
                    [input_1] + [root_parent_edge, placeholder] * sibling_count,
                ))
                add_rule(lookup_2, Rule(
                    [],
                    [base_class],
                    [valid_letter_overlap] * (sibling_count - 1) + [input_1],
                    [base_class] + [valid_letter_overlap] * sibling_count,
                ))
        return [lookup_1, lookup_2]

    def _categorize_edges(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        old_groups = [s.path.group() for s in classes['all']]
        child_edges = {}
        parent_edges = {}
        def get_child_edge(lineage):
            lineage = tuple(lineage)
            child_edge = child_edges.get(lineage)
            if child_edge is None:
                child_edge = default_child_edge.clone(cmap=None, path=default_child_edge.path.clone(lineage=lineage))
                child_edges[lineage] = child_edge
            return child_edge
        def get_parent_edge(lineage):
            lineage = tuple(lineage)
            parent_edge = parent_edges.get(lineage)
            if parent_edge is None:
                parent_edge = default_parent_edge.clone(cmap=None, path=default_parent_edge.path.clone(lineage=lineage))
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
                classes['all'].append(schema)
            elif isinstance(schema.path, ParentEdge):
                classes['all'].append(schema)
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

    def _promote_final_letter_overlap_to_continuing_overlap(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('rclt', {'DFLT', 'dupl'}, 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                classes['overlap'].append(schema)
                if all(x[0] == x[1] for x in schema.path.lineage[:-1]):
                    classes['final_letter_overlap'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                continuing_overlap = schema
                classes['overlap'].append(schema)
            elif isinstance(schema.path, ParentEdge) and not schema.path.lineage:
                root_parent_edge = schema
                classes['secant_or_root_parent_edge'].append(schema)
            elif isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.MARK:
                classes['secant_or_root_parent_edge'].append(schema)
        add_rule(lookup, Rule([], 'final_letter_overlap', 'overlap', lookups=[None]))
        named_lookups['promote'] = Lookup(None, None, None)
        add_rule(named_lookups['promote'], Rule('final_letter_overlap', [continuing_overlap]))
        for overlap in classes['final_letter_overlap']:
            named_lookups[f'promote_{overlap.path}_and_parent'] = Lookup(
                None,
                None,
                None,
                flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                mark_filtering_set=str(overlap.path),
            )
            classes[str(overlap.path)].append(overlap)
            for parent_edge in new_schemas:
                if (isinstance(parent_edge.path, ParentEdge)
                    and parent_edge.path.lineage
                    and overlap.path.lineage[:-1] == parent_edge.path.lineage[:-1]
                    and overlap.path.lineage[-1][0] == parent_edge.path.lineage[-1][0] == parent_edge.path.lineage[-1][1]
                ):
                    classes[str(overlap.path)].append(parent_edge)
                    classes[f'parent_for_{overlap.path}'].append(parent_edge)
            add_rule(named_lookups['promote'], Rule(f'parent_for_{overlap.path}', [root_parent_edge]))
            add_rule(named_lookups[f'promote_{overlap.path}_and_parent'], Rule(
                [],
                [overlap, f'parent_for_{overlap.path}'],
                [],
                lookups=['promote', 'promote'],
            ))
            named_lookups[f'check_and_promote_{overlap.path}'] = Lookup(
                None,
                None,
                None,
                flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                mark_filtering_set='secant_or_root_parent_edge',
            )
            add_rule(named_lookups[f'check_and_promote_{overlap.path}'], Rule([], [overlap], 'secant_or_root_parent_edge', lookups=[None]))
            add_rule(named_lookups[f'check_and_promote_{overlap.path}'], Rule([], [overlap], [], lookups=[f'promote_{overlap.path}_and_parent']))
            add_rule(lookup, Rule([], [overlap], [], lookups=[f'check_and_promote_{overlap.path}']), track_possible_outputs=False)
        return [lookup]

    def _reposition_chinook_jargon_overlap_points(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        # TODO: This should be a general thing, not limited to specific Chinook
        # Jargon abbreviations and a few similar patterns.
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        line_classes = {}
        for schema in schemas:
            if schema.glyph_class == GlyphClass.MARK:
                if isinstance(schema.path, ChildEdge):
                    classes['all'].append(schema)
                    classes['overlap'].append(schema)
                    classes['letter_overlap'].append(schema)
                elif isinstance(schema.path, ContinuingOverlap):
                    classes['all'].append(schema)
                    classes['overlap'].append(schema)
                    classes['continuing_overlap'].append(schema)
                elif not schema.path.invisible():
                    classes['all'].append(schema)
            elif schema.glyph_class == GlyphClass.JOINER:
                if schema.path.max_tree_width(schema.size) == 0:
                    continue
                if (isinstance(schema.path, Line)
                    and (schema.size == 1 or schema.cps == [0x1BC07])
                    and not schema.path.secant
                    and not schema.path.dots
                ):
                    angle = schema.path.angle
                    max_tree_width = schema.path.max_tree_width(schema.size)
                    line_class = f'line_{angle}_{max_tree_width}'
                    classes['line'].append(schema)
                    classes[line_class].append(schema)
                    line_classes[line_class] = (angle, max_tree_width)
                elif (isinstance(schema.path, Curve)
                    and schema.cps in [[0x1BC1B], [0x1BC1C]]
                    and schema.size == 6
                    and schema.joining_type == Type.JOINING
                    and (schema.path.angle_in, schema.path.angle_out) in [(90, 270), (270, 90)]
                ):
                    classes['curve'].append(schema)
        if len(original_schemas) == len(schemas):
            for width in range(1, MAX_TREE_WIDTH + 1):
                add_rule(lookup, Rule(['line', *['letter_overlap'] * (width - 1), 'overlap'], 'curve', 'overlap', 'curve'))
        for curve in classes['curve']:
            if curve in new_schemas:
                for line_class, (angle, _) in line_classes.items():
                    for width in range(1, curve.path.max_tree_width(curve.size) + 1):
                        add_rule(lookup, Rule(
                            [],
                            [curve],
                            [*['overlap'] * width, line_class],
                            [curve.clone(cmap=None, path=curve.path.clone(overlap_angle=angle))],
                        ))
        for curve_child in classes['curve']:
            if curve_child in new_schemas:
                for line_class, (angle, max_tree_width) in line_classes.items():
                    for width in range(1, max_tree_width + 1):
                        add_rule(lookup, Rule(
                            [line_class, *['letter_overlap'] * (width - 1), 'overlap'],
                            [curve_child],
                            [],
                            [curve_child.clone(cmap=None, path=curve_child.path.clone(overlap_angle=angle))],
                        ))
        return [lookup]

    def _make_mark_variants_of_children(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('blwm', {'DFLT', 'dupl'}, 'dflt')
        children_to_be = []
        old_child_count = len(classes['child'])
        for schema in new_schemas:
            if isinstance(schema.path, ParentEdge) and schema.path.lineage:
                classes['all'].append(schema)
            elif schema.glyph_class == GlyphClass.JOINER and schema.path.can_be_child(schema.size):
                classes['child_to_be'].append(schema)
        for i, child_to_be in enumerate(classes['child_to_be']):
            if i < old_child_count:
                continue
            child = child_to_be.clone(cmap=None, child=True)
            classes['child'].append(child)
            classes[PARENT_EDGE_CLASS].append(child)
            for child_index in range(MAX_TREE_WIDTH):
                classes[CHILD_EDGE_CLASSES[child_index]].append(child)
        add_rule(lookup, Rule('all', 'child_to_be', [], 'child'))
        return [lookup]

    def _reposition_stenographic_period(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if (isinstance(schema.path, InvalidStep)
                or isinstance(schema.path, Space) and schema.joining_type == Type.JOINING
            ) and schema.glyph_class != GlyphClass.MARK:
                classes['c'].append(schema)
            elif schema.cmap == 0x2E3C:
                period = schema
        zwnj = Schema(None, Space(0), 0, Type.NON_JOINING, side_bearing=0)
        joining_period = period.clone(cmap=None, joining_type=Type.JOINING)
        add_rule(lookup, Rule('c', [period], [], [joining_period, zwnj]))
        return [lookup]

    def _disjoin_equals_sign(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        equals_sign = next(s for s in schemas if s.cmap == 0x003D)
        continuing_overlap = next(s for s in schemas if isinstance(s.path, ContinuingOverlap))
        root_parent_edge = next(s for s in schemas if isinstance(s.path, ParentEdge) and not s.path.lineage)
        zwnj = Schema(None, Space(0), 0, Type.NON_JOINING, side_bearing=0)
        classes['all'].append(continuing_overlap)
        classes['all'].append(root_parent_edge)
        add_rule(lookup, Rule([equals_sign], [zwnj, equals_sign]))
        add_rule(lookup, Rule([equals_sign, continuing_overlap], [root_parent_edge], [], lookups=[None]))
        add_rule(lookup, Rule([equals_sign], [root_parent_edge], [], [zwnj, root_parent_edge]))
        return [lookup]

    def _join_with_next_step(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        old_input_count = len(classes['i'])
        for schema in new_schemas:
            if isinstance(schema.path, InvalidStep):
                classes['i'].append(schema)
            if schema.glyph_class == GlyphClass.JOINER:
                classes['c'].append(schema)
        new_context = 'o' not in classes
        for i, target_schema in enumerate(classes['i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(NO_CONTEXT, NO_CONTEXT).clone(
                    size=800,
                    joining_type=Type.JOINING,
                    side_bearing=0,
                )
                classes['o'].append(output_schema)
        if new_context:
            add_rule(lookup, Rule([], 'i', 'c', 'o'))
        return [lookup]

    def _separate_subantiparallel_lines(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        lines_by_angle = collections.defaultdict(list)
        for schema in new_schemas:
            if schema.glyph_class != GlyphClass.JOINER:
                continue
            if isinstance(schema.path, Line):
                if (schema.path.dots is None
                    and schema.path.secant is None
                    and schema.path.original_angle is None
                ):
                    lines_by_angle[schema.path.angle].append(schema)
            elif (isinstance(schema.path, Circle) and schema.is_primary
                or isinstance(schema.path, (RomanianU, Ou, Wa, Wi))
            ):
                classes['vowel'].append(schema)
        closeness_threshold = 20
        def axis_alignment(x):
            return abs(x % 90 - 45)
        for a1, lines_1 in lines_by_angle.items():
            for a2, lines_2 in lines_by_angle.items():
                if (axis_alignment(a1) < axis_alignment(a2)
                    and Curve.in_degree_range(
                        a1,
                        (a2 + 180 - (closeness_threshold - EPSILON)) % 360,
                        (a2 + 180 + closeness_threshold - EPSILON) % 360,
                        False,
                    )
                ):
                    classes[f'i_{a1}_{a2}'].extend(lines_1)
                    classes[f'c_{a1}_{a2}'].extend(lines_2)
                    for line_1 in lines_1:
                        classes[f'o_{a1}_{a2}'].append(line_1.clone(
                            cmap=None,
                            path=line_1.path.clone(
                                angle=(a2 + 180 + 50 * (-1 if (a2 + 180) % 360 > a1 else 1)) % 360,
                                original_angle=line_1.path.angle,
                            ),
                        ))
                    add_rule(lookup, Rule([], f'i_{a1}_{a2}', f'c_{a1}_{a2}', f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule(f'c_{a1}_{a2}', f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule([], f'i_{a1}_{a2}', ['vowel', f'c_{a1}_{a2}'], f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule([f'c_{a1}_{a2}', 'vowel'], f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
                    # TODO: Once `Line.context_in` and `Line_context_out` report the true angle, add
                    # the following rule.
                    #add_rule(lookup, Rule(f'o_{a1}_{a2}', f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
        return [lookup]

    def _prepare_for_secondary_diphthong_ligature(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if isinstance(schema.path, Ou) or not schema.can_become_part_of_diphthong:
                continue
            if isinstance(schema.path, Curve):
                if schema.is_primary:
                    classes['primary_semicircle'].append(schema)
            elif schema.path.reversed:
                classes['reversed_circle'].append(schema)
                classes['pinned_circle'].append(schema.clone(cmap=None, path=schema.path.clone(pinned=True)))
        add_rule(lookup, Rule([], 'reversed_circle', 'primary_semicircle', 'pinned_circle'))
        return [lookup]

    def _join_with_previous(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        lookup_2 = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [lookup_1, lookup_2]
        contexts_in = OrderedSet()
        @functools.cache
        def get_context_marker(context):
            return Schema(None, ContextMarker(False, context), 0)
        for schema in original_schemas:
            if schema.glyph_class == GlyphClass.JOINER and not (isinstance(schema.path, Line) and schema.path.secant):
                if (schema.joining_type == Type.ORIENTING
                    and schema.context_in == NO_CONTEXT
                ):
                    classes['i'].append(schema)
                if (context_in := schema.path_context_out()) != NO_CONTEXT:
                    if context_in.ignorable_for_topography:
                        context_in = context_in.clone(angle=0)
                    context_in = get_context_marker(context_in)
                    classes['all'].append(context_in)
                    classes['i2'].append(schema)
                    classes['o2'].append(context_in)
                    contexts_in.add(context_in)
        classes['all'].extend(classes[CONTINUING_OVERLAP_CLASS])
        add_rule(lookup_1, Rule('i2', ['i2', 'o2']))
        for j, context_in in enumerate(contexts_in):
            for i, target_schema in enumerate(classes['i']):
                classes[f'o_{j}'].append(target_schema.contextualize(context_in.path.context, target_schema.context_out))
            add_rule(lookup_2, Rule([context_in], 'i', [], f'o_{j}'))
        return [lookup_1, lookup_2]

    def _unignore_last_orienting_glyph_in_initial_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        if 'check_previous' in named_lookups:
            return [lookup]
        for schema in new_schemas:
            if schema.ignored_for_topography:
                classes['i'].append(schema)
                classes['o'].append(schema.clone(ignored_for_topography=False))
            elif (schema.glyph_class == GlyphClass.JOINER
                and not isinstance(schema.path, Space)
                and not (isinstance(schema.path, Line) and schema.path.secant)
                and not schema.pseudo_cursive
            ):
                if (schema.joining_type == Type.ORIENTING
                    and schema.can_be_ignored_for_topography()
                ):
                    classes['first'].append(schema)
                else:
                    classes['c'].append(schema)
                    if schema.can_lead_orienting_sequence and not isinstance(schema.path, Line):
                        classes['fixed_form'].append(schema)
        named_lookups['check_previous'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        add_rule(named_lookups['check_previous'], Rule(['c', 'first'], 'i', [], lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule('c', 'i', [], lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule([], 'i', 'fixed_form', lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule('i', 'o'))
        add_rule(lookup, Rule([], 'i', 'c', lookups=['check_previous']))
        return [lookup]

    def _ignore_first_orienting_glyph_in_initial_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        for schema in new_schemas:
            if (schema.glyph_class != GlyphClass.JOINER
                or schema.pseudo_cursive
                or isinstance(schema.path, Line) and schema.path.secant
            ):
                continue
            classes['joiner'].append(schema)
            if isinstance(schema.path, Ou):
                classes['c'].append(schema)
            if (schema.can_lead_orienting_sequence
                and schema.can_be_ignored_for_topography()
            ):
                classes['c'].append(schema)
                if schema.joining_type == Type.ORIENTING and not isinstance(schema.path, Ou):
                    classes['i'].append(schema)
                    angle_out = schema.path.angle_out - schema.path.angle_in
                    path = schema.path.clone(
                        angle_in=0,
                        angle_out=(angle_out if schema.path.clockwise else -angle_out) % 360,
                        clockwise=True,
                        **({'role': CircleRole.DEPENDENT} if isinstance(schema.path, Circle) else {})
                    )
                    classes['o'].append(schema.clone(
                        cmap=None,
                        path=path,
                        ignored_for_topography=True,
                        context_in=None,
                        context_out=None,
                    ))
        add_rule(lookup, Rule('joiner', 'i', [], 'i'))
        add_rule(lookup, Rule([], 'i', 'c', 'o'))
        return [lookup]

    def _tag_main_glyph_in_orienting_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='dependent',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if schema.ignored_for_topography:
                classes['dependent'].append(schema)
            elif (schema.joining_type == Type.ORIENTING
                and schema.glyph_class == GlyphClass.JOINER
                and (isinstance(schema.path, (Circle, Ou))
                    and schema.path.role == CircleRole.INDEPENDENT
                )
            ):
                classes['i'].append(schema)
                classes['o'].append(schema.clone(cmap=None, path=schema.path.clone(role=CircleRole.LEADER)))
        add_rule(lookup, Rule('dependent', 'i', [], 'o'))
        add_rule(lookup, Rule([], 'i', 'dependent', 'o'))
        return [lookup]

    def _join_with_next(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        pre_lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set=CONTINUING_OVERLAP_CLASS,
        )
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set=CONTINUING_OVERLAP_CLASS,
            reversed=True,
        )
        post_lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='continuing_overlap_after_secant',
            reversed=True,
        )
        contexts_out = OrderedSet()
        new_contexts_out = set()
        old_input_count = len(classes['i'])
        if old_input_count == 0:
            for schema in original_schemas:
                if (schema.glyph_class == GlyphClass.JOINER
                    and schema.joining_type == Type.ORIENTING
                    and schema.context_out == NO_CONTEXT
                ):
                    classes['i'].append(schema)
                    if isinstance(schema.path, Line) and schema.path.secant:
                        classes['secant_i'].append(schema)
                        classes['secant_o'].append(schema)
            continuing_overlap = next(iter(classes[CONTINUING_OVERLAP_CLASS]))
            continuing_overlap_after_secant = Schema(None, ContinuingOverlapS(), 0)
            classes['continuing_overlap_after_secant'].append(continuing_overlap_after_secant)
            add_rule(pre_lookup, Rule('secant_i', [continuing_overlap], [], [continuing_overlap_after_secant]))
        for schema in new_schemas:
            if (schema.glyph_class == GlyphClass.JOINER
                and (old_input_count == 0 or not isinstance(schema.path, (Curve, Circle, Complex)))
                and not (isinstance(schema.path, Line) and schema.path.secant)
                and (context_out := schema.path.context_in()) != NO_CONTEXT
            ):
                contexts_out.add(context_out)
                if schema not in (context_out_class := classes[f'c_{context_out}']):
                    if not context_out_class:
                        new_contexts_out.add(context_out)
                    context_out_class.append(schema)
        for context_out in contexts_out:
            output_class_name = f'o_{context_out}'
            new_context = context_out in new_contexts_out
            for i, target_schema in enumerate(classes['i']):
                if new_context or i >= old_input_count:
                    output_schema = target_schema.contextualize(target_schema.context_in, context_out)
                    classes[output_class_name].append(output_schema)
                    if isinstance(output_schema.path, Line) and output_schema.path.secant:
                        classes['secant_o'].append(output_schema)
            if new_context:
                add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
        if old_input_count == 0:
            # FIXME: This rule shouldn’t need to be contextual, but without the
            # context, fontTools throws a `KeyError` in `buildCoverage`.
            add_rule(post_lookup, Rule(['secant_o'], [continuing_overlap_after_secant], [], [continuing_overlap]))
        return [pre_lookup, lookup, post_lookup]

    def _join_circle_with_adjacent_nonorienting_glyph(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ignored_for_topography',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        contexts_out = OrderedSet()
        for schema in new_schemas:
            if schema.ignored_for_topography:
                if isinstance(schema.path, Circle):
                    classes['i'].append(schema)
                classes['ignored_for_topography'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and (not schema.can_lead_orienting_sequence
                    or isinstance(schema.path, Line) and not schema.path.secant
                )
            ):
                if (context_out := schema.path.context_in()) != NO_CONTEXT:
                    context_out = Context(context_out.angle)
                    contexts_out.add(context_out)
                    classes[f'c_{context_out}'].append(schema)
        for context_out in contexts_out:
            output_class_name = f'o_{context_out}'
            for circle in classes['i']:
                classes[output_class_name].append(circle.clone(cmap=None, context_out=context_out))
            add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
        return [lookup]

    def _ligate_diphthongs(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ignored_for_topography',
            reversed=True,
        )
        diphthong_1_classes = OrderedSet()
        diphthong_2_classes = OrderedSet()
        for schema in new_schemas:
            if not schema.can_become_part_of_diphthong:
                continue
            is_circle_letter = isinstance(schema.path, Circle) or schema.path.reversed_circle
            is_ignored = schema.ignored_for_topography
            is_primary = schema.is_primary
            if is_ignored and not is_primary:
                continue
            input_class_name = f'i1_{is_circle_letter}_{is_ignored}'
            classes[input_class_name].append(schema)
            output_class_name = f'o1_{is_circle_letter}_{is_ignored}'
            output_schema = schema.clone(cmap=None, diphthong_1=True)
            classes[output_class_name].append(output_schema)
            diphthong_1_classes.add((
                input_class_name,
                is_circle_letter,
                is_ignored,
                output_class_name,
            ))
            if schema.ignored_for_topography:
                classes['ignored_for_topography'].append(output_schema)
            input_class_name = f'i2_{is_circle_letter}_{is_ignored}'
            classes[input_class_name].append(schema)
            output_class_name = f'o2_{is_circle_letter}_{is_ignored}'
            output_schema = schema.clone(cmap=None, diphthong_2=True)
            classes[output_class_name].append(output_schema)
            diphthong_2_classes.add((
                input_class_name,
                is_circle_letter,
                is_ignored,
                output_class_name,
            ))
            if schema.ignored_for_topography:
                classes['ignored_for_topography'].append(schema)
                classes['ignored_for_topography'].append(output_schema)
        for input_1, is_circle_1, is_ignored_1, output_1 in diphthong_1_classes.keys():
            for input_2, is_circle_2, is_ignored_2, output_2 in diphthong_2_classes.keys():
                if is_circle_1 != is_circle_2 and (is_ignored_1 or is_ignored_2):
                    add_rule(lookup, Rule(input_1, input_2, [], output_2))
                    add_rule(lookup, Rule([], input_1, output_2, output_1))
        return [lookup]

    def _unignore_noninitial_orienting_sequences(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        contexts_in = OrderedSet()
        new_contexts_in = set()
        old_input_count = len(classes['i'])
        for schema in new_schemas:
            if schema.ignored_for_topography and (
                schema.context_in.angle is None or schema.context_in.ignorable_for_topography
            ):
                classes['i'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and schema.can_lead_orienting_sequence
                and ((schema.path.angle_out - schema.path.angle_in) % 180 == 0
                    or schema.phase_index < self._phases.index(self._join_circle_with_adjacent_nonorienting_glyph)
                    if isinstance(schema.path, Circle)
                    else isinstance(schema.path, Ou) or schema.can_be_ignored_for_topography())
            ):
                context_in = schema.path_context_out().clone(diphthong_start=False, diphthong_end=False)
                contexts_in.add(context_in)
                if schema not in (context_in_class := classes[f'c_{context_in}']):
                    if not context_in_class:
                        new_contexts_in.add(context_in)
                    context_in_class.append(schema)
        for context_in in contexts_in:
            output_class_name = f'o_{context_in}'
            new_context = context_in in new_contexts_in
            for i, target_schema in enumerate(classes['i']):
                if new_context or i >= old_input_count:
                    output_schema = target_schema.contextualize(context_in, target_schema.context_out, ignore_dependent_schemas=False)
                    classes[output_class_name].append(output_schema)
            if new_context:
                add_rule(lookup, Rule(f'c_{context_in}', 'i', [], output_class_name))
        return [lookup]

    def _unignore_initial_orienting_sequences(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
            reversed=True,
        )
        contexts_out = OrderedSet()
        new_contexts_out = set()
        old_input_count = len(classes['i'])
        for schema in new_schemas:
            if schema.ignored_for_topography and (
                schema.context_out.angle is None or schema.context_out.ignorable_for_topography
            ):
                classes['i'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and schema.can_lead_orienting_sequence
                and ((schema.path.angle_out - schema.path.angle_in) % 180 == 0
                    or schema.phase_index < self._phases.index(self._join_circle_with_adjacent_nonorienting_glyph)
                    if isinstance(schema.path, Circle)
                    else isinstance(schema.path, Ou) or schema.can_be_ignored_for_topography())
            ):
                context_out = schema.path_context_in().clone(diphthong_start=False, diphthong_end=False)
                contexts_out.add(context_out)
                if schema not in (context_out_class := classes[f'c_{context_out}']):
                    if not context_out_class:
                        new_contexts_out.add(context_out)
                    context_out_class.append(schema)
        for context_out in contexts_out:
            output_class_name = f'o_{context_out}'
            new_context = context_out in new_contexts_out
            for i, target_schema in enumerate(classes['i']):
                if new_context or i >= old_input_count:
                    output_schema = target_schema.contextualize(target_schema.context_in, context_out, ignore_dependent_schemas=False)
                    classes[output_class_name].append(output_schema)
            if new_context:
                add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
        return [lookup]

    def _join_double_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            'dupl',
            'dflt',
            mark_filtering_set='all',
        )
        for schema in new_schemas:
            if schema.cps == [0x1BC9E]:
                classes['all'].append(schema)
                for i in range(2, MAX_DOUBLE_MARKS + 1):
                    add_rule(lookup, Rule([schema] * i, [schema.clone(
                        cmap=None,
                        cps=schema.cps * i,
                        path=Complex([
                            (1, schema.path),
                            (500, Space((schema.path.angle + 180) % 360, margins=False)),
                            (250, Space((schema.path.angle - 90) % 360, margins=False)),
                        ] * i),
                    )]))
        return [lookup]

    def _rotate_diacritics(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        base_anchors_and_contexts = OrderedSet()
        new_base_anchors_and_contexts = set()
        for schema in original_schemas:
            if schema.anchor:
                if (schema.joining_type == Type.ORIENTING
                        and schema.base_angle is None
                        and schema in new_schemas):
                    classes['all'].append(schema)
                    classes[f'i_{schema.anchor}'].append(schema)
            elif not schema.ignored_for_topography:
                for base_anchor, base_angle in schema.diacritic_angles.items():
                    base_context = schema.path_context_out()
                    base_context = Context(base_angle, base_context.clockwise, ignorable_for_topography=base_context.ignorable_for_topography)
                    base_anchor_and_context = (base_anchor, base_context)
                    base_anchors_and_contexts.add(base_anchor_and_context)
                    if schema not in (base_anchor_and_context_class := classes[f'c_{base_anchor}_{base_context}']):
                        if not base_anchor_and_context_class:
                            new_base_anchors_and_contexts.add(base_anchor_and_context)
                        base_anchor_and_context_class.append(schema)
                        if schema.glyph_class == GlyphClass.MARK:
                            classes['all'].append(schema)
        for base_anchor_and_context in base_anchors_and_contexts:
            if base_anchor_and_context in new_base_anchors_and_contexts:
                anchor, context = base_anchor_and_context
                output_class_name = f'o_{anchor}_{context}'
                for target_schema in classes[f'i_{anchor}']:
                    if anchor == target_schema.anchor:
                        output_schema = target_schema.rotate_diacritic(context)
                        classes[output_class_name].append(output_schema)
                add_rule(lookup, Rule(f'c_{anchor}_{context}', f'i_{anchor}', [], output_class_name))
        return [lookup]

    def _shade(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            'dupl',
            'dflt',
            mark_filtering_set='independent_mark',
        )
        dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
        classes['independent_mark'].append(dtls)
        if new_schemas:
            for schema in new_schemas:
                if schema.anchor and not (isinstance(schema.path, Line) and schema.path.secant):
                    if schema.cmap is not None:
                        classes['independent_mark'].append(schema)
                elif (schema in original_schemas
                    and not schema.ignored_for_topography
                    and schema.shading_allowed
                    and schema.path.is_shadable()
                ):
                    classes['i'].append(schema)
                    classes['o'].append(schema.clone(cmap=None, cps=schema.cps + dtls.cps))
                    if schema.glyph_class == GlyphClass.MARK:
                        classes['independent_mark'].append(schema)
            add_rule(lookup, Rule(['i', dtls], 'o'))
        return [lookup]

    def _make_widthless_variants_of_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('rclt', {'DFLT', 'dupl'}, 'dflt')
        first_iteration = 'i' not in classes
        for schema in new_schemas:
            if schema.glyph_class == GlyphClass.MARK:
                if schema.anchor and schema.widthless is None and not schema.path.invisible():
                    classes['i'].append(schema)
                    widthless_variant = schema.clone(cmap=None, widthless=True)
                    classes['o'].append(widthless_variant)
                    classes['c'].append(widthless_variant)
            elif schema.joining_type == Type.NON_JOINING:
                classes['c'].append(schema)
        if first_iteration:
            add_rule(lookup, Rule('c', 'i', [], 'o'))
        return [lookup]

    def _classify_marks_for_trees(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        for schema in schemas:
            for anchor in MARK_ANCHORS:
                if schema.child or schema.anchor == anchor:
                    classes[f'global..{mkmk(anchor)}'].append(schema)
        return []

    def _merge_lookalikes(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        grouper = group_schemas(new_schemas)
        for group in grouper.groups():
            group.sort(key=Schema.sort_key)
            group_iter = iter(group)
            lookalike_schema = next(group_iter)
            if not lookalike_schema.might_need_width_markers:
                continue
            lookalike_schema.lookalike_group = group
            for schema in group_iter:
                add_rule(lookup, Rule([schema], [lookalike_schema]))
                schema.lookalike_group = group
        return [lookup]

    def _add_shims_for_pseudo_cursive(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        marker_lookup = Lookup(
            'abvm',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        space_lookup = Lookup(
            'abvm',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [marker_lookup, space_lookup]
        pseudo_cursive_schemas_to_classes = {}
        pseudo_cursive_info = {}
        exit_schemas = []
        entry_schemas = []
        for schema in new_schemas:
            if schema.glyph is None or schema.glyph_class != GlyphClass.JOINER:
                continue
            if schema.pseudo_cursive:
                x_min, y_min, x_max, y_max = schema.glyph.boundingBox()
                exit_x = exit_y = entry_x = entry_y = None
                for anchor_class_name, type, x, y in schema.glyph.anchorPoints:
                    if anchor_class_name == CURSIVE_ANCHOR:
                        if type == 'exit':
                            exit_x = x
                            exit_y = y
                        elif type == 'entry':
                            entry_x = x
                            entry_y = y
                assert entry_y == exit_y
                is_space = x_min == x_max
                if is_space:
                    assert x_min == 0
                    assert entry_x == 0
                    exit_x = 0
                bottom_bound = y_min - MINIMUM_STROKE_GAP - entry_y
                top_bound = y_max + MINIMUM_STROKE_GAP - entry_y
                class_name = f'pseudo_cursive_{is_space}_{bottom_bound}_{top_bound}'.replace('-', 'n')
                classes[class_name].append(schema)
                pseudo_cursive_schemas_to_classes[schema] = class_name
                pseudo_cursive_info[class_name] = (
                    is_space,
                    entry_x - x_min,
                    x_max - exit_x,
                    bottom_bound,
                    top_bound,
                    (y_max - y_min) / 2 if isinstance(schema.path, Dot) else 0,
                )
            if schema.context_in == NO_CONTEXT or schema.context_out == NO_CONTEXT:
                if (
                    (looks_like_valid_exit := any(s.context_out == NO_CONTEXT and not schema.diphthong_1 for s in schema.lookalike_group))
                    | (looks_like_valid_entry := any(s.context_in == NO_CONTEXT and not schema.diphthong_2 for s in schema.lookalike_group))
                ):
                    for anchor_class_name, type, x, y in schema.glyph.anchorPoints:
                        if anchor_class_name == CURSIVE_ANCHOR:
                            if looks_like_valid_exit and type == 'exit':
                                exit_schemas.append((schema, x, y))
                            elif looks_like_valid_entry and type == 'entry':
                                entry_schemas.append((schema, x, y))
        @functools.cache
        def get_shim(width, height):
            return Schema(
                None,
                Space(width and math.degrees(math.atan(height / width)) % 360, margins=False),
                math.hypot(width, height),
                side_bearing=width,
            )
        marker = get_shim(0, 0)
        rounding_base = 5
        for pseudo_cursive_index, (pseudo_cursive_class_name, (
            pseudo_cursive_is_space,
            pseudo_cursive_left_bound,
            pseudo_cursive_right_bound,
            pseudo_cursive_bottom_bound,
            pseudo_cursive_top_bound,
            pseudo_cursive_y_offset,
        )) in enumerate(pseudo_cursive_info.items()):
            add_rule(marker_lookup, Rule(pseudo_cursive_class_name, [marker, pseudo_cursive_class_name, marker]))
            exit_classes = {}
            exit_classes_containing_pseudo_cursive_schemas = set()
            exit_classes_containing_true_cursive_schemas = set()
            entry_classes = {}
            for prefix, e_schemas, e_classes, pseudo_cursive_x_bound, height_sign, get_distance_to_edge in [
                ('exit', exit_schemas, exit_classes, pseudo_cursive_left_bound, -1, lambda bounds, x: bounds[1] - x),
                ('entry', entry_schemas, entry_classes, pseudo_cursive_right_bound, 1, lambda bounds, x: x - bounds[0]),
            ]:
                for e_schema, x, y in e_schemas:
                    bounds = e_schema.glyph.foreground.xBoundsAtY(y + pseudo_cursive_bottom_bound, y + pseudo_cursive_top_bound)
                    distance_to_edge = 0 if bounds is None else get_distance_to_edge(bounds, x)
                    shim_width = distance_to_edge + DEFAULT_SIDE_BEARING + pseudo_cursive_x_bound
                    shim_height = pseudo_cursive_y_offset * height_sign
                    if (pseudo_cursive_is_space
                        and e_schemas is exit_schemas
                        and isinstance(e_schema.path, Space)
                    ):
                        # Margins do not collapse between spaces.
                        shim_width += DEFAULT_SIDE_BEARING
                    exit_is_pseudo_cursive = e_classes is exit_classes and e_schema in pseudo_cursive_schemas_to_classes
                    if exit_is_pseudo_cursive:
                        shim_height += pseudo_cursive_info[pseudo_cursive_schemas_to_classes[e_schema]][5]
                    shim_height = rounding_base * round(shim_height / rounding_base)
                    shim_width = rounding_base * round(shim_width / rounding_base)
                    e_class = f'{prefix}_shim_{pseudo_cursive_index}_{shim_width}_{shim_height}'.replace('-', 'n')
                    classes[e_class].append(e_schema)
                    if e_class not in e_classes:
                        e_classes[e_class] = get_shim(shim_width, shim_height)
                    (exit_classes_containing_pseudo_cursive_schemas
                            if exit_is_pseudo_cursive
                            else exit_classes_containing_true_cursive_schemas
                        ).add(e_class)
            for exit_class, shim in exit_classes.items():
                if exit_class in exit_classes_containing_pseudo_cursive_schemas:
                    add_rule(space_lookup, Rule([exit_class, marker], [marker], pseudo_cursive_class_name, [shim]))
                if exit_class in exit_classes_containing_true_cursive_schemas:
                    add_rule(space_lookup, Rule(exit_class, [marker], pseudo_cursive_class_name, [shim]))
            for entry_class, shim in entry_classes.items():
                add_rule(space_lookup, Rule(pseudo_cursive_class_name, [marker], entry_class, [shim]))
        return [marker_lookup, space_lookup]

    def _shrink_wrap_enclosing_circle(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        dist_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='o',
        )
        if len(original_schemas) != len(schemas):
            return [lookup, dist_lookup]
        punctuation = {}
        circle_schema = None
        for schema in schemas:
            if not schema.glyph:
                continue
            if schema.widthless and schema.cps == [0x20DD]:
                assert circle_schema is None
                circle_schema = schema
                classes['i'].append(circle_schema)
            elif schema.encirclable:
                x_min, y_min, x_max, y_max = schema.glyph.boundingBox()
                dx = x_max - x_min
                dy = y_max - y_min
                class_name = f'c_{dx}_{dy}'
                classes[class_name].append(schema)
                punctuation[class_name] = (dx, dy, schema.glyph.width)
        for class_name, (dx, dy, width) in punctuation.items():
            dx += 3 * self.stroke_gap + self.light_line
            dy += 3 * self.stroke_gap + self.light_line
            if dx > dy:
                dy = max(dy, dx * 0.75)
            elif dx < dy:
                dx = max(dx, dy * 0.75)
            new_circle_schema = circle_schema.clone(
                cmap=None,
                path=circle_schema.path.clone(stretch=max(dx, dy) / min(dx, dy) - 1, long=dx < dy),
                size=min(dx, dy) / 100,
            )
            add_rule(lookup, Rule(class_name, [circle_schema], [], [new_circle_schema]))
            classes['o'].append(new_circle_schema)
            side_bearing = round((dx + 2 * DEFAULT_SIDE_BEARING - width) / 2)
            add_rule(dist_lookup, Rule([], [class_name], [new_circle_schema], x_placements=[side_bearing], x_advances=[side_bearing]))
            add_rule(dist_lookup, Rule([class_name], [new_circle_schema], [], x_advances=[side_bearing]))
        return [lookup, dist_lookup]

    def _add_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookups_per_position = 6
        lookups = [
            Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
            for _ in range(lookups_per_position)
        ]
        digit_expansion_lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        carry_expansion_lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        rule_count = 0
        entry_width_markers = {}
        left_bound_markers = {}
        right_bound_markers = {}
        anchor_width_markers = {}
        path_to_markers = {
            EntryWidthDigit: entry_width_markers,
            LeftBoundDigit: left_bound_markers,
            RightBoundDigit: right_bound_markers,
            AnchorWidthDigit: anchor_width_markers,
        }
        start = Schema(None, Start(), 0)
        hubs = {-1: []}
        for hub_priority in range(0, MAX_HUB_PRIORITY + 1):
            hub = next((s for s in schemas if isinstance(s.path, Hub) and s.path.priority == hub_priority), None)
            if hub is None:
                hub = Schema(None, Hub(hub_priority), 0)
                classes[HUB_CLASS].append(hub)
                classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(hub)
            hubs[hub_priority] = [hub]
        end = Schema(None, End(), 0)
        mark_anchor_selectors = {}
        def get_mark_anchor_selector(schema):
            only_anchor_class_name = None
            for anchor_class_name, type, _, _ in schema.glyph.anchorPoints:
                if type == 'mark' and anchor_class_name in MARK_ANCHORS:
                    assert only_anchor_class_name is None, f'{schema} has multiple anchors: {only_anchor_class_name} and {anchor_class_name}'
                    only_anchor_class_name = anchor_class_name
            index = MARK_ANCHORS.index(only_anchor_class_name)
            if index in mark_anchor_selectors:
                return mark_anchor_selectors[index]
            return mark_anchor_selectors.setdefault(index, Schema(None, MarkAnchorSelector(index), 0))
        glyph_class_selectors = {}
        def get_glyph_class_selector(schema):
            glyph_class = schema.glyph_class
            if glyph_class in glyph_class_selectors:
                return glyph_class_selectors[glyph_class]
            return glyph_class_selectors.setdefault(glyph_class, Schema(None, GlyphClassSelector(glyph_class), 0))
        def register_width_marker(width_markers, digit_path, *args):
            if args not in width_markers:
                width_marker = Schema(None, digit_path(*args), 0)
                width_markers[args] = width_marker
            return width_markers[args]
        width_number_schemas = {}
        def get_width_number_schema(width_number):
            if width_number in width_number_schemas:
                return width_number_schemas[width_number]
            return width_number_schemas.setdefault(width_number, Schema(None, width_number, 0))
        width_number_counter = collections.Counter()
        minimum_optimizable_width_number_count = 2
        width_numbers = {}
        def get_width_number(digit_path, width):
            width = round(width)
            if (digit_path, width) in width_numbers:
                width_number = width_numbers[(digit_path, width)]
            else:
                width_number = WidthNumber(digit_path, width)
                width_numbers[(digit_path, width)] = width_number
            width_number_counter[width_number] += 1
            if width_number_counter[width_number] == minimum_optimizable_width_number_count:
                add_rule(digit_expansion_lookup, Rule(
                    [get_width_number_schema(width_number)],
                    width_number.to_digits(functools.partial(register_width_marker, path_to_markers[digit_path])),
                ))
            return width_number
        rules_to_add = []
        for schema in new_schemas:
            if schema not in original_schemas:
                continue
            if schema.glyph is None:
                if isinstance(schema.path, MarkAnchorSelector):
                    mark_anchor_selectors[schema.path.index] = schema
                elif isinstance(schema.path, GlyphClassSelector):
                    glyph_class_selectors[schema.glyph_class] = schema
                if not isinstance(schema.path, Space):
                    # Not a schema created in `add_shims_for_pseudo_cursive`
                    continue
            if schema.might_need_width_markers and (
                schema.glyph_class != GlyphClass.MARK or any(a[0] in MARK_ANCHORS for a in schema.glyph.anchorPoints)
            ):
                entry_xs = {}
                exit_xs = {}
                if schema.glyph is None and isinstance(schema.path, Space):
                    entry_xs[CURSIVE_ANCHOR] = 0
                    exit_xs[CURSIVE_ANCHOR] = schema.size
                else:
                    for anchor_class_name, type, x, _ in schema.glyph.anchorPoints:
                        if type in ['entry', 'mark']:
                            entry_xs[anchor_class_name] = x
                        elif type in ['base', 'basemark', 'exit']:
                            exit_xs[anchor_class_name] = x
                if not (entry_xs or exit_xs):
                    # This glyph never appears in the final glyph buffer.
                    continue
                entry_xs.setdefault(CURSIVE_ANCHOR, 0)
                if CURSIVE_ANCHOR not in exit_xs:
                    exit_xs[CURSIVE_ANCHOR] = exit_xs.get(CONTINUING_OVERLAP_ANCHOR, 0)
                entry_xs.setdefault(CONTINUING_OVERLAP_ANCHOR, entry_xs[CURSIVE_ANCHOR])
                exit_xs.setdefault(CONTINUING_OVERLAP_ANCHOR, exit_xs[CURSIVE_ANCHOR])
                start_x = entry_xs[CURSIVE_ANCHOR if schema.glyph_class == GlyphClass.JOINER else anchor_class_name]
                if schema.glyph is None:
                    x_min = x_max = 0
                else:
                    x_min, _, x_max, _ = schema.glyph.boundingBox()
                if x_min == x_max == 0:
                    x_min = entry_xs[CURSIVE_ANCHOR]
                    x_max = exit_xs[CURSIVE_ANCHOR]
                if schema.glyph_class == GlyphClass.MARK:
                    mark_anchor_selector = [get_mark_anchor_selector(schema)]
                else:
                    mark_anchor_selector = []
                glyph_class_selector = get_glyph_class_selector(schema)
                widths = []
                for width, digit_path in [
                    (entry_xs[CURSIVE_ANCHOR] - entry_xs[CONTINUING_OVERLAP_ANCHOR], EntryWidthDigit),
                    (x_min - start_x, LeftBoundDigit),
                    (x_max - start_x, RightBoundDigit),
                    *[
                        (
                            exit_xs[anchor] - start_x if anchor in exit_xs else 0,
                            AnchorWidthDigit,
                        ) for anchor in MARK_ANCHORS
                    ],
                    *[
                        (
                            exit_xs[anchor] - start_x if schema.glyph_class == GlyphClass.JOINER else 0,
                            AnchorWidthDigit,
                        ) for anchor in CURSIVE_ANCHORS
                    ],
                ]:
                    assert (width < WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                        if width >= 0
                        else width >= -WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                        ), f'Glyph {schema} is too wide: {width} units'
                    widths.append(get_width_number(digit_path, width))
                lookup = lookups[rule_count % lookups_per_position]
                rule_count += 1
                rules_to_add.append((
                    widths,
                    (lambda widths,
                            lookup=lookup, glyph_class_selector=glyph_class_selector, mark_anchor_selector=mark_anchor_selector, schema=schema:
                        add_rule(lookup, Rule([schema], [
                            start,
                            glyph_class_selector,
                            *mark_anchor_selector,
                            *hubs[schema.hub_priority],
                            schema,
                            *widths,
                            end,
                        ]))
                    ),
                ))
        for widths, rule_to_add in rules_to_add:
            final_widths = []
            for width in widths:
                if width_number_counter[width] >= minimum_optimizable_width_number_count:
                    final_widths.append(get_width_number_schema(width))
                else:
                    final_widths.extend(width.to_digits(functools.partial(register_width_marker, path_to_markers[width.digit_path])))
            rule_to_add(final_widths)
            rule_count -= 1
        return [
            *lookups,
            digit_expansion_lookup,
        ]

    def _add_end_markers_for_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        end = next(s for s in new_schemas if isinstance(s.path, End))
        for schema in new_schemas:
            if (schema.glyph is not None
                and schema.glyph_class == GlyphClass.MARK
                and not schema.ignored_for_topography
                and not schema.path.invisible()
                and not any(a[0] in MARK_ANCHORS for a in schema.glyph.anchorPoints)
            ):
                add_rule(lookup, Rule([schema], [schema, end]))
        return [lookup]

    def _remove_false_end_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        if 'all' in classes:
            return [lookup]
        dummy = Schema(None, Dummy(), 0)
        end = next(s for s in new_schemas if isinstance(s.path, End))
        classes['all'].append(end)
        add_rule(lookup, Rule([], [end], [end], [dummy]))
        return [lookup]

    def _clear_entry_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        zeros = [None] * WIDTH_MARKER_PLACES
        if 'zero' not in named_lookups:
            named_lookups['zero'] = Lookup(None, None, None)
        for schema in schemas:
            if isinstance(schema.path, EntryWidthDigit):
                classes['all'].append(schema)
                classes[str(schema.path.place)].append(schema)
                if schema.path.digit == 0:
                    zeros[schema.path.place] = schema
            elif isinstance(schema.path, ContinuingOverlap):
                classes['all'].append(schema)
                continuing_overlap = schema
        for schema in new_schemas:
            if isinstance(schema.path, EntryWidthDigit) and schema.path.digit != 0:
                add_rule(named_lookups['zero'], Rule([schema], [zeros[schema.path.place]]))
        add_rule(lookup, Rule(
            [continuing_overlap],
            [*map(str, range(WIDTH_MARKER_PLACES))],
            [],
            lookups=[None] * WIDTH_MARKER_PLACES,
        ))
        add_rule(lookup, Rule(
            [],
            [*map(str, range(WIDTH_MARKER_PLACES))],
            [],
            lookups=['zero'] * WIDTH_MARKER_PLACES,
        ))
        return [lookup]

    def _sum_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            prepending=True,
        )
        carry_schema = None
        carry_0_placeholder = object()
        original_carry_schemas = [carry_0_placeholder]
        entry_digit_schemas = {}
        original_entry_digit_schemas = []
        left_digit_schemas = {}
        original_left_digit_schemas = []
        right_digit_schemas = {}
        original_right_digit_schemas = []
        anchor_digit_schemas = {}
        original_anchor_digit_schemas = []
        mark_anchor_selectors = {}
        def get_mark_anchor_selector(index, class_name):
            if index in mark_anchor_selectors:
                rv = mark_anchor_selectors[index]
                classes[class_name].append(rv)
                return rv
            rv = Schema(
                None,
                MarkAnchorSelector(index - len(CURSIVE_ANCHORS)),
                0,
            )
            classes['all'].append(rv)
            classes[class_name].append(rv)
            return mark_anchor_selectors.setdefault(index, rv)
        glyph_class_selectors = {}
        def get_glyph_class_selector(glyph_class, class_name):
            if glyph_class in glyph_class_selectors:
                rv = glyph_class_selectors[glyph_class]
                classes[class_name].append(rv)
                return rv
            rv = Schema(
                None,
                GlyphClassSelector(glyph_class),
                0,
            )
            classes['all'].append(rv)
            classes[class_name].append(rv)
            return glyph_class_selectors.setdefault(glyph_class, rv)
        for schema in schemas:
            if isinstance(schema.path, ContinuingOverlap):
                classes['all'].append(schema)
                continuing_overlap = schema
            elif isinstance(schema.path, Carry):
                carry_schema = schema
                original_carry_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
            elif isinstance(schema.path, EntryWidthDigit):
                entry_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_entry_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'idx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, LeftBoundDigit):
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_left_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'ldx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, RightBoundDigit):
                right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_right_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'rdx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, AnchorWidthDigit):
                anchor_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_anchor_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'adx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, Dummy):
                dummy = schema
            elif isinstance(schema.path, MarkAnchorSelector):
                mark_anchor_selectors[schema.path.index] = schema
            elif isinstance(schema.path, GlyphClassSelector):
                glyph_class_selectors[schema.path.glyph_class] = schema
        for (
            original_augend_schemas,
            augend_letter,
            inner_iterable,
        ) in [(
            original_entry_digit_schemas,
            'i',
            [*[(
                False,
                0,
                i,
                'a',
                original_anchor_digit_schemas,
                anchor_digit_schemas,
                AnchorWidthDigit,
            ) for i, anchor in enumerate(ALL_ANCHORS)], (
                False,
                0,
                0,
                'l',
                original_left_digit_schemas,
                left_digit_schemas,
                LeftBoundDigit,
            ), (
                False,
                0,
                0,
                'r',
                original_right_digit_schemas,
                right_digit_schemas,
                RightBoundDigit,
            )],
        ), (
            original_anchor_digit_schemas,
            'a',
            [*[(
                True,
                i,
                0,
                'i',
                original_entry_digit_schemas,
                entry_digit_schemas,
                EntryWidthDigit,
            ) for i in range(len(ALL_ANCHORS) - 1, -1, -1)], *[(
                False,
                i,
                len(ALL_ANCHORS) - 1 - i,
                'a',
                original_anchor_digit_schemas,
                anchor_digit_schemas,
                AnchorWidthDigit,
            ) for i in range(len(ALL_ANCHORS))]],
        )]:
            for augend_schema in original_augend_schemas:
                augend_is_new = augend_schema in new_schemas
                place = augend_schema.path.place
                augend = augend_schema.path.digit
                for (
                    continuing_overlap_is_relevant,
                    augend_skip_backtrack,
                    addend_skip_backtrack,
                    addend_letter,
                    original_addend_schemas,
                    addend_schemas,
                    addend_path,
                ) in inner_iterable:
                    for carry_in_schema in original_carry_schemas:
                        carry_in = 0 if carry_in_schema is carry_0_placeholder else 1
                        carry_in_is_new = carry_in_schema in new_schemas
                        for addend_schema in original_addend_schemas:
                            if place != addend_schema.path.place:
                                continue
                            if not (carry_in_is_new or augend_is_new or addend_schema in new_schemas):
                                continue
                            addend = addend_schema.path.digit
                            carry_out, sum_digit = divmod(carry_in + augend + addend, WIDTH_MARKER_RADIX)
                            context_in_lookup_name = f'e{place}_c{carry_in}_{addend_letter}{addend}'
                            if continuing_overlap_is_relevant:
                                classes[context_in_lookup_name].append(continuing_overlap)
                            classes[context_in_lookup_name].extend(classes[f'{augend_letter}dx_{augend_schema.path.place}'])
                            if (carry_out != 0 and place != WIDTH_MARKER_PLACES - 1) or sum_digit != addend:
                                if carry_out == 0:
                                    carry_out_schema = carry_0_placeholder
                                elif carry_schema is not None:
                                    carry_out_schema = carry_schema
                                else:
                                    assert carry_out == 1, carry_out
                                    carry_out_schema = Schema(None, Carry(), 0)
                                    carry_schema = carry_out_schema
                                sum_index = place * WIDTH_MARKER_RADIX + sum_digit
                                if sum_index in addend_schemas:
                                    sum_digit_schema = addend_schemas[sum_index]
                                else:
                                    sum_digit_schema = Schema(None, addend_path(place, sum_digit), 0)
                                    addend_schemas[sum_index] = sum_digit_schema
                                    classes[f'{addend_letter}dx_{sum_digit_schema.path.place}'].append(sum_digit_schema)
                                    classes['all'].append(sum_digit_schema)
                                outputs = ([sum_digit_schema]
                                    if carry_out == 0 or place == WIDTH_MARKER_PLACES - 1
                                    else [sum_digit_schema, carry_out_schema])
                                sum_lookup_name = str(sum_digit)
                                if sum_lookup_name not in named_lookups:
                                    named_lookups[sum_lookup_name] = Lookup(None, None, None)
                                if context_in_lookup_name not in named_lookups:
                                    classes[context_in_lookup_name].append(addend_schema)
                                    named_lookups[context_in_lookup_name] = Lookup(
                                        None,
                                        None,
                                        None,
                                        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                                        mark_filtering_set=context_in_lookup_name,
                                    )
                                add_rule(lookup, Rule(
                                    AlwaysTrueList() if carry_in == 0 else [carry_in_schema],
                                    [addend_schema],
                                    [],
                                    lookups=[context_in_lookup_name],
                                ))
                                classes[context_in_lookup_name].extend(classes[f'idx_{augend_schema.path.place}'])
                                if addend_skip_backtrack != 0:
                                    classes[context_in_lookup_name].extend(classes[f'{addend_letter}dx_{sum_digit_schema.path.place}'])
                                context_in_lookup_context_in = []
                                if augend_letter == 'i' and addend_letter == 'a':
                                    context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.JOINER, context_in_lookup_name))
                                context_in_lookup_context_in.append(augend_schema)
                                context_in_lookup_context_in.extend([f'{augend_letter}dx_{augend_schema.path.place}'] * augend_skip_backtrack)
                                if augend_letter == 'a' and addend_letter == 'a':
                                    context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.MARK, context_in_lookup_name))
                                    context_in_lookup_context_in.append(f'idx_{augend_schema.path.place}')
                                elif augend_skip_backtrack == 1:
                                    context_in_lookup_context_in.append(continuing_overlap)
                                elif augend_letter == 'a' and addend_letter == 'i' and augend_skip_backtrack != 0:
                                    context_in_lookup_context_in.append(get_mark_anchor_selector(
                                        len(ALL_ANCHORS) - augend_skip_backtrack - 1,
                                        context_in_lookup_name,
                                    ))
                                context_in_lookup_context_in.extend([f'{addend_letter}dx_{sum_digit_schema.path.place}'] * addend_skip_backtrack)
                                add_rule(named_lookups[context_in_lookup_name], Rule(
                                    context_in_lookup_context_in,
                                    [addend_schema],
                                    [],
                                    lookups=[sum_lookup_name],
                                ))
                                add_rule(named_lookups[sum_lookup_name], Rule([addend_schema], outputs))
        return [lookup]

    def _calculate_bound_extrema(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        left_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='ldx',
        )
        named_lookups['ldx_copy'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='ldx',
        )
        left_digit_schemas = {}
        right_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='rdx',
        )
        named_lookups['rdx_copy'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='rdx',
        )
        right_digit_schemas = {}
        for schema in schemas:
            if isinstance(schema.path, LeftBoundDigit):
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                if schema in new_schemas:
                    classes['ldx'].append(schema)
            elif isinstance(schema.path, RightBoundDigit):
                right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                if schema in new_schemas:
                    classes['rdx'].append(schema)
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
                        (left_schema_i, left_digit_schemas, left_lookup, 'ldx', 'ldx_copy', int.__gt__),
                        (right_schema_i, right_digit_schemas, right_lookup, 'rdx', 'rdx_copy', int.__lt__),
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

    def _remove_false_start_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
            reversed=True,
        )
        dummy = next(s for s in new_schemas if isinstance(s.path, Dummy))
        start = next(s for s in new_schemas if isinstance(s.path, Start))
        classes['all'].append(start)
        add_rule(lookup, Rule([start], [start], [], [dummy]))
        return [lookup]

    def _mark_hubs_after_initial_secants(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            'dupl',
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        hubs = OrderedSet()
        needed_hub_priorities = set()
        for schema in new_schemas:
            if isinstance(schema.path, Hub) and not schema.path.initial_secant:
                hubs.add(schema)
                classes['all'].append(schema)
            elif isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.JOINER:
                classes['secant'].append(schema)
        for hub in hubs:
            initial_secant_hub = hub.clone(path=hub.path.clone(initial_secant=True))
            classes[HUB_CLASS].append(initial_secant_hub)
            classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(initial_secant_hub)
            add_rule(lookup, Rule(
                ['secant'],
                [hub],
                [],
                [initial_secant_hub],
            ))
        return [lookup]

    def _find_real_hub(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        hubs = collections.defaultdict(list)
        for schema in new_schemas:
            if isinstance(schema.path, Dummy):
                dummy = schema
            elif isinstance(schema.path, Hub):
                hubs[schema.path.priority].append(schema)
                classes['all'].append(schema)
            elif isinstance(schema.path, InitialSecantMarker):
                classes['all'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                continuing_overlap = schema
                classes['all'].append(schema)
        for priority_a, hubs_a in sorted(hubs.items()):
            for priority_b, hubs_b in sorted(hubs.items()):
                for hub_a in hubs_a:
                    if not hub_a.path.initial_secant:
                        add_rule(lookup, Rule([continuing_overlap], [hub_a], [], [dummy]))
                    for hub_b in hubs_b:
                        if hub_b.path.initial_secant:
                            continue
                        if priority_a <= priority_b:
                            add_rule(lookup, Rule([hub_a], [hub_b], [], [dummy]))
                        else:
                            add_rule(lookup, Rule([], [hub_a], [hub_b], [dummy]))
        return [lookup]

    def _expand_start_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        start = next(s for s in new_schemas if isinstance(s.path, Start))
        add_rule(lookup, Rule([start], [
            start,
            *(Schema(None, LeftBoundDigit(place, 0, DigitStatus.DONE), 0) for place in range(WIDTH_MARKER_PLACES)),
        ]))
        return [lookup]

    def _mark_maximum_bounds(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        left_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ldx',
            reversed=True,
        )
        right_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='rdx',
            reversed=True,
        )
        anchor_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='adx',
            reversed=True,
        )
        new_left_bounds = []
        new_right_bounds = []
        new_anchor_widths = []
        end = next(s for s in schemas if isinstance(s.path, End))
        for schema in new_schemas:
            if isinstance(schema.path, LeftBoundDigit):
                classes['ldx'].append(schema)
                new_left_bounds.append(schema)
            elif isinstance(schema.path, RightBoundDigit):
                classes['rdx'].append(schema)
                new_right_bounds.append(schema)
            elif isinstance(schema.path, AnchorWidthDigit):
                classes['adx'].append(schema)
                new_anchor_widths.append(schema)
        for new_digits, lookup, class_name, digit_path, status in [
            (new_left_bounds, left_lookup, 'ldx', LeftBoundDigit, DigitStatus.ALMOST_DONE),
            (new_right_bounds, right_lookup, 'rdx', RightBoundDigit, DigitStatus.DONE),
            (new_anchor_widths, anchor_lookup, 'adx', AnchorWidthDigit, DigitStatus.DONE),
        ]:
            for schema in new_digits:
                if schema.path.status != DigitStatus.NORMAL:
                    continue
                skipped_schemas = [class_name] * schema.path.place
                add_rule(lookup, Rule(
                    [],
                    [schema],
                    [*[class_name] * (WIDTH_MARKER_PLACES - schema.path.place - 1), end],
                    [Schema(None, digit_path(schema.path.place, schema.path.digit, status), 0)]))
        return [left_lookup, right_lookup, anchor_lookup]

    def _copy_maximum_left_bound_to_start(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        new_left_totals = []
        new_left_start_totals = [None] * WIDTH_MARKER_PLACES
        start = next(s for s in schemas if isinstance(s.path, Start))
        if start not in classes['all']:
            classes['all'].append(start)
        for schema in new_schemas:
            if isinstance(schema.path, LeftBoundDigit):
                if schema.path.status == DigitStatus.ALMOST_DONE:
                    new_left_totals.append(schema)
                elif schema.path.status == DigitStatus.DONE and schema.path.digit == 0:
                    new_left_start_totals[schema.path.place] = schema
        for total in new_left_totals:
            classes['all'].append(total)
            if total.path.digit == 0:
                done = new_left_start_totals[total.path.place]
            else:
                done = Schema(None, LeftBoundDigit(total.path.place, total.path.digit, DigitStatus.DONE), 0)
            classes['all'].append(done)
            if total.path.digit != 0:
                input = new_left_start_totals[total.path.place]
                if input not in classes['all']:
                    classes['all'].append(input)
                add_rule(lookup, Rule(
                    [start, *['all'] * total.path.place],
                    [input],
                    [*['all'] * (WIDTH_MARKER_PLACES - 1), total],
                    [done]))
        return [lookup]

    def _dist(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        for schema in new_schemas:
            if ((isinstance(schema.path, LeftBoundDigit)
                    or isinstance(schema.path, RightBoundDigit)
                    or isinstance(schema.path, AnchorWidthDigit))
                    and schema.path.status == DigitStatus.DONE):
                digit = schema.path.digit
                if schema.path.place == WIDTH_MARKER_PLACES - 1 and digit >= WIDTH_MARKER_RADIX / 2:
                    digit -= WIDTH_MARKER_RADIX
                x_advance = digit * WIDTH_MARKER_RADIX ** schema.path.place
                if not isinstance(schema.path, RightBoundDigit):
                    x_advance = -x_advance
                if schema.path.place == 0 and not isinstance(schema.path, AnchorWidthDigit):
                    x_advance += DEFAULT_SIDE_BEARING
                if x_advance:
                    add_rule(lookup, Rule([], [schema], [], x_advances=[x_advance]))
        return [lookup]

    def _run_phases(self, all_input_schemas, phases, all_classes=None):
        global CURRENT_PHASE_INDEX
        all_schemas = OrderedSet(all_input_schemas)
        all_input_schemas = OrderedSet(all_input_schemas)
        all_lookups_with_phases = []
        if all_classes is None:
            all_classes = collections.defaultdict(FreezableList)
        all_named_lookups_with_phases = {}
        for CURRENT_PHASE_INDEX, phase in enumerate(phases):
            all_output_schemas = OrderedSet()
            autochthonous_schemas = OrderedSet()
            original_input_schemas = OrderedSet(all_input_schemas)
            new_input_schemas = OrderedSet(all_input_schemas)
            output_schemas = OrderedSet(all_input_schemas)
            classes = PrefixView(phase, all_classes)
            named_lookups = PrefixView(phase, {})
            lookups = None
            while new_input_schemas:
                output_lookups = phase(
                    original_input_schemas,
                    all_input_schemas,
                    new_input_schemas,
                    classes,
                    named_lookups,
                    functools.partial(
                        add_rule,
                        autochthonous_schemas,
                        output_schemas,
                        classes,
                        named_lookups,
                     ),
                 )
                if lookups is None:
                    lookups = output_lookups
                else:
                    assert len(lookups) == len(output_lookups), f'Incompatible lookup counts for phase {phase.__name__}'
                    for i, lookup in enumerate(lookups):
                        lookup.extend(output_lookups[i])
                if len(output_lookups) == 1:
                    might_have_feedback = False
                    for rule in (lookup := output_lookups[0]).rules:
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
            all_schemas |= all_input_schemas
            all_lookups_with_phases.extend((lookup, phase) for lookup in lookups)
            all_named_lookups_with_phases |= ((name, (lookup, phase)) for name, lookup in named_lookups.items())
        return (
            all_schemas,
            all_input_schemas,
            all_lookups_with_phases,
            all_classes,
            all_named_lookups_with_phases,
        )

    def _add_lookup(
        self,
        feature_tag,
        anchor_class_name,
        *,
        flags,
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
        for script in Lookup.KNOWN_SCRIPTS:
            feature.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
            feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
            feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts):
        parent_edge_lookup = None
        child_edge_lookups = [None] * MAX_TREE_WIDTH
        self._add_lookup(
                'abvm',
                PARENT_EDGE_ANCHOR,
                flags=0,
                mark_filtering_set=class_asts[PARENT_EDGE_CLASS],
            )
        for layer_index in range(MAX_TREE_DEPTH):
            if layer_index < 2:
                for child_index in range(MAX_TREE_WIDTH):
                    self._add_lookup(
                            'blwm',
                            CHILD_EDGE_ANCHORS[layer_index][child_index],
                            flags=0,
                            mark_filtering_set=class_asts[CHILD_EDGE_CLASSES[child_index]],
                        )
            for child_index in range(MAX_TREE_WIDTH):
                self._add_lookup(
                    'mkmk',
                    INTER_EDGE_ANCHORS[layer_index][child_index],
                    flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                    mark_filtering_set=class_asts[INTER_EDGE_CLASSES[layer_index][child_index]],
                )
        self._add_lookup(
            'curs',
            CONTINUING_OVERLAP_ANCHOR,
            flags=0,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            CURSIVE_ANCHOR,
            flags=0,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            PRE_HUB_CONTINUING_OVERLAP_ANCHOR,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            POST_HUB_CONTINUING_OVERLAP_ANCHOR,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            PRE_HUB_CURSIVE_ANCHOR,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            POST_HUB_CURSIVE_ANCHOR,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        for anchor in MARK_ANCHORS:
            self._add_lookup(
                'mark',
                anchor,
                flags=0,
            )
        for anchor in MKMK_ANCHORS:
            self._add_lookup(
                'mkmk',
                mkmk(anchor),
                flags=0,
                mark_filtering_set=class_asts[f'global..{mkmk(anchor)}'],
            )

    def _add_altuni(self, uni, glyph_name):
        glyph = self.font[glyph_name]
        if uni != -1:
            if glyph.unicode == -1:
                glyph.unicode = uni
            else:
                new_altuni = ((uni, -1, 0),)
                if glyph.altuni is None:
                    glyph.altuni = new_altuni
                else:
                    glyph.altuni += new_altuni
        return glyph

    def _draw_glyph(self, glyph, schema):
        assert not schema.marks
        pen = glyph.glyphPen()
        invisible = schema.path.invisible()
        floating = schema.path.draw(
            glyph,
            not invisible and pen,
            self.light_line if invisible or schema.cmap is not None or schema.cps[-1:] != [0x1BC9D] else self.shaded_line,
            self.light_line,
            self.stroke_gap,
            schema.size,
            schema.anchor,
            schema.joining_type,
            schema.child,
            schema.context_in == NO_CONTEXT and schema.diphthong_1 and isinstance(schema.path, Circle),
            schema.context_out == NO_CONTEXT and schema.diphthong_2 and isinstance(schema.path, Circle),
            schema.diphthong_1,
            schema.diphthong_2,
        )
        if schema.joining_type == Type.NON_JOINING:
            glyph.left_side_bearing = schema.side_bearing
        else:
            entry_x = next(
                (x for anchor_class_name, type, x, _ in glyph.anchorPoints
                    if anchor_class_name == CURSIVE_ANCHOR and type == 'entry'),
                0,
            )
            glyph.transform(fontTools.misc.transform.Offset(-entry_x, 0))
        if not floating:
            _, y_min, _, _ = glyph.boundingBox()
            glyph.transform(fontTools.misc.transform.Offset(0, -y_min))
        if schema.glyph_class == GlyphClass.MARK:
            glyph.width = 0
        else:
            glyph.right_side_bearing = schema.side_bearing

    def _create_glyph(self, schema, *, drawing):
        if schema.path.name_in_sfd():
            return self.font[schema.path.name_in_sfd()]
        glyph_name = str(schema)
        uni = -1 if schema.cmap is None else schema.cmap
        if glyph_name in self.font:
            return self._add_altuni(uni, glyph_name)
        glyph = self.font.createChar(uni, glyph_name)
        glyph.glyphclass = schema.glyph_class
        glyph.temporary = schema
        if drawing:
            self._draw_glyph(glyph, schema)
        else:
            glyph.width = glyph.width
        return glyph

    def _create_marker(self, schema):
        assert schema.cmap is None, f'A marker has the code point U+{schema.cmap:04X}'
        glyph = self._create_glyph(schema, drawing=True)
        glyph.width = 0

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
            if glyph_class == GlyphClass.BLOCKER:
                bases.append(glyph.glyphname)
            elif glyph_class == GlyphClass.MARK:
                marks.append(glyph.glyphname)
            elif glyph_class == GlyphClass.JOINER:
                ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            fontTools.feaLib.ast.GlyphClass(bases),
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    @staticmethod
    def _glyph_to_schema(glyph):
        if glyph.temporary is None:
            schema = Schema(glyph.unicode if glyph.unicode != -1 else None, SFDGlyphWrapper(glyph.glyphname), 0, Type.NON_JOINING)
        else:
            schema = glyph.temporary
            glyph.temporary = None
        schema.glyph = glyph
        return schema

    def convert_classes(self, classes):
        class_asts = {}
        for name, schemas in classes.items():
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                name,
                fontTools.feaLib.ast.GlyphClass([*map(str, schemas)]),
            )
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        return class_asts

    def convert_named_lookups(self, named_lookups_with_phases, class_asts):
        named_lookup_asts = {}
        named_lookups_to_do = [*named_lookups_with_phases.keys()]
        while named_lookups_to_do:
            new_named_lookups_to_do = []
            for name, (lookup, phase) in named_lookups_with_phases.items():
                if name not in named_lookups_to_do:
                    continue
                try:
                    named_lookup_ast = lookup.to_asts(
                        PrefixView(phase, class_asts),
                        PrefixView(phase, named_lookup_asts),
                        name,
                    )
                    assert len(named_lookup_ast) == 1, f'A named lookup should generate 1 AST, not {len(named_lookup_ast)}'
                    named_lookup_ast = named_lookup_ast[0]
                except KeyError:
                    new_named_lookups_to_do.append(name)
                    continue
                self._fea.statements.append(named_lookup_ast)
                assert name not in named_lookup_asts.keys(), name
                named_lookup_asts[name] = named_lookup_ast
            assert len(new_named_lookups_to_do) < len(named_lookups_to_do)
            named_lookups_to_do = new_named_lookups_to_do
        return named_lookup_asts

    def _merge_schemas(self, schemas, lookups_with_phases, classes):
        grouper = group_schemas(schemas)
        previous_phase = None
        for lookup, phase in reversed(lookups_with_phases):
            if phase is not previous_phase is not None:
                rename_schemas(grouper, self._phases.index(previous_phase))
            previous_phase = phase
            prefix_classes = PrefixView(phase, classes)
            for rule in lookup.rules:
                sift_groups(grouper, rule, rule.contexts_in, prefix_classes)
                sift_groups(grouper, rule, rule.contexts_out, prefix_classes)
                sift_groups(grouper, rule, rule.inputs, prefix_classes)
        rename_schemas(grouper, NO_PHASE_INDEX)

    def augment(self):
        (
            schemas,
            output_schemas,
            lookups_with_phases,
            classes,
            named_lookups_with_phases,
        ) = self._run_phases(self._schemas, self._phases)
        self._merge_schemas(schemas, lookups_with_phases, classes)
        class_asts = self.convert_classes(classes)
        named_lookup_asts = self.convert_named_lookups(named_lookups_with_phases, class_asts)
        (
            _,
            more_output_schemas,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = self._run_phases([schema for schema in output_schemas if schema.canonical_schema is schema], self._middle_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for schema in schemas.sorted(key=lambda schema: not (schema in output_schemas and schema in more_output_schemas)):
            self._create_glyph(
                schema,
                drawing=schema in output_schemas and schema in more_output_schemas and not schema.ignored_for_topography,
            )
        for schema in schemas:
            if name_in_sfd := schema.path.name_in_sfd():
                self.font[name_in_sfd].temporary = schema
                self.font[name_in_sfd].glyphname = str(schema)
        (
            schemas,
            _,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = self._run_phases([*map(self._glyph_to_schema, self.font.glyphs())], self._marker_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        for schema in schemas:
            if schema.glyph is None:
                self._create_marker(schema)
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for i, lp in enumerate(lookups_with_phases):
            for statement in lp[0].to_asts(PrefixView(lp[1], class_asts), PrefixView(lp[1], named_lookup_asts), i):
                self._fea.statements.append(statement)
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

