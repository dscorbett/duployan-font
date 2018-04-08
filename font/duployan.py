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

def b(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 500 * size)
    pen.lineTo((0, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 0)
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def d(glyph, pen, size):
    pen.moveTo((0, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
    pen.lineTo((500 * size, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 500 * size, 0)
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def v(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 500 * size)
    pen.lineTo((500 * size, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 500 * size, 0)
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def g(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 500 * size)
    pen.lineTo((0, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 0)
    glyph.transform(psMat.skew(math.radians(30)), ('round',))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def r(glyph, pen, size):
    pen.moveTo((0, 0))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 0)
    pen.lineTo((0, 500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, 500 * size)
    glyph.transform(psMat.skew(math.radians(60)), ('round',))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def m(glyph, pen, size):
    cp = (4 * (2 ** 0.5 - 1) / 3) * size * 500
    pen.moveTo((0, 500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'entry', 0, 500 * size)
    pen.curveTo((-cp, 500 * size), (-500 * size, cp), (-500 * size, 0))
    pen.curveTo((-500 * size, -cp), (-cp, -500 * size), (0, -500 * size))
    glyph.addAnchorPoint(CURSIVE_ANCHOR, 'exit', 0, -500 * size)
    glyph.transform(psMat.scale(0.75, 1))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def n(glyph, pen, size):
    m(glyph, pen, size)
    glyph.transform(psMat.scale(-1, 1))

def j(glyph, pen, size):
    n(glyph, pen, size)
    glyph.transform(psMat.rotate(math.radians(90)))

def s(glyph, pen, size):
    m(glyph, pen, size)
    glyph.transform(psMat.rotate(math.radians(90)))

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
}

def augment(font):
    add_lookups(font)
    for cp, schema in DUPLOYAN.items ():
        draw_glyph(font, cp, schema)

