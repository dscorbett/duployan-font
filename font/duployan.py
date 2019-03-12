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

from __future__ import division

__all__ = ['Builder']

import collections
import math
import re
import tempfile

import fontforge
import fontTools.agl
import fontTools.feaLib.ast
import fontTools.feaLib.builder
import fontTools.feaLib.parser
import fontTools.misc.py23
import fontTools.otlLib.builder
import psMat
import unicodedata2

BASELINE = 402
DEFAULT_SIDE_BEARING = 85
RADIUS = 50
STROKE_WIDTH = 70
CURSIVE_LOOKUP = "'curs'"
CURSIVE_SUBTABLE = CURSIVE_LOOKUP + '-1'
CURSIVE_ANCHOR = 'cursive'
RELATIVE_1_LOOKUP = "'mark' relative mark inside or above"
RELATIVE_1_SUBTABLE = RELATIVE_1_LOOKUP + '-1'
RELATIVE_1_ANCHOR = 'rel1'
RELATIVE_2_LOOKUP = "'mark' relative mark outside or below"
RELATIVE_2_SUBTABLE = RELATIVE_2_LOOKUP + '-1'
RELATIVE_2_ANCHOR = 'rel2'
ABOVE_LOOKUP = "'mark' above"
ABOVE_SUBTABLE = ABOVE_LOOKUP + '-1'
ABOVE_ANCHOR = 'abv'
BELOW_LOOKUP = "'mark' below"
BELOW_SUBTABLE = BELOW_LOOKUP + '-1'
BELOW_ANCHOR = 'blw'
CLONE_DEFAULT = object()

def add_lookup(font, lookup, lookup_type, flags, feature, subtable, anchor_class):
    font.addLookup(lookup,
        lookup_type,
        flags,
        ((feature, (('dupl', ('dflt',)),)),))
    font.addLookupSubtable(lookup, subtable)
    font.addAnchorClass(subtable, anchor_class)

def add_lookups(font):
    add_lookup(font,
        CURSIVE_LOOKUP,
        'gpos_cursive',
        ('ignore_marks',),
        'curs',
        CURSIVE_SUBTABLE,
        CURSIVE_ANCHOR)
    add_lookup(font,
        RELATIVE_1_LOOKUP,
        'gpos_mark2base',
        (),
        'mark',
        RELATIVE_1_SUBTABLE,
        RELATIVE_1_ANCHOR)
    add_lookup(font,
        RELATIVE_2_LOOKUP,
        'gpos_mark2base',
        (),
        'mark',
        RELATIVE_2_SUBTABLE,
        RELATIVE_2_ANCHOR)
    add_lookup(font,
        ABOVE_LOOKUP,
        'gpos_mark2base',
        (),
        'mark',
        ABOVE_SUBTABLE,
        ABOVE_ANCHOR)
    add_lookup(font,
        BELOW_LOOKUP,
        'gpos_mark2base',
        (),
        'mark',
        BELOW_SUBTABLE,
        BELOW_ANCHOR)

class Enum(object):
    def __init__(self, names):
        for i, name in enumerate(names):
            setattr(self, name, i)

TYPE = Enum([
    'JOINING',
    'ORIENTING',
    'NON_JOINING',
])

class Context(object):
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
            '' if self.clockwise is None else 'neg' if self.clockwise else 'pos')

    def __eq__(self, other):
        return self.angle == other.angle and self.clockwise == other.clockwise

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash(self.angle) ^ hash(self.clockwise)

NO_CONTEXT = Context()

def rect(r, theta):
    return (r * math.cos(theta), r * math.sin(theta))

class Shape(object):
    def clone(self):
        raise NotImplementedError

    def group(self):
        return str(self)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        raise NotImplementedError

    def context_in(self):
        raise NotImplementedError

    def context_out(self):
        raise NotImplementedError

class Space(Shape):
    def __init__(self, angle):
        self.angle = angle

    def clone(self, angle=CLONE_DEFAULT):
        return Space(self.angle if angle is CLONE_DEFAULT else angle)

    def __str__(self):
        return 'Z.{}'.format(self.angle)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        if joining_type != TYPE.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', -size, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 0)
            glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))

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

    def context_in(self):
        return NO_CONTEXT

    def context_out(self):
        return NO_CONTEXT

