# Copyright 2018-2019, 2022-2024 David Corbett
# Copyright 2019-2022 Google LLC
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

import collections
import math
from typing import Final
from typing import TYPE_CHECKING
from typing import cast

import fontTools.agl
import fontTools.feaLib.ast
import fontTools.feaLib.builder
import fontTools.misc.transform
import fontTools.otlLib.builder
import fontTools.ttLib.ttFont

import anchors
import charset
import phases.main
import phases.marker
import phases.middle
from schema import Ignorability
from schema import NO_PHASE_INDEX
from schema import Schema
from shapes import Circle
from shapes import Line
from shapes import Notdef
import sifting
from utils import CAP_HEIGHT
from utils import DEFAULT_SIDE_BEARING
from utils import GlyphClass
from utils import KNOWN_SCRIPTS
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import MINIMUM_STROKE_GAP
from utils import NO_CONTEXT
from utils import PrefixView
from utils import REGULAR_LIGHT_LINE
from utils import SHADING_FACTOR
from utils import Type
from utils import mkmk


if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Mapping
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet

    import fontforge

    from phases import FreezableList
    from phases import Lookup
    from phases import Phase


def rename_schemas(grouper: sifting.Grouper[Schema], phase_index: int) -> None:
    for group in grouper.groups():
        if all(s.phase_index < phase_index for s in group):
            continue
        group.sort(key=Schema.sort_key)
        canonical_schema = next((s for s in group if s.phase_index < phase_index), None)
        if canonical_schema is None:
            canonical_schema = group[0]
        for schema in list(group):
            if schema.phase_index >= phase_index:
                schema.canonical_schema = canonical_schema
                if grouper.group_of(schema):
                    grouper.remove_item(group, schema)


