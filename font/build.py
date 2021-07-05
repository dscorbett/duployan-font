#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019 David Corbett
# Copyright 2020-2021 Google LLC
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

import argparse
import os
import re
import subprocess
import tempfile

import fontforge
import fontTools.misc.timeTools
import fontTools.ttLib.tables.otBase
import fontTools.ttLib.ttFont

import duployan
import fonttools_patches

LEADING_ZEROS = re.compile('(?<= )0+')

def build_font(options, font):
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        os.environ['SOURCE_DATE_EPOCH'] = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct'], encoding='utf-8').rstrip()
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = ['no-hints', 'omit-instructions', 'opentype']
    font.generate(options.output, flags=flags)

def generate_feature_string(font, lookup):
    with tempfile.NamedTemporaryFile() as fea_file:
        font.generateFeatureFile(fea_file.name, lookup)
        return fea_file.read().decode('utf-8')

def patch_fonttools():
    if fontTools.__version__ not in [
        '4.18.2',
        '4.19.0',
        '4.19.1',
        '4.20.0',
        '4.21.0',
        '4.21.1',
        '4.22.0',
        '4.22.1',
        '4.23.0',
        '4.23.1',
        '4.24.0',
        '4.24.1',
        '4.24.2',
        '4.24.3',
        '4.24.4',
        '4.25.0',
    ]:
        return

    getGlyphID_inner = fontTools.ttLib.ttFont.TTFont.getGlyphID
    def getGlyphID(self, glyphName, requireReal=False):
        try:
            return self._reverseGlyphOrderDict[glyphName]
        except (AttributeError, KeyError):
            getGlyphID_inner(self, glyphName, requireReal)
    fontTools.ttLib.ttFont.TTFont.getGlyphID = getGlyphID

    fontTools.ttLib.tables.otBase.BaseTTXConverter.compile = fonttools_patches.compile
    fontTools.ttLib.tables.otBase.CountReference.__len__ = fonttools_patches.CountReference_len
    fontTools.ttLib.tables.otBase.OTTableWriter.__len__ = fonttools_patches.OTTableWriter_len
    fontTools.ttLib.tables.otBase.OTTableWriter.getDataLength = fonttools_patches.getDataLength
    fontTools.ttLib.tables.otBase.OTTableWriter.writeInt8 = fonttools_patches.writeInt8
    fontTools.ttLib.tables.otBase.OTTableWriter.writeShort = fonttools_patches.writeShort
    fontTools.ttLib.tables.otBase.OTTableWriter.writeUInt8 = fonttools_patches.writeUInt8
    fontTools.ttLib.tables.otBase.OTTableWriter.writeUShort = fonttools_patches.writeUShort

def filter_map_name(name):
    if name.platformID != 3 or name.platEncID != 1:
        return None
    if isinstance(name.string, bytes):
        name.string = name.string.decode('utf-16be')
    if name.nameID == 5:
        name.string = LEADING_ZEROS.sub('', name.string)
    name.string = name.string.strip()
    return name

def set_unique_id(names):
    for name in names:
        if name.nameID == 3:
            unique_id_record = name
        elif name.nameID == 4:
            full_name = name.string
        elif name.nameID == 5:
            version = name.string.removeprefix('Version ')
    git_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], encoding='utf-8').rstrip()
    unique_id_record.string = ';'.join([full_name, version, git_hash])

def tweak_font(options, builder):
    with fontTools.ttLib.ttFont.TTFont(options.output, recalcBBoxes=False) as tt_font:
        # Remove the FontForge timestamp table.
        if 'FFTM' in tt_font:
            del tt_font['FFTM']

        # Merge all the lookups.
        font = builder.font
        lookups = font.gpos_lookups + font.gsub_lookups
        old_fea = ''.join(generate_feature_string(font, lookup) for lookup in lookups)
        for lookup in lookups:
            font.removeLookup(lookup)
        builder.merge_features(tt_font, old_fea)

        fontTools.feaLib.builder.addOpenTypeFeatures(
            tt_font,
            options.fea,
            tables=['OS/2', 'head', 'name'],
        )
        tt_font['OS/2'].fsSelection += 0x40
        tt_font['OS/2'].usWinAscent = max(tt_font['OS/2'].usWinAscent, tt_font['head'].yMax)
        tt_font['OS/2'].usWinDescent = max(tt_font['OS/2'].usWinDescent, -tt_font['head'].yMin)
        tt_font['OS/2'].sTypoAscender = tt_font['OS/2'].usWinAscent
        tt_font['OS/2'].sTypoDescender = -tt_font['OS/2'].usWinDescent
        tt_font['OS/2'].yStrikeoutPosition = duployan.STRIKEOUT_POSITION
        tt_font['OS/2'].yStrikeoutSize = duployan.LIGHT_LINE
        tt_font['post'].underlinePosition = tt_font['OS/2'].sTypoDescender
        tt_font['post'].underlineThickness = duployan.LIGHT_LINE
        tt_font['head'].created = fontTools.misc.timeTools.timestampFromString('Sat Apr  7 21:21:15 2018')
        tt_font['hhea'].ascender = tt_font['OS/2'].sTypoAscender
        tt_font['hhea'].descender = tt_font['OS/2'].sTypoDescender
        tt_font['hhea'].lineGap = tt_font['OS/2'].sTypoLineGap
        tt_font['name'].names = [*filter(None, map(filter_map_name, tt_font['name'].names))]
        set_unique_id(tt_font['name'].names)

        tt_font.save(options.output)

def make_font(options):
    font = fontforge.font()
    font.familyname = 'Duployan'
    font.fontname = font.familyname
    font.fullname = font.familyname
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font)
    builder.augment()
    build_font(options, builder.font)
    patch_fonttools()
    tweak_font(options, builder)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--fea', metavar='FILE', required=True, help='feature file to add')
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    args = parser.parse_args()
    make_font(args)