class Line(Shape):
    def __init__(self, angle):
        self.angle = angle

    def clone(self, angle=CLONE_DEFAULT):
        return Line(self.angle if angle is CLONE_DEFAULT else angle)

    def __str__(self):
        return 'L.{}'.format(self.angle)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        pen.moveTo((0, 0))
        length = int(500 * (size or 0.2) / (abs(math.sin(math.radians(self.angle))) or 1))
        pen.lineTo((length, 0))
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(length / 2, 0))
        else:
            if joining_type != TYPE.NON_JOINING:
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', length, 0)
            if size == 2 and self.angle == 30:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', length / 2 - 2 * STROKE_WIDTH, -STROKE_WIDTH)
                glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', length / 2 + 2 * STROKE_WIDTH, -STROKE_WIDTH)
            else:
                glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', length / 2, STROKE_WIDTH)
                glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', length / 2, -STROKE_WIDTH)
        glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def context_in(self):
        return Context(self.angle)

    def context_out(self):
        return Context(self.angle)

class Curve(Shape):
    def __init__(self, angle_in, angle_out, clockwise):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise

    def clone(self, angle_in=CLONE_DEFAULT, angle_out=CLONE_DEFAULT, clockwise=CLONE_DEFAULT):
        return Curve(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise)

    def __str__(self):
        return 'C.{}.{}.{}'.format(
            self.angle_in,
            self.angle_out,
            'neg' if self.clockwise else 'pos')

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
            p0 = rect(r, theta0)
            p1 = rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = rect(r, theta3)
            p2 = rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        pen.endPath()
        glyph.stroke('circular', STROKE_WIDTH, 'round')
        relative_mark_angle = (a1 + a2) / 2
        if joining_type != TYPE.NON_JOINING:
            x = r * math.cos(math.radians(a1))
            y = r * math.sin(math.radians(a1))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', x, y)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', p3[0], p3[1])
        glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base',
            *(rect(0, 0) if abs(da) > 180 else rect(
                min(STROKE_WIDTH, r - 2 * STROKE_WIDTH),
                math.radians(relative_mark_angle))))
        glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(relative_mark_angle)))
        if joining_type == TYPE.ORIENTING:
            glyph.addAnchorPoint(ABOVE_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(90)))
            glyph.addAnchorPoint(BELOW_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(270)))

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

class Circle(Shape):
    def __init__(self, angle_in, angle_out, clockwise, reversed):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.reversed = reversed

    def clone(
            self,
            angle_in=CLONE_DEFAULT,
            angle_out=CLONE_DEFAULT,
            clockwise=CLONE_DEFAULT,
            reversed=CLONE_DEFAULT):
        return Circle(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            self.reversed if reversed is CLONE_DEFAULT else reversed)

    def __str__(self):
        return 'O.{}.{}.{}{}'.format(
            self.angle_in,
            self.angle_out,
            'neg' if self.clockwise else 'pos',
            '.rev' if self.reversed else '')

    def group(self):
        angle_in = self.angle_in
        angle_out = self.angle_out
        clockwise = self.clockwise
        if clockwise and angle_in == angle_out:
            clockwise = False
            angle_in = angle_out = angle_in % 180
        return 'O.{}.{}.{}'.format(
            angle_in,
            angle_out,
            'neg' if clockwise else 'pos',
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
        glyph.stroke('circular', STROKE_WIDTH, 'round')
        if joining_type != TYPE.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *rect(r, math.radians(a2)))
        glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', *rect(0, 0))
        glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', *rect(r + 2 * STROKE_WIDTH, math.radians(90)))

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
                self.reversed)
        da = abs(angle_out - angle_in)
        clockwise_ignoring_curvature = (da >= 180) != (angle_out > angle_in)
        clockwise = self.reversed != (
            clockwise_from_adjacent_curve
                if clockwise_from_adjacent_curve is not None
                else clockwise_ignoring_curvature)
        if clockwise == clockwise_ignoring_curvature and not self.reversed:
            return Curve(angle_in, angle_out, clockwise)
        return Circle(angle_in, angle_out, clockwise, self.reversed)

    def context_in(self):
        return Context(self.angle_in, self.clockwise)

    def context_out(self):
        return Context(self.angle_out, self.clockwise)

