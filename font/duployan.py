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

import math

import fontforge
import psMat

BASELINE = 402
CURSIVE_ANCHOR = 'cursive'
CURSIVE_LOOKUP = "'curs'"
CURSIVE_SUBTABLE = CURSIVE_LOOKUP + '-1'
SIDE_BEARING = 85
STROKE_WIDTH = 70

def add_lookups(font):
    font.addLookup(CURSIVE_LOOKUP,
        'gpos_cursive',
        ('ignore_marks',),
        (('curs', (('dupl', ('dflt',)),)),))
    font.addLookupSubtable(CURSIVE_LOOKUP, CURSIVE_SUBTABLE)
    font.addAnchorClass(CURSIVE_SUBTABLE, CURSIVE_ANCHOR)

def line(glyph, pen, size, angle):
    pen.moveTo((0, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
    if angle % 180 == 0:
        pen.lineTo((500 * size, 0))
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 500 * size, 0)
    else:
        pen.lineTo((0, 500 * size))
        glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 500 * size)
        if 180 < angle:
            skew = angle + 270
        else:
            skew = -angle - 90
        glyph.transform(psMat.skew(math.radians(skew)), ('round',))
        if 180 < angle:
            glyph.transform(psMat.scale(1, -1))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def b(glyph, pen, size):
    line(glyph, pen, size, 270)

def d(glyph, pen, size):
    line(glyph, pen, size, 0)

def v(glyph, pen, size):
    line(glyph, pen, size, 315)

def g(glyph, pen, size):
    line(glyph, pen, size, 240)

def r(glyph, pen, size):
    line(glyph, pen, size, 30)

def rect(r, theta):
    return (r * math.cos(theta), r * math.sin(theta))

def curve(glyph, pen, size, angle_in, angle_out, clockwise):
    if clockwise and angle_out > angle_in:
        angle_out -= 360
    elif not clockwise and angle_out < angle_in:
        angle_out += 360
    a1 = (90 if clockwise else -90) + angle_in
    a2 = (90 if clockwise else -90) + angle_out
    r = 250 * size
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

def m(glyph, pen, size):
    curve(glyph, pen, size, 180, 0, False)

def n(glyph, pen, size):
    curve(glyph, pen, size, 0, 180, True)

def j(glyph, pen, size):
    curve(glyph, pen, size, 90, 270, True)

def s(glyph, pen, size):
    curve(glyph, pen, size, 270, 90, False)

def circle(glyph, pen, size, angle_in, angle_out, clockwise):
    if clockwise and angle_out > angle_in:
        angle_out -= 360
    elif not clockwise and angle_out < angle_in:
        angle_out += 360
    a1 = (90 if clockwise else -90) + angle_in
    a2 = (90 if clockwise else -90) + angle_out
    r = 100 * size
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

def o(glyph, pen, size):
    circle(glyph, pen, size, 0, 0, False)

def draw_glyph(font, cp, schema):
    glyph = font.createChar(cp, str(schema))
    glyph.glyphclass = 'baseglyph'
    pen = glyph.glyphPen()
    schema.path(glyph, pen, schema.size)
    glyph.left_side_bearing = SIDE_BEARING
    glyph.right_side_bearing = SIDE_BEARING
    bbox = glyph.boundingBox()
    center = (bbox[3] - bbox[1]) / 2 + bbox[1]
    glyph.transform(psMat.translate(0, BASELINE - center))

class Schema(object):
    def __init__(self, path, size):
        self.path = path
        self.size = size

    def __str__(self):
        return self.path.__name__ + str(self.size)

DUPLOYAN = {
    0x1BC02: Schema(b, 1),
    0x1BC03: Schema(d, 1),
    0x1BC04: Schema(v, 1),
    0x1BC05: Schema(g, 1),
    0x1BC06: Schema(r, 1),
    0x1BC07: Schema(b, 2),
    0x1BC08: Schema(d, 2),
    0x1BC09: Schema(v, 2),
    0x1BC0A: Schema(g, 2),
    0x1BC0B: Schema(r, 2),
    0x1BC19: Schema(m, 2),
    0x1BC1A: Schema(n, 2),
    0x1BC1B: Schema(j, 2),
    0x1BC1C: Schema(s, 2),
    0x1BC44: Schema(o, 2),
}

def augment(font):
    add_lookups(font)
    for cp, schema in DUPLOYAN.items ():
        draw_glyph(font, cp, schema)

