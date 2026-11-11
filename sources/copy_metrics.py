#!/usr/bin/env python3

# Copyright 2021 Google LLC
# Copyright 2023-2026 David Corbett
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
import math
from typing import TYPE_CHECKING

import fontTools.misc.psCharStrings
import fontTools.pens.boundsPen
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


def update_metrics(tt_font: fontTools.ttLib.ttFont.TTFont) -> None:
    """Sets a font’s vertical metrics consistently with `Noto’s
    requirements
    <https://github.com/notofonts/noto-source/blob/ec575e4a32479faae41f314da4d3e9c2eb107d21/FONT_CONTRIBUTION.md#noto-font-metrics-requirements>`_.

    The values considered are the OS/2 table’s usWinAscent and
    usWinDescent, the 'head' table’s yMax and yMin, and the glyphs’
    control point bounding boxes. A positive descent means a descent
    below the baseline.

    The font is assumed to already contain all the tables relevant to
    vertical metrics. It is not saved to disk.

    Args:
        tt_font: A font.
    """
    _set_metrics(tt_font, *_get_metrics(tt_font))


def _set_metrics(
    tt_font: fontTools.ttLib.ttFont.TTFont,
    ascent: int,
    descent: int,
    control_ascent: float | None = None,
    control_descent: float | None = None,
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
        control_ascent: head.yMax. It may be less than `ascent`. If
            ``None``, yMax is not set.
        control_descent: The negation of head.yMin. It may be less than
            `descent`. If ``None``, yMin is not set.
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
    if control_ascent is not None or control_descent is not None:
        head_table = tt_font['head']
        assert isinstance(head_table, fontTools.ttLib.tables._h_e_a_d.table__h_e_a_d)
        if control_ascent is not None:
            head_table.yMax = math.ceil(control_ascent)
        if control_descent is not None:
            head_table.yMin = -math.ceil(control_descent)


def _get_control_metrics(font: fontTools.ttLib.ttFont.TTFont) -> tuple[float, float]:
    """Returns a font’s most extreme control point y values.

    Args:
        font: A font.

    Returns:
        A tuple of the most extreme ascent and descent control points
        in `font`. A positive descent means a descent below the
        baseline.
    """
    glyph_set = font.getGlyphSet()
    y_min = float('inf')
    y_max = float('-inf')
    pen = fontTools.pens.boundsPen.ControlBoundsPen(glyph_set)
    for glyph in glyph_set.values():
        pen.init()
        glyph.draw(pen)
        if bounds := pen.bounds:
            if (new_y_min := bounds[1]) < y_min:
                y_min = new_y_min
            if (new_y_max := bounds[3]) > y_max:
                y_max = new_y_max
    return y_max, -y_min


def _get_text_metrics(
    path: StrOrBytesPath | None,
    text: str | None,
) -> tuple[float, float]:
    """Returns the y extrema of a string shaped with a font.

    Args:
        path: A path to a font. If ``None``, shaping is skipped, and
            it has no effect on the return value.
        text: A string to shape with the font to get its bounding box.
            If ``None``, shaping is skipped.

    Returns:
        A tuple of the most extreme rendered ascent and descent visible
        points (as opposed to control points) of `text` shaped with
        `font`. A positive descent means a descent below the baseline.
    """
    y_min = float('inf')
    y_max = float('-inf')
    if path is not None is not text:
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
            y_max = max(y_max, dy + yb)
            y_min = min(y_min, dy + yb + h)
    return y_max, -y_min


def _get_metrics(
    font: fontTools.ttLib.ttFont.TTFont,
    path: StrOrBytesPath | None = None,
    text: str | None = None,
) -> tuple[int, int, float, float]:
    """Gets a font’s most extreme ascent and descent values.

    The values considered are the OS/2 table’s usWinAscent and
    usWinDescent, the 'head' table’s yMax and yMin, the glyphs’ control
    point bounding boxes, and the bounding box of a string (if
    provided). A positive descent means a descent below the baseline.

    Args:
        font: A font.
        path: The path to `font`. If ``None``, shaping is skipped, and
            it has no effect on the return value.
        text: A string to shape with the font to get its bounding box.
            If ``None``, shaping is skipped.

    Returns:
        A tuple of the most extreme ascent and descent values attested
        for a font, and its most extreme contour points’ ascent and
        descent values.
    """
    os2_table = font['OS/2']
    assert isinstance(os2_table, fontTools.ttLib.tables.O_S_2f_2.table_O_S_2f_2)
    head_table = font['head']
    assert isinstance(head_table, fontTools.ttLib.tables._h_e_a_d.table__h_e_a_d)
    control_ascent, control_descent = _get_control_metrics(font)
    text_ascent, text_descent = _get_text_metrics(path, text)
    ascent = math.ceil(max(os2_table.usWinAscent, head_table.yMax, control_ascent, text_ascent))
    descent = math.ceil(max(os2_table.usWinDescent, -head_table.yMin, control_descent, text_descent))
    return ascent, descent, control_ascent, control_descent


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
            source_ascent, source_descent, _, _ = _get_metrics(source_font, source, text)
            ascent = max(ascent, source_ascent)
            descent = max(descent, source_descent)
    with fontTools.ttLib.ttFont.TTFont(main_source, recalcBBoxes=False, recalcTimestamp=False) as target_font:
        _set_metrics(target_font, ascent, descent)
        target_font.save(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Copies a font, setting its vertical metrics to the extrema from a list of fonts.')
    parser.add_argument('--text', help='an optional string to shape whose ascent and descent are candidates for the most extreme vertical metrics')
    parser.add_argument('target', help='the font to copy to')
    parser.add_argument('source', help='the font to copy from')
    parser.add_argument('others', nargs='*', help='more fonts to consider when determining the most extreme vertical metrics')
    args = parser.parse_args()
    assert isinstance(args.source, str)  # type: ignore[misc]
    assert isinstance(args.others, list)  # type: ignore[misc]
    assert isinstance(args.target, str)  # type: ignore[misc]
    assert isinstance(args.text, str | None)  # type: ignore[misc]
    copy_metrics(args.source, args.others, args.target, args.text)