STYLE = Enum([
    'PERNIN',
])

class Schema(object):
    _CHARACTER_NAME_SUBSTITUTIONS = map(lambda (pattern, repl): (re.compile(pattern), repl), [
        (r'^ZERO WIDTH SPACE$', 'ZWSP'),
        (r'^ZERO WIDTH NON-JOINER$', 'ZWNJ'),
        (r'^ZERO WIDTH JOINER$', 'ZWJ'),
        (r'^MEDIUM MATHEMATICAL SPACE$', 'MMSP'),
        (r'^WORD JOINER$', 'WJ'),
        (r'^ZERO WIDTH NO-BREAK SPACE$', 'ZWNBSP'),
        (r'^COMBINING ', ''),
        (r'^DUPLOYAN ((LETTER|AFFIX|SIGN|PUNCTUATION) )?', ''),
        (r'^SHORTHAND FORMAT ', ''),
        (r'\b(QUAD|SPACE)\b', 'SP'),
        (r' (WITH|AND) ', ' '),
        (r'(?<! |-)[A-Z]+', lambda m: m.group(0).lower()),
        (r'[ -]+', ''),
    ])
    _canonical_names = {}

    def __init__(
            self,
            cp,
            path,
            size,
            joining_type=TYPE.JOINING,
            side_bearing=DEFAULT_SIDE_BEARING,
            anchor=None,
            marks=None,
            ignored=False,
            styles=None,
            ss_pernin=None,
            context_in=None,
            context_out=None,
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
        self.styles = frozenset(STYLE.__dict__.keys() if styles is None else styles)
        self.ss_pernin = ss_pernin
        self.context_in = context_in or NO_CONTEXT
        self.context_out = context_out or NO_CONTEXT
        self.cps = cps or [cp]
        self.ss = ss
        self._original_shape = _original_shape or type(path)
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
            'NJ' if self.joining_type == TYPE.NON_JOINING else '',
            'mark' if self.anchor else 'base',
            map(lambda m: repr(m), self.marks or []),
        ])))

    def _calculate_group(self):
        return (
            self.path.group(),
            self.size,
            self.side_bearing,
            self.anchor,
            tuple(map(lambda m: m.group, self.marks or [])),
        )

    def canonical_schema(self, canonical_schema):
        self._canonical_schema = canonical_schema
        self._glyph_name = None

    def calculate_name(self):
        def get_names(cp):
            try:
                agl_name = readable_name = fontTools.agl.UV2AGL[cp]
            except KeyError:
                try:
                    readable_name = unicodedata2.name(fontTools.misc.py23.unichr(cp))
                    for regex, repl in self._CHARACTER_NAME_SUBSTITUTIONS:
                        readable_name = regex.sub(repl, readable_name)
                    agl_name = '{}{:04X}'.format('uni' if cp <= 0xFFFF else 'u', cp)
                except UnicodeDecodeError, ValueError:
                    agl_name = readable_name = ''
            return agl_name, readable_name
        cps = self.cps
        if -1 in cps:
            name = ''
        else:
            agl_name, readable_name = map('_'.join, zip(*map(get_names, cps)))
            name = agl_name if agl_name == readable_name else '{}.{}'.format(agl_name, readable_name)
        if self.cp == -1:
            name = '{}.{}.{}{}'.format(
                name or 'dupl',
                self.path,
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
        assert self.joining_type == TYPE.ORIENTING
        return self.clone(
            cp=-1,
            path=self.path.contextualize(context_in, context_out),
            anchor=None,
            marks=None,
            context_in=context_in,
            context_out=context_out)

class OrderedSet(collections.OrderedDict):
    def __init__(self, iterable=None):
        super(OrderedSet, self).__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item):
        self[item] = None

    def remove(self, item):
        self.pop(item, None)

