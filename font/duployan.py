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

__all__ = ['augment']

import math

import fontforge
import psMat

BASELINE = 402
SIDE_BEARING = 85
STROKE_WIDTH = 70

def b(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    pen.lineTo((0, 0))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def d(glyph, pen, size):
    pen.moveTo((0, 0))
    pen.lineTo((500 * size, 0))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def v(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    pen.lineTo((500 * size, 0))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def g(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    pen.lineTo((0, 0))
    glyph.transform(psMat.skew(math.radians(30)), ('round',))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

def r(glyph, pen, size):
    pen.moveTo((0, 500 * size))
    pen.lineTo((0, 0))
    glyph.transform(psMat.skew(math.radians(60)), ('round',))
    glyph.stroke('circular', STROKE_WIDTH, 'round')

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
}

def augment(font):
    for cp, schema in DUPLOYAN.items ():
        draw_glyph(font, cp, schema)

