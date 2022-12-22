#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019, 2022 David Corbett
# Copyright 2020-2022 Google LLC
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
from collections.abc import Collection
import datetime
import os
import re
import subprocess
import tempfile
from typing import Any

import fontforge
import fontTools.cffLib
import fontTools.misc.timeTools
import fontTools.ttLib
import fontTools.ttLib.ttFont

import duployan
import utils


LEADING_ZEROS = re.compile('(?<= )0+')


VERSION_PREFIX = 'Version '


def build_font(options: argparse.Namespace, font: fontforge.font) -> None:
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        try:
            os.environ['SOURCE_DATE_EPOCH'] = subprocess.check_output(
                    ['git', 'log', '-1', '--format=%ct'],
                    encoding='utf-8',
                ).rstrip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            os.environ['SOURCE_DATE_EPOCH'] = '0'
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = ['no-hints', 'omit-instructions', 'opentype']
    os.makedirs(os.path.dirname(os.path.realpath(options.output)), exist_ok=True)
    font.generate(options.output, flags=flags)


def generate_feature_string(font: fontforge.font, lookup: str) -> str:
    with tempfile.NamedTemporaryFile() as fea_file:
        font.generateFeatureFile(fea_file.name, lookup)
        return fea_file.read().decode('utf-8')


def filter_map_name(name: Any) -> Any:
    if name.platformID != 3 or name.platEncID != 1:
        return None
    if isinstance(name.string, bytes):
        name.string = name.string.decode('utf-16be')
    if name.nameID == 5:
        name.string = LEADING_ZEROS.sub('', name.string)
    name.string = name.string.strip()
    return name


def set_subfamily_name(names: Collection[Any], bold: bool) -> None:
    for name in names:
        if name.nameID == 1:
            family_name = name.string
        elif name.nameID == 2:
            subfamily_name_record = name
            subfamily_name_record.string = 'Bold' if bold else 'Regular'
        elif name.nameID == 4:
            full_name_record = name
        elif name.nameID == 6:
            postscript_name_record = name
    full_name_record.string = f'{family_name} {subfamily_name_record.string}'
    postscript_name_record.string = re.sub(r"[^!-$&-'*-.0-;=?-Z\\^-z|~]", '', family_name)
    postscript_name_record.string += f'-{subfamily_name_record.string}'


def set_unique_id(names: Collection[Any], vendor: str) -> None:
    for name in names:
        if name.nameID == 3:
            unique_id_record = name
        elif name.nameID == 5:
            version = name.string.removeprefix(VERSION_PREFIX)
        elif name.nameID == 6:
            postscript_name = name.string
    unique_id_record.string = f'{version};{vendor};{postscript_name}'


def set_version(
    tt_font: fontTools.ttLib.ttFont.TTFont,
    noto: bool,
    version: float,
    release: bool,
) -> None:
    tt_font['head'].fontRevision = version
    if noto:
        os.environ['GIT_PYTHON_REFRESH'] = 'warn'
        import fontv.libfv
        fontv_version = fontv.libfv.FontVersion(tt_font)
        fontv_version.set_version_number(f'{version:.03f}')
        if not release:
            try:
                fontv_version.set_state_git_commit_sha1(development=True)
            except OSError:
                fontv_version.set_development_status()
        fontv_version.write_version_string()
    else:
        for name in tt_font['name'].names:
            if name.nameID == 5:
                if release:
                    release_suffix = ''
                else:
                    timestamp_format = '%Y%m%dT%H%M%SZ'
                    os.environ['TZ'] = 'UTC'
                    try:
                        git_date = subprocess.check_output(
                                ['git', 'log', '-1', f'--date=format-local:{timestamp_format}', '--format=%cd'],
                                encoding='utf-8',
                            ).rstrip()
                        git_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], encoding='utf-8').rstrip()
                        metadata = f'{git_date}.{git_hash}'
                    except (FileNotFoundError, subprocess.CalledProcessError):
                        metadata = datetime.datetime.fromtimestamp(int(os.environ['SOURCE_DATE_EPOCH']), datetime.timezone.utc).strftime(timestamp_format)
                    release_suffix = f'-alpha+{metadata}'
                name.string = f'{VERSION_PREFIX}{version}.0{release_suffix}'
                break


def set_cff_data(names: Collection[Any], cff: fontTools.cffLib.CFFFontSet) -> None:
    for name in names:
        if name.nameID == 0:
            cff[0].Copyright = name.string
        elif name.nameID == 1:
            cff[0].FamilyName = name.string
        elif name.nameID == 2:
            cff[0].Weight = name.string
        elif name.nameID == 4:
            cff[0].FullName = name.string
        elif name.nameID == 5:
            cff[0].version = name.string.removeprefix(VERSION_PREFIX)
        elif name.nameID == 6:
            cff.fontNames[0] = name.string
        elif name.nameID == 7:
            cff[0].Notice = name.string


def add_meta(tt_font: fontTools.ttLib.ttFont.TTFont) -> None:
    meta = tt_font['meta'] = fontTools.ttLib.newTable('meta')
    meta.data['dlng'] = 'Dupl'
    meta.data['slng'] = 'Dupl'


def tweak_font(options: argparse.Namespace, builder: duployan.Builder) -> None:
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

        if options.bold:
            tt_font['OS/2'].usWeightClass = 700
            tt_font['OS/2'].fsSelection |= 1 << 5
            tt_font['OS/2'].fsSelection &= ~(1 << 0 | 1 << 6)
            tt_font['head'].macStyle |= 1 << 0
        else:
            tt_font['OS/2'].fsSelection |= 1 << 6
            tt_font['OS/2'].fsSelection &= ~(1 << 0 | 1 << 5)

        tt_font['name'].names = [*filter(None, map(filter_map_name, tt_font['name'].names))]

        if options.noto:
            for name in tt_font['name'].names:
                name.string = name.string.replace('\n', ' ')
        elif 'CFF ' in tt_font:
            tt_font['CFF '].cff[0].Notice = ''

        tt_font['OS/2'].usWinAscent = max(tt_font['OS/2'].usWinAscent, tt_font['head'].yMax)
        tt_font['OS/2'].usWinDescent = max(tt_font['OS/2'].usWinDescent, -tt_font['head'].yMin)
        tt_font['OS/2'].sTypoAscender = tt_font['OS/2'].usWinAscent
        tt_font['OS/2'].sTypoDescender = -tt_font['OS/2'].usWinDescent
        tt_font['OS/2'].yStrikeoutPosition = utils.STRIKEOUT_POSITION
        tt_font['OS/2'].yStrikeoutSize = duployan.REGULAR_LIGHT_LINE
        tt_font['post'].underlinePosition = tt_font['OS/2'].sTypoDescender
        tt_font['post'].underlineThickness = duployan.REGULAR_LIGHT_LINE
        tt_font['head'].created = fontTools.misc.timeTools.timestampFromString('Sat Apr  7 21:21:15 2018')
        tt_font['hhea'].ascender = tt_font['OS/2'].sTypoAscender
        tt_font['hhea'].descender = tt_font['OS/2'].sTypoDescender
        tt_font['hhea'].lineGap = tt_font['OS/2'].sTypoLineGap
        set_subfamily_name(tt_font['name'].names, options.bold)
        set_version(tt_font, options.noto, options.version, options.release)
        set_unique_id(tt_font['name'].names, tt_font['OS/2'].achVendID)
        if 'CFF ' in tt_font:
            set_cff_data(tt_font['name'].names, tt_font['CFF '].cff)

        add_meta(tt_font)

        tt_font.save(options.output)


def make_font(options: argparse.Namespace) -> None:
    font = fontforge.font()
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font, options.bold, options.noto)
    builder.augment()
    build_font(options, builder.font)
    tweak_font(options, builder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--bold', action='store_true', help='Make a bold font.')
    parser.add_argument('--fea', metavar='FILE', required=True, help='feature file to add')
    parser.add_argument('--noto', action='store_true', help='Build Noto Sans Duployan.')
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    parser.add_argument('--release', action='store_true', help='Set the version number as appropriate for a stable release, as opposed to an alpha.')
    parser.add_argument('--version', type=float, required=True, help='The version number.')
    args = parser.parse_args()
    make_font(args)
