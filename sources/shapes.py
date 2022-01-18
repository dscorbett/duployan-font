# Copyright 2018-2019 David Corbett
# Copyright 2019-2022 Google LLC
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

from __future__ import annotations


__all__ = [
    'AnchorWidthDigit',
    'Bound',
    'Carry',
    'ChildEdge',
    'Circle',
    'CircleRole',
    'Complex',
    'ContextMarker',
    'ContinuingOverlap',
    'ContinuingOverlapS',
    'Curve',
    'DigitStatus',
    'Dot',
    'Dummy',
    'End',
    'EntryWidthDigit',
    'GlyphClassSelector',
    'Hub',
    'InitialSecantMarker',
    'InvalidDTLS',
    'InvalidOverlap',
    'InvalidStep',
    'LINE_FACTOR',
    'LeftBoundDigit',
    'Line',
    'MarkAnchorSelector',
    'Notdef',
    'Ou',
    'ParentEdge',
    'RADIUS',
    'RightBoundDigit',
    'RomanianU',
    'RootOnlyParentEdge',
    'SFDGlyphWrapper',
    'SeparateAffix',
    'Shape',
    'Space',
    'Start',
    'TangentHook',
    'ValidDTLS',
    'Wa',
    'Wi',
    'WidthNumber',
    'XShape',
]


import collections
from collections.abc import Mapping
from collections.abc import MutableSequence
from collections.abc import Sequence
import enum
import math
import typing
from typing import Any
from typing import Callable
from typing import Final
from typing import Literal
from typing import Optional
from typing import Tuple
from typing import Union


import fontTools.misc.transform
import fontforge


import anchors
from utils import CLONE_DEFAULT
from utils import CURVE_OFFSET
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import EPSILON
from utils import GlyphClass
from utils import NO_CONTEXT
from utils import Type
from utils import WIDTH_MARKER_PLACES
from utils import WIDTH_MARKER_RADIX
from utils import mkmk


LINE_FACTOR: Final[float] = 500


RADIUS: Final[float] = 50


def _rect(r: float, theta: float) -> Tuple[float, float]:
    return (r * math.cos(theta), r * math.sin(theta))


class Shape:
    def clone(self) -> Shape:
        raise NotImplementedError

    def name_in_sfd(self) -> Optional[str]:
        return None

    def __str__(self) -> str:
        raise NotImplementedError

    @staticmethod
    def name_implies_type() -> bool:
        return False

    def group(self):
        return str(self)

    def invisible(self) -> bool:
        return False

    @staticmethod
    def can_take_secant() -> bool:
        return False

    def hub_priority(self, size) -> int:
        return 0 if self.invisible() else -1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen,
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        if not self.invisible():
            raise NotImplementedError
        return False

    def can_be_child(self, size: float) -> bool:
        return False

    def max_tree_width(self, size: float) -> int:
        return 0

    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence) -> int:
        return 0

    def is_pseudo_cursive(self, size: float) -> bool:
        return False

    def is_shadable(self) -> bool:
        return False

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        raise NotImplementedError

    def context_in(self) -> Context:
        raise NotImplementedError

    def context_out(self) -> Context:
        raise NotImplementedError

    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        return {}

    @staticmethod
    def guaranteed_glyph_class() -> Optional[str]:
        return None


class SFDGlyphWrapper(Shape):
    def __init__(self, sfd_name: str) -> None:
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
        is_context_in: bool,
        context: Context,
    ) -> None:
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
        priority: int,
        *,
        initial_secant: bool = False,
    ) -> None:
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
    ) -> bool:
        if self.initial_secant:
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'exit', 0, 0)
        else:
            glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'exit', 0, 0)
        return False

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
    ) -> bool:
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
        return False

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
    def __init__(self, place: int, digit: int) -> None:
        self.place = place
        self.digit = digit

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
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        self.place = place
        self.digit = digit
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
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        self.place = place
        self.digit = digit
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
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        self.place = place
        self.digit = digit
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
    def __init__(
        self,
        digit_path: Union[type[AnchorWidthDigit], type[EntryWidthDigit], type[LeftBoundDigit], type[RightBoundDigit]],
        width: int,
    ) -> None:
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

    def to_digits(
        self,
        register_width_marker: Callable[[Union[type[AnchorWidthDigit], type[EntryWidthDigit], type[LeftBoundDigit], type[RightBoundDigit]], int, int], Any],
    ) -> Sequence:
        digits = []
        quotient = self.width
        for i in range(WIDTH_MARKER_PLACES):
            quotient, remainder = divmod(quotient, WIDTH_MARKER_RADIX)
            digits.append(register_width_marker(self.digit_path, i, remainder))
        return digits


