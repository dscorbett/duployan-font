# Copyright 2018-2019, 2022-2023 David Corbett
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

__all__ = ['Builder']


import collections
from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from collections.abc import Sequence
import io
import math
from typing import Any
from typing import Callable
from typing import Final
from typing import Optional
from typing import Tuple
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
import schema
from schema import Ignorability
from schema import MAX_DOUBLE_MARKS
from schema import MAX_HUB_PRIORITY
from schema import NO_PHASE_INDEX
from schema import Schema
from shapes import AnchorWidthDigit
from shapes import Bound
from shapes import Carry
from shapes import ChildEdge
from shapes import Circle
from shapes import CircleRole
from shapes import Complex
from shapes import ContextMarker
from shapes import ContinuingOverlap
from shapes import ContinuingOverlapS
from shapes import Curve
from shapes import DigitStatus
from shapes import Dot
from shapes import Dummy
from shapes import End
from shapes import EntryWidthDigit
from shapes import GlyphClassSelector
from shapes import Hub
from shapes import InitialSecantMarker
from shapes import InvalidDTLS
from shapes import InvalidOverlap
from shapes import InvalidStep
from shapes import LINE_FACTOR
from shapes import LeftBoundDigit
from shapes import Line
from shapes import MarkAnchorSelector
from shapes import Notdef
from shapes import Ou
from shapes import ParentEdge
from shapes import RADIUS
from shapes import RightBoundDigit
from shapes import RomanianU
from shapes import RootOnlyParentEdge
from shapes import SeparateAffix
from shapes import Space
from shapes import Start
from shapes import TangentHook
from shapes import ValidDTLS
from shapes import Wa
from shapes import Wi
from shapes import WidthNumber
from shapes import XShape
import sifting
from utils import BRACKET_DEPTH
from utils import BRACKET_HEIGHT
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import EPSILON
from utils import GlyphClass
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import MINIMUM_STROKE_GAP
from utils import NO_CONTEXT
from utils import PrefixView
from utils import REGULAR_LIGHT_LINE
from utils import SHADING_FACTOR
from utils import Type
from utils import WIDTH_MARKER_PLACES
from utils import WIDTH_MARKER_RADIX
from utils import mkmk


def rename_schemas(grouper: sifting.Grouper, phase_index: int) -> None:
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


