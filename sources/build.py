#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019, 2022-2026 David Corbett
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

"""A CLI to make a Duployan font.
"""

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


def _prepare_environment_variables(dirty: bool) -> None:
    """Sets or unsets environment variables needed to build the font.

    The point is to make builds reproducible by setting
    ``GIT_CONFIG_GLOBAL``, ``GIT_CONFIG_NOSYSTEM``, ``TZ``, and (if not
    already set) ``SOURCE_DATE_EPOCH``. It also unsets ``TMPDIR`` to
    avoid segmentation faults in FontForge and cffsubr.

    Args:
        dirty: Whether the font is being built with uncommitted changes.
    """
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


def _save_font(
    font: fontforge.font,
    output_path: str,
) -> None:
    """Saves a font to a file using FontForge.

    Args:
        font: A font.
        output_path: The file to save the font to.
    """
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    Path(output_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    font.generate(output_path, flags=('no-hints', 'omit-instructions', 'opentype'))


def _set_family_names(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, family_name: str, bold: bool) -> None:
    """Sets names in a 'name' table that are related to a font name.

    Args:
        name_table: A 'name' table.
        family_name: The name of the font family (name ID 1).
        bold: Whether a bold font is being built.
    """
    name_0 = name_table.names[0]
    platform_id = name_0.platformID
    encoding_id = name_0.platEncID
    language_id = name_0.langID
    name_table.setName(family_name, 1, platform_id, encoding_id, language_id)
    subfamily_name = 'Bold' if bold else 'Regular'
    name_table.setName(subfamily_name, 2, platform_id, encoding_id, language_id)
    name_table.setName(f'{family_name} {subfamily_name}', 4, platform_id, encoding_id, language_id)
    name_table.setName(re.sub(r"[^!-$&-'*-.0-;=?-Z\\^-z|~]", '', f'{family_name}-{subfamily_name}'), 6, platform_id, encoding_id, language_id)


def _set_unique_id(name_table: fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e, vendor: str) -> None:
    """Sets the unique ID in a 'name' table.

    The unique ID depends on the version ('name' ID 5) and the font name
    ('name' ID 6), which must already be set in the input 'name' table,
    plus the font vendor (OS/2.achVendID).

    Args:
        name_table: A 'name' table.
        vendor: The font vendor.
    """
    for name in name_table.names:
        assert isinstance(name.string, str)
        match name.nameID:
            case 5:
                version = name.string.removeprefix(VERSION_PREFIX)
            case 6:
                postscript_name = name.string
    name_table.setName(f'{version};{vendor};{postscript_name}', 3, name.platformID, name.platEncID, name.langID)


def _get_date() -> str:
    """Returns the font’s modification date.

    This is based on ``SOURCE_DATE_EPOCH``, so
    `_prepare_environment_variables` should already have been run.
    """
    return datetime.datetime.fromtimestamp(int(os.environ['SOURCE_DATE_EPOCH']), datetime.UTC).strftime(TIMESTAMP_FORMAT)


def _set_version(
    tt_font: fontTools.ttLib.ttFont.TTFont,
    noto: bool,
    version: float,
    release: bool,
    dirty: bool,
) -> None:
    """Sets the version in a font’s 'head' and 'name' tables.

    Args:
        tt_font: A font.
        noto: Whether to use Noto’s conventions in the 'name' table, as
            opposed to semver.
        version: The first two components of the version number.
        release: Whether this is a release build.
        dirty: Whether the font is being built with uncommitted changes.
    """
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
                    date = _get_date()
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
                metadata = _get_date()
            release_suffix = f'-alpha+{metadata}'
    name_table = tt_font['name']
    assert isinstance(name_table, fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e)
    name = name_table.names[0]
    name_table.setName(f'{VERSION_PREFIX}{version_string}{release_suffix}', 5, name.platformID, name.platEncID, name.langID)


def _set_cff_data(
    names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord],
    underline_thickness: float,
    cff: fontTools.cffLib.CFFFontSet,
) -> None:
    """Sets some fields of a 'CFF ' table.

    Args:
        names: The names from 'name'. The CFF-relevant ones are copied
            to 'CFF '.
        underline_thickness: The underline thickness from 'post'.
        cff: The 'CFF ' table to modify.
    """
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


def _add_meta(tt_font: fontTools.ttLib.ttFont.TTFont) -> None:
    """Adds a 'meta' table to a font.

    Args:
        tt_font: A font.
    """
    meta = tt_font['meta'] = fontTools.ttLib.ttFont.newTable('meta')
    assert isinstance(meta, fontTools.ttLib.tables._m_e_t_a.table__m_e_t_a)
    meta.data['dlng'] = 'Dupl'
    meta.data['slng'] = 'Dupl'


def tweak_font(
    font_path: str,
    builder: duployan.Builder,
    family_name: str,
    noto: bool,
    bold: bool,
    version: float,
    release: bool,
    dirty: bool,
    fea: str,
) -> None:
    """Loads a font and modifies it with fontTools.

    Args:
        font_path: The file to load the font from and save it back to.
        builder: The font’s `Builder`.
        family_name: The name of the font family.
        noto: Whether the font is a Noto font.
        bold: Whether the font is bold.
        version: The first two components of the font’s version number.
        release: Whether this is a release build.
        dirty: Whether the font is being built with uncommitted changes.
        fea: The path of a feature file to add to the font.
    """
    with fontTools.ttLib.ttFont.TTFont(font_path, recalcBBoxes=False) as tt_font:
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
            fea,
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
        if bold:
            os2_table.usWeightClass = 700
            os2_table.fsSelection |= 1 << 5
            os2_table.fsSelection &= ~(1 << 0 | 1 << 6)
            head_table.macStyle |= 1 << 0
        else:
            os2_table.fsSelection |= 1 << 6
            os2_table.fsSelection &= ~(1 << 0 | 1 << 5)

        name_table = tt_font['name']
        assert isinstance(name_table, fontTools.ttLib.tables._n_a_m_e.table__n_a_m_e)
        if noto:
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
        _set_family_names(name_table, family_name, bold)
        _set_version(tt_font, noto, version, release, dirty)
        _set_unique_id(name_table, os2_table.achVendID)
        if 'CFF ' in tt_font:
            _set_cff_data(name_table.names, post_table.underlineThickness, cff_table.cff)
        copy_metrics.update_metrics(
            tt_font,
            max(os2_table.usWinAscent, head_table.yMax),
            max(os2_table.usWinDescent, -head_table.yMin),
        )

        _add_meta(tt_font)

        if 'CFF ' in tt_font:
            cffsubr.subroutinize(tt_font)
            cff_table.cff[0].decompileAllCharStrings()
            cff_table.cff[0].Encoding = 0

        tt_font.save(font_path)


def _is_dirty() -> bool:
    """Returns whether the font is being built with uncommitted changes.

    Returns:
        Whether the font is being built with uncommitted changes. If
        there is a problem running Git, it returns ``False``.
    """
    try:
        return bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no']))
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _make_font(options: argparse.Namespace) -> None:
    """Makes a Duployan font.

    Args:
        options: The CLI options.
    """
    font = fontforge.font()
    font.encoding = 'UnicodeFull'
    builder = duployan.Builder(font, options.bold, options.charset, options.unjoined)
    builder.build()
    dirty = _is_dirty()
    _prepare_environment_variables(dirty)
    _save_font(builder.font, options.output)
    tweak_font(options.output, builder, options.name, options.noto, options.bold, options.version, options.release, dirty, options.fea)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Makes a Duployan font.')
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
    _make_font(args)
