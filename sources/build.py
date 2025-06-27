#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019, 2022-2025 David Corbett
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
import fontTools.ttLib.tables.C_F_F_
import fontTools.ttLib.tables.O_S_2f_2
import fontTools.ttLib.tables._h_e_a_d
import fontTools.ttLib.tables._h_h_e_a
import fontTools.ttLib.tables._m_e_t_a
import fontTools.ttLib.tables._n_a_m_e
import fontTools.ttLib.tables._p_o_s_t
import fontTools.ttLib.ttFont
import fontforge

import charsets
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
    Path(options.output).resolve().parent.mkdir(parents=True, exist_ok=True)
    font.generate(options.output, flags=('no-hints', 'omit-instructions', 'opentype'))


def set_family_names(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, family_name: str, bold: bool) -> None:
    name_0 = name_table.names[0]
    platform_id = name_0.platformID
    encoding_id = name_0.platEncID
    language_id = name_0.langID
    name_table.setName(family_name, 1, platform_id, encoding_id, language_id)
    subfamily_name = 'Bold' if bold else 'Regular'
    name_table.setName(subfamily_name, 2, platform_id, encoding_id, language_id)
    name_table.setName(f'{family_name} {subfamily_name}', 4, platform_id, encoding_id, language_id)
    name_table.setName(re.sub(r"[^!-$&-'*-.0-;=?-Z\\^-z|~]", '', f'{family_name}-{subfamily_name}'), 6, platform_id, encoding_id, language_id)


def set_unique_id(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, vendor: str) -> None:
    for name in name_table.names:
        assert isinstance(name.string, str)
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
    head_table = tt_font['head']
    assert isinstance(head_table, fontTools.ttLib.tables._h_e_a_d.table__h_e_a_d)
    head_table.fontRevision = version
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
    assert isinstance(name_table, fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e)
    name = name_table.names[0]
    name_table.setName(f'{VERSION_PREFIX}{version_string}{release_suffix}', 5, name.platformID, name.platEncID, name.langID)


def set_cff_data(
    names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord],
    underline_thickness: float,
    cff: fontTools.cffLib.CFFFontSet,
) -> None:
    for name in names:
        assert isinstance(name.string, str)
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
    meta = tt_font['meta'] = fontTools.ttLib.ttFont.newTable('meta')
    assert isinstance(meta, fontTools.ttLib.tables._m_e_t_a.table__m_e_t_a)
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
            cff_table = tt_font['CFF ']
            assert isinstance(cff_table, fontTools.ttLib.tables.C_F_F_.table_C_F_F_)
            for name, value in [*cff_table.cff[0].rawDict.items()]:
                if isinstance(value, str):
                    del cff_table.cff[0].rawDict[name]
                    if hasattr(cff_table.cff[0], name):
                        delattr(cff_table.cff[0], name)

        # Complete the OpenType Layout tables.
        builder.complete_layout(tt_font)

        fontTools.feaLib.builder.addOpenTypeFeatures(
            tt_font,
            options.fea,
            tables=['OS/2', 'head', 'name'],
        )

        head_table = tt_font['head']
        assert isinstance(head_table, fontTools.ttLib.tables._h_e_a_d.table__h_e_a_d)
        upem = head_table.unitsPerEm
        os2_table = tt_font['OS/2']
        assert isinstance(os2_table, fontTools.ttLib.tables.O_S_2f_2.table_O_S_2f_2)
        os2_table.recalcAvgCharWidth(tt_font)
        os2_table.ySubscriptXSize = round(upem * utils.SMALL_DIGIT_FACTOR)
        os2_table.ySubscriptYSize = os2_table.ySubscriptXSize
        os2_table.ySubscriptXOffset = 0
        os2_table.ySubscriptYOffset = round(-utils.SUBSCRIPT_DEPTH)
        os2_table.ySuperscriptXSize = os2_table.ySubscriptXSize
        os2_table.ySuperscriptYSize = os2_table.ySuperscriptXSize
        os2_table.ySuperscriptXOffset = 0
        os2_table.ySuperscriptYOffset = round(utils.SUPERSCRIPT_HEIGHT - utils.SMALL_DIGIT_FACTOR * utils.CAP_HEIGHT)
        os2_table.usDefaultChar = 0
        if options.bold:
            os2_table.usWeightClass = 700
            os2_table.fsSelection |= 1 << 5
            os2_table.fsSelection &= ~(1 << 0 | 1 << 6)
            head_table.macStyle |= 1 << 0
        else:
            os2_table.fsSelection |= 1 << 6
            os2_table.fsSelection &= ~(1 << 0 | 1 << 5)

        name_table = tt_font['name']
        assert isinstance(name_table, fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e)
        if options.noto:
            for name in name_table.names:
                assert isinstance(name.string, str)
                name.string = name.string.replace('\n', ' ')

        os2_table.sCapHeight = round(utils.CAP_HEIGHT)
        os2_table.sxHeight = round(utils.X_HEIGHT)
        os2_table.yStrikeoutPosition = round(utils.STRIKEOUT_POSITION)
        os2_table.yStrikeoutSize = round(utils.REGULAR_LIGHT_LINE)
        post_table = tt_font['post']
        assert isinstance(post_table, fontTools.ttLib.tables._p_o_s_t.table__p_o_s_t)
        post_table.underlineThickness = round(utils.REGULAR_LIGHT_LINE)
        head_table.created = fontTools.misc.timeTools.timestampFromString('Sat Apr  7 21:21:15 2018')
        hhea_table = tt_font['hhea']
        assert isinstance(hhea_table, fontTools.ttLib.tables._h_h_e_a.table__h_h_e_a)
        hhea_table.lineGap = os2_table.sTypoLineGap
        set_family_names(name_table, options.name, options.bold)
        set_version(tt_font, options.noto, options.version, options.release, dirty)
        set_unique_id(name_table, os2_table.achVendID)
        if 'CFF ' in tt_font:
            set_cff_data(name_table.names, post_table.underlineThickness, cff_table.cff)
        copy_metrics.update_metrics(
            tt_font,
            max(os2_table.usWinAscent, head_table.yMax),
            max(os2_table.usWinDescent, -head_table.yMin),
        )

        add_meta(tt_font)

        if 'CFF ' in tt_font:
            cffsubr.subroutinize(tt_font)
            cff_table.cff[0].decompileAllCharStrings()
            cff_table.cff[0].Encoding = 0

        tt_font.save(options.output)


def is_dirty() -> bool:
    try:
        return bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no']))
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def make_font(options: argparse.Namespace) -> None:
    font = fontforge.font()
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font, options.bold, options.charset, options.unjoined)
    builder.augment()
    dirty = is_dirty()
    set_environment_variables(dirty)
    build_font(options, builder.font)
    tweak_font(options, builder, dirty)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--bold', action='store_true', help='Make a bold font.')
    parser.add_argument(
        '--charset', default=charsets.Charset.STANDARD, type=charsets.Charset,
        help=f'The character set, one of {{{", ".join(c.value for c in charsets.Charset)}}} (default: %(default)s).',
    )
    parser.add_argument('--fea', metavar='FILE', required=True, help='feature file to add')
    parser.add_argument('--name', required=True, help='The name of the font family (name ID 1).')
    parser.add_argument('--noto', action='store_true', help="Use Noto conventions in the 'name' table.")
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    parser.add_argument('--release', action='store_true', help='Set the version number as appropriate for a stable release, as opposed to an alpha.')
    parser.add_argument('--unjoined', action='store_true', help='Disable cursive joining.')
    parser.add_argument('--version', type=float, required=True, help='The base version number.')
    args = parser.parse_args()
    make_font(args)