class Substitution(object):
    def __init__(self, a1, a2, a3=None, a4=None):
        def _l(glyphs):
            return [glyphs] if isinstance(glyphs, str) else glyphs
        if a4 is None:
            assert a3 is None, 'Substitution takes 2 or 4 inputs, given 3'
            self.contexts_in = []
            self.inputs = _l(a1)
            self.contexts_out = []
            self.outputs = _l(a2)
        else:
            self.contexts_in = _l(a1)
            self.inputs = _l(a2)
            self.contexts_out = _l(a3)
            self.outputs = _l(a4)

    def to_ast(self, class_asts, in_contextual_lookup, in_multiple_lookup):
        def glyph_to_ast(glyph):
            if isinstance(glyph, str):
                return fontTools.feaLib.ast.GlyphClassName(class_asts[fontTools.misc.py23.tounicode(glyph)])
            return fontTools.feaLib.ast.GlyphName(fontTools.misc.py23.tounicode(str(glyph)))
        def glyphs_to_ast(glyphs):
            return map(glyph_to_ast, glyphs)
        def glyph_to_name(glyph):
            assert not isinstance(glyph, str), 'Glyph classes are not allowed in multiple substitutions'
            return fontTools.misc.py23.tounicode(str(glyph))
        def glyphs_to_names(glyphs):
            return map(glyph_to_name, glyphs)
        if len(self.inputs) == 1:
            if len(self.outputs) == 1 and not in_multiple_lookup:
                return fontTools.feaLib.ast.SingleSubstStatement(
                    glyphs_to_ast(self.inputs),
                    glyphs_to_ast(self.outputs),
                    glyphs_to_ast(self.contexts_in),
                    glyphs_to_ast(self.contexts_out),
                    in_contextual_lookup)
            else:
                return fontTools.feaLib.ast.MultipleSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyph_to_name(self.inputs[0]),
                    glyphs_to_ast(self.contexts_out),
                    glyphs_to_names(self.outputs))
        else:
            return fontTools.feaLib.ast.LigatureSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                glyph_to_name(self.outputs[0]),
                in_contextual_lookup)

    def is_contextual(self):
        return bool(self.contexts_in or self.contexts_out)

    def is_multiple(self):
        return len(self.inputs) == 1 and len(self.outputs) != 1

class Lookup(object):
    def __init__(self, feature, script, language):
        self.feature = feature
        self.script = script
        self.language = language
        self.rules = []
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
        else:
            raise ValueError("Unrecognized script tag: '{}'".format(self.script))

    def to_ast(self, class_asts):
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        ast = fontTools.feaLib.ast.FeatureBlock(self.feature)
        ast.statements.append(fontTools.feaLib.ast.ScriptStatement(self.script))
        ast.statements.append(fontTools.feaLib.ast.LanguageStatement(self.language))
        ast.statements.append(fontTools.feaLib.ast.LookupFlagStatement(fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS))
        ast.statements.extend(r.to_ast(class_asts, contextual, multiple) for r in self.rules)
        return ast

    def append(self, rule):
        self.rules.append(rule)

    def extend(self, other):
        assert self.feature == other.feature, "Incompatible features: '{}', '{}'".format(self.feature, other.feature)
        assert self.script == other.script, "Incompatible scripts: '{}', '{}'".format(self.script, other.script)
        assert self.language == other.language, "Incompatible languages: '{}', '{}'".format(self.language, other.language)
        for rule in other.rules:
            self.append(rule)

def dont_ignore_default_ignorables(schemas, new_schemas, classes, add_rule):
    lookup_1 = Lookup('ccmp', 'dupl', 'dflt')
    lookup_2 = Lookup('ccmp', 'dupl', 'dflt')
    for schema in schemas:
        if schema.ignored:
            add_rule(lookup_1, Substitution([schema], [schema, schema]))
            add_rule(lookup_2, Substitution([schema, schema], [schema]))
    return [lookup_1, lookup_2]

