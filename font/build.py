#!/usr/bin/env python

# build.py - Duployan font build utility
#
# Written in 2010-2018 by Khaled Hosny <khaledhosny@eglug.org>
# Written in 2018-2019 by David Corbett <corbett.dav@husky.neu.edu>
#
# To the extent possible under law, the authors have dedicated all
# copyright and related and neighboring rights to this software to the
# public domain worldwide. This software is distributed without any
# warranty.
#
# You should have received a copy of the CC0 Public Domain Dedication
# along with this software. If not, see
# <http://creativecommons.org/publicdomain/zero/1.0/>.

import argparse
import os
import subprocess

import fontforge
import fontTools.ttLib
import tempfile

import duployan

def build_font(options, font):
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        os.environ['SOURCE_DATE_EPOCH'] = subprocess.check_output(['git', 'log', '-1', '--format=%ct']).rstrip()
    font.appendSFNTName('English (US)', 'UniqueID', '{};{};{}'.format(
        font.fullname,
        font.version,
        os.environ['SOURCE_DATE_EPOCH'],
    ))
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = ['dummy-dsig', 'no-hints', 'omit-instructions', 'opentype']
    font.generate(options.output, flags=flags)

def generate_feature_string(font, lookup):
    with tempfile.NamedTemporaryFile() as fea_file:
        font.generateFeatureFile(fea_file.name, lookup)
        return fea_file.read().decode('utf-8')

def patch_fonttools():
    getGlyphID_inner = fontTools.ttLib.TTFont.getGlyphID
    def getGlyphID(self, glyphName, requireReal=False):
        try:
            return self._reverseGlyphOrderDict[glyphName]
        except (AttributeError, KeyError):
            getGlyphID_inner(glyphName, requireReal)
    fontTools.ttLib.TTFont.getGlyphID = getGlyphID

def tweak_font(options, builder):
    tt_font = fontTools.ttLib.TTFont(options.output, recalcBBoxes=False)

    # Remove the FontForge timestamp table.
    if 'FFTM' in tt_font:
        del tt_font['FFTM']

    # This font has no vendor.
    tt_font['OS/2'].achVendID = '    '

    # Merge all the lookups.
    font = builder.font
    lookups = font.gpos_lookups + font.gsub_lookups
    old_fea = ''.join(generate_feature_string(font, lookup) for lookup in lookups)
    for lookup in lookups:
        font.removeLookup(lookup)
    builder.merge_features(tt_font, old_fea)

    tt_font.save(options.output)

def make_font(options):
    font = fontforge.open(options.input)
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font)
    builder.augment()
    build_font(options, builder.font)
    patch_fonttools()
    tweak_font(options, builder)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--input', metavar='FILE', required=True, help='input font')
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    args = parser.parse_args()
    make_font(args)

