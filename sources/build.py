#!/usr/bin/env python3

# Copyright 2010-2019 Khaled Hosny <khaledhosny@eglug.org>
# Copyright 2018-2019, 2022-2023 David Corbett
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

import fontforge
import fontTools.cffLib
import fontTools.misc.timeTools
import fontTools.ttLib
import fontTools.ttLib.tables._n_a_m_e
import fontTools.ttLib.ttFont

import copy_metrics
import duployan
import utils


LEADING_ZEROS = re.compile('(?<= )0+')


TIMESTAMP_FORMAT = '%Y%m%dT%H%M%SZ'


VERSION_PREFIX = 'Version '


def build_font(
    options: argparse.Namespace,
    font: fontforge.font,
    dirty: bool,
) -> None:
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        try:
            if dirty:
                os.environ['SOURCE_DATE_EPOCH'] = f'{datetime.datetime.now(datetime.UTC).timestamp():.0f}'
            else:
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


def filter_map_name(name: fontTools.ttLib.tables._n_a_m_e.NameRecord) -> fontTools.ttLib.tables._n_a_m_e.NameRecord | None:
    if name.platformID != 3 or name.platEncID != 1:
        return None
    if isinstance(name.string, bytes):
        name.string = name.string.decode('utf-16be')
    if name.nameID == 5:
        name.string = LEADING_ZEROS.sub('', name.string)
    name.string = name.string.strip()
    return name


def set_subfamily_name(names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord], bold: bool) -> None:
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


def set_unique_id(names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord], vendor: str) -> None:
    for name in names:
        if name.nameID == 3:
            unique_id_record = name
        elif name.nameID == 5:
            version = name.string.removeprefix(VERSION_PREFIX)
        elif name.nameID == 6:
            postscript_name = name.string
    unique_id_record.string = f'{version};{vendor};{postscript_name}'


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
        for name in tt_font['name'].names:
            if name.nameID == 5:
                release_suffix = '' if release else ';DEV'
                name.string = f'{VERSION_PREFIX}{version:.03f}{release_suffix}'
                break
    else:
        for name in tt_font['name'].names:
            if name.nameID == 5:
                if release:
                    release_suffix = ''
                else:
                    os.environ['TZ'] = 'UTC'
                    try:
                        if dirty:
                            date = get_date()
                        else:
                            date = subprocess.check_output(
                                    ['git', 'log', '-1', f'--date=format-local:{TIMESTAMP_FORMAT}', '--format=%cd'],
                                    encoding='utf-8',
                                ).rstrip()
                        git_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], encoding='utf-8').rstrip()
                        metadata = f'{date}.{git_hash}'
                        if dirty:
                            git_diff = subprocess.check_output(['git', 'diff-index', '--patch', 'HEAD'])
                            try:
                                import hashlib
                                metadata += f'.{hashlib.md5(git_diff).hexdigest()}'
                            except AttributeError:
                                metadata += '.dirty'
                    except (FileNotFoundError, subprocess.CalledProcessError):
                        metadata = get_date()
                    release_suffix = f'-alpha+{metadata}'
                name.string = f'{VERSION_PREFIX}{version}.0{release_suffix}'
                break


def set_cff_data(
    names: Collection[fontTools.ttLib.tables._n_a_m_e.NameRecord],
    underline_thickness: float,
    cff: fontTools.cffLib.CFFFontSet,
) -> None:
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

        tt_font['OS/2'].usDefaultChar = 0
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

        tt_font['OS/2'].yStrikeoutPosition = round(utils.STRIKEOUT_POSITION)
        tt_font['OS/2'].yStrikeoutSize = round(utils.REGULAR_LIGHT_LINE)
        tt_font['post'].underlineThickness = round(utils.REGULAR_LIGHT_LINE)
        tt_font['head'].created = fontTools.misc.timeTools.timestampFromString('Sat Apr  7 21:21:15 2018')
        tt_font['hhea'].lineGap = tt_font['OS/2'].sTypoLineGap
        set_subfamily_name(tt_font['name'].names, options.bold)
        set_version(tt_font, options.noto, options.version, options.release, dirty)
        set_unique_id(tt_font['name'].names, tt_font['OS/2'].achVendID)
        if 'CFF ' in tt_font:
            set_cff_data(tt_font['name'].names, tt_font['post'].underlineThickness, tt_font['CFF '].cff)
        copy_metrics.update_metrics(
            tt_font,
            max(tt_font['OS/2'].usWinAscent, tt_font['head'].yMax),
            max(tt_font['OS/2'].usWinDescent, -tt_font['head'].yMin),
        )

        add_meta(tt_font)

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
    build_font(options, builder.font, dirty)
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