class MarkAnchorSelector(Shape):
    def __init__(self, index: int):
        self.index = index

    def __str__(self):
        return f'anchor.{anchors.ALL_MARK[self.index]}'

    @staticmethod
    def name_implies_type():
        return True

    def invisible(self):
        return True

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK


class GlyphClassSelector(Shape):
    def __init__(self, glyph_class: GlyphClass):
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
    ) -> bool:
        stroke_width = 51
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.BLOCKER


class Space(Shape):
    def __init__(
        self,
        angle: float,
        *,
        margins: bool = False,
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
    ) -> bool:
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            glyph.transform(
                fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
                ('round',),
            )
        return False

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
    ) -> bool:
        stroke_width = 75
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        pen.moveTo((stroke_width / 2, 639 + stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return False

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
    def __init__(self, lineage: Sequence[Tuple[int, int]]) -> None:
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
    ) -> bool:
        layer_index = len(self.lineage) - 1
        child_index = self.lineage[-1][0] - 1
        glyph.addAnchorPoint(anchors.CHILD_EDGES[min(1, layer_index)][child_index], 'mark', 0, 0)
        glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'basemark', 0, 0)
        return False

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
    ) -> bool:
        return False

    @staticmethod
    def guaranteed_glyph_class():
        return GlyphClass.MARK


class ContinuingOverlap(ContinuingOverlapS):
    pass


