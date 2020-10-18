# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019 David Corbett
# Copyright 2020 Google LLC
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
import subprocess
import tempfile

import fontforge
import fontTools.ttLib.tables.otBase
import fontTools.ttLib.ttFont

import duployan
import fonttools_patches

def build_font(options, font):
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        os.chdir(os.environ.get('OWD', '.'))
        os.environ['SOURCE_DATE_EPOCH'] = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct'], encoding='utf-8').rstrip()
    font.appendSFNTName('English (US)', 'UniqueID', '{};{};{}'.format(
        font.fullname,
        font.version,
        os.environ['SOURCE_DATE_EPOCH'],
    ))
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
        '4.2.5',
        '4.3.0',
        '4.4.0',
        '4.4.1',
        '4.4.2.dev0',
        '4.4.2',
        '4.4.3',
        '4.5.0',
        '4.6.0',
        '4.7.0',
        '4.8.0',
        '4.8.1',
        '4.9.0',
        '4.10.1',
        '4.10.2',
        '4.11.0',
        '4.12.0',
        '4.12.1',
        '4.13.0',
        '4.14.0',
        '4.15.0',
        '4.16.0',
        '4.16.1',
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

