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

import argparse


__all__ = [
    'cast_cff_number',
    'copy_metrics',
    'update_metrics',
]


import fontTools.misc.psCharStrings
import fontTools.ttLib.ttFont


def cast_cff_number(number: float | int) -> float | int:
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


def copy_metrics(main_source: str, metrics_sources: list[str], target: str) -> None:
    """Copies a font with modified vertical metrics.

    The target font is saved to disk. Its vertical metrics are set to
    the most extreme values attested in `main_source` or any font in
    `metrics_sources`.

    Args:
        main_source: The path of the font to copy from.
        metrics_sources: The paths of other fonts to check the vertical metrics of.
        target: The path of the font to copy to.
    """
    ascent = 0
    descent = 0
    for source in [main_source, *metrics_sources]:
        with fontTools.ttLib.ttFont.TTFont(source, recalcBBoxes=False) as source_font:
            ascent = max(ascent, source_font['OS/2'].usWinAscent, source_font['head'].yMax)
            descent = max(descent, source_font['OS/2'].usWinDescent, -source_font['head'].yMin)
    with fontTools.ttLib.ttFont.TTFont(main_source, recalcBBoxes=False) as target_font:
        update_metrics(target_font, ascent, descent)
        target_font.save(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Copies a font, setting its vertical metrics to the extrema from a list of fonts.')
    parser.add_argument('target', help='the font to copy to')
    parser.add_argument('source', help='the font to copy from')
    parser.add_argument('others', nargs='*', help='more fonts to consider when determining the most extreme vertical metrics')
    args = parser.parse_args()
    copy_metrics(args.source, args.others, args.target)