def ligate_pernin_r(schemas, new_schemas, classes, add_rule):
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
                and STYLE.PERNIN in schema.styles):
            classes['ll_vowel'].append(schema)
            vowels.append(schema)
    assert classes['ll_vowel'], 'No Pernin circle vowels found'
    if vowels:
        add_rule(liga, Substitution([], 'll_vowel', [zwj, r, 'll_vowel'], 'll_vowel'))
        add_rule(dlig, Substitution([], 'll_vowel', [r, 'll_vowel'], 'll_vowel'))
    for vowel in vowels:
        reversed_vowel = vowel.clone(
            cp=-1,
            path=vowel.path.clone(clockwise=not vowel.path.clockwise, reversed=True),
            cps=vowel.cps + zwj.cps + r.cps,
        )
        add_rule(liga, Substitution([vowel, zwj, r], [reversed_vowel]))
        add_rule(dlig, Substitution([vowel, r], [reversed_vowel]))
    return [liga, dlig]

def decompose(schemas, new_schemas, classes, add_rule):
    lookup = Lookup('abvs', 'dupl', 'dflt')
    for schema in schemas:
        if schema.marks and schema in new_schemas:
            add_rule(lookup, Substitution([schema], [schema.without_marks] + schema.marks))
    return [lookup]

def ss_pernin(schemas, new_schemas, classes, add_rule):
    lookup = Lookup('ss01', 'dupl', 'dflt')
    for schema in schemas:
        if schema in new_schemas and schema.ss_pernin:
            add_rule(lookup, Substitution([schema], [schema.clone(cp=-1, ss_pernin=None, ss=1, **schema.ss_pernin)]))
    return [lookup]

def join_with_previous(schemas, new_schemas, classes, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt')
    contexts_in = OrderedSet()
    new_contexts_in = set()
    old_input_count = len(classes['jp_i'])
    for schema in schemas:
        if not schema.anchor:
            if (schema.joining_type == TYPE.ORIENTING
                    and schema.context_in == NO_CONTEXT
                    and schema in new_schemas):
                classes['jp_i'].append(schema)
            if schema.joining_type != TYPE.NON_JOINING:
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
            add_rule(lookup, Substitution('jp_c_' + str(context_in), 'jp_i', [], output_class_name))
    return [lookup]

def join_with_next(schemas, new_schemas, classes, add_rule):
    lookup = Lookup('rclt', 'dupl', 'dflt')
    contexts_out = OrderedSet()
    new_contexts_out = set()
    old_input_count = len(classes['jn_i'])
    for schema in schemas:
        if not schema.anchor:
            if (schema.joining_type == TYPE.ORIENTING
                    and schema.context_out == NO_CONTEXT
                    and schema in new_schemas):
                classes['jn_i'].append(schema)
            if schema.joining_type != TYPE.NON_JOINING:
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
            add_rule(lookup, Substitution([], 'jn_i', 'jn_c_' + str(context_out), output_class_name))
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
    for phase in phases:
        all_output_schemas = OrderedSet()
        autochthonous_schemas = OrderedSet()
        new_input_schemas = OrderedSet(all_input_schemas)
        output_schemas = OrderedSet(all_input_schemas)
        classes = collections.defaultdict(list)
        lookups = None
        while new_input_schemas:
            in_phase = False
            output_lookups = phase(
                all_input_schemas,
                new_input_schemas,
                classes,
                lambda lookup, rule: add_rule(autochthonous_schemas, output_schemas, classes, lookup, rule))
            new_input_schemas = OrderedSet()
            for output_schema in output_schemas:
                all_output_schemas.add(output_schema)
                if output_schema not in all_input_schemas:
                    all_input_schemas.add(output_schema)
                    autochthonous_schemas.add(output_schema)
                    new_input_schemas.add(output_schema)
            if lookups is None:
                lookups = output_lookups
            else:
                assert len(lookups) == len(output_lookups), 'Incompatible lookup counts for phase {}'.format(phase)
                for i, lookup in enumerate(lookups):
                    lookup.extend(output_lookups[i])
        all_input_schemas = all_output_schemas
        all_schemas.update(all_input_schemas)
        all_lookups.extend(lookups)
        all_classes.update(classes)
    return all_schemas, all_lookups, all_classes

class OrderedDefaultDict(collections.OrderedDict, collections.defaultdict):
    def __init__(self, default_factory):
        super(OrderedDefaultDict, self).__init__()
        self.default_factory = default_factory

class Grouper(object):
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
    group_dict = OrderedDefaultDict(list)
    for schema in schemas:
        group_dict[schema.group].append(schema)
    return Grouper(group_dict.viewvalues())

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
                                    new_groups = OrderedDefaultDict(list)
                                    for input_schema, output_schema in zip(cls, output):
                                        if input_schema in intersection_set:
                                            key = id(grouper.group_of(output_schema) or output_schema)
                                            new_groups[key].append(input_schema)
                                    for new_group in new_groups.viewvalues():
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
    for i, group in enumerate(groups):
        group.sort(key=Schema.sort_key)
        group = iter(group)
        canonical_schema = next(group)
        canonical_name = canonical_schema.calculate_name()
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
    ss_pernin,
    join_with_previous,
    join_with_next,
]

