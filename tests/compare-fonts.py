#!/usr/bin/env python3

# Copyright 2026 Chainguard, Inc.
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

"""A CLI to compare a built font against a reference font.

This answers one question: did the build draw everything the reference
draws, in about the same place? It is meant to catch a stroker that has
quietly stopped stroking, which the shaping tests cannot see, because an
empty glyph shapes exactly like a drawn one.

A glyph that the reference draws but the build leaves empty, or does not
contain at all, is an error. Everything else is reported but not fatal:
outlines move by a unit or two whenever FontForge changes, and only a
human can say whether that is acceptable.

Glyphs are compared by name. A name whose suffix is assigned in creation
order, such as an enclosing circle variant, is only comparable when both
fonts have the same glyph inventory; when they do not, a difference
reported for such a glyph may be two unrelated variants being compared.
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib.ttFont import TTFont


if TYPE_CHECKING:
    from collections.abc import Mapping

    #: The x and y minima and maxima of a glyph’s outline.
    Bounds = tuple[float, float, float, float]

#: How many glyph names to list before summarizing the rest as a count.
MAX_EXAMPLES = 10

#: The bucket in the bounding box histogram for everything at least this large.
MAX_DELTA_BUCKET = 10


class Glyph:
    """The measurements of a glyph that this script compares."""

    def __init__(self, width: float, bounds: Bounds | None) -> None:
        """Initializes a glyph’s measurements.

        Args:
            width: The advance width.
            bounds: The bounding box, or ``None`` if the glyph draws
                nothing.
        """
        self.width = width
        self.bounds = bounds

    def max_edge_delta(self, other: Glyph) -> float:
        """Returns the largest difference between corresponding bounding box edges.

        An empty glyph has no bounding box to compare, so a pair
        involving one is reported as 0 here and caught separately.

        Args:
            other: The glyph to compare this one to.
        """
        if self.bounds is None or other.bounds is None:
            return 0
        return max(abs(a - b) for a, b in zip(self.bounds, other.bounds, strict=True))


def measure(path: Path) -> Mapping[str, Glyph]:
    """Returns the measurements of every glyph in a font.

    Args:
        path: The path to a font.
    """
    glyphs = {}
    with TTFont(path, lazy=True) as font:
        glyph_set = font.getGlyphSet()
        for name in glyph_set:
            glyph = glyph_set[name]
            pen = BoundsPen(glyph_set)
            glyph.draw(pen)
            glyphs[name] = Glyph(glyph.width, pen.bounds)
    return glyphs


def print_names(label: str, names: list[str]) -> None:
    """Prints some glyph names, eliding all but ``MAX_EXAMPLES`` of them.

    Nothing is printed if there are no names, so that a clean comparison
    stays short.

    Args:
        label: What the names have in common.
        names: The glyph names.
    """
    if not names:
        return
    shown = ', '.join(names[:MAX_EXAMPLES])
    if len(names) > MAX_EXAMPLES:
        shown += f', and {len(names) - MAX_EXAMPLES} more'
    print(f'{label}: {len(names)}')
    print(f'  {shown}')


def compare(built: Mapping[str, Glyph], reference: Mapping[str, Glyph]) -> bool:
    """Returns whether the build drew everything the reference draws, and prints a report.

    Args:
        built: The measurements of the font that was just built.
        reference: The measurements of the font to compare it to.
    """
    missing = sorted(reference.keys() - built.keys())
    added = sorted(built.keys() - reference.keys())
    common = sorted(reference.keys() & built.keys())
    print(f'glyphs: {len(built)} built, {len(reference)} reference, {len(common)} common')
    print_names('in the reference but not the build', missing)
    print_names('in the build but not the reference', added)
    if missing or added:
        print('  note: the inventories differ, so a glyph whose name suffix is assigned')
        print('  in creation order may not be the same glyph in both fonts')

    emptied = [n for n in common if built[n].bounds is None and reference[n].bounds is not None]
    filled = [n for n in common if built[n].bounds is not None and reference[n].bounds is None]
    widths = [n for n in common if built[n].width != reference[n].width]
    print_names('drawn in the reference but empty in the build', emptied)
    print_names('empty in the reference but drawn in the build', filled)
    print_names('advance width differs', widths)

    histogram: collections.Counter[int] = collections.Counter()
    for name in common:
        histogram[min(int(built[name].max_edge_delta(reference[name])), MAX_DELTA_BUCKET)] += 1
    print('largest bounding box edge difference, in whole font units, rounded down:')
    for delta in sorted(histogram):
        label = f'>={delta}' if delta == MAX_DELTA_BUCKET else str(delta)
        print(f'  {label:>4}: {histogram[delta]}')

    return not missing and not emptied


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compare a built font against a reference font.')
    parser.add_argument('built', type=Path, help='The path to the font that was just built.')
    parser.add_argument('reference', type=Path, help='The path to the font to compare it against.')
    args = parser.parse_args()
    assert isinstance(args.built, Path)  # type: ignore[misc]
    assert isinstance(args.reference, Path)  # type: ignore[misc]
    if not compare(measure(args.built), measure(args.reference)):
        sys.exit(1)
