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
CURSIVE_ANCHOR = 'cursive'
CURSIVE_LOOKUP = "'curs'"
CURSIVE_SUBTABLE = CURSIVE_LOOKUP + '-1'
RADIUS = 100
SIDE_BEARING = 85
STROKE_WIDTH = 70

def add_lookups(font):
    font.addLookup(CURSIVE_LOOKUP,
        'gpos_cursive',
        ('ignore_marks',),
        (('curs', (('dupl', ('dflt',)),)),))
    font.addLookupSubtable(CURSIVE_LOOKUP, CURSIVE_SUBTABLE)
    font.addAnchorClass(CURSIVE_SUBTABLE, CURSIVE_ANCHOR)

def rect(r, theta):
    return (r * math.cos(theta), r * math.sin(theta))

class Line(object):
    def __init__(self, angle):
        self.angle_in = angle
        self.angle_out = angle

    def __str__(self):
        name = ''
        if self.angle_in == 0:
            name = 'D'
        if self.angle_in == 30:
            name = 'R'
        if self.angle_in == 240:
            name = 'G'
        if self.angle_in == 270:
            name = 'B'
        if self.angle_in == 315:
            name = 'V'
        return 'ligne{}.{}.{}'.format(name, self.angle_in, self.angle_out)

    def __call__(self, glyph, pen, size):
        pen.moveTo((0, 0))
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
        if self.angle_in % 180 == 0:
            pen.lineTo((500 * size, 0))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 500 * size, 0)
        else:
            pen.lineTo((0, 500 * size))
            glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 500 * size)
            if 180 < self.angle_in:
                skew = self.angle_in + 270
            else:
                skew = -self.angle_in - 90
            glyph.transform(psMat.skew(math.radians(skew)), ('round',))
            if 180 < self.angle_in:
                glyph.transform(psMat.scale(1, -1))
        glyph.stroke('circular', STROKE_WIDTH, 'round')

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

    def __call__(self, glyph, pen, size):
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
        x = r * math.cos(math.radians(a1))
        y = r * math.sin(math.radians(a1))
        pen.moveTo(rect(r, math.radians(a1)))
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', x, y)
        for i in range(1, beziers_needed + 1):
            theta0 = math.radians(a1 + (i - 1) * bezier_arc)
            p0 = rect(r, theta0)
            p1 = rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = rect(r, theta3)
            p2 = rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', p3[0], p3[1])
        pen.endPath()
        glyph.stroke('circular', STROKE_WIDTH, 'round')

    def contextualize(self, angle_in, angle_out):
        if angle_in is None:
            if angle_out is not None:
                angle_in = (angle_out + self.angle_in - self.angle_out) % 360
            else:
                angle_in = self.angle_in
        return Curve(
            angle_in,
            (angle_in + self.angle_out - self.angle_in) % 360,
            self.clockwise if angle_out is None else (abs(angle_out - angle_in) >= 180) == (angle_out > angle_in))

class Circle(object):
    def __init__(self, angle_in, angle_out, clockwise):
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise

    def __str__(self):
        return 'cercle.{}.{}.{}'.format(
            self.angle_in, self.angle_out, 'neg' if self.clockwise else 'pos')

    def __call__(self, glyph, pen, size):
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
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', *rect(r, math.radians(a1)))
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', *rect(r, math.radians(a2)))

    def contextualize(self, angle_in, angle_out):
        if angle_in is None:
            if angle_out is None:
                angle_in = 0
            else:
                angle_in = angle_out
        if angle_out is None:
            angle_out = angle_in
        if angle_in == angle_out:
            return Circle(angle_in, angle_out, self.clockwise)
        return Curve(angle_in, angle_out,
            (abs(angle_out - angle_in) >= 180) != (angle_out > angle_in))

class Schema(object):
    def __init__(self, cp, path, size, orienting=False):
        self.cp = cp
        self.path = path
        self.size = size
        self.orienting = orienting

    def __str__(self):
        return '{}.{}.{}'.format(self.path, self.size,
            'con' if self.orienting and self.cp == -1 else 'nom')

    def contextualize(self, angle_in, angle_out):
        assert self.orienting
        return Schema(-1,
            self.path.contextualize(angle_in, angle_out),
            self.size,
            self.orienting)

def class_key(class_item):
    glyph_class, glyphs = class_item
    return -glyph_class.count('_'), glyph_class, glyphs

def merge_feature(font, feature_string):
    fea_path = tempfile.mkstemp(suffix='.fea')[1]
    try:
        with open(fea_path, 'w') as fea:
            fea.write(feature_string)
        font.mergeFeature(fea_path)
    finally:
        os.remove(fea_path)

