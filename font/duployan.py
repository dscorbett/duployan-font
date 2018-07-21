# Copyright 2018 David Corbett
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

__all__ = ['augment']

import collections
import math
import os
import tempfile

import fontforge
import psMat

BASELINE = 402
DEFAULT_SIDE_BEARING = 85
RADIUS = 100
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

    def __str__(self):
        if self.angle is None:
            return ''
        return '{}{}'.format(
            self.angle,
            '' if self.clockwise is None else 'neg' if self.clockwise else 'pos')

    def __eq__(self, other):
        return self.angle == other.angle and self.clockwise == other.clockwise

    def __hash__(self):
        return hash(self.angle) ^ hash(self.clockwise)

def rect(r, theta):
    return (r * math.cos(theta), r * math.sin(theta))

class Space(object):
    def __init__(self, angle):
        self.angle = angle

    def __str__(self):
        return 'espace.{}'.format(self.angle)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        if joining_type != TYPE.NON_JOINING:
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', -size, 0)
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 0)
            glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))

    def context_in(self):
        return Context()

    def context_out(self):
        return Context()

class Dot(object):
    def __str__(self):
        return 'point'

    def __call__(self, glyph, pen, size, anchor, joining_type):
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', STROKE_WIDTH, 'round')
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(0, 0))

    def context_in(self):
        return Context()

    def context_out(self):
        return Context()

class Line(object):
    def __init__(self, angle):
        self.angle = angle

    def __str__(self):
        name = ''
        if self.angle == 0:
            name = 'D'
        if self.angle == 30:
            name = 'R'
        if self.angle == 240:
            name = 'G'
        if self.angle == 270:
            name = 'B'
        if self.angle == 315:
            name = 'V'
        return 'ligne{}.{}'.format(name, self.angle)

    def __call__(self, glyph, pen, size, anchor, joining_type):
        pen.moveTo((0, 0))
        length = 500 * (size or 0.2) / (abs(math.sin(math.radians(self.angle))) or 1)
        pen.lineTo((length, 0))
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *rect(length / 2, 0))
        else:
            if joining_type != TYPE.NON_JOINING:
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
                glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', length, 0)
            glyph.addAnchorPoint(RELATIVE_1_ANCHOR, 'base', length / 2, STROKE_WIDTH)
            glyph.addAnchorPoint(RELATIVE_2_ANCHOR, 'base', length / 2, -STROKE_WIDTH)
        glyph.transform(psMat.rotate(math.radians(self.angle)), ('round',))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def context_in(self):
        return Context(self.angle)

    def context_out(self):
        return Context(self.angle)