class ParentEdge(Shape):
    def __init__(self, lineage: Sequence[Tuple[int, int]]) -> None:
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
    ) -> bool:
        if self.lineage:
            layer_index = len(self.lineage) - 1
            child_index = self.lineage[-1][0] - 1
            glyph.addAnchorPoint(anchors.PARENT_EDGE, 'basemark', 0, 0)
            glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'mark', 0, 0)
        return False

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
        centered: bool = False,
    ) -> None:
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
    ) -> bool:
        assert not child
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', stroke_width, 'round')
        if anchor:
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *_rect(0, 0))
            glyph.addAnchorPoint(anchor, 'mark', *_rect(0, 0))
        elif joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', 0, 0 if self.centered else -(stroke_width / 2))
        return False

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
        angle: float,
        *,
        minor: bool = False,
        stretchy: bool = False,
        secant: Optional[float] = None,
        secant_curvature_offset: float = 45,
        dots: Optional[int] = None,
        final_tick: bool = False,
        original_angle: Optional[float] = None,
    ) -> None:
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

    def _get_length(self, size: float) -> int:
        if self.stretchy:
            length_denominator = abs(math.sin(math.radians(self.angle if self.original_angle is None else self.original_angle)))
            if length_denominator < EPSILON:
                length_denominator = 1
        else:
            length_denominator = 1
        return int(LINE_FACTOR * size / length_denominator)

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
    ) -> bool:
        end_y = 0
        length: float = self._get_length(size)
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
                or anchor not in [anchors.ABOVE, anchors.BELOW]
            ):
                length *= self.secant or 0.5
            elif (anchor == anchors.ABOVE) == (self.angle < 180):
                length = 0
            glyph.addAnchorPoint(anchor, 'mark', length, end_y)
            glyph.addAnchorPoint(mkmk(anchor), 'mark', length, end_y)
        elif self.secant:
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
        else:
            anchor_name = mkmk if child else lambda a: a
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = length / (max_tree_width + 2)
                for child_index in range(max_tree_width):
                    glyph.addAnchorPoint(
                        anchors.CHILD_EDGES[int(child)][child_index],
                        base,
                        child_interval * (child_index + 2),
                        0,
                    )
                if child:
                    glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', child_interval, 0)
                else:
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', child_interval, 0)
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', child_interval * (max_tree_width + 1), 0)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'exit', length, end_y)
                    glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', child_interval, 0)
                    if self.hub_priority(size) != -1:
                        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
                    if self.hub_priority(size) != 0:
                        glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', length, end_y)
                    glyph.addAnchorPoint(anchor_name(anchors.SECANT), base, child_interval * (max_tree_width + 1), 0)
            if size == 2 and 0 < self.angle <= 45:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, length / 2 - (light_line + stroke_gap), -(stroke_width + light_line) / 2)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, length / 2 + light_line + stroke_gap, -(stroke_width + light_line) / 2)
            else:
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, length / 2, (stroke_width + light_line) / 2)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, length / 2, -(stroke_width + light_line) / 2)
            glyph.addAnchorPoint(anchor_name(anchors.MIDDLE), base, length / 2, 0)
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
            ('round',)
        )
        glyph.stroke('circular', stroke_width, 'round')
        if not anchor and not self.secant:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_width / 2 + 2 * stroke_gap + light_line / 2)
            glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - (stroke_width / 2 + 2 * stroke_gap + light_line / 2))
        return False

    def can_be_child(self, size):
        return not (self.secant or self.dots)

    def max_tree_width(self, size):
        return 2 if size == 2 and not self.secant else 1

    def max_double_marks(self, size, joining_type, marks):
        return (0
            if self.secant or self.dots or any(
                m.anchor in [anchors.RELATIVE_1, anchors.RELATIVE_2, anchors.MIDDLE]
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
            anchors.RELATIVE_1: angle,
            anchors.RELATIVE_2: angle,
            anchors.MIDDLE: (angle + 90) % 180,
            anchors.SECANT: angle,
        }

    def reversed(self) -> Line:
        return self.clone(angle=(self.angle + 180) % 360)


class Curve(Shape):
    def __init__(
        self,
        angle_in: float,
        angle_out: float,
        *,
        clockwise: bool,
        stretch: float = 0,
        long: bool = False,
        relative_stretch: bool = True,
        hook: bool = False,
        reversed_circle: bool = False,
        overlap_angle: Optional[float] = None,
        secondary: Optional[bool] = None,
        would_flip: bool = False,
        early_exit: bool = False,
    ) -> None:
        assert overlap_angle is None or abs(angle_out - angle_in) == 180, 'Only a semicircle may have an overlap angle'
        assert would_flip or not early_exit, 'An early exit is not needed if the curve would not flip'
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
        self.would_flip = would_flip
        self.early_exit = early_exit

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
        would_flip=CLONE_DEFAULT,
        early_exit=CLONE_DEFAULT,
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
            would_flip=self.would_flip if would_flip is CLONE_DEFAULT else would_flip,
            early_exit=self.early_exit if early_exit is CLONE_DEFAULT else early_exit,
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
            self.early_exit,
        )

    @staticmethod
    def can_take_secant():
        return True

    def hub_priority(self, size):
        return 0 if size >= 6 else 1

    def _get_normalized_angles(
        self,
        diphthong_1: bool = False,
        diphthong_2: bool = False,
    ) -> Tuple[float, float]:
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

    def _get_normalized_angles_and_da(
        self,
        diphthong_1: bool,
        diphthong_2: bool,
        final_circle_diphthong: bool,
        initial_circle_diphthong: bool,
    ) -> Tuple[float, float, float]:
        a1, a2 = self._get_normalized_angles(diphthong_1, diphthong_2)
        if final_circle_diphthong:
            a2 = a1
        elif initial_circle_diphthong:
            a1 = a2
        return a1, a2, a2 - a1 or 360

    def get_da(self) -> float:
        return self._get_normalized_angles_and_da(False, False, False, False)[2]

    def _get_angle_to_overlap_point(
        self,
        a1: float,
        a2: float,
        *,
        is_entry: bool,
    ) -> float:
        assert self.overlap_angle is not None
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
    ) -> bool:
        a1, a2, da = self._get_normalized_angles_and_da(diphthong_1, diphthong_2, final_circle_diphthong, initial_circle_diphthong)
        r = int(RADIUS * size)
        beziers_needed = int(math.ceil(abs(da) / 90))
        bezier_arc = da / beziers_needed
        cp = r * (4 / 3) * math.tan(math.pi / (2 * beziers_needed * 360 / da))
        cp_distance = math.hypot(cp, r)
        cp_angle = math.asin(cp / cp_distance)
        p0 = _rect(r, math.radians(a1))
        if diphthong_2:
            entry = _rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (p0[0] + entry[0], p0[1] + entry[1])
            pen.moveTo(entry)
            pen.lineTo(p0)
        else:
            entry = p0
            pen.moveTo(entry)
        for i in range(1, beziers_needed + 1):
            theta0 = math.radians(a1 + (i - 1) * bezier_arc)
            p1 = _rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = _rect(r, theta3)
            p2 = _rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        if self.reversed_circle and not diphthong_1 and not diphthong_2:
            swash_angle = (360 - abs(da)) / 2
            swash_length = math.sin(math.radians(swash_angle)) * r / math.sin(math.radians(90 - swash_angle))
            swash_endpoint = _rect(abs(swash_length), math.radians(self.angle_out))
            swash_endpoint = (p3[0] + swash_endpoint[0], p3[1] + swash_endpoint[1])
            pen.lineTo(swash_endpoint)
            exit = _rect(min(r, abs(swash_length)), math.radians(self.angle_out))
            exit = (p3[0] + exit[0], p3[1] + exit[1])
        elif self.early_exit:
            # TODO: Track the precise output angle instead of assuming that the exit
            # should be halfway along the curve.
            exit = _rect(r, math.radians(a1 + da / 2))
        else:
            exit = p3
        if diphthong_1:
            exit_delta = _rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
        pen.endPath()
        relative_mark_angle = (a1 + a2) / 2
        anchor_name = mkmk if child else lambda a: a
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *_rect(r, math.radians(relative_mark_angle)))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *_rect(r, math.radians(relative_mark_angle)))
        else:
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = da / (max_tree_width + 2)
                if self.overlap_angle is None:
                    for child_index in range(max_tree_width):
                        glyph.addAnchorPoint(
                            anchors.CHILD_EDGES[int(child)][child_index],
                            base,
                            *_rect(r, math.radians(a1 + child_interval * (child_index + 2))),
                        )
                else:
                    overlap_exit_angle = self._get_angle_to_overlap_point(a1, a2, is_entry=False)
                    glyph.addAnchorPoint(
                        anchors.CHILD_EDGES[int(child)][0],
                        base,
                        *_rect(r, math.radians(overlap_exit_angle)),
                    )
                overlap_entry_angle = (a1 + child_interval
                    if self.overlap_angle is None
                    else self._get_angle_to_overlap_point(a1, a2, is_entry=True))
                if child:
                    glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', *_rect(r, math.radians(overlap_entry_angle)))
                else:
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', *_rect(r, math.radians(overlap_entry_angle)))
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', *_rect(r, math.radians(
                        a1 + child_interval * (max_tree_width + 1)
                            if self.overlap_angle is None
                            else overlap_exit_angle)))
                    glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
                    glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', *_rect(r, math.radians(overlap_entry_angle)))
                    if self.hub_priority(size) != -1:
                        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *_rect(r, math.radians(a1)))
                    if self.hub_priority(size) != 0:
                        glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
                    glyph.addAnchorPoint(
                        anchor_name(anchors.SECANT),
                        base,
                        *_rect(0, 0)
                            if abs(da) > 180
                            else _rect(r, math.radians(a1 + child_interval * (max_tree_width + 1))),
                    )
            glyph.addAnchorPoint(anchor_name(anchors.MIDDLE), base, *_rect(r, math.radians(relative_mark_angle)))
        if not anchor:
            if self.stretch:
                scale_x = 1.0
                scale_y = 1.0 + self.stretch
                if self.long:
                    scale_x, scale_y = scale_y, scale_x
                theta = self.relative_stretch and math.radians(self.angle_in % 180)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, *_rect(0, 0))
                glyph.transform(
                    fontTools.misc.transform.Identity
                        .rotate(theta)
                        .scale(scale_x, scale_y)
                        .rotate(-theta),
                )
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(scale_x * r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(self.angle_in)))
            else:
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base,
                    *(_rect(0, 0) if abs(da) > 180 else _rect(
                        min(stroke_width, r - (stroke_width / 2 + stroke_gap + light_line / 2)),
                        math.radians(relative_mark_angle))))
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(relative_mark_angle)))
        glyph.stroke('circular', stroke_width, 'round')
        if not anchor:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_gap)
            glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - stroke_gap)
        return False

    def can_be_child(self, size):
        a1, a2 = self._get_normalized_angles()
        return abs(a2 - a1) <= 180

    def max_tree_width(self, size):
        return 1

    def max_double_marks(self, size, joining_type, marks):
        if any(m.anchor == anchors.MIDDLE for m in marks):
            return 0
        a1, a2 = self._get_normalized_angles()
        return min(3, int(abs(a1 - a2) / 360 * size))

    def is_shadable(self):
        return True

    @staticmethod
    def in_degree_range(key: float, start: float, stop: float, clockwise: bool) -> bool:
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
        flips = 0

        candidate_clockwise: bool
        candidate_angle_in: float
        candidate_angle_out: float

        def flip() -> None:
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
            slight_overlap_offset = abs(a1 - a2) / 3 * (1 if candidate_clockwise else -1)
            if final_hook == (
                (abs(slight_overlap_offset) + abs(curve_offset) >= abs(a1 - a2)
                    and math.copysign(1, slight_overlap_offset) != math.copysign(1, curve_offset))
                or self.in_degree_range(
                    (angle_out + 180) % 360,
                    (candidate_angle_out + slight_overlap_offset) % 360,
                    (candidate_angle_in + curve_offset) % 360,
                    candidate_clockwise,
                )
            ):
                flip()
                flips += not final_hook
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
                flips += 1
        if context_in.diphthong_start or context_out.diphthong_end:
            candidate_angle_in = (candidate_angle_in - 180) % 360
            candidate_angle_out = (candidate_angle_out - 180) % 360
        would_flip = flips % 2 == 1 and context_in != NO_CONTEXT != context_out
        if would_flip:
            flip()
        return self.clone(
            angle_in=candidate_angle_in,
            angle_out=candidate_angle_out,
            clockwise=candidate_clockwise,
            would_flip=would_flip,
        )

    def context_in(self):
        return Context(self.angle_in, self.clockwise)

    def context_out(self):
        return Context(self.angle_out, self.clockwise)

    def calculate_diacritic_angles(self):
        halfway_angle = (self.angle_in + self.angle_out) / 2 % 180
        return {
            anchors.RELATIVE_1: halfway_angle,
            anchors.RELATIVE_2: halfway_angle,
            anchors.MIDDLE: (halfway_angle + 90) % 180,
            anchors.SECANT: self.angle_out % 180,
        }

    def reversed(self) -> Curve:
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
        angle_in: float,
        angle_out: float,
        *,
        clockwise: bool,
        reversed: bool = False,
        pinned: bool = False,
        stretch: float = 0,
        long: bool = False,
        role: CircleRole = CircleRole.INDEPENDENT,
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
        angle_in = self.angle_in
        angle_out = self.angle_out
        clockwise = self.clockwise
        if angle_in == angle_out >= 180:
            angle_in = (angle_in + 180) % 360
            angle_out = angle_in
            clockwise = not clockwise
        return f'''{
                int(angle_in)
            }{
                'n' if clockwise else 'p'
            }{
                int(angle_out)
            }{
                'r' if self.reversed and self.angle_in != self.angle_out else ''
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
    ) -> bool:
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
            return False
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
        entry = _rect(r, math.radians(a1))
        if diphthong_2:
            pen.moveTo(entry)
            entry_delta = _rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (entry[0] + entry_delta[0], entry[1] + entry_delta[1])
            pen.lineTo(entry)
            pen.endPath()
        pen.moveTo((0, r))
        pen.curveTo((cp, r), (r, cp), (r, 0))
        pen.curveTo((r, -cp), (cp, -r), (0, -r))
        pen.curveTo((-cp, -r), (-r, -cp), (-r, 0))
        pen.curveTo((-r, cp), (-cp, r), (0, r))
        pen.endPath()
        exit = _rect(r, math.radians(a2))
        if diphthong_1:
            pen.moveTo(exit)
            exit_delta = _rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
            pen.endPath()
        anchor_name = mkmk if child else lambda a: a
        base = 'basemark' if child else 'base'
        if joining_type != Type.NON_JOINING:
            if child:
                glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', 0, 0)
            else:
                glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', 0, 0)
                glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
                glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
                glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
                if self.hub_priority(size) != -1:
                    glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
                if self.hub_priority(size) != 0:
                    glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
                glyph.addAnchorPoint(anchor_name(anchors.SECANT), base, 0, 0)
        glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, *_rect(0, 0))
        if anchor:
            glyph.addAnchorPoint(anchors.MIDDLE, 'mark', 0, 0)
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
            glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(scale_x * r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians(angle_in)))
        else:
            glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(r + stroke_width / 2 + stroke_gap + light_line / 2, math.radians((a1 + a2) / 2)))
        glyph.stroke('circular', stroke_width, 'round')
        if diphthong_1 or diphthong_2:
            glyph.removeOverlap()
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_gap)
        glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - stroke_gap)
        return False

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
        is_reversed = self.reversed and self.role != CircleRole.LEADER
        clockwise_from_adjacent_curve = (
            context_in.clockwise
                if context_in.clockwise is not None
                else None
                if context_in.angle == context_out.angle
                else context_out.clockwise)

        clockwise: bool

        def flop() -> None:
            nonlocal clockwise
            nonlocal angle_in
            nonlocal angle_out
            if self.role == CircleRole.LEADER:
                clockwise = self.clockwise
            elif (context_in.ignorable_for_topography and (context_in.clockwise == clockwise) != context_in.diphthong_start
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
            clockwise = (clockwise_from_adjacent_curve != is_reversed
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
        clockwise = clockwise_ignoring_reversal != is_reversed
        flop()
        if angle_in == angle_out:
            clockwise = (clockwise_from_adjacent_curve != is_reversed
                if clockwise_from_adjacent_curve is not None
                else self.clockwise
            )
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_out,
                clockwise=clockwise,
            )
        if self.role != CircleRole.INDEPENDENT and (self.pinned or not is_reversed):
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_in if self.role == CircleRole.LEADER else angle_out,
                clockwise=clockwise,
            )
        elif clockwise_ignoring_reversal == clockwise_ignoring_curvature:
            if is_reversed:
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
            if is_reversed:
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

    def as_reversed(self) -> Circle:
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
            reversed=not self.reversed,
        )


_AnchorType = Union[Literal['base'], Literal['basemark'], Literal['entry'], Literal['exit'], Literal['ligature'], Literal['mark']]


_Instructions = Sequence[Union[Callable[[Context], Context], Union[Tuple[float, Shape], Tuple[float, Shape, bool]]]]


_Point = Tuple[float, float]


class Complex(Shape):
    def __init__(
        self,
        instructions: _Instructions,
        *,
        hook: bool = False,
        maximum_tree_width: int = 0,
        _final_rotation: float = 0,
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
        def __init__(self) -> None:
            self.anchor_points: collections.defaultdict[Tuple[str, _AnchorType], MutableSequence[_Point]] = collections.defaultdict(list)
            self.contour = fontforge.contour()

        def addAnchorPoint(
            self,
            anchor_class_name: str,
            anchor_type: _AnchorType,
            x: float,
            y: float,
        ) -> None:
            self.anchor_points[(anchor_class_name, anchor_type)].append((x, y))

        def stroke(self, *args) -> None:
            pass

        def boundingBox(self) -> Tuple[float, float, float, float]:
            return self.contour.boundingBox()

        def transform(self, matrix: Tuple[float, float, float, float, float, float], *args) -> None:
            for anchor, points in self.anchor_points.items():
                for i, x_y in enumerate(points):
                    new_point = fontforge.point(*x_y).transform(matrix)
                    self.anchor_points[anchor][i] = (new_point.x, new_point.y)
            self.contour.transform(matrix)

        def moveTo(self, x_y: _Point) -> None:
            if not self.contour:
                self.contour.moveTo(*x_y)

        def lineTo(self, x_y: _Point) -> None:
            self.contour.lineTo(*x_y)

        def curveTo(self, cp1: _Point, cp2: _Point, x_y: _Point) -> None:
            self.contour.cubicTo(cp1, cp2, x_y)

        def endPath(self) -> None:
            pass

        def removeOverlap(self) -> None:
            pass

        def get_crossing_point(self, component: Union[Curve, Circle]) -> _Point:
            entry_list = self.anchor_points[(anchors.CURSIVE, 'entry')]
            assert len(entry_list) == 1
            if component.angle_in == component.angle_out:
                return entry_list[0]
            exit_list = self.anchor_points[(anchors.CURSIVE, 'exit')]
            assert len(exit_list) == 1
            if isinstance(component, Circle):
                rel1_list = self.anchor_points[(anchors.RELATIVE_1, 'base')]
                assert len(rel1_list) == 1
                rel2_list = self.anchor_points[(anchors.RELATIVE_2, 'base')]
                assert len(rel2_list) == 1
                r = math.hypot(entry_list[0][1] - rel1_list[0][1], entry_list[0][0] - rel1_list[0][0])
                theta = math.atan2(rel2_list[0][1] - rel1_list[0][1], rel2_list[0][0] - rel1_list[0][0])
                return _rect(r, theta)
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

    def draw_to_proxy(
        self,
        pen: fontforge.glyphPen,
        stroke_width: float,
        light_line: bool,
        stroke_gap: float,
        size: float,
    ) -> Tuple[bool, collections.defaultdict[Tuple[str, _AnchorType], list[_Point]]]:
        first_is_invisible = None
        singular_anchor_points: collections.defaultdict[Tuple[str, _AnchorType], list[_Point]] = collections.defaultdict(list)
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
            this_entry_list = proxy.anchor_points[(anchors.CURSIVE, 'entry')]
            assert len(this_entry_list) == 1
            this_x, this_y = this_entry_list[0]
            if exit_list := singular_anchor_points.get((anchors.CURSIVE, 'exit')):
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
        assert first_is_invisible is not None
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    @staticmethod
    def _remove_bad_contours(glyph: fontforge.glyph) -> None:
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

    def enter_on_first_path(self) -> bool:
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
    ) -> bool:
        (
            first_is_invisible,
            singular_anchor_points,
        ) = self.draw_to_proxy(pen, stroke_width, light_line, stroke_gap, size)
        glyph.stroke('circular', stroke_width, 'round')
        glyph.removeOverlap()
        self._remove_bad_contours(glyph)
        if not (anchor or child or joining_type == Type.NON_JOINING):
            entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][0 if self.enter_on_first_path() else -1]
            exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][-1]
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
        anchor_name = mkmk if anchor or child else lambda a: a
        base = 'basemark' if anchor or child else 'base'
        if anchor is None:
            for (singular_anchor, type), points in singular_anchor_points.items():
                if singular_anchor in anchors.ALL_MARK or (
                    self.maximum_tree_width and (
                        singular_anchor == anchors.CONTINUING_OVERLAP
                        or any(map(lambda l: singular_anchor in l, anchors.CHILD_EDGES))
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
        if anchor == anchors.MIDDLE:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_center)
        elif anchor == anchors.ABOVE:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_min + stroke_width / 2)
        elif anchor == anchors.BELOW:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_max - stroke_width / 2)
        elif anchor is None:
            glyph.addAnchorPoint(anchors.MIDDLE, 'base', x_center, y_center)
            glyph.addAnchorPoint(anchors.ABOVE, 'base', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
            glyph.addAnchorPoint(anchors.BELOW, 'base', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
        return first_is_invisible

    def can_be_child(self, size):
        # TODO: return not callable(self.instructions[0]) and self.instructions[0][1].can_be_child(size)
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
                if forced_context.ignorable_for_topography:
                    forced_context = forced_context.clone(ignorable_for_topography=False)
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
                    actual_context = component.context_out() if initial_hook else component.context_in()
                    if forced_context.clockwise is None:
                        actual_context = actual_context.clone(clockwise=None)
                    assert actual_context == forced_context, f'{actual_context} != {forced_context}'
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
        continuing: bool,
        instructions: _Instructions,
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
    def __init__(
        self,
        angle: float,
        instructions: _Instructions,
    ):
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
        return Space(self.angle, margins=True)

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
        singular_anchor_points[(anchors.RELATIVE_1, 'base')] = singular_anchor_points[(anchors.CURSIVE, 'exit')]
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
        instructions: _Instructions,
        role: CircleRole = CircleRole.INDEPENDENT,
        _initial: bool = False,
        _isolated: bool = True,
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
    ) -> bool:
        drawer: Union[super, Complex]
        if self.role != CircleRole.LEADER or self._isolated:
            drawer = super()
        else:
            circle_op = self.instructions[2 if self._initial else 0]
            circle_path = circle_op[1]  # type: ignore[index]
            assert isinstance(circle_path, (Circle, Curve))
            clockwise = circle_path.clockwise
            curve_op = self.instructions[0 if self._initial else 2]
            curve_path = curve_op[1]  # type: ignore[index]
            assert isinstance(curve_path, Curve)
            curve_da = curve_path.angle_out - curve_path.angle_in
            if self._initial:
                angle_out = circle_path.angle_out
                intermediate_angle = (angle_out + curve_da) % 360
                instructions = [
                    (curve_op[0], curve_path.clone(  # type: ignore[index]
                        angle_in=angle_out,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (circle_op[0], Curve(  # type: ignore[index]
                        angle_in=intermediate_angle,
                        angle_out=angle_out,
                        clockwise=clockwise,
                    )),
                ]
            else:
                angle_in = circle_path.angle_in
                intermediate_angle = (angle_in - curve_da) % 360
                instructions = [
                    (circle_op[0], Curve(  # type: ignore[index]
                        angle_in=angle_in,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (curve_op[0], curve_path.clone(  # type: ignore[index]
                        angle_in=intermediate_angle,
                        angle_out=angle_in,
                        clockwise=clockwise,
                    )),
                ]
            drawer = Complex(instructions=instructions)
        drawer.draw(  # type: ignore[union-attr]
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
        return False

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

    def as_reversed(self) -> Ou:
        circle_path = self.instructions[0][1]  # type: ignore[index]
        curve_path = self.instructions[2][1]  # type: ignore[index]
        assert isinstance(circle_path, Circle)
        assert isinstance(curve_path, Curve)
        intermediate_angle = (circle_path.angle_in - circle_path.angle_out) % 360
        return self.clone(instructions=[
            (self.instructions[0][0], circle_path.clone(  # type: ignore[index]
                angle_in=(circle_path.angle_in + 180) % 360,
                angle_out=intermediate_angle,
                clockwise=not circle_path.clockwise,
            )),
            self.instructions[1],
            (self.instructions[2][0], curve_path.clone(  # type: ignore[index]
                angle_in=intermediate_angle,
                clockwise=not curve_path.clockwise,
            )),
        ])


class SeparateAffix(Complex):
    def __init__(
        self,
        instructions: _Instructions,
        *,
        low: bool = False,
        tight: bool = False,
    ):
        super().__init__(instructions)
        self.low = low
        self.tight = tight

    def clone(
        self,
        *,
        instructions=CLONE_DEFAULT,
        low=CLONE_DEFAULT,
        tight=CLONE_DEFAULT,
    ):
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            low=self.low if low is CLONE_DEFAULT else low,
            tight=self.tight if tight is CLONE_DEFAULT else tight,
        )

    def group(self):
        return (
            super().group(),
            self.low,
            self.tight,
        )

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
    ) -> bool:
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
            if anchor_class_name == anchors.CURSIVE:
                if type == 'entry':
                    entry = x, y
                elif type == 'exit':
                    exit = x, y
        glyph.anchorPoints = []
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        cursive_y = (y_max + 200 if self.low else y_min - 200)
        entry_x, exit_x = x_min, x_max
        if self.tight:
            entry_x, exit_x = exit_x, entry_x
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', entry_x, cursive_y)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', exit_x, cursive_y)
        return False

    def is_pseudo_cursive(self, size):
        return True

    def is_shadable(self):
        return False

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT


class Wa(Complex):
    def __init__(
        self,
        instructions: _Instructions,
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
        first_entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][0]
        last_entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][-1]
        if math.hypot(first_entry[0] - last_entry[0], first_entry[1] - last_entry[1]) >= 10:
            proxy = Complex.Proxy()
            # FIXME: Using the anchor points unmodified, FontForge gets stuck in
            # `font.generate`. If some but not all the points are offset by 0.01,
            # the stroking code produces buggy results for some glyphs.
            proxy.moveTo((first_entry[0], first_entry[1] + 0.01))
            proxy.lineTo((last_entry[0], last_entry[1] + 0.01))
            proxy.contour.draw(pen)
        first_exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][0]
        last_exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][-1]
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

    def as_reversed(self) -> Wa:
        return self.clone(
            instructions=[op if callable(op) else (op[0], op[1].as_reversed(), *op[2:]) for op in self.instructions],  # type: ignore[attr-defined]
        )


class Wi(Complex):
    def contextualize(self, context_in, context_out):
        if context_in != NO_CONTEXT or context_out == NO_CONTEXT:
            curve_index = next(i for i, op in enumerate(self.instructions) if not callable(op) and not isinstance(op[1], Circle))
            if curve_index == 1:
                return super().contextualize(context_in, context_out)
            curve_path = self.clone(instructions=self.instructions[curve_index - 1:]).contextualize(context_in, context_out)
            circle_path = self.instructions[0][1].clone(
                angle_in=curve_path.instructions[1][1].angle_in,
                angle_out=curve_path.instructions[1][1].angle_in,
                clockwise=curve_path.instructions[1][1].clockwise,
            )
            return self.clone(instructions=[(self.instructions[0][0], circle_path), *curve_path.instructions])
        if Curve.in_degree_range(
            context_out.angle,
            self.instructions[-1][1].angle_out,
            (self.instructions[-1][1].angle_out + 180 - EPSILON * (-1 if self.instructions[-1][1].clockwise else 1)) % 360,
            self.instructions[-1][1].clockwise,
        ):
            return self.as_reversed()
        return self

    def as_reversed(self) -> Wi:
        first_callable = True
        return self.clone(
            instructions=[
                ((lambda op: (lambda c: (lambda c0: c0.clone(clockwise=not c0.clockwise))(op(c))))(op)
                        if (first_callable | (first_callable := False))
                        else op
                    )
                    if callable(op)
                    else (
                        op[0],
                        op[1].clone(
                                angle_in=(op[1].angle_in + 180) % 360,
                                angle_out=(op[1].angle_out + 180) % 360,
                                clockwise=not op[1].clockwise,
                            ) if isinstance(op[1], (Circle, Curve))
                            else op[1],
                        *op[2:],
                    ) for op in self.instructions
            ],
        )


class TangentHook(Complex):
    def __init__(
        self,
        instructions: _Instructions,
        *,
        _initial: bool = False,
    ):
        while callable(instructions[0]):
            instructions = instructions[1:]
        super().__init__([self.override_initial_context if _initial else self.override_noninitial_context, *instructions], hook=True)
        self._initial = _initial

    @staticmethod
    def override_noninitial_context(c: Context) -> Context:
        assert c.angle is not None
        return Context(
            None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360,
            not (90 < c.angle < 315),
        )

    @staticmethod
    def override_initial_context(c: Context) -> Context:
        assert c.angle is not None
        return Context(
            None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360,
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
    ) -> bool:
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
            if anchor_class_name == anchors.CURSIVE:
                if type == 'entry':
                    entry = x, y
                elif type == 'exit':
                    exit = x, y
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != anchors.CURSIVE]
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_avg = (x_min + x_max) / 2
        y_avg = (y_min + y_max) / 2
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', x_avg, y_avg)
        return False

    def is_pseudo_cursive(self, size):
        return True

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT
