#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019, 2022-2024 David Corbett
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

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING

import cffsubr
import fontTools.cffLib
import fontTools.misc.timeTools
import fontTools.ttLib
import fontTools.ttLib.tables._n_a_m_e
import fontTools.ttLib.ttFont
import fontforge

import copy_metrics
import duployan
import utils


if TYPE_CHECKING:
    from collections.abc import Collection


TIMESTAMP_FORMAT = '%Y%m%dT%H%M%SZ'


VERSION_PREFIX = 'Version '


def set_environment_variables(dirty: bool) -> None:
    os.environ['GIT_CONFIG_GLOBAL'] = ''
    os.environ['GIT_CONFIG_NOSYSTEM'] = 'true'
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        try:
            if dirty:
                os.environ['SOURCE_DATE_EPOCH'] = f'{datetime.datetime.now(datetime.UTC).timestamp():.0f}'
            else:
                os.environ['SOURCE_DATE_EPOCH'] = subprocess.check_output(
                        ['git', 'rev-list', '-1', '--format=%ct', '--no-commit-header', 'HEAD'],
                        encoding='utf-8',
                    ).rstrip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            os.environ['SOURCE_DATE_EPOCH'] = '0'
    os.environ.pop('TMPDIR', None)
    os.environ['TZ'] = 'UTC'


def build_font(
    options: argparse.Namespace,
    font: fontforge.font,
) -> None:
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = ['no-hints', 'omit-instructions', 'opentype']
    Path(options.output).resolve().parent.mkdir(parents=True, exist_ok=True)
    font.generate(options.output, flags=flags)


def set_subfamily_name(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, bold: bool) -> None:
    for name in name_table.names:
        if name.nameID == 1:
            family_name = name.string
            platform_id = name.platformID
            encoding_id = name.platEncID
            language_id = name.langID
            break
    subfamily_name = 'Bold' if bold else 'Regular'
    name_table.setName(subfamily_name, 2, platform_id, encoding_id, language_id)
    name_table.setName(f'{family_name} {subfamily_name}', 4, platform_id, encoding_id, language_id)
    name_table.setName(re.sub(r"[^!-$&-'*-.0-;=?-Z\\^-z|~]", '', f'{family_name}-{subfamily_name}'), 6, platform_id, encoding_id, language_id)


def set_unique_id(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, vendor: str) -> None:
    for name in name_table.names:
        match name.nameID:
            case 5:
                version = name.string.removeprefix(VERSION_PREFIX)
            case 6:
                postscript_name = name.string
    name_table.setName(f'{version};{vendor};{postscript_name}', 3, name.platformID, name.platEncID, name.langID)


def get_date() -> str:
    return datetime.datetime.fromtimestamp(int(os.environ['SOURCE_DATE_EPOCH']), datetime.UTC).strftime(TIMESTAMP_FORMAT)


def set_version(
    tt_font: fontTools.ttLib.ttFont.TTFont,
    noto: bool,
    version: float,
    release: bool,
    dirty: bool,
) -> None:
    tt_font['head'].fontRevision = version
    if noto:
        version_string = f'{version:.03f}'
        release_suffix = '' if release else ';DEV'
    else:
        version_string = f'{version}.0'
        if release:
            release_suffix = ''
        else:
            try:
                if dirty:
                    date = get_date()
                else:
                    date = subprocess.check_output(
                            ['git', 'rev-list', '-1', f'--date=format-local:{TIMESTAMP_FORMAT}', '--format=%cd', '--no-commit-header', 'HEAD'],
                            encoding='utf-8',
                        ).rstrip()
                git_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], encoding='utf-8').rstrip()
                metadata = f'{date}.{git_hash}'
                if dirty:
                    git_diff = subprocess.check_output(['git', 'diff-index', '--binary', 'HEAD'])
                    try:
                        metadata += f'.{hashlib.md5(git_diff, usedforsecurity=False).hexdigest()}'
                    except AttributeError:
                        metadata += '.dirty'
            except (FileNotFoundError, subprocess.CalledProcessError):
                metadata = get_date()
            release_suffix = f'-alpha+{metadata}'
    name_table = tt_font['name']
    name = name_table.names[0]
    name_table.setName(f'{VERSION_PREFIX}{version_string}{release_suffix}', 5, name.platformID, name.platEncID, name.langID)


def set_cff_data(
    names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord],
    underline_thickness: float,
    cff: fontTools.cffLib.CFFFontSet,
) -> None:
    for name in names:
        match name.nameID:
            case 0:
                cff[0].Copyright = name.string
            case 1:
                cff[0].FamilyName = name.string
            case 2:
                cff[0].Weight = name.string
            case 4:
                cff[0].FullName = name.string
            case 5:
                cff[0].version = name.string.removeprefix(VERSION_PREFIX)
            case 6:
                cff.fontNames[0] = name.string
            case 7:
                cff[0].Notice = name.string
    cff[0].UnderlineThickness = copy_metrics.cast_cff_number(underline_thickness)