class GlyphManager(object):
    def __init__(self, font, schemas):
        self.font = font
        self.schemas = schemas
        self.classes = collections.defaultdict(list)
        self._canonical_classes = collections.defaultdict(set)
        self.angles_in = set()
        self.angles_out = set()
        for schema in self.schemas:
            self.angles_in.add(schema.path.angle_in)
            self.angles_out.add(schema.path.angle_out)
            if schema.orienting:
                delta = int((schema.path.angle_out - schema.path.angle_in) % 360)
                deltas = {delta}
                ndelta = delta
                while True:
                    ndelta = (ndelta + delta) % 360
                    if ndelta in deltas:
                        break
                    deltas.add(ndelta)
                for angle_out in set(self.angles_out):
                    for delta in deltas:
                        self.angles_out.add((angle_out + delta) % 360)

    def refresh(self):
        # Work around https://github.com/fontforge/fontforge/issues/3278
        sfd_path = 'refresh.sfd'
        assert not os.path.exists(sfd_path), '{} already exists'.format(sfd_path)
        self.font.save(sfd_path)
        self.font = fontforge.open(sfd_path)
        os.remove(sfd_path)

    def draw_glyph(self, schema):
        glyph_name = str(schema)
        if glyph_name in self.font.temporary:
            return self.font.temporary[glyph_name]
        glyph = self.font.createChar(schema.cp, glyph_name)
        self.font.temporary[glyph_name] = glyph
        glyph.glyphclass = 'baseglyph'
        pen = glyph.glyphPen()
        schema.path(glyph, pen, schema.size)
        glyph.left_side_bearing = SIDE_BEARING
        glyph.right_side_bearing = SIDE_BEARING
        bbox = glyph.boundingBox()
        center = (bbox[3] - bbox[1]) / 2 + bbox[1]
        glyph.transform(psMat.translate(0, BASELINE - center))
        angle_in = schema.path.angle_in
        angle_out = schema.path.angle_out
        if glyph.glyphname not in self.classes['i{}'.format(angle_in)]:
            self.classes['i{}'.format(angle_in)].append(glyph.glyphname)
        if glyph.glyphname not in self.classes['o{}'.format(angle_out)]:
            self.classes['o{}'.format(angle_out)].append(glyph.glyphname)
        return glyph

    def run(self):
        self.font.temporary = {}
        for schema in self.schemas:
            glyph = self.draw_glyph(schema)
            if schema.orienting:
                self.classes['nominal'].append(glyph.glyphname)
                for angle_in in self.angles_out:
                    for angle_out in self.angles_in:
                        glyph = self.draw_glyph(schema.contextualize(angle_in, angle_out))
                        self.classes['medial_{}_{}'.format(angle_in, angle_out)].append(glyph.glyphname)
                for angle_in in self.angles_out:
                    glyph = self.draw_glyph(schema.contextualize(angle_in, None))
                    self.classes['final_{}'.format(angle_in)].append(glyph.glyphname)
                for angle_out in self.angles_in:
                    glyph = self.draw_glyph(schema.contextualize(None, angle_out))
                    self.classes['initial_{}'.format(angle_out)].append(glyph.glyphname)
        self.refresh()
        final_lookup_string = ('feature rclt {\n'
            '    languagesystem dupl dflt;\n')
        nonfinal_lookup_string = final_lookup_string
        for glyph_class, glyphs in sorted(self.classes.items(), key=class_key):
            class_fields = glyph_class.split('_')
            if glyph_class.startswith('final_'):
                prev_class = 'o' + class_fields[1]
                final_lookup_string += "    substitute @{} @nominal' by @{};\n".format(
                    prev_class, glyph_class)
            elif glyph_class.startswith('medial_'):
                target_class = 'final_' + class_fields[1]
                next_class = 'i' + class_fields[2]
                nonfinal_lookup_string += "    substitute @{}' @{} by @{};\n".format(
                    target_class, next_class, glyph_class)
            elif glyph_class.startswith('initial_'):
                next_class = 'i' + class_fields[1]
                nonfinal_lookup_string += "    substitute @nominal' @{} by @{};\n".format(
                    next_class, glyph_class)
        final_lookup_string += '} rclt;\n'
        nonfinal_lookup_string += '} rclt;\n'
        classes_string = ''
        for glyph_class, glyphs in self.classes.items():
            classes_string += '@{} = [{}];\n'.format(glyph_class, ' '.join(glyphs))
        merge_feature(self.font, classes_string + final_lookup_string + nonfinal_lookup_string)
        return self.font

B = Line(270)
D = Line(0)
V = Line(315)
G = Line(240)
R = Line(30)
M = Curve(180, 0, False)
N = Curve(0, 180, True)
J = Curve(90, 270, True)
S = Curve(270, 90, False)
O = Circle(0, 0, False)

SCHEMAS = [
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
    Schema(0x1BC19, M, 3),
    Schema(0x1BC1A, N, 3),
    Schema(0x1BC1B, J, 3),
    Schema(0x1BC1C, S, 3),
    Schema(0x1BC41, O, 1, True),
    Schema(0x1BC44, O, 2, True),
    Schema(0x1BC46, M, 1, True),
    Schema(0x1BC47, S, 1, True),
]

def augment(font):
    add_lookups(font)
    return GlyphManager(font, SCHEMAS).run()