SPACE = Space(0)
H = Dot()
P = Line(270)
T = Line(0)
F = Line(315)
K = Line(240)
L = Line(30)
L_SHALLOW = Line(25)
M = Curve(180, 0, False)
N = Curve(0, 180, True)
N_SHALLOW = Curve(295, 245, True)
J = Curve(90, 270, True)
J_SHALLOW = Curve(25, 335, True)
S = Curve(270, 90, False)
S_SHALLOW = Curve(335, 25, False)
S_T = Curve(270, 0, False)
S_P = Curve(270, 180, True)
T_S = Curve(0, 270, True)
W = Curve(180, 270, False)
S_N = Curve(0, 90, False)
K_R_S = Curve(90, 180, False)
S_K = Curve(90, 0, True)
O = Circle(0, 0, False, False)
O_REVERSE = Circle(0, 0, True, True)
DOWN_STEP = Space(270)
UP_STEP = Space(90)

DOT_1 = Schema(-1, H, 1, anchor=RELATIVE_1_ANCHOR)
DOT_2 = Schema(-1, H, 1, anchor=RELATIVE_2_ANCHOR)

SCHEMAS = [
    Schema(0x0020, SPACE, 260, TYPE.NON_JOINING, 260),
    Schema(0x00A0, SPACE, 260, TYPE.NON_JOINING, 260),
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
    Schema(0x200B, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, ignored=True),
    Schema(0x200C, SPACE, 0, TYPE.NON_JOINING, 0, ignored=True),
    Schema(0x200D, SPACE, 0, side_bearing=0),
    Schema(0x202F, SPACE, 200, side_bearing=200),
    Schema(0x205F, SPACE, 222, side_bearing=222),
    Schema(0x2060, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, ignored=True),
    Schema(0xFEFF, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, ignored=True),
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
    Schema(0x1BC21, M, 6, marks=[DOT_1]),
    Schema(0x1BC22, N, 6, marks=[DOT_1]),
    Schema(0x1BC23, J, 6, marks=[DOT_1], ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC24, J, 6, marks=[DOT_1, DOT_2]),
    Schema(0x1BC25, S, 6, marks=[DOT_1], ss_pernin={'path': S_SHALLOW, 'size': chord_to_radius(6, 50)}),
    Schema(0x1BC26, S, 6, marks=[DOT_2]),
    Schema(0x1BC27, M, 8),
    Schema(0x1BC28, N, 8),
    Schema(0x1BC29, J, 8, ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(8, 50)}),
    Schema(0x1BC2A, S, 8),
    Schema(0x1BC2F, J, 8, marks=[DOT_1], ss_pernin={'path': J_SHALLOW, 'size': chord_to_radius(8, 50)}),
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
    Schema(0x1BC41, O, 2, TYPE.ORIENTING, styles=[STYLE.PERNIN]),
    Schema(0x1BC42, O_REVERSE, 2, TYPE.ORIENTING),
    Schema(0x1BC43, O, 3, TYPE.ORIENTING, styles=[STYLE.PERNIN]),
    Schema(0x1BC44, O, 4, TYPE.ORIENTING, styles=[STYLE.PERNIN]),
    Schema(0x1BC45, O, 5, TYPE.ORIENTING),
    Schema(0x1BC46, M, 2, TYPE.ORIENTING),
    Schema(0x1BC47, S, 2, TYPE.ORIENTING),
    Schema(0x1BC48, M, 2),
    Schema(0x1BC49, N, 2),
    Schema(0x1BC4A, J, 2),
    Schema(0x1BC4B, S, 2),
    Schema(0x1BC4C, S, 2, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC4D, S, 2, TYPE.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC51, S_T, 2, TYPE.ORIENTING),
    Schema(0x1BC53, S_T, 2, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC5A, O, 4, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC65, S_P, 2, TYPE.ORIENTING),
    Schema(0x1BC66, W, 2, TYPE.ORIENTING),
    Schema(0x1BCA2, DOWN_STEP, 800, side_bearing=0, ignored=True),
    Schema(0x1BCA3, UP_STEP, 800, side_bearing=0, ignored=True),
]

