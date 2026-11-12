# Copyright 2026 David Corbett
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

"""File size optimization by reordering glyphs.
"""

from collections import Counter
from collections import defaultdict
from typing import TYPE_CHECKING

import fontTools.agl
import fontTools.ttLib.tables._c_m_a_p
import fontTools.ttLib.tables._h_m_t_x
import fontTools.ttLib.tables.otBase
import fontTools.ttLib.tables.otTables


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Final

    from fontTools.ttLib.ttFont import TTFont


def _count_coverage_sets(tt_font: TTFont) -> Counter[frozenset[str]]:
    """Counts all glyph sets in a font that are compiled into coverage
    tables.

    Args:
        tt_font: A font.

    Returns:
        A counter mapping `tt_font`’s sets of glyph names to how many
        Python objects each appears in that would be serialized as
        coverage tables.
    """
    counter: Counter[frozenset[str]] = Counter()
    seen_ids = set()

    def extract(obj: object) -> None:
        obj_id = id(obj)
        if obj_id in seen_ids:
            return
        seen_ids.add(obj_id)
        obj_dict: dict[str, object]
        match obj:
            case list():
                for item in obj:
                    extract(item)
            case (
                fontTools.ttLib.tables.otTables.AlternateSubst(alternates=glyphs)
                | fontTools.ttLib.tables.otTables.Coverage(glyphs=glyphs)
                | fontTools.ttLib.tables.otTables.LigatureSubst(ligatures=glyphs)
                | fontTools.ttLib.tables.otTables.MultipleSubst(mapping=glyphs)
                | fontTools.ttLib.tables.otTables.SingleSubst(mapping=glyphs)
            ):
                counter[frozenset(glyphs)] += 1
            case object(__dict__=obj_dict):
                for v in obj_dict.values():
                    extract(v)

    for tag in ['GDEF', 'GPOS', 'GSUB']:
        if tag in tt_font:
            table = tt_font[tag]
            assert isinstance(table, fontTools.ttLib.tables.otBase.BaseTTXConverter)
            extract(table.table)
    return counter


_PROMINENCE_POWER: Final[float] = 0.283


def _find_optimized_glyph_order(tt_font: TTFont) -> list[str]:
    r"""Returns a glyph order that minimizes a font’s size.

    The glyph set is grouped into equivalence classes by three criteria:

    1. Whether the glyph is ``.notdef``. This ensures that ``.notdef``
       is the first glyph.
    2. Whether the glyph’s advance width is the most common advance
       width. Such groups are sorted last, optimizing 'hmtx' by
       minimizing hhea.numberOfHMetrics.
    3. The set of coverage sets the glyph appears in. A coverage set is
       a set of glyphs corresponding to a coverage table. Groups with
       lower-indexed (more prominent) coverage sets come first.

    Coverage sets are ordered by decreasing prominence by three
    criteria:

    1. 𝑐 × \|𝑆\|^𝑝, where 𝑐 is how many times 𝑆 (a coverage set) appears
       in the font and 𝑝 is a heuristic. Common, large sets come first.
       Rare, small sets come last. A sufficiently large set can precede
       a more common set, but 𝑝 is tuned so that frequency is more
       important. This helps prominent sets avoid being inefficiently
       split into many non-contiguous ranges.
    2. The size of the set. Larger sets are more prominent.
    3. The glyphs in the set sorted by name. This is just a tie-breaker.

    Within each group, glyphs are sorted by their AGL mappings. This
    reduces the number of segments in 'cmap' formats 4 and 12. It also
    encourages single substitution subtables to use format 1 (with
    deltaGlyphID).

    Args:
        tt_font: A font.

    Returns:
        An optimized glyph order for `tt_font`.
    """
    current_order = tt_font.getGlyphOrder()

    hmtx_table = tt_font['hmtx']
    assert isinstance(hmtx_table, fontTools.ttLib.tables._h_m_t_x.table__h_m_t_x)
    advance_widths = {g: m[0] for g, m in hmtx_table.metrics.items()}
    last_width = Counter([advance_widths[g] for g in current_order]).most_common(1)[0][0]

    coverage_set_index_sets = defaultdict(set)
    coverage_set_counts = _count_coverage_sets(tt_font)
    for i, coverage_set in enumerate(
        sorted(coverage_set_counts, key=lambda cs: (-coverage_set_counts[cs] * len(cs) ** _PROMINENCE_POWER, -len(cs), sorted(cs))),  # type: ignore[misc]
    ):
        for glyph in coverage_set:
            coverage_set_index_sets[glyph].add(i)

    def group_key(glyph: str) -> tuple[bool, bool, tuple[int, ...]]:
        is_not_notdef = glyph != '.notdef'
        has_last_width = last_width == advance_widths[glyph]
        coverage_set_index_set = tuple(sorted(coverage_set_index_sets[glyph]))
        return (is_not_notdef, has_last_width, coverage_set_index_set)

    grouper = defaultdict(list)
    for glyph in current_order:
        grouper[group_key(glyph)].append(glyph)

    def glyph_sort_key(glyph: str) -> tuple[str, str]:
        return (fontTools.agl.toUnicode(glyph), glyph)

    groups = [*grouper.values()]
    for group in groups:
        group.sort(key=glyph_sort_key)

    def group_sort_key(group: Sequence[str]) -> tuple[bool, bool, tuple[int, ...]]:
        return group_key(group[0])

    groups.sort(key=group_sort_key)
    return [*group for group in groups]


def optimize_glyph_order(tt_font: TTFont) -> None:
    """Reorders a font’s glyphs to minimize file size.

    It also drops any non-Unicode or format 0 subtables from 'cmap'.
    They are incompatible with assumptions made by the optimizer.

    Args:
        tt_font: The font to optimize.
    """
    cmap_table = tt_font['cmap']
    assert isinstance(cmap_table, fontTools.ttLib.tables._c_m_a_p.table__c_m_a_p)
    cmap_table.tables = [t for t in cmap_table.tables if t.format != 0 and t.isUnicode()]
    tt_font.reorderGlyphs(_find_optimized_glyph_order(tt_font))