class Curve(object):
    def __init__(self, angle_in, angle_out, clockwise):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise

    def __str__(self):
        name = ''
        if self.angle_in == 0 and self.angle_out == 180 and self.clockwise:
            name = 'N'
        if self.angle_in == 90 and self.angle_out == 270 and self.clockwise:
            name = 'J'
        if self.angle_in == 180 and self.angle_out == 0 and not self.clockwise:
            name = 'M'
        if self.angle_in == 270 and self.angle_out == 90 and not self.clockwise:
            name = 'S'
        return 'courbe{}.{}.{}.{}'.format(
            name, self.angle_in, self.angle_out, 'neg' if self.clockwise else 'pos')

    def __call__(self, glyph, pen, size, anchor, joining_type):
        assert anchor is None
        angle_out = self.angle_out
        if self.clockwise and angle_out > self.angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < self.angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + self.angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        r = RADIUS * size
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
            *(rect(0, 0) if da > 180 else rect(
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

class Circle(object):
    def __init__(self, angle_in, angle_out, clockwise):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise

    def __str__(self):
        return 'cercle.{}.{}.{}'.format(
            self.angle_in, self.angle_out, 'neg' if self.clockwise else 'pos')

    def __call__(self, glyph, pen, size, anchor, joining_type):
        assert anchor is None
        angle_out = self.angle_out
        if self.clockwise and self.angle_out > self.angle_in:
            angle_out -= 360
        elif not self.clockwise and self.angle_out < self.angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + self.angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        r = RADIUS * size
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
                clockwise_from_adjacent_curve
                    if clockwise_from_adjacent_curve is not None
                    else self.clockwise)
        da = abs(angle_out - angle_in)
        clockwise_ignoring_curvature = (da >= 180) != (angle_out > angle_in)
        clockwise = (
            clockwise_from_adjacent_curve
                if clockwise_from_adjacent_curve is not None
                else clockwise_ignoring_curvature)
        shape = Curve if clockwise == clockwise_ignoring_curvature else Circle
        return shape(angle_in, angle_out, clockwise)

    def context_in(self):
        return Context(self.angle_in, self.clockwise)

    def context_out(self):
        return Context(self.angle_out, self.clockwise)

class Schema(object):
    def __init__(
            self,
            cp,
            path,
            size,
            joining_type=TYPE.JOINING,
            side_bearing=DEFAULT_SIDE_BEARING,
            anchor=None,
            marks=None,
            default_ignorable=False,
            _origin='_'):
        assert not (marks and anchor), 'A schema has both marks {} and anchor {}'.format(marks, anchor)
        self.cp = cp
        self.path = path
        self.size = size
        self.joining_type = joining_type
        self.side_bearing = side_bearing
        self.anchor = anchor
        self.marks = marks or []
        self.default_ignorable = default_ignorable
        self._origin = _origin

    def __str__(self):
        return '{}.{}.{}{}{}{}'.format(
            self.path,
            self.size,
            str(self.side_bearing) + '.' if self.side_bearing != DEFAULT_SIDE_BEARING else '',
            'neu' if self.joining_type == TYPE.NON_JOINING else self._origin,
            '.' + self.anchor if self.anchor else '',
            '.' + '.'.join(map(str, self.marks)) if self.marks else '')

    def contextualize(self, context_in, context_out, origin):
        assert self.joining_type == TYPE.ORIENTING
        return Schema(-1,
            self.path.contextualize(context_in, context_out),
            self.size,
            self.joining_type,
            self.side_bearing,
            _origin=origin)

    def without_marks(self):
        return Schema(
            -1,
            self.path,
            self.size,
            self.joining_type,
            self.side_bearing,
            self.anchor)

def class_key(class_item):
    glyph_class, glyphs = class_item
    return -len(filter(None, glyph_class.split('_'))), glyph_class, glyphs

def merge_feature(font, feature_string):
    fea_path = tempfile.mkstemp(suffix='.fea')[1]
    try:
        with open(fea_path, 'w') as fea:
            fea.write(feature_string)
        font.mergeFeature(fea_path)
    finally:
        os.remove(fea_path)

def wrap(tag, lookup):
    return ('feature {} {{\n'
        '    languagesystem dupl dflt;\n'
        '    lookupflag IgnoreMarks;\n'
        '{}}} {};\n').format(tag, lookup, tag)

class GlyphManager(object):
    def __init__(self, font, schemas):
        self.font = font
        self.schemas = schemas
        self.classes = collections.defaultdict(list)
        self.contexts_in = {Context()}
        self.contexts_out = {Context()}
        code_points = collections.defaultdict(int)
        for schema in self.schemas:
            if schema.cp != -1:
                code_points[schema.cp] += 1
            if schema.joining_type == TYPE.NON_JOINING:
                continue
            self.contexts_in.add(schema.path.context_in())
            self.contexts_out.add(schema.path.context_out())
            if schema.joining_type == TYPE.ORIENTING:
                angle_out = schema.path.context_out().angle
                delta = int((angle_out - schema.path.context_in().angle) % 360)
                deltas = {delta}
                ndelta = delta
                while True:
                    ndelta = (ndelta + delta) % 360
                    if ndelta in deltas:
                        break
                    deltas.add(ndelta)
                for context_out in set(self.contexts_out):
                    for delta in deltas:
                        self.contexts_out.add(Context((angle_out + delta) % 360))
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    ' +
            '\n    '.join(map(hex, sorted(code_points.keys()))))

    def refresh(self):
        # Work around https://github.com/fontforge/fontforge/issues/3278
        sfd_path = 'refresh.sfd'
        assert not os.path.exists(sfd_path), '{} already exists'.format(sfd_path)
        self.font.save(sfd_path)
        temporary = self.font.temporary
        self.font = fontforge.open(sfd_path)
        self.font.temporary = temporary
        os.remove(sfd_path)

    def draw_glyph_with_marks(self, schema, glyph_name):
        base_glyph = self.draw_glyph(schema.without_marks()).glyphname
        mark_glyphs = []
        for mark in schema.marks:
            mark_glyphs.append(self.draw_glyph(mark).glyphname)
        self.refresh()
        glyph = self.font.createChar(schema.cp, glyph_name)
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

    def add_altuni(self, cp, glyph_name):
        glyph = self.font.temporary[glyph_name]
        if cp != -1:
            new_altuni = ((cp, -1, 0),)
            if glyph.altuni is None:
                glyph.altuni = new_altuni
            else:
                glyph.altuni += new_altuni
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
        if schema.joining_type != TYPE.NON_JOINING:
            class_in = 'i{}'.format(schema.path.context_in())
            class_out = 'o{}'.format(schema.path.context_out())
            if glyph.glyphname not in self.classes[class_in]:
                self.classes[class_in].append(glyph.glyphname)
            if glyph.glyphname not in self.classes[class_out]:
                self.classes[class_out].append(glyph.glyphname)
        return glyph

    def run(self):
        self.font.temporary = {}
        ignorable_lookup_string_1 = ''
        ignorable_lookup_string_2 = ''
        decomposition_lookup_string = ''
        for schema in self.schemas:
            glyph = self.draw_glyph(schema)
            if glyph.altuni:
                # This glyph has already been processed.
                continue
            if schema.marks:
                decomposition_lookup_string += '    substitute {} by {};\n'.format(
                    glyph.glyphname, ' '.join(reversed([r[0] for r in glyph.references])))
            elif schema.joining_type == TYPE.ORIENTING:
                self.classes['nominal'].append(glyph.glyphname)
                for context_in in self.contexts_out:
                    for context_out in self.contexts_in:
                        contextual_class = 'contextual_{}_{}'.format(context_in, context_out)
                        glyph = self.draw_glyph(schema.contextualize(context_in, context_out, contextual_class))
                        self.classes[contextual_class].append(glyph.glyphname)
            elif schema.default_ignorable:
                ignorable_lookup_string_1 += '    substitute {} by {} {};\n'.format(
                    glyph.glyphname, glyph.glyphname, glyph.glyphname)
                ignorable_lookup_string_2 += '    substitute {} {} by {};\n'.format(
                    glyph.glyphname, glyph.glyphname, glyph.glyphname)
        final_lookup_string = ''
        nonfinal_lookup_string = ''
        for glyph_class, glyphs in sorted(self.classes.items(), key=class_key):
            class_fields = glyph_class.split('_')
            if glyph_class.startswith('contextual_'):
                next_class = class_fields[2] and '@i' + class_fields[2]
                prev_class = '' if next_class else class_fields[1] and '@o' + class_fields[1]
                if prev_class or next_class:
                    target_class = ('@contextual_{}_'.format(class_fields[1])
                        if class_fields[1] and class_fields[2]
                        else '@nominal')
                    if ((not prev_class or prev_class[1:] in self.classes) and
                            (not target_class or target_class[1:] in self.classes) and
                            (not prev_class or prev_class[1:] in self.classes)):
                        topographical_lookup_string = "    substitute {} {}' {} by @{};\n".format(
                            prev_class, target_class, next_class, glyph_class)
                        if prev_class:
                            final_lookup_string += topographical_lookup_string
                        else:
                            nonfinal_lookup_string += topographical_lookup_string
        classes_string = ''
        for glyph_class, glyphs in self.classes.items():
            classes_string += '@{} = [{}];\n'.format(glyph_class, ' '.join(glyphs))
        self.refresh()
        merge_feature(self.font,
            classes_string
            + wrap('ccmp', ignorable_lookup_string_1)
            + wrap('ccmp', ignorable_lookup_string_2)
            + wrap('ccmp', decomposition_lookup_string)
            + wrap('rclt', final_lookup_string)
            + wrap('rclt', nonfinal_lookup_string))
        return self.font