class Builder(object):
    def __init__(self, font, schemas=SCHEMAS, phases=PHASES):
        self.font = font
        self.schemas = schemas
        self.phases = phases
        self.fea = fontTools.feaLib.ast.FeatureFile()
        code_points = collections.defaultdict(int)
        for schema in schemas:
            if schema.cp != -1:
                code_points[schema.cp] += 1
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    ' +
            '\n    '.join(map(hex, sorted(code_points.viewkeys()))))

    def add_altuni(self, cp, glyph_name):
        glyph = self.font.temporary[glyph_name]
        if cp != -1:
            new_altuni = ((cp, -1, 0),)
            if glyph.altuni is None:
                glyph.altuni = new_altuni
            else:
                glyph.altuni += new_altuni
        return glyph

    def draw_glyph_with_marks(self, schema, glyph_name):
        base_glyph = self.draw_glyph(schema.without_marks).glyphname
        mark_glyphs = []
        for mark in schema.marks:
            mark_glyphs.append(self.draw_glyph(mark).glyphname)
        glyph = self.font.createChar(schema.cp, glyph_name)
        self._refresh(glyph)
        self.font.temporary[glyph_name] = glyph
        glyph.glyphclass = 'baseglyph'
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

    def draw_base_glyph(self, schema, glyph_name):
        glyph = self.font.createChar(schema.cp, glyph_name)
        self.font.temporary[glyph_name] = glyph
        glyph.glyphclass = 'mark' if schema.anchor else 'baseglyph'
        pen = glyph.glyphPen()
        schema.path(glyph, pen, schema.size, schema.anchor, schema.joining_type)
        return glyph

    def draw_glyph(self, schema):
        glyph_name = str(schema)
        if glyph_name in self.font.temporary:
            return self.add_altuni(schema.cp, glyph_name)
        if schema.marks:
            glyph = self.draw_glyph_with_marks(schema, glyph_name)
        else:
            glyph = self.draw_base_glyph(schema, glyph_name)
        glyph.left_side_bearing = schema.side_bearing
        glyph.right_side_bearing = schema.side_bearing
        bbox = glyph.boundingBox()
        center = (bbox[3] - bbox[1]) / 2 + bbox[1]
        glyph.transform(psMat.translate(0, BASELINE - center))
        return glyph

    def _refresh(self, glyph):
        # Work around https://github.com/fontforge/fontforge/issues/3278
        glyph.glyphname = glyph.glyphname

    def augment(self):
        add_lookups(self.font)
        self.font.temporary = {}
        schemas, lookups, classes = run_phases(self.schemas, self.phases)
        merge_schemas(schemas, lookups, classes)
        for schema in schemas:
            glyph = self.draw_glyph(schema)
        class_asts = {}
        for name, schemas in sorted(classes.items()):
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                fontTools.misc.py23.tounicode(name),
                fontTools.feaLib.ast.GlyphClass([fontTools.misc.py23.tounicode(str(s)) for s in schemas]))
            self.fea.statements.append(class_ast)
            class_asts[name] = class_ast
        self.fea.statements.extend(l.to_ast(class_asts) for l in lookups)

    def merge_features(self, tt_font, old_fea):
        self.fea.statements.extend(
            fontTools.feaLib.parser.Parser(
                fontTools.misc.py23.UnicodeIO(fontTools.misc.py23.tounicode(old_fea)),
                tt_font.getReverseGlyphMap())
            .parse().statements)
        fontTools.feaLib.builder.addOpenTypeFeatures(tt_font, self.fea)

