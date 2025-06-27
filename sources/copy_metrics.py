#!/usr/bin/env python3

# Copyright 2021 Google LLC
# Copyright 2023-2025 David Corbett
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
from typing import TYPE_CHECKING

import fontTools.misc.psCharStrings
import fontTools.ttLib.tables.C_F_F_
import fontTools.ttLib.tables.O_S_2f_2
import fontTools.ttLib.tables._h_e_a_d
import fontTools.ttLib.tables._h_h_e_a
import fontTools.ttLib.tables._p_o_s_t
import fontTools.ttLib.ttFont
import uharfbuzz


if TYPE_CHECKING:
    from _typeshed import StrOrBytesPath


def cast_cff_number(number: float) -> float:
    """Losslessly casts a number to the data type in which it uses the
    fewest bytes in CFF.

    Args:
        number: A number. It must be representable in CFF as either an
            integer or a real number.

    Returns:
        `number` as either a `float` or an `int`, whichever uses the
        fewest bytes in CFF.
    """
    if not number.is_integer():
        return number
    f = float(number)
    if not (-2 ** 31 <= number <= 2 ** 31 - 1):
        return f
    i = int(number)
    if len(fontTools.misc.psCharStrings.encodeFloat(f)) < len(fontTools.misc.psCharStrings.encodeIntCFF(i)):
        return f
    return i


def update_metrics(
    tt_font: fontTools.ttLib.ttFont.TTFont,
    ascent: int,
    descent: int,
) -> None:
    """Sets a font’s vertical metrics consistently with `Noto’s
    requirements
    <https://github.com/notofonts/noto-source/blob/ec575e4a32479faae41f314da4d3e9c2eb107d21/FONT_CONTRIBUTION.md#noto-font-metrics-requirements>`_.

    The font is assumed to already contain all the tables relevant to
    vertical metrics. It is not saved to disk.

    Args:
        tt_font: A font.
        ascent: The ascent (“A” in the Noto requirements).
        descent: The descent (“B” in the Noto requirements). This is a
            positive number for descents that reach below the baseline.
    """
    if 'CFF ' in tt_font:
        cff_table = tt_font['CFF ']
        assert isinstance(cff_table, fontTools.ttLib.tables.C_F_F_.table_C_F_F_)
        cff = cff_table.cff[0]
        assert cff.UnderlineThickness is not None
        cff.UnderlinePosition = cast_cff_number(-descent - cff.UnderlineThickness / 2)
    os2_table = tt_font['OS/2']
    assert isinstance(os2_table, fontTools.ttLib.tables.O_S_2f_2.table_O_S_2f_2)
    os2_table.sTypoAscender = ascent
    os2_table.sTypoDescender = -descent
    os2_table.usWinAscent = ascent
    os2_table.usWinDescent = descent
    hhea_table = tt_font['hhea']
    assert isinstance(hhea_table, fontTools.ttLib.tables._h_h_e_a.table__h_h_e_a)
    hhea_table.ascent = ascent
    hhea_table.descent = -descent
    post_table = tt_font['post']
    assert isinstance(post_table, fontTools.ttLib.tables._p_o_s_t.table__p_o_s_t)
    post_table.underlinePosition = -descent


def get_metrics(
    path: StrOrBytesPath,
    font: fontTools.ttLib.ttFont.TTFont,
    text: str | None,
) -> tuple[int, int]:
    """Gets a font’s most extreme ascent and descent values.

    The values considered are the OS/2 table’s usWinAscent and
    usWinDescent, the 'head' table’s yMax and yMin, and the bounding box
    of a string (if provided). A positive descent means a descent below
    the baseline.

    Args:
        path: A path to a font.
        font: The font at `path`.
        text: A string to shape with the font to get its bounding box.
            If ``None``, shaping is skipped, and it has no effect on the
            return value.

    Returns:
        A tuple of the most extreme ascent and descent values attested
        for a font.
    """
    os2_table = font['OS/2']
    assert isinstance(os2_table, fontTools.ttLib.tables.O_S_2f_2.table_O_S_2f_2)
    head_table = font['head']
    assert isinstance(head_table, fontTools.ttLib.tables._h_e_a_d.table__h_e_a_d)
    ascent = max(os2_table.usWinAscent, head_table.yMax)
    descent = max(os2_table.usWinDescent, -head_table.yMin)
    if text is not None:
        buffer = uharfbuzz.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb_font = uharfbuzz.Font(uharfbuzz.Face(uharfbuzz.Blob.from_file_path(path)))
        uharfbuzz.shape(hb_font, buffer)
        assert buffer.glyph_positions is not None
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            extents = hb_font.get_glyph_extents(info.codepoint)
            assert extents is not None
            dy = position.y_offset
            yb = extents.y_bearing
            h = extents.height
            ascent = max(ascent, dy + yb)
            descent = max(descent, -(dy + yb + h))
    return ascent, descent


def copy_metrics(
    main_source: StrOrBytesPath,
    metrics_sources: list[StrOrBytesPath],
    target: str,
    text: str | None,
) -> None:
    """Copies a font with modified vertical metrics.

    The target font is saved to disk. Its vertical metrics are set to
    the most extreme values attested in `main_source` or any font in
    `metrics_sources`.

    Args:
        main_source: The path of the font to copy from.
        metrics_sources: The paths of other fonts to check the vertical
            metrics of.
        target: The path of the font to copy to.
        text: An extra source of vertical metrics. If it is not
            ``None``, its bounding box when shaped with the main font is
            taken into account.
    """
    ascent = 0
    descent = 0
    for source in [main_source, *metrics_sources]:
        with fontTools.ttLib.ttFont.TTFont(source, recalcBBoxes=False) as source_font:
            source_ascent, source_descent = get_metrics(source, source_font, text)
            ascent = max(ascent, source_ascent)
            descent = max(descent, source_descent)
    with fontTools.ttLib.ttFont.TTFont(main_source, recalcBBoxes=False, recalcTimestamp=False) as target_font:
        update_metrics(target_font, ascent, descent)
        target_font.save(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Copies a font, setting its vertical metrics to the extrema from a list of fonts.')
    parser.add_argument('--text', help='an optional string to shape whose ascent and descent are candidates for the most extreme vertical metrics')
    parser.add_argument('target', help='the font to copy to')
    parser.add_argument('source', help='the font to copy from')
    parser.add_argument('others', nargs='*', help='more fonts to consider when determining the most extreme vertical metrics')
    args = parser.parse_args()
    copy_metrics(args.source, args.others, args.target, args.text)