def add_meta(tt_font: fontTools.ttLib.ttFont.TTFont) -> None:
    meta = tt_font['meta'] = fontTools.ttLib.newTable('meta')
    meta.data['dlng'] = 'Dupl'
    meta.data['slng'] = 'Dupl'


def tweak_font(options: argparse.Namespace, builder: duployan.Builder, dirty: bool) -> None:
    with fontTools.ttLib.ttFont.TTFont(options.output, recalcBBoxes=False) as tt_font:
        # Remove the FontForge timestamp table.
        if 'FFTM' in tt_font:
            del tt_font['FFTM']

        # Discard strings supplied by FontForge.
        if 'name' in tt_font:
            del tt_font['name']
        if 'CFF ' in tt_font:
            for name, value in [*tt_font['CFF '].cff[0].rawDict.items()]:
                if isinstance(value, str):
                    del tt_font['CFF '].cff[0].rawDict[name]
                    if hasattr(tt_font['CFF '].cff[0], name):
                        delattr(tt_font['CFF '].cff[0], name)

        # Complete the OpenType Layout tables.
        builder.complete_layout(tt_font)

        fontTools.feaLib.builder.addOpenTypeFeatures(
            tt_font,
            options.fea,
            tables=['OS/2', 'head', 'name'],
        )

        upem = tt_font['head'].unitsPerEm
        tt_font['OS/2'].recalcAvgCharWidth(tt_font)
        tt_font['OS/2'].ySubscriptXSize = round(upem * utils.SMALL_DIGIT_FACTOR)
        tt_font['OS/2'].ySubscriptYSize = tt_font['OS/2'].ySubscriptXSize
        tt_font['OS/2'].ySubscriptXOffset = 0
        tt_font['OS/2'].ySubscriptYOffset = round(-utils.SUBSCRIPT_DEPTH)
        tt_font['OS/2'].ySuperscriptXSize = tt_font['OS/2'].ySubscriptXSize
        tt_font['OS/2'].ySuperscriptYSize = tt_font['OS/2'].ySuperscriptXSize
        tt_font['OS/2'].ySuperscriptXOffset = 0
        tt_font['OS/2'].ySuperscriptYOffset = round(utils.SUPERSCRIPT_HEIGHT - utils.SMALL_DIGIT_FACTOR * utils.CAP_HEIGHT)
        tt_font['OS/2'].usDefaultChar = 0
        if options.bold:
            tt_font['OS/2'].usWeightClass = 700
            tt_font['OS/2'].fsSelection |= 1 << 5
            tt_font['OS/2'].fsSelection &= ~(1 << 0 | 1 << 6)
            tt_font['head'].macStyle |= 1 << 0
        else:
            tt_font['OS/2'].fsSelection |= 1 << 6
            tt_font['OS/2'].fsSelection &= ~(1 << 0 | 1 << 5)

        if options.noto:
            for name in tt_font['name'].names:
                name.string = name.string.replace('\n', ' ')

        tt_font['OS/2'].sCapHeight = round(utils.CAP_HEIGHT)
        tt_font['OS/2'].sxHeight = round(utils.X_HEIGHT)
        tt_font['OS/2'].yStrikeoutPosition = round(utils.STRIKEOUT_POSITION)
        tt_font['OS/2'].yStrikeoutSize = round(utils.REGULAR_LIGHT_LINE)
        tt_font['post'].underlineThickness = round(utils.REGULAR_LIGHT_LINE)
        tt_font['head'].created = fontTools.misc.timeTools.timestampFromString('Sat Apr  7 21:21:15 2018')
        tt_font['hhea'].lineGap = tt_font['OS/2'].sTypoLineGap
        set_subfamily_name(tt_font['name'], options.bold)
        set_version(tt_font, options.noto, options.version, options.release, dirty)
        set_unique_id(tt_font['name'], tt_font['OS/2'].achVendID)
        if 'CFF ' in tt_font:
            set_cff_data(tt_font['name'].names, tt_font['post'].underlineThickness, tt_font['CFF '].cff)
        copy_metrics.update_metrics(
            tt_font,
            max(tt_font['OS/2'].usWinAscent, tt_font['head'].yMax),
            max(tt_font['OS/2'].usWinDescent, -tt_font['head'].yMin),
        )

        add_meta(tt_font)

        if 'CFF ' in tt_font:
            cffsubr.subroutinize(tt_font)
            tt_font['CFF '].cff[0].decompileAllCharStrings()
            tt_font['CFF '].cff[0].Encoding = 0

        tt_font.save(options.output)


def is_dirty() -> bool:
    try:
        return bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no']))
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def make_font(options: argparse.Namespace) -> None:
    font = fontforge.font()
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font, options.bold, options.noto)
    builder.augment()
    dirty = is_dirty()
    set_environment_variables(dirty)
    build_font(options, builder.font)
    tweak_font(options, builder, dirty)


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