class Builder:
    def __init__(self, font: fontforge.font, bold: bool, noto: bool) -> None:
        self.font: Final = font
        self._fea: Final = fontTools.feaLib.ast.FeatureFile()
        self._anchors: Final[MutableMapping[str, fontTools.feaLib.ast.LookupBlock]] = {}
        self._initialize_phases(noto)
        self.light_line: Final = 101 if bold else REGULAR_LIGHT_LINE
        self.shaded_line: Final = SHADING_FACTOR * self.light_line
        self.stroke_gap: Final = max(MINIMUM_STROKE_GAP, self.light_line)
        self._schemas = charset.initialize_schemas(noto, self.light_line, self.stroke_gap)
        if __debug__:
            code_points: Final[collections.defaultdict[int, int]] = collections.defaultdict(int)
            for schema in self._schemas:
                if schema.cmap is not None:
                    code_points[schema.cmap] += 1
            duplicate_code_points = {cp: count for cp, count in code_points.items() if count > 1}
            assert not duplicate_code_points, ('Duplicate code points:\n    '
                + '\n    '.join(map(hex, sorted(duplicate_code_points.keys()))))

    def _initialize_phases(self, noto: bool) -> None:
        self._phases = phases.main.PHASE_LIST
        if noto:
            self._phases = [p for p in self._phases if p is not phases.main.reversed_circle_kludge]
        self._middle_phases = phases.middle.PHASE_LIST
        self._marker_phases = phases.marker.PHASE_LIST

    def _add_lookup(
        self,
        feature_tag: str,
        anchor_class_name: str,
        *,
        flags: int,
        mark_filtering_set: fontTools.feaLib.ast.GlyphClassDefinition | None = None,
    ) -> None:
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
            flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        lookup = fontTools.feaLib.ast.LookupBlock(anchor_class_name)
        if flags:
            lookup.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
                flags,
                markFilteringSet=fontTools.feaLib.ast.GlyphClassName(mark_filtering_set)
                    if mark_filtering_set
                    else None,
                ))
        self._fea.statements.append(lookup)
        self._anchors[anchor_class_name] = lookup
        feature = fontTools.feaLib.ast.FeatureBlock(feature_tag)
        for script in KNOWN_SCRIPTS:
            feature.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
            feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
            feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition]) -> None:
        self._add_lookup(
                'abvm',
                anchors.PARENT_EDGE,
                flags=0,
                mark_filtering_set=class_asts[phases.PARENT_EDGE_CLASS],
            )
        for layer_index in range(MAX_TREE_DEPTH):
            if layer_index < 2:
                for child_index in range(MAX_TREE_WIDTH):
                    self._add_lookup(
                            'blwm',
                            anchors.CHILD_EDGES[layer_index][child_index],
                            flags=0,
                            mark_filtering_set=class_asts[phases.CHILD_EDGE_CLASSES[child_index]],
                        )
            for child_index in range(MAX_TREE_WIDTH):
                self._add_lookup(
                    'mkmk',
                    anchors.INTER_EDGES[layer_index][child_index],
                    flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                    mark_filtering_set=class_asts[phases.INTER_EDGE_CLASSES[layer_index][child_index]],
                )
        self._add_lookup(
            'curs',
            anchors.CONTINUING_OVERLAP,
            flags=0,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.CURSIVE,
            flags=0,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[phases.CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        for anchor in anchors.ALL_MARK:
            self._add_lookup(
                'mark',
                anchor,
                flags=0,
            )
        for anchor in anchors.ALL_MKMK:
            self._add_lookup(
                'mkmk',
                mkmk(anchor),
                flags=0,
                mark_filtering_set=class_asts[f'global..{mkmk(anchor)}'],
            )

    def _add_altuni(self, uni: int, glyph_name: str) -> fontforge.glyph:
        glyph = self.font[glyph_name]
        if uni != -1:
            if glyph.unicode == -1:
                glyph.unicode = uni
            else:
                new_altuni = ((uni, -1, 0),)
                if glyph.altuni is None:
                    glyph.altuni = new_altuni
                else:
                    glyph.altuni += new_altuni
        return glyph

    def _draw_glyph(
        self,
        glyph: fontforge.glyph,
        schema: Schema,
        cmapped_anchors: AbstractSet[str],
        _scalar: float = 1,
    ) -> None:
        assert not schema.marks
        invisible = schema.path.invisible()
        stroke_width = self.light_line if invisible or schema.cmap is not None or schema.cps[-1:] != (0x1BC9D,) else self.shaded_line
        effective_bounding_box = schema.path.draw(
            glyph,
            stroke_width,
            self.light_line,
            self.stroke_gap,
            _scalar * schema.size,
            schema.anchor,
            schema.joining_type,
            # TODO: `isinstance(schema.path, Circle)` is redundant. The
            # shape can check that itself.
            schema.context_in == NO_CONTEXT and schema.diphthong_1 and isinstance(schema.path, Circle),
            schema.context_out == NO_CONTEXT and schema.diphthong_2 and isinstance(schema.path, Circle),
            schema.diphthong_1,
            schema.diphthong_2,
        )
        assert schema.max_double_marks == 0 or any(anchor_class_name == anchors.MIDDLE for anchor_class_name, _, _, _ in glyph.anchorPoints), (
            f'{glyph.glyphname} has max_double_marks == {schema.max_double_marks} but no {anchors.MIDDLE!r} anchor point')
        if invisible:
            glyph.draw(glyph.glyphPen())
        if schema.joining_type != Type.NON_JOINING:
            entry_x = next(
                (x for anchor_class_name, anchor_type, x, _ in glyph.anchorPoints
                    if anchor_class_name == anchors.CURSIVE and anchor_type == 'entry'),
                0,
            )
            glyph.transform(fontTools.misc.transform.Offset(-entry_x, 0))
        true_bounding_box = glyph.boundingBox()
        _, true_y_min, _, true_y_max = true_bounding_box
        x_min, y_min, x_max, y_max = effective_bounding_box or true_bounding_box
        y_proportion_below_min = (y_min - true_y_min) / (true_y_max - true_y_min) if true_y_max != true_y_min else 0
        if not schema.path.fixed_y() and y_min != y_max:
            if schema.y_min is not None:
                if schema.y_max is not None:
                    desired_height = schema.y_max - schema.y_min
                    actual_height = y_max - y_min
                    if (desired_to_actual_ratio := (desired_height - stroke_width) / (actual_height - stroke_width)) != 1:
                        if _scalar == 1:
                            glyph.clear()
                            self._draw_glyph(glyph, schema, cmapped_anchors, desired_to_actual_ratio)
                        else:
                            glyph.transform(fontTools.misc.transform.Offset(0, -y_min)
                                .scale(desired_height / actual_height)
                            )
                    _, y_min, _, y_max = glyph.boundingBox()
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min - y_proportion_below_min * (y_max - y_min)))
                else:
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
            elif schema.y_max is not None:
                glyph.transform(fontTools.misc.transform.Offset(0, schema.y_max - y_max))
        side_bearing = int(_scalar * schema.side_bearing)
        if x_min != x_max:
            glyph.left_side_bearing = side_bearing
        if schema.glyph_class == GlyphClass.MARK:
            if schema.cps == (0x20DD,) and x_min != x_max:
                radius = (x_max - x_min - self.light_line) / 2
                inscribed_square_size = math.sqrt(2) * radius
                # This should stay consistent with `shrink_wrap_enclosing_circle`.
                shrunk_square_size = inscribed_square_size - 3 * self.stroke_gap - self.light_line
                glyph.transform(fontTools.misc.transform.Offset(0, (CAP_HEIGHT - (y_max - y_min)) / 2))
                glyph.left_side_bearing = -int(DEFAULT_SIDE_BEARING + (shrunk_square_size + x_max - x_min) / 2)
            glyph.width = 0
        else:
            glyph.right_side_bearing = side_bearing
        self._wrangle_anchor_points(schema, glyph, cmapped_anchors, stroke_width)

    def _add_mkmk_anchor_points(
        self,
        schema: Schema,
        glyph: fontforge.glyph,
        stroke_width: float,
    ) -> None:
        for anchor_class_name, anchor_type, x, y in glyph.anchorPoints:
            if anchor_type == 'mark' and schema.anchor == anchor_class_name in anchors.ALL_MKMK:
                mkmk_anchor_class_name = mkmk(anchor_class_name)
                glyph.addAnchorPoint(mkmk_anchor_class_name, 'mark', x, y)
                _, y_min, _, y_max = glyph.boundingBox()
                gap = stroke_width / 2 + self.stroke_gap + self.light_line / 2
                match anchor_class_name:
                    case anchors.ABOVE:
                        y = y_max + gap
                    case anchors.BELOW:
                        y = y_min - gap
                    case _:
                        continue
                glyph.addAnchorPoint(mkmk_anchor_class_name, 'basemark', x, y)
                return

    @staticmethod
    def _convert_base_to_basemark(
        glyph: fontforge.glyph,
    ) -> None:
        for anchor_class_name, anchor_type, x, y in glyph.anchorPoints:
            if anchor_type == 'base':
                if anchor_class_name in anchors.ALL_MKMK:
                    anchor_class_name = mkmk(anchor_class_name)
                elif anchor_class_name in anchors.ALL_MARK:
                    continue
                glyph.addAnchorPoint(anchor_class_name, 'basemark', x, y)
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[1] in {'basemark', 'mark'}]

    def _wrangle_anchor_points(
        self,
        schema: Schema,
        glyph: fontforge.glyph,
        cmapped_anchors: AbstractSet[str],
        stroke_width: float,
    ) -> None:
        if schema.anchor:
            self._add_mkmk_anchor_points(schema, glyph, stroke_width)
        if schema.glyph_class == GlyphClass.MARK and not schema.path.invisible():
            self._convert_base_to_basemark(glyph)
        if not schema.path.invisible():
            glyph.anchorPoints = [a for a in glyph.anchorPoints if (
                a[0] not in {anchors.PARENT_EDGE, *anchors.CHILD_EDGES[1]}
                    if schema.anchor or schema.glyph_class != GlyphClass.MARK
                    else a[1] not in {'entry', 'exit'} and a[0] not in anchors.CHILD_EDGES[0]
            )]
        if schema.glyph_class == GlyphClass.MARK or isinstance(schema.path, Notdef) or schema.path.guaranteed_glyph_class() is not None and schema.path.invisible():
            return
        anchor_tests = {anchor: anchor in cmapped_anchors or anchor in schema.anchors for anchor in anchors.ALL_MARK}
        anchor_tests[anchors.MIDDLE] = schema.encirclable or schema.max_double_marks != 0 or schema.cmap == 0x25CC
        anchor_tests[anchors.SECANT] |= schema.can_take_secant
        anchor_tests[anchors.CONTINUING_OVERLAP] = schema.joining_type != Type.NON_JOINING and (
            schema.can_take_secant or schema.max_tree_width() != 0 or schema.can_be_child()
        )
        anchor_tests[anchors.CURSIVE] = schema.joining_type != Type.NON_JOINING and not schema.is_secant
        anchor_tests[anchors.PRE_HUB_CONTINUING_OVERLAP] = schema.is_secant
        anchor_tests[anchors.POST_HUB_CONTINUING_OVERLAP] = (
            anchor_tests[anchors.CONTINUING_OVERLAP] and (schema.can_be_child() or isinstance(schema.path, Line) and schema.path.dots is not None))
        anchor_tests[anchors.PRE_HUB_CURSIVE] = anchor_tests[anchors.CURSIVE] and schema.hub_priority != 0 and not schema.pseudo_cursive
        anchor_tests[anchors.POST_HUB_CURSIVE] = anchor_tests[anchors.CURSIVE] and schema.hub_priority != -1
        if schema.encirclable:
            glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != anchors.MIDDLE]
        anchor_class_names = {a[0] for a in glyph.anchorPoints}
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        if x_min == x_max == 0:
            x_max = schema.side_bearing
            y_max = CAP_HEIGHT
        x_center = (x_max + x_min) / 2
        y_center = (y_max + y_min) / 2
        for anchor_class_name, should_have_anchor in anchor_tests.items():
            should_have_anchor &= schema.ignorability != Ignorability.DEFAULT_YES
            if (has_anchor := anchor_class_name in anchor_class_names) != should_have_anchor:
                if has_anchor:
                    glyph.anchorPoints = [*filter(lambda a: a[0] != anchor_class_name, glyph.anchorPoints)]
                elif anchor_class_name == anchors.MIDDLE:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_center)
                elif anchor_class_name == anchors.ABOVE:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_max + stroke_width / 2 + self.stroke_gap + self.light_line / 2)
                elif anchor_class_name == anchors.BELOW:
                    glyph.addAnchorPoint(anchor_class_name, 'base', x_center, y_min - (stroke_width / 2 + self.stroke_gap + self.light_line / 2))
                else:
                    assert False, f'{glyph.glyphname}: {anchor_class_name}: {has_anchor} != {should_have_anchor}'

    def _create_glyph(
        self,
        schema: Schema,
        cmapped_anchors: AbstractSet[str],
        *,
        drawing: bool,
    ) -> fontforge.glyph:
        glyph_name = str(schema)
        uni = -1 if schema.cmap is None else schema.cmap
        if glyph_name in self.font:
            return self._add_altuni(uni, glyph_name)
        assert uni not in self.font, f'Duplicate code point: {hex(uni)}'
        glyph = self.font.createChar(uni, glyph_name)
        glyph.unicode = uni
        glyph.glyphclass = schema.glyph_class.value
        glyph.temporary = schema
        if drawing:
            self._draw_glyph(glyph, schema, cmapped_anchors)
        else:
            glyph.width = glyph.width
        return glyph

    def _create_marker(self, schema: Schema) -> None:
        assert schema.cmap is None, f'A marker has the code point U+{schema.cmap:04X}'
        glyph = self._create_glyph(schema, set(), drawing=True)
        glyph.width = 0

    def _complete_gpos(self) -> None:
        mark_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = (
            collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass)))
        base_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = (
            collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass)))
        basemark_positions: collections.defaultdict[str, collections.defaultdict[tuple[float, float], fontTools.feaLib.ast.GlyphClass]] = (
            collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass)))
        cursive_positions: collections.defaultdict[str, collections.defaultdict[str, MutableSequence[fontTools.feaLib.ast.Anchor | None]]] = (
            collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None])))
        for glyph in self.font.glyphs():
            for anchor_class_name, anchor_type, x, y in glyph.anchorPoints:
                x = round(x)
                y = round(y)
                glyph_name = glyph.glyphname
                match anchor_type:
                    case 'mark':
                        mark_positions[anchor_class_name][x, y].append(glyph_name)
                    case 'base':
                        base_positions[anchor_class_name][x, y].append(glyph_name)
                    case 'basemark':
                        basemark_positions[anchor_class_name][x, y].append(glyph_name)
                    case 'entry':
                        cursive_positions[anchor_class_name][glyph_name][0] = fontTools.feaLib.ast.Anchor(x, y)
                    case 'exit':
                        cursive_positions[anchor_class_name][glyph_name][1] = fontTools.feaLib.ast.Anchor(x, y)
                    case _:
                        raise ValueError(f'Unknown anchor type: {anchor_type}')
        for anchor_class_name, lookup in self._anchors.items():
            mark_class = fontTools.feaLib.ast.MarkClass(anchor_class_name)
            for x_y, glyph_class in mark_positions[anchor_class_name].items():
                mark_class_definition = fontTools.feaLib.ast.MarkClassDefinition(
                    mark_class,
                    fontTools.feaLib.ast.Anchor(*x_y),
                    glyph_class)
                mark_class.addDefinition(mark_class_definition)
                lookup.statements.append(mark_class_definition)
            for x_y, glyph_class in base_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.MarkBasePosStatement(
                    glyph_class,
                    [(fontTools.feaLib.ast.Anchor(*x_y), mark_class)]))
            for x_y, glyph_class in basemark_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.MarkMarkPosStatement(
                    glyph_class,
                    [(fontTools.feaLib.ast.Anchor(*x_y), mark_class)]))
            for glyph_name, entry_exit in cursive_positions[anchor_class_name].items():
                lookup.statements.append(fontTools.feaLib.ast.CursivePosStatement(
                    fontTools.feaLib.ast.GlyphName(glyph_name),
                    *entry_exit))

    def _recreate_gdef(self) -> None:
        marks = []
        ligatures = []
        for glyph in self.font.glyphs():
            match glyph.glyphclass:
                case GlyphClass.MARK.value:
                    marks.append(glyph.glyphname)
                case GlyphClass.JOINER.value:
                    ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            None,
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    @staticmethod
    def _glyph_to_schema(glyph: fontforge.glyph) -> Schema:
        schema = glyph.temporary
        glyph.temporary = None
        schema.glyph = glyph
        return cast(Schema, schema)

    def convert_classes(
        self,
        classes: Mapping[str, Collection[Schema]],
    ) -> dict[str, fontTools.feaLib.ast.GlyphClassDefinition]:
        class_asts = {}
        for name, schemas in classes.items():
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                name,
                fontTools.feaLib.ast.GlyphClass([*map(str, schemas)]),
            )
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        return class_asts

    def convert_named_lookups(
        self,
        named_lookups_with_phases: Mapping[str, tuple[Lookup, Phase]],
        class_asts: MutableMapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
    ) -> dict[str, fontTools.feaLib.ast.LookupBlock]:
        named_lookup_asts: dict[str, fontTools.feaLib.ast.LookupBlock] = {}
        named_lookups_to_do = [*named_lookups_with_phases.keys()]
        while named_lookups_to_do:
            new_named_lookups_to_do = []
            for name, (lookup, phase) in named_lookups_with_phases.items():
                if name not in named_lookups_to_do:
                    continue
                try:
                    named_lookup_ast = lookup.to_asts(
                        None,
                        PrefixView(phase, class_asts),
                        PrefixView(phase, named_lookup_asts),
                        name,
                    )
                except KeyError:
                    new_named_lookups_to_do.append(name)
                    continue
                self._fea.statements.append(named_lookup_ast)
                assert name not in named_lookup_asts, name
                named_lookup_asts[name] = named_lookup_ast
            assert len(new_named_lookups_to_do) < len(named_lookups_to_do)
            named_lookups_to_do = new_named_lookups_to_do
        return named_lookup_asts

    def _merge_schemas(
        self,
        schemas: Collection[Schema],
        lookups_with_phases: Sequence[tuple[Lookup, Phase]],
        classes: MutableMapping[str, FreezableList[Schema]],
        named_lookups_with_phases: MutableMapping[str, tuple[Lookup, Phase]],
    ) -> None:
        grouper = sifting.group_schemas(schemas)
        previous_phase: Phase | None = None
        for lookup, phase in reversed(lookups_with_phases):
            if phase is not previous_phase is not None:
                rename_schemas(grouper, self.phase_index(previous_phase))
            previous_phase = phase
            prefix_classes = PrefixView(phase, classes)
            prefix_named_lookups_with_phases = PrefixView(phase, named_lookups_with_phases)
            sifting.sift_groups(grouper, lookup, prefix_classes, prefix_named_lookups_with_phases)
        rename_schemas(grouper, NO_PHASE_INDEX)

    def phase_index(self, phase: Phase) -> int:
        """Returns the index of a phase among all this builder’s phases.

        Args:
            phase: A phase.

        Raises:
            ValueError: If `phase` is not one of this builder’s phases.
        """
        return [*self._phases, *self._middle_phases, *self._marker_phases].index(phase)

    def augment(self) -> None:
        (
            schemas,
            output_schemas,
            lookups_with_phases,
            classes,
            named_lookups_with_phases,
        ) = phases.run_phases(self, self._schemas, self._phases)
        self._merge_schemas(schemas, lookups_with_phases, classes, named_lookups_with_phases)
        class_asts = self.convert_classes(classes)
        named_lookup_asts = self.convert_named_lookups(named_lookups_with_phases, class_asts)
        (
            _,
            more_output_schemas,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = phases.run_phases(self, [schema for schema in output_schemas if schema.canonical_schema is schema], self._middle_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        classes |= more_classes
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        cmapped_anchors = {schema.anchor for schema in schemas if schema.anchor is not None and schema.cmap is not None}
        for schema in schemas.sorted(key=lambda schema: (
            schema.canonical_schema is not schema,
            schema.cmap is None and schema.glyph_class == GlyphClass.MARK
                or str(schema).startswith('_')
                or not (not schema.ignored_for_topography and schema in output_schemas and schema in more_output_schemas),
        )):
            if schema.canonical_schema is schema or schema.cmap is not None:
                self._create_glyph(
                    schema,
                    cmapped_anchors,
                    drawing=not schema.ignored_for_topography and schema in output_schemas and schema in more_output_schemas,
                )
        (
            schemas,
            _,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = phases.run_phases(self, [*map(self._glyph_to_schema, self.font.glyphs())], self._marker_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        classes |= more_classes
        for schema in schemas.sorted(key=Schema.glyph_id_sort_key):
            if schema.glyph is None:
                self._create_marker(schema)
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        features_to_scripts: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
        for lp in lookups_with_phases:
            if lp[0].feature:
                prefix_classes = PrefixView(lp[1], classes)
                features_to_scripts[lp[0].feature] |= lp[0].get_scripts(prefix_classes)
        for i, lp in enumerate(lookups_with_phases):
            self._fea.statements.extend(lp[0].to_asts(features_to_scripts, PrefixView(lp[1], class_asts), PrefixView(lp[1], named_lookup_asts), i))
        self._add_lookups(class_asts)
        self.font.selection.all()
        self.font.round()
        self.font.simplify(3, (
            'setstarttoextremum',
            'smoothcurves',
        ))
        self.font.canonicalStart()
        self.font.canonicalContours()

    def complete_layout(
        self,
        tt_font: fontTools.ttLib.ttFont.TTFont,
    ) -> None:
        self._complete_gpos()
        self._recreate_gdef()
        fontTools.feaLib.builder.addOpenTypeFeatures(
                tt_font,
                self._fea,
                ['GDEF', 'GPOS', 'GSUB'])
