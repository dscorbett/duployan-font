# Copyright 2018-2019, 2022-2024 David Corbett
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


__all__ = ['Builder']


import collections
from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from collections.abc import Sequence
from collections.abc import Set
import io
import math
from typing import Final
from typing import TYPE_CHECKING
from typing import cast
import unicodedata


import fontforge
import fontTools.agl
import fontTools.feaLib.ast
import fontTools.feaLib.builder
import fontTools.feaLib.parser
import fontTools.misc.transform
import fontTools.otlLib.builder
import fontTools.ttLib.ttFont


import anchors
from phases import Lookup
import phases.main
import phases.marker
import phases.middle
from schema import Ignorability
from schema import NO_PHASE_INDEX
from schema import Schema
from shapes import Bound
from shapes import Circle
from shapes import Complex
from shapes import Curve
from shapes import Dot
from shapes import Instructions
from shapes import InvalidDTLS
from shapes import InvalidOverlap
from shapes import InvalidStep
from shapes import LINE_FACTOR
from shapes import Line
from shapes import Notdef
from shapes import Ou
from shapes import RADIUS
from shapes import RomanianU
from shapes import SeparateAffix
from shapes import Space
from shapes import StretchAxis
from shapes import TangentHook
from shapes import Wa
from shapes import Wi
from shapes import XShape
import sifting
from utils import BRACKET_DEPTH
from utils import BRACKET_HEIGHT
from utils import CAP_HEIGHT
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import FULL_FONT_CODE_POINTS
from utils import GlyphClass
from utils import KNOWN_SCRIPTS
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import MINIMUM_STROKE_GAP
from utils import NO_CONTEXT
from utils import PrefixView
from utils import REGULAR_LIGHT_LINE
from utils import SHADING_FACTOR
from utils import SMALL_DIGIT_FACTOR
from utils import SUBSCRIPT_DEPTH
from utils import SUPERSCRIPT_HEIGHT
from utils import Type
from utils import X_HEIGHT
from utils import mkmk


if TYPE_CHECKING:
    from phases import Phase


def rename_schemas(grouper: sifting.Grouper[Schema], phase_index: int) -> None:
    for group in grouper.groups():
        if all(s.phase_index < phase_index for s in group):
            continue
        group.sort(key=Schema.sort_key)
        canonical_schema = next((s for s in group if s.phase_index < phase_index), None)
        if canonical_schema is None:
            canonical_schema = group[0]
        for schema in list(group):
            if schema.phase_index >= phase_index:
                schema.canonical_schema = canonical_schema
                if grouper.group_of(schema):
                    grouper.remove_item(group, schema)


