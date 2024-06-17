#!/usr/bin/env python3

# Copyright 2021 Google LLC
# Copyright 2023-2024 David Corbett
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
import fontTools.ttLib.ttFont
import uharfbuzz


if TYPE_CHECKING:
    from _typeshed import StrOrBytesPath


def cast_cff_number(number: float | int) -> float | int:  # noqa: PYI041
    """Losslessly casts a number to the data type in which it uses the
    fewest bytes in CFF.

    Args:
        number: A number. It must be representable in CFF as either an
            integer or a real number.

    Returns:
        `number` as either a `float` or an `int`, whichever uses the
        fewest bytes in CFF.
    """
    if isinstance(number, float) and not number.is_integer():
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
        cff = tt_font['CFF '].cff[0]
        cff.UnderlinePosition = cast_cff_number(-descent - cff.UnderlineThickness / 2)
    tt_font['OS/2'].sTypoAscender = ascent
    tt_font['OS/2'].sTypoDescender = -descent
    tt_font['OS/2'].usWinAscent = ascent
    tt_font['OS/2'].usWinDescent = descent
    tt_font['hhea'].ascender = ascent
    tt_font['hhea'].descender = -descent
    tt_font['post'].underlinePosition = -descent


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
    ascent = max(font['OS/2'].usWinAscent, font['head'].yMax)
    descent = max(font['OS/2'].usWinDescent, -font['head'].yMin)
    if text is not None:
        buffer = uharfbuzz.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb_font = uharfbuzz.Font(uharfbuzz.Face(uharfbuzz.Blob.from_file_path(path)))
        uharfbuzz.shape(hb_font, buffer)
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            extents = hb_font.get_glyph_extents(info.codepoint)
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
    with fontTools.ttLib.ttFont.TTFont(main_source, recalcBBoxes=False) as target_font:
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