SPACE = Space(0)
H = Dot()
B = Line(270)
D = Line(0)
V = Line(315)
G = Line(240)
R = Line(30)
M = Curve(180, 0, False)
N = Curve(0, 180, True)
J = Curve(90, 270, True)
S = Curve(270, 90, False)
S_T = Curve(270, 0, False)
S_P = Curve(270, 180, True)
T_S = Curve(0, 270, True)
W = Curve(180, 270, False)
S_N = Curve(0, 90, False)
G_R_S = Curve(90, 180, False)
S_K = Curve(90, 0, True)
O = Circle(0, 0, False)
DOWN_STEP = Space(270)
UP_STEP = Space(90)

DOT_1 = Schema(-1, H, 1, anchor=RELATIVE_1_ANCHOR)
DOT_2 = Schema(-1, H, 1, anchor=RELATIVE_2_ANCHOR)

SCHEMAS = [
    Schema(0x0020, SPACE, 260, TYPE.NON_JOINING, 260),
    Schema(0x00A0, SPACE, 260, TYPE.NON_JOINING, 260),
    Schema(0x0304, D, 0, anchor=ABOVE_ANCHOR),
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
    Schema(0x200B, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, default_ignorable=True),
    Schema(0x200C, SPACE, 0, TYPE.NON_JOINING, 0, default_ignorable=True),
    Schema(0x202F, SPACE, 200, side_bearing=200),
    Schema(0x205F, SPACE, 222, side_bearing=222),
    Schema(0x2060, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, default_ignorable=True),
    Schema(0xFEFF, SPACE, 2 * DEFAULT_SIDE_BEARING, side_bearing=0, default_ignorable=True),
    Schema(0x1BC00, H, 1),
    Schema(0x1BC02, B, 1),
    Schema(0x1BC03, D, 1),
    Schema(0x1BC04, V, 1),
    Schema(0x1BC05, G, 1),
    Schema(0x1BC06, R, 1),
    Schema(0x1BC07, B, 2),
    Schema(0x1BC08, D, 2),
    Schema(0x1BC09, V, 2),
    Schema(0x1BC0A, G, 2),
    Schema(0x1BC0B, R, 2),
    Schema(0x1BC0C, B, 3),
    Schema(0x1BC0D, D, 3),
    Schema(0x1BC0E, V, 3),
    Schema(0x1BC0F, G, 3),
    Schema(0x1BC10, R, 3),
    Schema(0x1BC11, D, 1, marks=[DOT_1]),
    Schema(0x1BC12, D, 1, marks=[DOT_2]),
    Schema(0x1BC13, D, 2, marks=[DOT_1]),
    Schema(0x1BC14, G, 1, marks=[DOT_2]),
    Schema(0x1BC15, G, 2, marks=[DOT_1]),
    Schema(0x1BC16, R, 1, marks=[DOT_1]),
    Schema(0x1BC17, R, 1, marks=[DOT_2]),
    Schema(0x1BC19, M, 3),
    Schema(0x1BC1A, N, 3),
    Schema(0x1BC1B, J, 3),
    Schema(0x1BC1C, S, 3),
    Schema(0x1BC21, M, 3, marks=[DOT_1]),
    Schema(0x1BC22, N, 3, marks=[DOT_1]),
    Schema(0x1BC23, J, 3, marks=[DOT_1]),
    Schema(0x1BC24, J, 3, marks=[DOT_1, DOT_2]),
    Schema(0x1BC25, S, 3, marks=[DOT_1]),
    Schema(0x1BC26, S, 3, marks=[DOT_2]),
    Schema(0x1BC27, M, 4),
    Schema(0x1BC28, N, 4),
    Schema(0x1BC29, J, 4),
    Schema(0x1BC2A, S, 4),
    Schema(0x1BC2F, J, 4, marks=[DOT_1]),
    Schema(0x1BC32, S_T, 2),
    Schema(0x1BC33, S_T, 3),
    Schema(0x1BC34, S_P, 2),
    Schema(0x1BC35, S_P, 3),
    Schema(0x1BC36, T_S, 2),
    Schema(0x1BC37, T_S, 3),
    Schema(0x1BC38, W, 2),
    Schema(0x1BC39, W, 2, marks=[DOT_1]),
    Schema(0x1BC3A, W, 3),
    Schema(0x1BC3B, S_N, 2),
    Schema(0x1BC3C, S_N, 3),
    Schema(0x1BC3D, G_R_S, 2),
    Schema(0x1BC3E, G_R_S, 3),
    Schema(0x1BC3F, S_K, 2),
    Schema(0x1BC40, S_K, 3),
    Schema(0x1BC41, O, 1, TYPE.ORIENTING),
    Schema(0x1BC44, O, 2, TYPE.ORIENTING),
    Schema(0x1BC46, M, 1, TYPE.ORIENTING),
    Schema(0x1BC47, S, 1, TYPE.ORIENTING),
    Schema(0x1BC4C, S, 1, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC4D, S, 1, TYPE.ORIENTING, marks=[DOT_2]),
    Schema(0x1BC51, S_T, 1, TYPE.ORIENTING),
    Schema(0x1BC53, S_T, 1, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC5A, O, 2, TYPE.ORIENTING, marks=[DOT_1]),
    Schema(0x1BC65, S_P, 1, TYPE.ORIENTING),
    Schema(0x1BC66, W, 1, TYPE.ORIENTING),
    Schema(0x1BCA2, DOWN_STEP, 800, side_bearing=0, default_ignorable=True),
    Schema(0x1BCA3, UP_STEP, 800, side_bearing=0, default_ignorable=True),
]

def augment(font):
    add_lookups(font)
    return GlyphManager(font, SCHEMAS).run()