class Builder:
    def __init__(self, font: fontforge.font, bold: bool, noto: bool) -> None:
        self.font: Final = font
        self._fea: Final = fontTools.feaLib.ast.FeatureFile()
        self._anchors: MutableMapping[str, fontTools.feaLib.ast.LookupBlock] = {}
        self._initialize_phases(noto)
        self.light_line = 101 if bold else REGULAR_LIGHT_LINE
        self.shaded_line = SHADING_FACTOR * self.light_line
        self.stroke_gap = max(MINIMUM_STROKE_GAP, self.light_line)
        code_points: collections.defaultdict[int, int] = collections.defaultdict(int)
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
        h_op = ((Dot.SCALAR - 1) * light_line / 2 / RADIUS, Circle(0, 0, clockwise=False))
        exclamation = Complex([(2, h), (244, Space(90)), (1.109, Line(90))])
        dollar = Complex([(2.58, Curve(180 - 18, 180 + 26, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (2.88, Curve(180 + 26, 360 - 8, clockwise=False, stretch=0.5, long=True, relative_stretch=False)), (0.0995, Line(360 - 8)), (2.88, Curve(360 - 8, 180 + 26, clockwise=True, stretch=0.5, long=True, relative_stretch=False)), (2.58, Curve(180 + 26, 180 - 18, clockwise=True, stretch=2.058, long=True, relative_stretch=False)), (151.739, Space(328.952)), (1.484, Line(90)), (140, Space(0)), (1.484, Line(270))])
        asterisk = Complex([(310, Space(90)), (0.467, Line(90)), (0.467, Line(198)), (0.467, Line(18), False), (0.467, Line(126)), (0.467, Line(306), False), (0.467, Line(54)), (0.467, Line(234), False), (0.467, Line(342))])
        plus = Complex([(146, Space(90)), (0.828, Line(90)), (0.414, Line(270)), (0.414, Line(180)), (0.828, Line(0))])
        comma = Complex([(35, Space(0)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True))])
        slash = Line(60)
        zero = Circle(180, 180, clockwise=False, stretch=132 / 193, long=True)
        one = Complex([(1.288, Line(90)), (0.416, Line(218))])
        two = Complex([(3.528, Curve(42, 25, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232)), (0.7, Line(0))])
        three = Complex([(3, Curve(36, 0, clockwise=True, stretch=0.2, long=True)), (3, Curve(0, 180, clockwise=True, stretch=0.2, long=True)), (0.15, Line(180)), (0.15, Line(0)), (3.36, Curve(0, 180, clockwise=True, stretch=0.375, long=True)), (3.42, Curve(180, 155, clockwise=True, stretch=0.937, long=True))])
        four = Complex([(1.296, Line(90)), (1.173, Line(235)), (0.922, Line(0))])
        five = Complex([(3.72, Curve(330, 0, clockwise=False, stretch=0.196, long=True)), (3.72, Curve(0, 180, clockwise=False, stretch=13 / 93, long=True)), (3.72, Curve(180, 210, clockwise=False, stretch=0.196, long=True)), (0.565, Line(86.145)), (0.572, Line(0))])
        six = Complex([(3.88, Circle(90, 90, clockwise=True)), (19.5, Curve(90, 70, clockwise=True, stretch=0.45)), (4, Curve(65, 355, clockwise=True))])
        seven = Complex([(0.818, Line(0)), (1.36, Line(246))])
        eight = Complex([(2.88, Curve(180, 90, clockwise=True)), (2.88, Curve(90, 270, clockwise=True)), (2.88, Curve(270, 180, clockwise=True)), (3.16, Curve(180, 270, clockwise=False)), (3.16, Curve(270, 90, clockwise=False)), (3.16, Curve(90, 180, clockwise=False))])
        nine = Complex([(3.5, Circle(270, 270, clockwise=True)), (35.1, Curve(270, 260, clockwise=True, stretch=0.45)), (4, Curve(255, 175, clockwise=True))])
        colon = Complex([h_op, (481, Space(90)), h_op])
        semicolon = Complex([*comma.instructions, (3, Curve(41, 101, clockwise=False), True), (0.5, Circle(101, 180, clockwise=False), True), (423, Space(90)), h_op])
        question = Complex([(2, h), (244, Space(90)), (4.162, Curve(90, 45, clockwise=True)), (0.16, Line(45)), (4.013, Curve(45, 210, clockwise=False))])
        less_than = Complex([(1, Line(153)), (1, Line(27))])
        equal = Complex([(305, Space(90)), (1, Line(0)), (180, Space(90)), (1, Line(180)), (90, Space(270)), (1, Line(0), True)], maximum_tree_width=1)
        greater_than = Complex([(1, Line(27)), (1, Line(153))])
        left_bracket = Complex([(0.45, Line(180)), (2.059, Line(90)), (0.45, Line(0))])
        right_bracket = Complex([(0.45, Line(0)), (2.059, Line(90)), (0.45, Line(180))])
        left_ceiling = Complex([(2.059, Line(90)), (0.45, Line(0))])
        right_ceiling = Complex([(2.059, Line(90)), (0.45, Line(180))])
        left_floor = Complex([(0.45, Line(180)), (2.059, Line(90))])
        right_floor = Complex([(0.45, Line(0)), (2.059, Line(90))])
        guillemet_vertical_space = (75, Space(90))
        guillemet_horizontal_space = (200, Space(0))
        left_guillemet = [(0.524, Line(129.89)), (0.524, Line(50.11))]
        right_guillemet = [*reversed(left_guillemet)]
        left_guillemet += [(op[0], op[1].reversed(), True) for op in left_guillemet]  # type: ignore[misc]
        right_guillemet += [(op[0], op[1].reversed(), True) for op in right_guillemet]  # type: ignore[misc]
        left_double_guillemet = Complex([guillemet_vertical_space, *left_guillemet, guillemet_horizontal_space, *left_guillemet])
        right_double_guillemet = Complex([guillemet_vertical_space, *right_guillemet, guillemet_horizontal_space, *right_guillemet])
        left_single_guillemet = Complex([guillemet_vertical_space, *left_guillemet])
        right_single_guillemet = Complex([guillemet_vertical_space, *right_guillemet])
        enclosing_circle = Circle(180, 180, clockwise=False)
        masculine_ordinal_indicator = Complex([(625.5, Space(90)), (2.3, Circle(180, 180, clockwise=False, stretch=0.078125, long=True)), (370, Space(270)), (105, Space(180)), (0.42, Line(0))])
        multiplication = Complex([(1, Line(315)), (0.5, Line(135), False), (0.5, Line(225)), (1, Line(45))])
        grave = Line(150)
        acute = Line(45)
        circumflex = Complex([(1, Line(25)), (1, Line(335))])
        macron = Line(0)
        breve = Curve(270, 90, clockwise=False, stretch=0.2)
        diaeresis = Complex([h_op, (Dot.SCALAR * 10 / 7 * light_line, Space(0)), h_op])
        caron = Complex([(1, Line(335)), (1, Line(25))])
        inverted_breve = Curve(90, 270, clockwise=False, stretch=0.2)
        en_dash = Complex([(395, Space(90)), (1, Line(0))])
        high_left_quote = Complex([(755, Space(90)), (3, Curve(221, 281, clockwise=False)), (0.5, Circle(281, 281, clockwise=False)), (160, Space(0)), (0.5, Circle(101, 101, clockwise=True)), (3, Curve(101, 41, clockwise=True))])
        high_right_quote = Complex([(742, Space(90)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        low_right_quote = Complex([(35, Space(0)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        ellipsis = Complex([h_op, (196, Space(0)), h_op, (196, Space(0)), h_op])
        nnbsp = Space(0)
        dotted_circle = Complex([(33, Space(90)), (1, h), (446, Space(90)), (1, h), (223, Space(270)), (223, Space(60)), (1, h), (446, Space(240)), (1, h), (223, Space(60)), (223, Space(30)), (1, h), (446, Space(210)), (1, h), (223, Space(30)), (223, Space(0)), (1, h), (446, Space(180)), (1, h), (223, Space(0)), (223, Space(330)), (1, h), (446, Space(150)), (1, h), (223, Space(330)), (223, Space(300)), (1, h), (446, Space(120)), (1, h)])
        skull_and_crossbones = Complex([(7, Circle(180, 180, clockwise=False, stretch=0.4, long=True)), (7 * 2 * 1.4 * RADIUS * 0.55, Space(270)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(120)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(0)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(240)), (7 * 2 * 1.4 * RADIUS * 0.3, Space(270)), (1, h), (150, Space(160)), (1, h), (150, Space(340)), (150, Space(20)), (1, h), (150, Space(200)), (7 * 2 * 1.4 * RADIUS / 2, Space(270)), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), False), (2.1, Curve(60, 90, clockwise=False), True), (2.1, Curve(270, 210, clockwise=True)), (2.1, Curve(30, 60, clockwise=False), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(330)), (2.1, Curve(60, 30, clockwise=True), True), (2.1, Curve(210, 270, clockwise=False)), (2.1, Curve(90, 60, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(30), True), (2.1, Curve(120, 90, clockwise=True)), (2.1, Curve(270, 330, clockwise=False)), (2.1, Curve(150, 120, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(210)), (2.1, Curve(120, 150, clockwise=False), True), (2.1, Curve(330, 270, clockwise=True)), (2.1, Curve(90, 120, clockwise=False), True)])
        stenographic_period = Complex([(0.5, Line(135)), *multiplication.instructions])
        double_hyphen = Complex([(305, Space(90)), (0.5, Line(0)), (179, Space(90)), (0.5, Line(180))])
        bound = Bound()
        cross_knob_line_factor = 0.42
        cross_knob_factor = cross_knob_line_factor * LINE_FACTOR / RADIUS
        cross_knob_instructions = [(cross_knob_line_factor, Line(270), True), (cross_knob_factor, Circle(180, 180, clockwise=True)), (cross_knob_line_factor / 2, Line(90), True), (cross_knob_factor / 2, Circle(180, 180, clockwise=True)), (cross_knob_line_factor / 2, Line(90), True)]
        cross_pommy = Complex([*cross_knob_instructions, (3 + 2 * cross_knob_line_factor, Line(270)), *cross_knob_instructions, (2 + cross_knob_line_factor, Line(90), True), (1 + cross_knob_line_factor, Line(180), True), *cross_knob_instructions, (2 + 2 * cross_knob_line_factor, Line(0)), *cross_knob_instructions])  # type: ignore[list-item]
        cross = Complex([(3, Line(270)), (2, Line(90), True), (1, Line(180), True), (2, Line(0))])
        sacred_heart = Complex([(3.528, Curve(42, 25, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232)), (0.904, Line(128)), (3.528, Curve(128, 335, clockwise=True, stretch=0.036, long=True)), (3.528, Curve(335, 318, clockwise=True, stretch=0.346, long=True)), (7.5, Space(0)), (1, cross.instructions[0][1].reversed(), True), *[(op[0] / 3, op[1]) for op in cross.instructions]])  # type: ignore[index, union-attr]
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
        ou_reverse = ou.as_reversed()
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
        tangent = Complex([lambda c: Context(None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360), (0.25, Line(270)), lambda c: Context((cast(float, c.angle) + 180) % 360), (0.5, Line(90))], hook=True)
        e_hook = Curve(90, 270, clockwise=True, hook=True)
        i_hook = Curve(180, 0, clockwise=False, hook=True)
        tangent_hook = TangentHook([(1, Curve(180, 270, clockwise=False)), Context.reversed, (1, Curve(90, 270, clockwise=True))])
        high_acute = SeparateAffix([(0.5, Line(45))])
        high_tight_acute = SeparateAffix([(0.5, Line(45))], tight=True)
        high_grave = SeparateAffix([(0.5, Line(315))])
        high_long_grave = SeparateAffix([(0.4, Line(300)), (0.75, Line(0))])
        high_dot = SeparateAffix([h_op])
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
        dotted_square = [(152, Space(270)), (0.26 - light_line / 1000, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.26 - light_line / 1000, Line(90)), (0.26 - light_line / 1000, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.26 - light_line / 1000, Line(0)), (0.26 - light_line / 1000, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.26 - light_line / 1000, Line(270)), (0.26 - light_line / 1000, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.26 - light_line / 1000, Line(180))]
        dtls = InvalidDTLS(instructions=dotted_square + [(341, Space(0)), (173, Space(90)), (0.238, Line(180)), (0.412, Line(90)), (130, Space(90)), (0.412, Line(90)), (0.18, Line(0)), (2.06, Curve(0, 180, clockwise=True, stretch=-27 / 115, long=True, relative_stretch=False)), (0.18, Line(180)), (369, Space(0)), (0.412, Line(90)), (0.148, Line(180), True), (0.296, Line(0)), (341, Space(270)), (14.5, Space(180)), (.345 * 2.58, Curve(164, 196, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (.345 * 2.88, Curve(196, 341, clockwise=False, stretch=0.25, long=True, relative_stretch=False)), (.345 *0.224, Line(341)), (.345 * 2.88, Curve(341, 196, clockwise=True, stretch=0.25, long=True, relative_stretch=False)), (.345 * 2.58, Curve(196, 164, clockwise=True, stretch=2.058, long=True, relative_stretch=False))])
        chinook_period = Complex([(100, Space(90)), (1, Line(0)), (179, Space(90)), (1, Line(180))])
        overlap = InvalidOverlap(continuing=False, instructions=dotted_square + [(162.5, Space(0)), (397, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (1.134, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220)), (170, Space(180)), (0.4116, Line(90))])
        continuing_overlap = InvalidOverlap(continuing=True, instructions=dotted_square + [(189, Space(0)), (522, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (0.726, Line(0)), (124, Space(180)), (145, Space(90)), (0.852, Line(270)), (0.552, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220))])
        down_step = InvalidStep(270, dotted_square + [(444, Space(0)), (749, Space(90)), (1.184, Line(270)), (0.32, Line(130)), (0.32, Line(310), True), (0.32, Line(50))])
        up_step = InvalidStep(90, dotted_square + [(444, Space(0)), (157, Space(90)), (1.184, Line(90)), (0.32, Line(230)), (0.32, Line(50), True), (0.32, Line(310))])
        line = Line(0)

        small_dot_1 = Schema(None, h, 1, anchor=anchors.RELATIVE_1)
        dot_1 = Schema(None, h, 2, anchor=anchors.RELATIVE_1)
        dot_2 = Schema(None, h, 2, anchor=anchors.RELATIVE_2)
        line_2 = Schema(None, line, 0.35, Type.ORIENTING, anchor=anchors.RELATIVE_2)
        line_middle = Schema(None, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE)

        self._schemas = [
            Schema(None, notdef, 1, Type.NON_JOINING, side_bearing=95, y_max=CAP_HEIGHT),
            Schema(0x0020, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x0021, exclamation, 1, Type.NON_JOINING, encirclable=True, y_max=CAP_HEIGHT),
            Schema(0x0024, dollar, 7 / 8, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x002A, asterisk, 1, Type.NON_JOINING),
            Schema(0x002B, plus, 1, Type.NON_JOINING),
            Schema(0x002C, comma, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x002E, h, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x002F, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, maximum_tree_width=0, shading_allowed=False),
            Schema(0x0030, zero, 3.882, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0031, one, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0032, two, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0033, three, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0034, four, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0035, five, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0036, six, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0037, seven, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0038, eight, 1.064, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0039, nine, 1.021, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x003A, colon, 0.856, Type.NON_JOINING, encirclable=True, shading_allowed=False),
            Schema(0x003B, semicolon, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x003C, less_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003D, equal, 1),
            Schema(0x003E, greater_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003F, question, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, encirclable=True),
            Schema(0x005B, left_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x005D, right_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x00A0, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x00AB, left_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00B0, enclosing_circle, 2.3, Type.NON_JOINING, y_min=None, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x00BA, masculine_ordinal_indicator, 1, Type.NON_JOINING),
            Schema(0x00BB, right_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00D7, multiplication, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0300, grave, 0.2, anchor=anchors.ABOVE),
            Schema(0x0301, acute, 0.2, anchor=anchors.ABOVE),
            Schema(0x0302, circumflex, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x0304, macron, 0.2, anchor=anchors.ABOVE),
            Schema(0x0306, breve, 1, anchor=anchors.ABOVE),
            Schema(0x0307, h, 2, anchor=anchors.ABOVE),
            Schema(0x0308, diaeresis, 1, anchor=anchors.ABOVE),
            Schema(0x030C, caron, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x0316, grave, 0.2, anchor=anchors.BELOW),
            Schema(0x0317, acute, 0.2, anchor=anchors.BELOW),
            Schema(0x0323, h, 2, anchor=anchors.BELOW),
            Schema(0x0324, diaeresis, 1, anchor=anchors.BELOW),
            Schema(0x032F, inverted_breve, 1, anchor=anchors.BELOW),
            Schema(0x0331, macron, 0.2, anchor=anchors.BELOW),
            Schema(0x034F, space, 0, Type.NON_JOINING, side_bearing=0, ignorability=Ignorability.DEFAULT_YES),
            Schema(0x2001, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x2003, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x200C, space, 0, Type.NON_JOINING, side_bearing=0, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x2013, en_dash, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x201C, high_left_quote, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x201D, high_right_quote, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x201E, low_right_quote, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x2026, ellipsis, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x202F, nnbsp, 200 - 2 * DEFAULT_SIDE_BEARING, side_bearing=200 - 2 * DEFAULT_SIDE_BEARING),
            Schema(0x2039, left_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x203A, right_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x2044, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x20DD, enclosing_circle, 10, anchor=anchors.MIDDLE),
            Schema(0x2308, left_ceiling, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x2309, right_ceiling, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x230A, left_floor, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x230B, right_floor, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x25CC, dotted_circle, 1, Type.NON_JOINING),
            Schema(0x2620, skull_and_crossbones, 1, Type.NON_JOINING, y_max=1.5 * CAP_HEIGHT, y_min=-0.5 * CAP_HEIGHT),
            Schema(0x271D, cross, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT, shading_allowed=False),
            Schema(0x2E3C, stenographic_period, 0.5, Type.NON_JOINING, shading_allowed=False),
            Schema(0x2E40, double_hyphen, 1, Type.NON_JOINING),
            Schema(0xE000, bound, 1, Type.NON_JOINING, side_bearing=0),
            Schema(0xE001, cross_pommy, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT, shading_allowed=False),
            Schema(0xE003, sacred_heart, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT),
            Schema(0xEC02, p_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC03, t_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC04, f_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC05, k_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC06, l_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC19, m_reverse, 6, shading_allowed=False),
            Schema(0xEC1A, n_reverse, 6, shading_allowed=False),
            Schema(0xEC1B, j_reverse, 6, shading_allowed=False),
            Schema(0xEC1C, s_reverse, 6, shading_allowed=False),
            Schema(0x1BC00, h, 2, shading_allowed=False),
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
            Schema(0x1BC76, rtl_secant, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC77, ltr_secant, 1, Type.ORIENTING, shading_allowed=False),
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
            Schema(0x1BC9D, dtls, 1, Type.NON_JOINING),
            Schema(0x1BC9E, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE),
            Schema(0x1BC9F, chinook_period, 1, Type.NON_JOINING),
            Schema(0x1BCA0, overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA1, continuing_overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA2, down_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA3, up_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
        ]
        if noto:
            self._schemas = [
                s for s in self._schemas
                if s.cmap is None or not (
                    s.cmap == 0x034F
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
        mark_filtering_set: Optional[fontTools.feaLib.ast.GlyphClassDefinition] = None,
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
        for script in Lookup.KNOWN_SCRIPTS:
            feature.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
            feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
            feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition]) -> None:
        parent_edge_lookup = None
        child_edge_lookups = [None] * MAX_TREE_WIDTH
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

    def _draw_glyph(self, glyph: fontforge.glyph, schema: Schema, scalar: float = 1) -> None:
        assert not schema.marks
        pen = glyph.glyphPen()
        invisible = schema.path.invisible()
        floating = schema.path.draw(
            glyph,
            not invisible and pen,
            scalar * (self.light_line if invisible or schema.cmap is not None or schema.cps[-1:] != [0x1BC9D] else self.shaded_line),
            scalar * self.light_line,
            scalar * self.stroke_gap,
            schema.size,
            schema.anchor,
            schema.joining_type,
            schema.child,
            # TODO: `isinstance(schema.path, Circle)` is redundant. The
            # shape can check that itself.
            schema.context_in == NO_CONTEXT and schema.diphthong_1 and isinstance(schema.path, Circle),
            schema.context_out == NO_CONTEXT and schema.diphthong_2 and isinstance(schema.path, Circle),
            schema.diphthong_1,
            schema.diphthong_2,
        )
        if schema.joining_type == Type.NON_JOINING:
            glyph.left_side_bearing = int(scalar * schema.side_bearing)
        else:
            entry_x = next(
                (x for anchor_class_name, type, x, _ in glyph.anchorPoints
                    if anchor_class_name == anchors.CURSIVE and type == 'entry'),
                0,
            )
            glyph.transform(fontTools.misc.transform.Offset(-entry_x, 0))
        if not floating:
            _, y_min, _, y_max = glyph.boundingBox()
            if y_min != y_max:
                if schema.y_min is not None:
                    if schema.y_max is not None:
                        if (desired_to_actual_ratio := (schema.y_max - schema.y_min) / (y_max - y_min)) != 1:
                            if scalar == 1:
                                glyph.clear()
                                self._draw_glyph(glyph, schema, 1 / desired_to_actual_ratio)
                            else:
                                glyph.transform(fontTools.misc.transform.Offset(0, -y_min)
                                    .scale(desired_to_actual_ratio)
                                )
                        _, y_min, _, _ = glyph.boundingBox()
                        glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
                    else:
                        glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
                elif schema.y_max is not None:
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_max - y_max))
        if schema.glyph_class == GlyphClass.MARK:
            glyph.width = 0
        else:
            glyph.right_side_bearing = int(scalar * schema.side_bearing)

    def _create_glyph(self, schema: Schema, *, drawing: bool) -> fontforge.glyph:
        glyph_name = str(schema)
        uni = -1 if schema.cmap is None else schema.cmap
        if glyph_name in self.font:
            return self._add_altuni(uni, glyph_name)
        assert uni not in self.font, f'Duplicate code point: {hex(uni)}'
        glyph = self.font.createChar(uni, glyph_name)
        glyph.glyphclass = schema.glyph_class.value
        glyph.temporary = schema
        if drawing:
            self._draw_glyph(glyph, schema)
        else:
            glyph.width = glyph.width
        return glyph

    def _create_marker(self, schema: Schema) -> None:
        assert schema.cmap is None, f'A marker has the code point U+{schema.cmap:04X}'
        glyph = self._create_glyph(schema, drawing=True)
        glyph.width = 0

    def _complete_gpos(self) -> None:
        mark_positions: collections.defaultdict[str, collections.defaultdict[Tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        base_positions: collections.defaultdict[str, collections.defaultdict[Tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        basemark_positions: collections.defaultdict[str, collections.defaultdict[Tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        cursive_positions: collections.defaultdict[str, collections.defaultdict[str, MutableSequence[Optional[fontTools.feaLib.ast.Anchor]]]] = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))
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

    def _recreate_gdef(self) -> None:
        bases = []
        marks = []
        ligatures = []
        for glyph in self.font.glyphs():
            match glyph.glyphclass:
                case GlyphClass.BLOCKER.value:
                    bases.append(glyph.glyphname)
                case GlyphClass.MARK.value:
                    marks.append(glyph.glyphname)
                case GlyphClass.JOINER.value:
                    ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            fontTools.feaLib.ast.GlyphClass(bases),
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    @staticmethod
    def _glyph_to_schema(glyph) -> Schema:
        schema = glyph.temporary
        glyph.temporary = None
        schema.glyph = glyph
        return schema

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
        named_lookups_with_phases: Mapping[str, Tuple[phases.Lookup, Any]],
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

    def _merge_schemas(
        self,
        schemas: Collection[Schema],
        lookups_with_phases: Sequence[Tuple[Lookup, Any]],
        classes: MutableMapping[str, Collection[Schema]],
        named_lookups_with_phases: MutableMapping[str, Tuple[Lookup, Any]],
    ) -> None:
        grouper = sifting.group_schemas(schemas)
        previous_phase: Optional[Callable] = None
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
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for schema in schemas.sorted(key=lambda schema: not (schema in output_schemas and schema in more_output_schemas)):
            self._create_glyph(
                schema,
                drawing=schema in output_schemas and schema in more_output_schemas and not schema.ignored_for_topography,
            )
        (
            schemas,
            _,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = phases.run_phases(self, [*map(self._glyph_to_schema, self.font.glyphs())], self._marker_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        for schema in schemas.sorted(key=Schema.glyph_id_sort_key):
            if schema.glyph is None:
                self._create_marker(schema)
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for i, lp in enumerate(lookups_with_phases):
            for statement in lp[0].to_asts(PrefixView(lp[1], class_asts), PrefixView(lp[1], named_lookup_asts), i):
                self._fea.statements.append(statement)
        self._add_lookups(class_asts)
        self.font.selection.all()
        self.font.round()
        self.font.simplify(3, ('smoothcurves',))

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