class Builder:
    def __init__(self, font: fontforge.font, bold: bool, noto: bool) -> None:
        self.font: Final = font
        self._fea: Final = fontTools.feaLib.ast.FeatureFile()
        self._anchors: Final[MutableMapping[str, fontTools.feaLib.ast.LookupBlock]] = {}
        self._initialize_phases(noto)
        self.light_line: Final = 101 if bold else REGULAR_LIGHT_LINE
        self.shaded_line: Final = SHADING_FACTOR * self.light_line
        self.stroke_gap: Final = max(MINIMUM_STROKE_GAP, self.light_line)
        code_points: Final[collections.defaultdict[int, int]] = collections.defaultdict(int)
        self._initialize_schemas(noto, self.light_line, self.stroke_gap)
        for schema in self._schemas:
            if schema.cmap is not None:
                code_points[schema.cmap] += 1
        duplicate_code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not duplicate_code_points, ('Duplicate code points:\n    '
            + '\n    '.join(map(hex, sorted(duplicate_code_points.keys()))))

    def _initialize_phases(self, noto: bool) -> None:
        self._phases = phases.main.PHASE_LIST
        if noto:
            self._phases = [p for p in self._phases if p is not phases.main.reversed_circle_kludge]
        self._middle_phases = phases.middle.PHASE_LIST
        self._marker_phases = phases.marker.PHASE_LIST

    def _initialize_schemas(self, noto: bool, light_line: float, stroke_gap: float) -> None:
        notdef = Notdef()
        space = Space(0, margins=True)
        h = Dot()
        exclamation = Complex([(0, h), (188, Space(90)), (1.109, Line(90))])
        inverted_exclamation = Complex([exclamation.instructions[0], (exclamation.instructions[1][0], exclamation.instructions[1][1].clone(angle=(exclamation.instructions[1][1].angle + 180) % 360)), (exclamation.instructions[2][0], exclamation.instructions[2][1].as_reversed())])  # type: ignore[call-arg, index, union-attr]
        dollar = Complex([(2.58, Curve(173.935, 189.062, clockwise=False, stretch=2.058, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (2.88, Curve(198.012, 354.647, clockwise=False, stretch=0.5, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0.098964, Line(354.647)), (2.88, Curve(354.647, 198.012, clockwise=True, stretch=0.5, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (2.58, Curve(189.062, 173.935, clockwise=True, stretch=2.058, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0, Space(0), True, True), (151.739, Space(328.952)), (1.484, Line(90)), (140, Space(0)), (1.484, Line(270))])
        percent = Complex([(2.3, Curve(326.31, 326.31, clockwise=True, stretch=0.078125, stretch_axis=StretchAxis.ABSOLUTE)), (2.3, Curve(326.31, 45, clockwise=False, stretch=0.7, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (1.463514, Line(240)), (2.3, Curve(45, 326.31, clockwise=True, stretch=0.7, long=True, stretch_axis=StretchAxis.ABSOLUTE), True), (2.3, Curve(326.31, 326.31, clockwise=False, stretch=0.078125, stretch_axis=StretchAxis.ABSOLUTE)),
        ])
        parenthesis_angle = 62.68
        left_parenthesis = Complex([(1, Curve(180 + parenthesis_angle, 360 - parenthesis_angle, clockwise=False))])
        right_parenthesis = Complex([(1, Curve(parenthesis_angle, 180 - parenthesis_angle, clockwise=False))])
        asterisk = Complex([(0.467, Line(270), True), (0.467, Line(90)), (0.467, Line(198)), (0.467, Line(18), True), (0.467, Line(126)), (0.467, Line(306), True), (0.467, Line(54)), (0.467, Line(234), True), (0.467, Line(342)), (0.467, Line(162), True)])
        asterism = Complex([*asterisk.instructions, (1.2, Line(60), True), *asterisk.instructions, (1.2, Line(300), True), *asterisk.instructions])
        plus = Complex([(0.828, Line(90)), (0.414, Line(270)), (0.414, Line(180)), (0.828, Line(0))])
        comma = Complex([(0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True), False, True)])
        turned_comma = Complex([(3, Curve(221, 281, clockwise=False)), (0.5, Circle(281, 281, clockwise=False))])
        slash = Line(60)
        zero = Circle(180, 180, clockwise=False, stretch=132 / 193, long=True)
        one = Complex([(1.288, Line(90)), (0.416, Line(218))])
        two = Complex([(3.528, Curve(42, 29.203, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(29.203, 231.189, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232)), (0.7, Line(0))])
        three = Complex([(3, Curve(36, 4.807, clockwise=True, stretch=0.2, long=True)), (3, Curve(4.807, 180, clockwise=True, stretch=0.2, long=True)), (0.15, Line(180)), (0.15, Line(0)), (3.36, Curve(0, 180, clockwise=True, stretch=0.375, long=True)), (3.42, Curve(180, 166.464, clockwise=True, stretch=0.937, long=True))])
        four = Complex([(1.296, Line(90)), (1.173, Line(235)), (0.922, Line(0))])
        five = Complex([(3.72, Curve(330, 0, clockwise=False, stretch=0.196, long=True)), (3.72, Curve(0, 180, clockwise=False, stretch=13 / 93, long=True)), (3.72, Curve(180, 205.768, clockwise=False, stretch=0.196, long=True)), (0.565, Line(86.145)), (0.572, Line(0))])
        six = Complex([(3.88, Circle(90, 90, clockwise=True)), (19.5, Curve(90, 61.5, clockwise=True, stretch=0.45)), (4, Curve(61.5, 355, clockwise=True))])
        seven = Complex([(0.818, Line(0)), (1.36, Line(246))])
        eight = Complex([(2.88, Curve(180, 90, clockwise=True)), (2.88, Curve(90, 270, clockwise=True)), (2.88, Curve(270, 180, clockwise=True)), (3.16, Curve(180, 270, clockwise=False)), (3.16, Curve(270, 90, clockwise=False)), (3.16, Curve(90, 180, clockwise=False))])
        nine = Complex([(3.5, Circle(270, 270, clockwise=True)), (35.1, Curve(270, 255.658, clockwise=True, stretch=0.45)), (4, Curve(255.658, 175, clockwise=True))])
        colon = Complex([(0, h), (X_HEIGHT - light_line * Dot.SCALAR ** h.size_exponent, Space(90)), (0, h)])
        semicolon = Complex([*comma.instructions, *[op if callable(op) else (op.size, op.shape.as_reversed(), True) for op in reversed(comma.instructions)], (comma.instructions[0].size, Circle(comma.instructions[0].shape.as_reversed().angle_out, 180, clockwise=False), True), (-(comma.instructions[0].size * RADIUS * 2 + light_line / 2) + light_line * Dot.SCALAR ** h.size_exponent / 2 + colon.instructions[1].size, colon.instructions[1].shape), (0, h)])  # type: ignore[attr-defined, list-item, union-attr]
        question = Complex([(0, h), (188, Space(90)), (4.162, Curve(90, 45, clockwise=True)), (0.16, Line(45)), (4.013, Curve(45, 210, clockwise=False))])
        inverted_question = Complex([question.instructions[0], (question.instructions[1][0], question.instructions[1][1].clone(angle=(question.instructions[1][1].angle + 180) % 360)), (question.instructions[2][0], question.instructions[2][1].clone(angle_in=(question.instructions[2][1].angle_in + 180) % 360, angle_out=(question.instructions[2][1].angle_out + 180) % 360)), (question.instructions[3][0], question.instructions[3][1].as_reversed()), (question.instructions[4][0], question.instructions[4][1].clone(angle_in=(question.instructions[4][1].angle_in + 180) % 360, angle_out=(question.instructions[4][1].angle_out + 180) % 360))])  # type: ignore[call-arg, index, union-attr]
        less_than = Complex([(1, Line(153)), (1, Line(27))])
        equal = Complex([(305, Space(90)), (1, Line(0)), (180, Space(90)), (1, Line(180)), (90, Space(270)), (1, Line(0), True)], maximum_tree_width=1)
        greater_than = Complex([(1, Line(27)), (1, Line(153))])
        left_bracket = Complex([(0.45, Line(180)), (2.059, Line(90)), (0.45, Line(0))])
        right_bracket = Complex([(0.45, Line(0)), (2.059, Line(90)), (0.45, Line(180))])
        left_ceiling = Complex([(2.059, Line(90)), (0.45, Line(0))])
        right_ceiling = Complex([(2.059, Line(90)), (0.45, Line(180))])
        left_floor = Complex([(0.45, Line(180)), (2.059, Line(90))])
        right_floor = Complex([(0.45, Line(0)), (2.059, Line(90))])
        upper_left_brace_section = Complex([(1, Curve(185.089, 288, clockwise=False, stretch=0.3, long=True, stretch_axis=StretchAxis.ANGLE_OUT)), (1, Curve(288, 185.089, clockwise=True, stretch=0.3, long=True))])
        lower_left_brace_section = Complex([(upper_left_brace_section.instructions[1][0], upper_left_brace_section.instructions[1][1].clone(angle_in=(180 - upper_left_brace_section.instructions[1][1].angle_out) % 360, angle_out=(180 - upper_left_brace_section.instructions[1][1].angle_in) % 360, stretch_axis=StretchAxis.ANGLE_OUT)), (upper_left_brace_section.instructions[0][0], upper_left_brace_section.instructions[0][1].clone(angle_in=(180 - upper_left_brace_section.instructions[0][1].angle_out) % 360, angle_out=(180 - upper_left_brace_section.instructions[0][1].angle_in) % 360, stretch_axis=StretchAxis.ANGLE_IN))])  # type: ignore[call-arg, index, union-attr]
        left_brace = Complex([*upper_left_brace_section.instructions, *lower_left_brace_section.instructions])
        upper_right_brace_section = Complex([(upper_left_brace_section.instructions[0][0], upper_left_brace_section.instructions[0][1].clone(angle_in=(180 - upper_left_brace_section.instructions[0][1].angle_in) % 360, angle_out=(180 - upper_left_brace_section.instructions[0][1].angle_out) % 360, clockwise=not upper_left_brace_section.instructions[0][1].clockwise)), (upper_left_brace_section.instructions[1][0], upper_left_brace_section.instructions[1][1].clone(angle_in=(180 - upper_left_brace_section.instructions[1][1].angle_in) % 360, angle_out=(180 - upper_left_brace_section.instructions[1][1].angle_out) % 360, clockwise=not upper_left_brace_section.instructions[1][1].clockwise))])  # type: ignore[call-arg, index, union-attr]
        lower_right_brace_section = Complex([(lower_left_brace_section.instructions[0][0], lower_left_brace_section.instructions[0][1].clone(angle_in=(180 - lower_left_brace_section.instructions[0][1].angle_in) % 360, angle_out=(180 - lower_left_brace_section.instructions[0][1].angle_out) % 360, clockwise=not lower_left_brace_section.instructions[0][1].clockwise)), (lower_left_brace_section.instructions[1][0], lower_left_brace_section.instructions[1][1].clone(angle_in=(180 - lower_left_brace_section.instructions[1][1].angle_in) % 360, angle_out=(180 - lower_left_brace_section.instructions[1][1].angle_out) % 360, clockwise=not lower_left_brace_section.instructions[1][1].clockwise))])  # type: ignore[call-arg, index, union-attr]
        right_brace = Complex([*upper_right_brace_section.instructions, *lower_right_brace_section.instructions])
        cent = Complex([(2.4, Curve(135, 225, clockwise=False, stretch=0.2, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (2.4, Curve(225, 315, clockwise=False, stretch=0.771, stretch_axis=StretchAxis.ABSOLUTE)), (2.4, Curve(315, 45, clockwise=False, stretch=0.2, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (2.4, Curve(225, 175, clockwise=True, stretch=0.2, long=True, stretch_axis=StretchAxis.ABSOLUTE), True), (0, Space(0), True, True), (0.156, Line(270)), (2 * 0.156 + 0.905, Line(90))])
        pound = Complex([(0.4, Curve(49, 180 - 10, clockwise=False, stretch=0.3, long=True, stretch_axis=StretchAxis.ANGLE_OUT)), (1, Curve(180 - 10, 180 + 10, clockwise=False, stretch=0.2, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (1, Curve(180 + 10, 270 + 10, clockwise=False, stretch=0.3, long=True, stretch_axis=StretchAxis.ANGLE_OUT)), (0.075, Line(270 + 10)), (0.07, Line(180), True), (0.18, Line(0)), (0.11, Line(180), True), (0.075, Line(270 + 10)), (2, Curve(270 + 10, 270 - 32, clockwise=True)), (0.4, Curve(270 - 32, 360 - 25, clockwise=True)), (0.15, Line(360 - 25)), (1, Curve(360 - 25, 41, clockwise=False))])
        guillemet_y_min = 40
        guillemet_horizontal_space = (200, Space(0))
        left_guillemet = [(0.524, Line(129.89)), (0.524, Line(50.11))]
        right_guillemet = [*reversed(left_guillemet)]
        left_guillemet += [(op[0], op[1].as_reversed(), True) for op in left_guillemet]  # type: ignore[misc]
        right_guillemet += [(op[0], op[1].as_reversed(), True) for op in right_guillemet]  # type: ignore[misc]
        left_double_guillemet = Complex([*left_guillemet, guillemet_horizontal_space, *left_guillemet])
        right_double_guillemet = Complex([*right_guillemet, guillemet_horizontal_space, *right_guillemet])
        left_single_guillemet = Complex(left_guillemet)
        right_single_guillemet = Complex(right_guillemet)
        circle = Circle(180, 180, clockwise=False)
        masculine_ordinal_indicator = Complex([(2.3, Circle(180, 180, clockwise=False, stretch=0.078125, long=True)), (370, Space(270)), (105, Space(180)), (0.42, Line(0))])
        multiplication = Complex([(1, Line(315)), (0.5, Line(135), True), (0.5, Line(225), True), (1, Line(45)), (0.5, Line(225), True)])
        reference_mark = Complex([*multiplication.instructions, (0.3, Line(0), True), (0, h), (0.3 * 2, Line(180), True), (0, h), (0.3, Line(0), True), (0.3, Line(90), True), (0, h), (0.3 * 2, Line(270), True), (0, h)])
        grave = Line(150)
        acute = Line(45)
        circumflex = Complex([(1, Line(25)), (1, Line(335))])
        macron = Line(0)
        breve = Curve(270, 90, clockwise=False, stretch=0.2)
        diaeresis = Complex([(0, h), (Dot.SCALAR * 10 / 7 * light_line, Space(0)), (0, h)])
        caron = Complex([(1, Line(335)), (1, Line(25))])
        vertical_line = Line(90)
        left_half_ring = Curve(180, 0, clockwise=False, stretch=0.2)
        inverted_breve = Curve(90, 270, clockwise=False, stretch=0.2)
        right_half_ring = Curve(0, 180, clockwise=False, stretch=0.2)
        en_dash = Complex([(395, Space(90)), (1, Line(0))])
        left_quote = Complex([*turned_comma.instructions, (160, Space(0)), (0.5, Circle(101, 101, clockwise=True)), (3, Curve(101, 41, clockwise=True))])
        right_quote = Complex([*comma.instructions, (160, Space(0)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        ellipsis = Complex([(0, h), (196, Space(0)), (0, h), (196, Space(0)), (0, h)])
        nnbsp = Space(0)
        prime = Line(240)
        double_prime = Complex([(1, prime), (274, Space(0)), (1, prime.as_reversed())])
        tricolon = Complex([(0, h), (322, Space(90)), (0, h), (322, Space(90)), (0, h)])
        dotted_circle = Complex([(0, Dot(0)), (446, Space(90)), (0, Dot(0)), (223, Space(270)), (223, Space(60)), (0, Dot(0)), (446, Space(240)), (0, Dot(0)), (223, Space(60)), (223, Space(30)), (0, Dot(0)), (446, Space(210)), (0, Dot(0)), (223, Space(30)), (223, Space(0)), (0, Dot(0)), (446, Space(180)), (0, Dot(0)), (223, Space(0)), (223, Space(330)), (0, Dot(0)), (446, Space(150)), (0, Dot(0)), (223, Space(330)), (223, Space(300)), (0, Dot(0)), (446, Space(120)), (0, Dot(0))])
        skull_and_crossbones = Complex([ (7, Circle(180, 180, clockwise=False, stretch=0.4, long=True)), (7 * 2 * 1.4 * RADIUS * 99 / 172, Space(270)), (0, Dot(1.3561)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(120)), (0, Dot(1.3561)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(0)), (0, Dot(1.3561)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(240)), (7 * 2 * 1.4 * RADIUS * 59 / 215 - 42, Space(270)), (0, Dot(0)), (150, Space(160)), (0, Dot(0)), (150, Space(340)), (150, Space(20)), (0, Dot(0)), (150, Space(200)), (7 * 2 * 1.4 * RADIUS / 2 + 42, Space(270)), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), True), (2.1, Curve(60, 90, clockwise=False), True), (2.1, Curve(270, 210, clockwise=True)), (2.1, Curve(30, 60, clockwise=False), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(330)), (2.1, Curve(60, 30, clockwise=True), True), (2.1, Curve(210, 270, clockwise=False)), (2.1, Curve(90, 60, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(30), True), (2.1, Curve(120, 90, clockwise=True)), (2.1, Curve(270, 330, clockwise=False)), (2.1, Curve(150, 120, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(210)), (2.1, Curve(120, 150, clockwise=False), True), (2.1, Curve(330, 270, clockwise=True)), (2.1, Curve(90, 120, clockwise=False), True)])
        earth = Complex([(2.72, Circle(180, 180, clockwise=False)), (0.476, Line(90)), (0.213, Line(270), True), (0.213, Line(180), True), (0.426, Line(0))])
        stenographic_period = Complex([(0.5, Line(135), True), *multiplication.instructions])
        double_hyphen = Complex([(0.5, Line(0)), (179, Space(90)), (0.5, Line(180))])
        bound = Bound()
        cross_knob_line_factor = 0.42
        cross_knob_op = (0, Dot(3.64))
        cross_pommy = Complex([cross_knob_op, (3 + 2 * cross_knob_line_factor, Line(270)), cross_knob_op, (2 + cross_knob_line_factor, Line(90), True), (1 + cross_knob_line_factor, Line(180), True), cross_knob_op, (2 + 2 * cross_knob_line_factor, Line(0)), cross_knob_op])
        cross = Complex([(3, Line(270)), (2, Line(90), True), (1, Line(180), True), (2, Line(0))])
        converging_lines = Complex([(2.72, Line(9 + 180)), (2.72, Line(360 - 9))])
        sacred_heart = Complex([(10.584, Curve(38.184, 25, clockwise=True, stretch=0.346, long=True, stretch_axis=StretchAxis.ANGLE_OUT)), (10.584, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (2.712, Line(232)), (2.712, Line(128)), (10.584, Curve(128, 335, clockwise=True, stretch=0.036, long=True, stretch_axis=StretchAxis.ANGLE_OUT)), (10.584, Curve(335, 321.816, clockwise=True, stretch=0.346, long=True)), (2.5, Space(0)), (cross.instructions[0][0], cross.instructions[0][1].as_reversed(), True), *cross.instructions])  # type: ignore[index, union-attr]
        parenthesis_stroke_size = 8
        parenthesis_stroke: Instructions = [(parenthesis_stroke_size / 2, Line(180), True), (parenthesis_stroke_size, Line(0)), (parenthesis_stroke_size / 2, Line(180), True)]
        parenthesis_with_stroke_size = 431
        left_parenthesis_with_stroke = Complex([(parenthesis_with_stroke_size, Curve(180 + parenthesis_angle, 270, clockwise=False)), *parenthesis_stroke, (parenthesis_with_stroke_size, Curve(270, 360 - parenthesis_angle, clockwise=False))])
        right_parenthesis_with_stroke = Complex([(parenthesis_with_stroke_size, Curve(parenthesis_angle, 90, clockwise=False)), *parenthesis_stroke, (parenthesis_with_stroke_size, Curve(90, 180 - parenthesis_angle, clockwise=False))])
        parenthesis_stroke_gap = 4.33
        parenthesis_double_stroke = [(parenthesis_stroke_gap / 2, Line(90), True), *parenthesis_stroke, (parenthesis_stroke_gap, Line(270), True), *parenthesis_stroke, (parenthesis_stroke_gap / 2, Line(90), True)]
        left_parenthesis_with_double_stroke = Complex([(parenthesis_with_stroke_size, Curve(180 + parenthesis_angle, 270, clockwise=False)), *parenthesis_double_stroke, (parenthesis_with_stroke_size, Curve(270, 360 - parenthesis_angle, clockwise=False))])
        right_parenthesis_with_double_stroke = Complex([(parenthesis_with_stroke_size, Curve(parenthesis_angle, 90, clockwise=False)), *parenthesis_double_stroke, (parenthesis_with_stroke_size, Curve(90, 180 - parenthesis_angle, clockwise=False))])
        stenographic_semicolon = Complex([*semicolon.instructions[:-1], *[op if callable(op) else (0.5 * op[0], *op[1:]) for op in stenographic_period.instructions]])  # type: ignore[list-item]
        x = XShape([(2, Curve(30, 130, clockwise=False)), (2, Curve(130, 30, clockwise=True))])
        p = Line(270, stretchy=True)
        p_reverse = Line(90, stretchy=True)
        t = Line(0, stretchy=True)
        t_reverse = Line(180, stretchy=True)
        f = Line(300, stretchy=True)
        f_reverse = Line(120, stretchy=True)
        k = Line(240, stretchy=True)
        k_reverse = Line(60, stretchy=True)
        l = Line(45, stretchy=True)
        l_reverse = Line(225, stretchy=True)
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
        o_reverse = o.as_reversed()
        ie = Curve(180, 0, clockwise=False)
        short_i = Curve(0, 180, clockwise=True)
        ui = Curve(90, 270, clockwise=True)
        ee = Curve(270, 90, clockwise=False, secondary=True)
        ye = Complex([(0.47, Line(0, minor=True)), (0.385, Line(242)), (0.47, t), (0.385, Line(242)), (0.47, t), (0.385, Line(242)), (0.47, t)])
        u_n = Curve(90, 180, clockwise=True)
        long_u = Curve(225, 45, clockwise=False, stretch=4, long=True)
        romanian_u = RomanianU([(1, Curve(180, 0, clockwise=False)), lambda c: c, (0.5, Curve(0, 180, clockwise=False))], hook=True)
        uh = Circle(45, 45, clockwise=False, reversed=False, stretch=2)
        ou = Ou([(1, Circle(180, 145, clockwise=False)), lambda c: c, (5 / 9, Curve(145, 270, clockwise=False))])
        wa = Wa([(4, Circle(180, 180, clockwise=False)), (2, Circle(180, 180, clockwise=False))])
        wo = Wa([(4, Circle(180, 180, clockwise=False)), (2.5, Circle(180, 180, clockwise=False))])
        wi = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (5 / 3, m)])
        wei = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (1, m), lambda c: c.clone(clockwise=not c.clockwise), (1, n)])
        left_horizontal_secant = Line(0, secant=2 / 3)
        mid_horizontal_secant = Line(0, secant=0.5)
        right_horizontal_secant = Line(0, secant=1 / 3)
        low_vertical_secant = Line(90, secant=2 / 3)
        mid_vertical_secant = Line(90, secant=0.5)
        high_vertical_secant = Line(90, secant=1 / 3)
        rtl_secant = Line(240, secant=0.5, secant_curvature_offset=55)
        ltr_secant = Line(310, secant=0.5, secant_curvature_offset=55)
        tangent = Complex([lambda c: Context(None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360), (0.25, Line(270), True), lambda c: Context((cast(float, c.angle) + 180) % 360), (0.5, Line(90))], hook=True)
        e_hook = Curve(90, 270, clockwise=True, hook=True)
        i_hook = Curve(180, 0, clockwise=False, hook=True)
        tangent_hook = TangentHook([(1, Curve(180, 270, clockwise=False)), Context.as_reversed, (1, Curve(90, 270, clockwise=True))])
        high_acute = SeparateAffix([(0.5, Line(45))])
        high_tight_acute = SeparateAffix([(0.5, Line(45))], tight=True)
        high_grave = SeparateAffix([(0.5, Line(315))])
        high_long_grave = SeparateAffix([(0.4, Line(300)), (0.75, Line(0))])
        high_dot = SeparateAffix([(0, h)])
        high_circle = SeparateAffix([(2, Circle(0, 0, clockwise=False))])
        high_line = SeparateAffix([(0.5, Line(0))])
        high_wave = SeparateAffix([(2, Curve(90, 315, clockwise=True)), (RADIUS * math.sqrt(2) / LINE_FACTOR, Line(315)), (2, Curve(315, 90, clockwise=False))])
        high_vertical = SeparateAffix([(0.5, Line(90))])
        low_acute = high_acute.clone(low=True)
        low_tight_acute = high_tight_acute.clone(low=True)
        low_grave = high_grave.clone(low=True)
        low_long_grave = high_long_grave.clone(low=True)
        low_dot = high_dot.clone(low=True)
        low_circle = high_circle.clone(low=True)
        low_line = high_line.clone(low=True)
        low_wave = high_wave.clone(low=True)
        low_vertical = high_vertical.clone(low=True)
        low_arrow = SeparateAffix([(0.4, Line(0)), (0.4, Line(240))], low=True)
        likalisti = Complex([(5, Circle(0, 0, clockwise=False)), (375, Space(90)), (0.5, p), (math.hypot(125, 125), Space(135)), (0.5, Line(0))])
        dotted_square_y_min = -187
        dotted_square = [(0.26 - light_line / 1000, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.26 - light_line / 1000, Line(90)), (0.26 - light_line / 1000, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.26 - light_line / 1000, Line(0)), (0.26 - light_line / 1000, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.26 - light_line / 1000, Line(270)), (0.26 - light_line / 1000, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.26 - light_line / 1000, Line(180))]
        dtls = InvalidDTLS(instructions=[*dotted_square, (341, Space(0)), (173, Space(90)), (0.238, Line(180)), (0.412, Line(90)), (130, Space(90)), (0.412, Line(90)), (0.18, Line(0)), (2.06, Curve(0, 180, clockwise=True, stretch=-27 / 115, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0.18, Line(180)), (369, Space(0)), (0.412, Line(90)), (0.148, Line(180), True), (0.296, Line(0)), (341, Space(270)), (14.5, Space(180)), (0.345 * 2.58, Curve(174.6430998400853, 185.3569001599147, clockwise=False, stretch=2.058, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0.345 * 2.88, Curve(192.9199090407727, 344.59913727986964, clockwise=False, stretch=0.25, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0.345 * 0.224, Line(341)), (0.345 * 2.88, Curve(344.59913727986964, 192.9199090407727, clockwise=True, stretch=0.25, long=True, stretch_axis=StretchAxis.ABSOLUTE)), (0.345 * 2.58, Curve(185.3569001599147, 174.6430998400853, clockwise=True, stretch=2.058, long=True, stretch_axis=StretchAxis.ABSOLUTE))])
        chinook_period_y_min = 65
        chinook_period = Complex([(1, Line(0)), (179, Space(90)), (1, Line(180))])
        chinook_period_double_stroke = Complex([*chinook_period.instructions, (chinook_period.instructions[-1][0] / 2, Line(0), True, True), (chinook_period.instructions[-2][0] / 2, Space(270)), (chinook_period.instructions[-2][0] * 0.9 / 2, Space(180)), (chinook_period.instructions[-1][0] * 1.1 / 2, Line(64), True), (chinook_period.instructions[-1][0] * 1.1, Line(64 + 180)), (chinook_period.instructions[-2][0] * 0.9, Space(0)), (chinook_period.instructions[-1][0] * 1.1, Line(64))])  # type: ignore[index]
        overlap = InvalidOverlap(continuing=False, instructions=[*dotted_square, (162.5, Space(0)), (397, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (1.134, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220)), (170, Space(180)), (0.4116, Line(90))])
        continuing_overlap = InvalidOverlap(continuing=True, instructions=[*dotted_square, (189, Space(0)), (522, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (0.726, Line(0)), (124, Space(180)), (145, Space(90)), (0.852, Line(270)), (0.552, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220))])
        down_step = InvalidStep(270, [*dotted_square, (444, Space(0)), (749, Space(90)), (1.184, Line(270)), (0.32, Line(130)), (0.32, Line(310), True), (0.32, Line(50))])
        up_step = InvalidStep(90, [*dotted_square, (444, Space(0)), (157, Space(90)), (1.184, Line(90)), (0.32, Line(230)), (0.32, Line(50), True), (0.32, Line(310))])
        line = Line(0)

        enclosing_circle = Schema(None, circle, 10, anchor=anchors.MIDDLE)
        small_dot_1 = Schema(None, Dot(0), 0, anchor=anchors.RELATIVE_1)
        dot_1 = Schema(None, h, 0, anchor=anchors.RELATIVE_1)
        dot_2 = Schema(None, h, 0, anchor=anchors.RELATIVE_2)
        line_2 = Schema(None, line, 0.35, Type.ORIENTING, anchor=anchors.RELATIVE_2)
        line_middle = Schema(None, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE)

        self._schemas = [
            Schema(None, notdef, 1, Type.NON_JOINING, side_bearing=95, y_max=CAP_HEIGHT),
            Schema(0x0020, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x0021, exclamation, 1, Type.NON_JOINING, encirclable=True, y_max=CAP_HEIGHT),
            Schema(0x0024, dollar, 7 / 8, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0025, percent, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0028, left_parenthesis, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x0029, right_parenthesis, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x002A, asterisk, 1, Type.NON_JOINING, y_min=None, y_max=1.073 * CAP_HEIGHT),
            Schema(0x002B, plus, 1, Type.NON_JOINING, y_min=111),
            Schema(0x002C, comma, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x002E, h, 0, Type.NON_JOINING),
            Schema(0x002F, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x0030, zero, 3.882, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0031, one, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0032, two, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0033, three, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0034, four, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0035, five, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0036, six, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0037, seven, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0038, eight, 1.064, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x0039, nine, 1.021, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x003A, colon, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x003B, semicolon, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x003C, less_than, 2, Type.NON_JOINING),
            Schema(0x003D, equal, 1, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0x003E, greater_than, 2, Type.NON_JOINING),
            Schema(0x003F, question, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, encirclable=True),
            Schema(0x005B, left_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x005D, right_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x007B, left_brace, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x007D, right_brace, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x00A0, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x00A1, inverted_exclamation, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=CAP_HEIGHT + BRACKET_DEPTH, encirclable=True),
            Schema(0x00A2, cent, 1, Type.NON_JOINING, y_max=X_HEIGHT),
            Schema(0x00A3, pound, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x00AB, left_double_guillemet, 1, Type.NON_JOINING, y_min=guillemet_y_min),
            Schema(0x00B0, circle, 2.3, Type.NON_JOINING, y_min=None, y_max=CAP_HEIGHT),
            Schema(0x00BA, masculine_ordinal_indicator, 1, Type.NON_JOINING, y_min=220),
            Schema(0x00BB, right_double_guillemet, 1, Type.NON_JOINING, y_min=guillemet_y_min),
            Schema(0x00BF, inverted_question, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=CAP_HEIGHT + BRACKET_DEPTH, encirclable=True),
            Schema(0x00D7, multiplication, 1, Type.NON_JOINING),
            Schema(0x0300, grave, 0.2, anchor=anchors.ABOVE),
            Schema(0x0301, acute, 0.2, anchor=anchors.ABOVE),
            Schema(0x0302, circumflex, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x0304, macron, 0.2, anchor=anchors.ABOVE),
            Schema(0x0306, breve, 1, anchor=anchors.ABOVE),
            Schema(0x0307, h, 0, anchor=anchors.ABOVE),
            Schema(0x0308, diaeresis, 1, anchor=anchors.ABOVE),
            Schema(0x030C, caron, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x030D, vertical_line, 0.2, anchor=anchors.ABOVE),
            Schema(0x0316, grave, 0.2, anchor=anchors.BELOW),
            Schema(0x0317, acute, 0.2, anchor=anchors.BELOW),
            Schema(0x031C, left_half_ring, 1, anchor=anchors.BELOW),
            Schema(0x0323, h, 0, anchor=anchors.BELOW),
            Schema(0x0324, diaeresis, 1, anchor=anchors.BELOW),
            Schema(0x032F, inverted_breve, 1, anchor=anchors.BELOW),
            Schema(0x0331, macron, 0.2, anchor=anchors.BELOW),
            Schema(0x0339, right_half_ring, 1, anchor=anchors.BELOW),
            Schema(0x034F, space, 0, Type.NON_JOINING, side_bearing=0),
            Schema(0x0351, left_half_ring, 1, anchor=anchors.ABOVE),
            Schema(0x0357, right_half_ring, 1, anchor=anchors.ABOVE),
            Schema(0x2001, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x2003, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x200C, space, 0, Type.NON_JOINING, side_bearing=0, override_ignored=True),
            Schema(0x2013, en_dash, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x2018, turned_comma, 1, Type.NON_JOINING, y_min=558, encirclable=True),
            Schema(0x2019, comma, 1, Type.NON_JOINING, y_min=677, encirclable=True),
            Schema(0x201C, left_quote, 1, Type.NON_JOINING, y_min=558, encirclable=True),
            Schema(0x201D, right_quote, 1, Type.NON_JOINING, y_min=677, encirclable=True),
            Schema(0x201E, right_quote, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x2026, ellipsis, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x202F, nnbsp, 200 - 2 * DEFAULT_SIDE_BEARING, side_bearing=200 - 2 * DEFAULT_SIDE_BEARING),
            Schema(0x2032, prime, 0.58, Type.NON_JOINING, y_min=None, y_max=CAP_HEIGHT),
            Schema(0x2033, double_prime, 0.58, Type.NON_JOINING, y_min=None, y_max=CAP_HEIGHT),
            Schema(0x2039, left_single_guillemet, 1, Type.NON_JOINING, y_min=guillemet_y_min),
            Schema(0x203A, right_single_guillemet, 1, Type.NON_JOINING, y_min=guillemet_y_min),
            Schema(0x203B, reference_mark, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x2042, asterism, 1, Type.NON_JOINING, y_min=-148),
            Schema(0x2044, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x205D, tricolon, 1, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x20DD, circle, 10, anchor=anchors.MIDDLE),
            Schema(0x2308, left_ceiling, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x2309, right_ceiling, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x230A, left_floor, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x230B, right_floor, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0x2463, four, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, marks=[enclosing_circle]),
            Schema(0x25CC, dotted_circle, 1, Type.NON_JOINING, y_min=33),
            Schema(0x2620, skull_and_crossbones, 0.1, Type.NON_JOINING, y_max=1.5 * CAP_HEIGHT, y_min=-0.5 * CAP_HEIGHT),
            Schema(0x2641, earth, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT),
            Schema(0x271D, cross, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT),
            Schema(0x2E3C, stenographic_period, 0.5, Type.NON_JOINING),
            Schema(0x2E40, double_hyphen, 1, Type.NON_JOINING, y_min=270),
            Schema(0xE000, bound, 1, Type.NON_JOINING, side_bearing=0),
            Schema(0xE001, cross_pommy, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT),
            Schema(0xE002, converging_lines, 1, Type.NON_JOINING),
            Schema(0xE003, sacred_heart, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT),
            Schema(0xE004, left_parenthesis_with_stroke, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0xE005, right_parenthesis_with_stroke, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0xE006, left_parenthesis_with_double_stroke, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0xE007, right_parenthesis_with_double_stroke, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT),
            Schema(0xE008, stenographic_semicolon, 1, Type.NON_JOINING),
            Schema(0xEC02, p_reverse, 1, Type.ORIENTING, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC03, t_reverse, 1, Type.ORIENTING, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC04, f_reverse, 1, Type.ORIENTING, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC05, k_reverse, 1, Type.ORIENTING, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC06, l_reverse, 1, Type.ORIENTING, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC19, m_reverse, 6, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC1A, n_reverse, 6, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC1B, j_reverse, 6, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC1C, s_reverse, 6, maximum_tree_width=MAX_TREE_WIDTH),
            Schema(0xEC9A, chinook_period_double_stroke, 1, Type.NON_JOINING, y_min=chinook_period_y_min),
            Schema(0x1BC00, h, 0, shading_allowed=False),
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
            Schema(0x1BC56, romanian_u, 3, Type.ORIENTING, marks=[small_dot_1], shading_allowed=False),
            Schema(0x1BC57, uh, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC58, uh, 2, Type.ORIENTING, marks=[small_dot_1], shading_allowed=False),
            Schema(0x1BC59, uh, 2, Type.ORIENTING, marks=[dot_2], shading_allowed=False),
            Schema(0x1BC5A, o, 3, Type.ORIENTING, marks=[small_dot_1], shading_allowed=False),
            Schema(0x1BC5B, ou, 3, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC5C, wa, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5D, wo, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5E, wi, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5F, wei, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC60, wo, 1, Type.ORIENTING, marks=[small_dot_1], shading_allowed=False),
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
            Schema(0x1BC76, rtl_secant, 1, Type.ORIENTING),
            Schema(0x1BC77, ltr_secant, 1, Type.ORIENTING),
            Schema(0x1BC78, tangent, 0.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC79, n_reverse, 6, shading_allowed=False),
            Schema(0x1BC7A, e_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC7B, i_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True),
            Schema(0x1BC7C, tangent_hook, 2, Type.ORIENTING, shading_allowed=False, can_lead_orienting_sequence=True),
            Schema(0x1BC80, high_acute, 1),
            Schema(0x1BC81, high_tight_acute, 1),
            Schema(0x1BC82, high_grave, 1),
            Schema(0x1BC83, high_long_grave, 1),
            Schema(0x1BC84, high_dot, 1),
            Schema(0x1BC85, high_circle, 1),
            Schema(0x1BC86, high_line, 1),
            Schema(0x1BC87, high_wave, 1),
            Schema(0x1BC88, high_vertical, 1),
            Schema(0x1BC90, low_acute, 1),
            Schema(0x1BC91, low_tight_acute, 1),
            Schema(0x1BC92, low_grave, 1),
            Schema(0x1BC93, low_long_grave, 1),
            Schema(0x1BC94, low_dot, 1),
            Schema(0x1BC95, low_circle, 1),
            Schema(0x1BC96, low_line, 1),
            Schema(0x1BC97, low_wave, 1),
            Schema(0x1BC98, low_vertical, 1),
            Schema(0x1BC99, low_arrow, 1),
            Schema(0x1BC9C, likalisti, 1, Type.NON_JOINING),
            Schema(0x1BC9D, dtls, 1, Type.NON_JOINING, y_min=dotted_square_y_min),
            Schema(0x1BC9E, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE),
            Schema(0x1BC9F, chinook_period, 1, Type.NON_JOINING, y_min=chinook_period_y_min),
            Schema(0x1BCA0, overlap, 1, Type.NON_JOINING, y_min=dotted_square_y_min, override_ignored=True),
            Schema(0x1BCA1, continuing_overlap, 1, Type.NON_JOINING, y_min=dotted_square_y_min, override_ignored=True),
            Schema(0x1BCA2, down_step, 1, Type.NON_JOINING, y_min=dotted_square_y_min, override_ignored=True),
            Schema(0x1BCA3, up_step, 1, Type.NON_JOINING, y_min=dotted_square_y_min, override_ignored=True),
        ]
        for script_cp in [
            0x00B2, 0x00B3, 0x00B9, 0x2070, 0x2074, 0x2075, 0x2076, 0x2077, 0x2078, 0x2079,
            0x2080, 0x2081, 0x2082, 0x2083, 0x2084, 0x2085, 0x2086, 0x2087, 0x2088, 0x2089,
        ]:
            schema = next(filter(lambda s: s.cmap == ord(unicodedata.normalize('NFKC', chr(script_cp))), self._schemas), None)
            if schema is None:
                continue
            is_superscript = unicodedata.decomposition(chr(script_cp)).startswith('<super>')
            self._schemas.append(schema.clone(
                cmap=script_cp,
                size=SMALL_DIGIT_FACTOR * schema.size,
                y_min=None if is_superscript else SUBSCRIPT_DEPTH,
                y_max=SUPERSCRIPT_HEIGHT if is_superscript else None,
                cps=None,
            ))
        if noto:
            self._schemas = [
                s for s in self._schemas
                if s.cmap is None or not (
                    s.cmap in FULL_FONT_CODE_POINTS
                    or unicodedata.category(chr(s.cmap)) == 'Co'
                    or unicodedata.category(chr(s.cmap)) == 'Zs' and s.joining_type != Type.NON_JOINING
                )
            ]

    def _add_lookup(
        self,
        feature_tag: str,
        anchor_class_name: str,
        *,
        flags: int,
        mark_filtering_set: fontTools.feaLib.ast.GlyphClassDefinition | None = None,
    ) -> None:
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
        for script in KNOWN_SCRIPTS:
            feature.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
            feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
            feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition]) -> None:
        self._add_lookup(
                'abvm',
                anchors.PARENT_EDGE,
                flags=0,
                mark_filtering_set=class_asts[phases.PARENT_EDGE_CLASS],
            )
        for layer_index in range(MAX_TREE_DEPTH):
            if layer_index < 2:
                for child_index in range(MAX_TREE_WIDTH):
                    self._add_lookup(
                            'blwm',
                            anchors.CHILD_EDGES[layer_index][child_index],
                            flags=0,
                            mark_filtering_set=class_asts[phases.CHILD_EDGE_CLASSES[child_index]],
                        )
            for child_index in range(MAX_TREE_WIDTH):
                self._add_lookup(
                    'mkmk',
                    anchors.INTER_EDGES[layer_index][child_index],
                    flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                    mark_filtering_set=class_asts[phases.INTER_EDGE_CLASSES[layer_index][child_index]],
                )
        self._add_lookup(
            'curs',
            anchors.CONTINUING_OVERLAP,
            flags=0,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.CURSIVE,
            flags=0,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        for anchor in anchors.ALL_MARK:
            self._add_lookup(
                'mark',
                anchor,
                flags=0,
            )
        for anchor in anchors.ALL_MKMK:
            self._add_lookup(
                'mkmk',
                mkmk(anchor),
                flags=0,
                mark_filtering_set=class_asts[f'global..{mkmk(anchor)}'],
            )

    def _add_altuni(self, uni: int, glyph_name: str) -> fontforge.glyph:
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

    def _draw_glyph(
        self,
        glyph: fontforge.glyph,
        schema: Schema,
        cmapped_anchors: Set[str],
        _scalar: float = 1,
    ) -> None:
        assert not schema.marks
        invisible = schema.path.invisible()
        stroke_width = self.light_line if invisible or schema.cmap is not None or schema.cps[-1:] != (0x1BC9D,) else self.shaded_line
        effective_bounding_box = schema.path.draw(
            glyph,
            stroke_width,
            self.light_line,
            self.stroke_gap,
            _scalar * schema.size,
            schema.anchor,
            schema.joining_type,
            # TODO: `isinstance(schema.path, Circle)` is redundant. The
            # shape can check that itself.
            schema.context_in == NO_CONTEXT and schema.diphthong_1 and isinstance(schema.path, Circle),
            schema.context_out == NO_CONTEXT and schema.diphthong_2 and isinstance(schema.path, Circle),
            schema.diphthong_1,
            schema.diphthong_2,
        )
        if invisible:
            glyph.draw(glyph.glyphPen())
        if schema.joining_type != Type.NON_JOINING:
            entry_x = next(
                (x for anchor_class_name, type, x, _ in glyph.anchorPoints
                    if anchor_class_name == anchors.CURSIVE and type == 'entry'),
                0,
            )
            glyph.transform(fontTools.misc.transform.Offset(-entry_x, 0))
        true_bounding_box = glyph.boundingBox()
        _, true_y_min, _, true_y_max = true_bounding_box
        x_min, y_min, x_max, y_max = effective_bounding_box or true_bounding_box
        y_proportion_below_min = (y_min - true_y_min) / (true_y_max - true_y_min) if true_y_max != true_y_min else 0
        if not schema.path.fixed_y() and y_min != y_max:
            if schema.y_min is not None:
                if schema.y_max is not None:
                    desired_height = schema.y_max - schema.y_min
                    actual_height = y_max - y_min
                    if (desired_to_actual_ratio := (desired_height - stroke_width) / (actual_height - stroke_width)) != 1:
                        if _scalar == 1:
                            glyph.clear()
                            self._draw_glyph(glyph, schema, cmapped_anchors, desired_to_actual_ratio)
                        else:
                            glyph.transform(fontTools.misc.transform.Offset(0, -y_min)
                                .scale(desired_height / actual_height)
                            )
                    _, y_min, _, y_max = glyph.boundingBox()
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min - y_proportion_below_min * (y_max - y_min)))
                else:
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
            elif schema.y_max is not None:
                glyph.transform(fontTools.misc.transform.Offset(0, schema.y_max - y_max))
        side_bearing = int(_scalar * schema.side_bearing)
        if x_min != x_max:
            glyph.left_side_bearing = side_bearing
        if schema.glyph_class == GlyphClass.MARK:
            if schema.cps == (0x20DD,) and x_min != x_max:
                radius = (x_max - x_min - self.light_line) / 2
                inscribed_square_size = math.sqrt(2) * radius
                # This should stay consistent with `shrink_wrap_enclosing_circle`.
                shrunk_square_size = inscribed_square_size - 3 * self.stroke_gap - self.light_line
                glyph.transform(fontTools.misc.transform.Offset(0, (CAP_HEIGHT - (y_max - y_min)) / 2))
                glyph.left_side_bearing = -int(DEFAULT_SIDE_BEARING + (shrunk_square_size + x_max - x_min) / 2)
            glyph.width = 0
        else:
            glyph.right_side_bearing = side_bearing
        self._wrangle_anchor_points(schema, glyph, cmapped_anchors, stroke_width)

    def _add_mkmk_anchor_points(
        self,
        schema: Schema,
        glyph: fontforge.glyph,
        stroke_width: float,
    ) -> None:
        for anchor_class_name, type, x, y in glyph.anchorPoints:
            if type == 'mark' and schema.anchor == anchor_class_name in anchors.ALL_MKMK:
                mkmk_anchor_class_name = mkmk(anchor_class_name)
                glyph.addAnchorPoint(mkmk_anchor_class_name, 'mark', x, y)
                _, y_min, _, y_max = glyph.boundingBox()
                gap = stroke_width / 2 + self.stroke_gap + self.light_line / 2
                match anchor_class_name:
                    case anchors.ABOVE:
                        y = y_max + gap
                    case anchors.BELOW:
                        y = y_min - gap
                    case _:
                        continue
                glyph.addAnchorPoint(mkmk_anchor_class_name, 'basemark', x, y)
                return

    def _convert_base_to_basemark(
        self,
        glyph: fontforge.glyph,
    ) -> None:
        for anchor_class_name, type, x, y in glyph.anchorPoints:
            if type == 'base':
                if anchor_class_name in anchors.ALL_MKMK:
                    anchor_class_name = mkmk(anchor_class_name)
                elif anchor_class_name in anchors.ALL_MARK:
                    continue
                glyph.addAnchorPoint(anchor_class_name, 'basemark', x, y)
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[1] in ['basemark', 'mark']]

    def _wrangle_anchor_points(
        self,
        schema: Schema,
        glyph: fontforge.glyph,
        cmapped_anchors: Set[str],
        stroke_width: float,
    ) -> None:
        if schema.anchor:
            self._add_mkmk_anchor_points(schema, glyph, stroke_width)
        if schema.glyph_class == GlyphClass.MARK and not schema.path.invisible():
            self._convert_base_to_basemark(glyph)
        if not schema.path.invisible():
            glyph.anchorPoints = [a for a in glyph.anchorPoints if (
                a[0] not in [anchors.PARENT_EDGE, *anchors.CHILD_EDGES[1]]
                    if schema.anchor or schema.glyph_class != GlyphClass.MARK
                    else a[1] not in ['entry', 'exit'] and a[0] not in anchors.CHILD_EDGES[0]
            )]
        if schema.glyph_class == GlyphClass.MARK or isinstance(schema.path, Notdef) or schema.path.guaranteed_glyph_class() is not None and schema.path.invisible():
            return
        anchor_tests = {anchor: anchor in cmapped_anchors or anchor in schema.anchors for anchor in anchors.ALL_MARK}
        anchor_tests[anchors.MIDDLE] = schema.encirclable or schema.max_double_marks != 0 or schema.cmap == 0x25CC
        anchor_tests[anchors.SECANT] |= schema.can_take_secant
        anchor_tests[anchors.CONTINUING_OVERLAP] = schema.joining_type != Type.NON_JOINING and (
            schema.can_take_secant or schema.max_tree_width() != 0 or schema.path.can_be_child(schema.size)
        )
        anchor_tests[anchors.CURSIVE] = schema.joining_type != Type.NON_JOINING and not schema.is_secant
        anchor_tests[anchors.PRE_HUB_CONTINUING_OVERLAP] = schema.is_secant
        anchor_tests[anchors.POST_HUB_CONTINUING_OVERLAP] = anchor_tests[anchors.CONTINUING_OVERLAP] and (schema.path.can_be_child(schema.size) or isinstance(schema.path, Line) and schema.path.dots is not None)
        anchor_tests[anchors.PRE_HUB_CURSIVE] = anchor_tests[anchors.CURSIVE] and schema.hub_priority != 0 and not schema.pseudo_cursive
        anchor_tests[anchors.POST_HUB_CURSIVE] = anchor_tests[anchors.CURSIVE] and schema.hub_priority != -1
        if schema.encirclable:
            glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != anchors.MIDDLE]
        anchor_class_names = {a[0] for a in glyph.anchorPoints}
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        if x_min == x_max == 0:
            x_max = schema.side_bearing
            y_max = CAP_HEIGHT
        x_center = (x_max + x_min) / 2
        y_center = (y_max + y_min) / 2
        for anchor_class_name, should_have_anchor in anchor_tests.items():
            should_have_anchor &= schema.ignorability != Ignorability.DEFAULT_YES
            if (has_anchor := anchor_class_name in anchor_class_names) != should_have_anchor:
                if has_anchor:
                    glyph.anchorPoints = [*filter(lambda a: a[0] != anchor_class_name, glyph.anchorPoints)]
                elif anchor_class_name == anchors.MIDDLE:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_center)
                elif anchor_class_name == anchors.ABOVE:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_max + stroke_width / 2 + self.stroke_gap + self.light_line / 2)
                elif anchor_class_name == anchors.BELOW:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_min - (stroke_width / 2 + self.stroke_gap + self.light_line / 2))
                else:
                    assert False, f'{glyph.glyphname}: {anchor_class_name}: {has_anchor} != {should_have_anchor}'

    def _create_glyph(
        self,
        schema: Schema,
        cmapped_anchors: Set[str],
        *,
        drawing: bool,
    ) -> fontforge.glyph:
        glyph_name = str(schema)
        uni = -1 if schema.cmap is None else schema.cmap
        if glyph_name in self.font:
            return self._add_altuni(uni, glyph_name)
        assert uni not in self.font, f'Duplicate code point: {hex(uni)}'
        glyph = self.font.createChar(uni, glyph_name)
        glyph.unicode = uni
        glyph.glyphclass = schema.glyph_class.value
        glyph.temporary = schema
        if drawing:
            self._draw_glyph(glyph, schema, cmapped_anchors)
        else:
            glyph.width = glyph.width
        return glyph

    def _create_marker(self, schema: Schema) -> None:
        assert schema.cmap is None, f'A marker has the code point U+{schema.cmap:04X}'
        glyph = self._create_glyph(schema, set(), drawing=True)
        glyph.width = 0

    def _complete_gpos(self) -> None:
        mark_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        base_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        basemark_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        cursive_positions: collections.defaultdict[str, collections.defaultdict[str, MutableSequence[fontTools.feaLib.ast.Anchor | None]]] = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))
        for glyph in self.font.glyphs():
            for anchor_class_name, type, x, y in glyph.anchorPoints:
                x = round(x)
                y = round(y)
                glyph_name = glyph.glyphname
                match type:
                    case 'mark':
                        mark_positions[anchor_class_name][(x, y)].append(glyph_name)
                    case 'base':
                        base_positions[anchor_class_name][(x, y)].append(glyph_name)
                    case 'basemark':
                        basemark_positions[anchor_class_name][(x, y)].append(glyph_name)
                    case 'entry':
                        cursive_positions[anchor_class_name][glyph_name][0] = fontTools.feaLib.ast.Anchor(x, y)
                    case 'exit':
                        cursive_positions[anchor_class_name][glyph_name][1] = fontTools.feaLib.ast.Anchor(x, y)
                    case _:
                        raise RuntimeError(f'Unknown anchor type: {type}')
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

    def _recreate_gdef(self) -> None:
        marks = []
        ligatures = []
        for glyph in self.font.glyphs():
            match glyph.glyphclass:
                case GlyphClass.MARK.value:
                    marks.append(glyph.glyphname)
                case GlyphClass.JOINER.value:
                    ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            None,
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    @staticmethod
    def _glyph_to_schema(glyph: fontforge.glyph) -> Schema:
        schema = glyph.temporary
        glyph.temporary = None
        schema.glyph = glyph
        return cast(Schema, schema)

    def convert_classes(
        self,
        classes: Mapping[str, Collection[Schema]],
    ) -> dict[str, fontTools.feaLib.ast.GlyphClassDefinition]:
        class_asts = {}
        for name, schemas in classes.items():
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                name,
                fontTools.feaLib.ast.GlyphClass([*map(str, schemas)]),
            )
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        return class_asts

    def convert_named_lookups(
        self,
        named_lookups_with_phases: Mapping[str, tuple[Lookup, Phase]],
        class_asts: MutableMapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
    ) -> dict[str, fontTools.feaLib.ast.LookupBlock]:
        named_lookup_asts: dict[str, fontTools.feaLib.ast.LookupBlock] = {}
        named_lookups_to_do = [*named_lookups_with_phases.keys()]
        while named_lookups_to_do:
            new_named_lookups_to_do = []
            for name, (lookup, phase) in named_lookups_with_phases.items():
                if name not in named_lookups_to_do:
                    continue
                try:
                    named_lookup_ast = lookup.to_asts(
                        None,
                        PrefixView(phase, class_asts),
                        PrefixView(phase, named_lookup_asts),
                        name,
                    )
                except KeyError:
                    new_named_lookups_to_do.append(name)
                    continue
                self._fea.statements.append(named_lookup_ast)
                assert name not in named_lookup_asts, name
                named_lookup_asts[name] = named_lookup_ast
            assert len(new_named_lookups_to_do) < len(named_lookups_to_do)
            named_lookups_to_do = new_named_lookups_to_do
        return named_lookup_asts

    def _merge_schemas(
        self,
        schemas: Collection[Schema],
        lookups_with_phases: Sequence[tuple[Lookup, Phase]],
        classes: MutableMapping[str, MutableSequence[Schema]],
        named_lookups_with_phases: MutableMapping[str, tuple[Lookup, Phase]],
    ) -> None:
        grouper = sifting.group_schemas(schemas)
        previous_phase: Phase | None = None
        for lookup, phase in reversed(lookups_with_phases):
            if phase is not previous_phase is not None:
                rename_schemas(grouper, self._phases.index(previous_phase))
            previous_phase = phase
            prefix_classes = PrefixView(phase, classes)
            prefix_named_lookups_with_phases = PrefixView(phase, named_lookups_with_phases)
            sifting.sift_groups(grouper, lookup, prefix_classes, prefix_named_lookups_with_phases)
        rename_schemas(grouper, NO_PHASE_INDEX)

    def augment(self) -> None:
        (
            schemas,
            output_schemas,
            lookups_with_phases,
            classes,
            named_lookups_with_phases,
        ) = phases.run_phases(self, self._schemas, self._phases)
        self._merge_schemas(schemas, lookups_with_phases, classes, named_lookups_with_phases)
        class_asts = self.convert_classes(classes)
        named_lookup_asts = self.convert_named_lookups(named_lookups_with_phases, class_asts)
        (
            _,
            more_output_schemas,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = phases.run_phases(self, [schema for schema in output_schemas if schema.canonical_schema is schema], self._middle_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        classes |= more_classes
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        cmapped_anchors = {schema.anchor for schema in schemas if schema.anchor is not None and schema.cmap is not None}
        for schema in schemas.sorted(key=lambda schema: (
            schema.canonical_schema is not schema,
            schema.cmap is None and schema.glyph_class == GlyphClass.MARK
                or str(schema).startswith('_')
                or not (not schema.ignored_for_topography and schema in output_schemas and schema in more_output_schemas),
        )):
            if schema.canonical_schema is schema or schema.cmap is not None:
                self._create_glyph(
                    schema,
                    cmapped_anchors,
                    drawing=not schema.ignored_for_topography and schema in output_schemas and schema in more_output_schemas,
                )
        (
            schemas,
            _,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = phases.run_phases(self, [*map(self._glyph_to_schema, self.font.glyphs())], self._marker_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        classes |= more_classes
        for schema in schemas.sorted(key=Schema.glyph_id_sort_key):
            if schema.glyph is None:
                self._create_marker(schema)
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        features_to_scripts: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
        for lp in lookups_with_phases:
            if lp[0].feature:
                features_to_scripts[lp[0].feature] |= lp[0].get_scripts(PrefixView(lp[1], classes))
        for i, lp in enumerate(lookups_with_phases):
            self._fea.statements.extend(lp[0].to_asts(features_to_scripts, PrefixView(lp[1], class_asts), PrefixView(lp[1], named_lookup_asts), i))
        self._add_lookups(class_asts)
        self.font.selection.all()
        self.font.round()
        self.font.simplify(3, (
            'setstarttoextremum',
            'smoothcurves',
        ))
        self.font.canonicalStart()
        self.font.canonicalContours()

    def merge_features(
        self,
        tt_font: fontTools.ttLib.ttFont.TTFont,
        old_fea: str,
    ) -> None:
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
