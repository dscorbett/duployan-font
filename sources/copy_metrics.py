#!/usr/bin/env python3

# Copyright 2021 Google LLC
# Copyright 2023 David Corbett
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
    'copy_metrics',
    'update_metrics',
]


import fontTools.ttLib.ttFont


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
    tt_font['OS/2'].sTypoAscender = ascent
    tt_font['OS/2'].sTypoDescender = -descent
    tt_font['OS/2'].usWinAscent = ascent
    tt_font['OS/2'].usWinDescent = descent
    tt_font['hhea'].ascender = ascent
    tt_font['hhea'].descender = -descent
    tt_font['post'].underlinePosition = -descent


def copy_metrics(source: str, target: str) -> None:
    """Copies vertical metrics from one font to another.

    The target font is saved to disk.

    Args:
        source: The path of the font to copy from.
        target: The path of the font to copy to.
    """
    with fontTools.ttLib.ttFont.TTFont(source, recalcBBoxes=False) as source_font:
        ascent = source_font['OS/2'].usWinAscent
        descent = source_font['OS/2'].usWinDescent
    with fontTools.ttLib.ttFont.TTFont(target, recalcBBoxes=False) as target_font:
        update_metrics(target_font, ascent, descent)
        target_font.save(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Copies vertical metrics from one font to another.')
    parser.add_argument('target', help='the font to copy to')
    parser.add_argument('source', help='the font to copy from')
    args = parser.parse_args()
    copy_metrics(args.source, args.target)
