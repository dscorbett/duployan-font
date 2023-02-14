# Copyright 2019, 2022-2023 David Corbett
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

from __future__ import annotations


__all__ = [
    'PHASE_LIST',
    'add_end_markers_for_marks',
    'add_shims_for_pseudo_cursive',
    'add_width_markers',
    'calculate_bound_extrema',
    'clear_entry_width_markers',
    'copy_maximum_left_bound_to_start',
    'dist',
    'expand_start_markers',
    'find_real_hub',
    'mark_hubs_after_initial_secants',
    'mark_maximum_bounds',
    'remove_false_end_markers',
    'remove_false_start_markers',
    'shrink_wrap_enclosing_circle',
    'sum_width_markers',
]


import collections
from collections.abc import Collection
import functools
import math
from typing import Literal
from typing import MutableMapping
from typing import MutableSequence
from typing import Optional
from typing import TYPE_CHECKING
from typing import TypeVar


import fontTools.otlLib.builder


from . import Lookup
from . import Rule
import anchors
import phases
from schema import MAX_HUB_PRIORITY
from schema import Schema
from shapes import AnchorWidthDigit
from shapes import Carry
from shapes import Circle
from shapes import ContinuingOverlap
from shapes import Digit
from shapes import DigitStatus
from shapes import Dot
from shapes import Dummy
from shapes import End
from shapes import EntryWidthDigit
from shapes import GlyphClassSelector
from shapes import Hub
from shapes import InitialSecantMarker
from shapes import LeftBoundDigit
from shapes import Line
from shapes import MarkAnchorSelector
from shapes import RightBoundDigit
from shapes import SeparateAffix
from shapes import Space
from shapes import Start
from shapes import WidthNumber
from utils import DEFAULT_SIDE_BEARING
from utils import GlyphClass
from utils import MINIMUM_STROKE_GAP
from utils import NO_CONTEXT
from utils import OrderedSet
from utils import PrefixView
from utils import WIDTH_MARKER_PLACES
from utils import WIDTH_MARKER_RADIX


if TYPE_CHECKING:
    from _typeshed import Incomplete
    from mypy_extensions import DefaultNamedArg

    from . import AddRule
    from duployan import Builder


def add_shims_for_pseudo_cursive(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    marker_lookup = Lookup(
        'abvm',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
    )
    space_lookup = Lookup(
        'abvm',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        reversed=True,
    )
    if len(original_schemas) != len(schemas):
        return [marker_lookup, space_lookup]
    pseudo_cursive_schemas_to_classes = {}
    pseudo_cursive_info = {}
    exit_schemas = []
    entry_schemas = []
    for schema in new_schemas:
        if schema.glyph is None or schema.glyph_class != GlyphClass.JOINER:
            continue
        if schema.pseudo_cursive:
            x_min, y_min, x_max, y_max = schema.glyph.boundingBox()
            exit_x = exit_y = entry_x = entry_y = None
            for anchor_class_name, type, x, y in schema.glyph.anchorPoints:
                if anchor_class_name == anchors.CURSIVE:
                    if type == 'exit':
                        exit_x = x
                        exit_y = y
                    elif type == 'entry':
                        entry_x = x
                        entry_y = y
            assert entry_y == exit_y
            is_space = x_min == x_max
            if is_space:
                assert x_min == 0
                assert entry_x == 0
                exit_x = 0
            bottom_bound = y_min - MINIMUM_STROKE_GAP - entry_y
            top_bound = y_max + MINIMUM_STROKE_GAP - entry_y
            class_name = f'pseudo_cursive_{is_space}_{bottom_bound}_{top_bound}'.replace('-', 'n')
            classes[class_name].append(schema)
            pseudo_cursive_schemas_to_classes[schema] = class_name
            pseudo_cursive_info[class_name] = (
                is_space,
                entry_x - x_min,
                x_max - exit_x,
                bottom_bound,
                top_bound,
                (y_max - y_min) / 2 if isinstance(schema.path, Dot) else 0,
                200 if isinstance(schema.path, SeparateAffix) else 6,
            )
        if schema.context_in == NO_CONTEXT or schema.context_out == NO_CONTEXT:
            if (
                (looks_like_valid_exit := any(s.context_out == NO_CONTEXT and not schema.diphthong_1 for s in schema.lookalike_group))
                | (looks_like_valid_entry := any(s.context_in == NO_CONTEXT and not schema.diphthong_2 for s in schema.lookalike_group))
            ):
                for anchor_class_name, type, x, y in schema.glyph.anchorPoints:
                    if anchor_class_name == anchors.CURSIVE:
                        if looks_like_valid_exit and type == 'exit':
                            exit_schemas.append((schema, x, y))
                        elif looks_like_valid_entry and type == 'entry':
                            entry_schemas.append((schema, x, y))

    @functools.cache
    def get_shim(width: float, height: float) -> Schema:
        return Schema(
            None,
            Space(width and math.degrees(math.atan(height / width)) % 360),
            math.hypot(width, height),
            side_bearing=width,
        )

    marker = get_shim(0, 0)

    def round_with_base(number: float, base: int, minimum: float, key=None) -> float:  # type: ignore[no-untyped-def]
        return max(minimum, base * round(number / base), key=key)

    for pseudo_cursive_index, (pseudo_cursive_class_name, (
        pseudo_cursive_is_space,
        pseudo_cursive_left_bound,
        pseudo_cursive_right_bound,
        pseudo_cursive_bottom_bound,
        pseudo_cursive_top_bound,
        pseudo_cursive_y_offset,
        rounding_base,
    )) in enumerate(pseudo_cursive_info.items()):
        add_rule(marker_lookup, Rule(pseudo_cursive_class_name, [marker, pseudo_cursive_class_name, marker]))
        exit_classes: MutableMapping[str, Schema] = {}
        exit_classes_containing_pseudo_cursive_schemas: set[str] = set()
        exit_classes_containing_true_cursive_schemas: set[str] = set()
        entry_classes: MutableMapping[str, Schema] = {}
        for prefix, e_schemas, e_classes, pseudo_cursive_x_bound, height_sign, get_distance_to_edge in [
            ('exit', exit_schemas, exit_classes, pseudo_cursive_left_bound, -1, lambda bounds, x: bounds[1] - x),
            ('entry', entry_schemas, entry_classes, pseudo_cursive_right_bound, 1, lambda bounds, x: x - bounds[0]),
        ]:
            for e_schema, x, y in e_schemas:
                assert e_schema.glyph is not None
                bounds: Optional[tuple[float, float]] = e_schema.glyph.foreground.xBoundsAtY(y + pseudo_cursive_bottom_bound, y + pseudo_cursive_top_bound)
                distance_to_edge = 0 if bounds is None else get_distance_to_edge(bounds, x)
                shim_width = distance_to_edge + DEFAULT_SIDE_BEARING + pseudo_cursive_x_bound
                shim_height = pseudo_cursive_y_offset * height_sign
                if (pseudo_cursive_is_space
                    and e_schemas is exit_schemas
                    and isinstance(e_schema.path, Space)
                ):
                    # Margins do not collapse between spaces.
                    shim_width += DEFAULT_SIDE_BEARING
                exit_is_pseudo_cursive = e_classes is exit_classes and e_schema in pseudo_cursive_schemas_to_classes
                if exit_is_pseudo_cursive:
                    shim_height += pseudo_cursive_info[pseudo_cursive_schemas_to_classes[e_schema]][5]
                shim_width = round_with_base(shim_width, rounding_base, MINIMUM_STROKE_GAP)
                shim_height = round_with_base(shim_height, rounding_base, 0, abs)
                e_class = f'{prefix}_shim_{pseudo_cursive_index}_{shim_width}_{shim_height}'.replace('-', 'n')
                classes[e_class].append(e_schema)
                if e_class not in e_classes:
                    e_classes[e_class] = get_shim(shim_width, shim_height)
                (exit_classes_containing_pseudo_cursive_schemas
                        if exit_is_pseudo_cursive
                        else exit_classes_containing_true_cursive_schemas
                    ).add(e_class)
        for exit_class, shim in exit_classes.items():
            if exit_class in exit_classes_containing_pseudo_cursive_schemas:
                add_rule(space_lookup, Rule([exit_class, marker], [marker], pseudo_cursive_class_name, [shim]))
            if exit_class in exit_classes_containing_true_cursive_schemas:
                add_rule(space_lookup, Rule(exit_class, [marker], pseudo_cursive_class_name, [shim]))
        for entry_class, shim in entry_classes.items():
            add_rule(space_lookup, Rule(pseudo_cursive_class_name, [marker], entry_class, [shim]))
    return [marker_lookup, space_lookup]


def shrink_wrap_enclosing_circle(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='i',
    )
    dist_lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='o',
    )
    if len(original_schemas) != len(schemas):
        return [lookup, dist_lookup]
    punctuation = {}
    circle_schema = None
    for schema in schemas:
        if not schema.glyph:
            continue
        if schema.widthless and schema.cps == (0x20DD,):
            assert circle_schema is None
            circle_schema = schema
            classes['i'].append(circle_schema)
        elif schema.encirclable:
            x_min, y_min, x_max, y_max = schema.glyph.boundingBox()
            dx = x_max - x_min
            dy = y_max - y_min
            dx += 3 * builder.stroke_gap + builder.light_line
            dy += 3 * builder.stroke_gap + builder.light_line
            if dx > dy:
                dy = max(dy, dx * 0.75)
            elif dx < dy:
                dx = max(dx, dy * 0.75)
            stretch = max(dx, dy) / min(dx, dy) - 1
            long = dx < dy
            size = min(dx, dy) / 100
            side_bearing = round((dx + 2 * DEFAULT_SIDE_BEARING - schema.glyph.width) / 2)
            class_name = f'c_{stretch}_{long}_{size}_{side_bearing}'
            classes[class_name].append(schema)
            punctuation[class_name] = (stretch, long, size, side_bearing)
    assert circle_schema is not None
    assert isinstance(circle_schema.path, Circle)
    for class_name, (stretch, long, size, side_bearing) in punctuation.items():
        new_circle_schema = circle_schema.clone(
            cmap=None,
            path=circle_schema.path.clone(stretch=stretch, long=long),
            size=size,
        )
        add_rule(lookup, Rule(class_name, [circle_schema], [], [new_circle_schema]))
        classes['o'].append(new_circle_schema)
        add_rule(dist_lookup, Rule([], [class_name], [new_circle_schema], x_placements=[side_bearing], x_advances=[side_bearing]))
        add_rule(dist_lookup, Rule([class_name], [new_circle_schema], [], x_advances=[side_bearing]))
    return [lookup, dist_lookup]


def add_width_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookups_per_position = 6
    lookups = [
        Lookup('dist', 'dflt')
        for _ in range(lookups_per_position)
    ]
    digit_expansion_lookup = Lookup('dist', 'dflt')
    rule_count = 0
    entry_width_markers: MutableMapping[tuple[Incomplete, ...], Schema] = {}
    left_bound_markers: MutableMapping[tuple[Incomplete, ...], Schema] = {}
    right_bound_markers: MutableMapping[tuple[Incomplete, ...], Schema] = {}
    anchor_width_markers: MutableMapping[tuple[Incomplete, ...], Schema] = {}
    path_to_markers = {
        EntryWidthDigit: entry_width_markers,
        AnchorWidthDigit: anchor_width_markers,
        LeftBoundDigit: left_bound_markers,
        RightBoundDigit: right_bound_markers,
    }
    start = next((s for s in schemas if isinstance(s.path, Start)), None)
    if start is None:
        start = Schema(None, Start(), 0)
        classes[phases.CONTINUING_OVERLAP_OR_HUB_CLASS].append(start)
    hubs: MutableMapping[int, list[Schema]] = {-1: []}
    for hub_priority in range(0, MAX_HUB_PRIORITY + 1):
        hub = next((s for s in schemas if isinstance(s.path, Hub) and s.path.priority == hub_priority), None)
        if hub is None:
            hub = Schema(None, Hub(hub_priority), 0, side_bearing=0)
            classes[phases.HUB_CLASS].append(hub)
            classes[phases.CONTINUING_OVERLAP_OR_HUB_CLASS].append(hub)
        hubs[hub_priority] = [hub]
    end = Schema(None, End(), 0, side_bearing=0)
    mark_anchor_selectors: MutableMapping[int, Schema] = {}

    def register_mark_anchor_selector(index: int) -> Schema:
        if index in mark_anchor_selectors:
            return mark_anchor_selectors[index]
        return mark_anchor_selectors.setdefault(index, Schema(None, MarkAnchorSelector(index), 0))

    def get_mark_anchor_selector(schema: Schema) -> Schema:
        only_anchor_class_name: Optional[str] = None
        assert schema.glyph is not None
        for anchor_class_name, type, _, _ in schema.glyph.anchorPoints:
            if type == 'mark' and anchor_class_name in anchors.ALL_MARK:
                assert only_anchor_class_name is None, f'{schema} has multiple anchors: {only_anchor_class_name} and {anchor_class_name}'
                only_anchor_class_name = anchor_class_name
        assert only_anchor_class_name is not None
        return register_mark_anchor_selector(anchors.ALL_MARK.index(only_anchor_class_name))

    glyph_class_selectors: MutableMapping[GlyphClass, Schema] = {}

    def register_glyph_class_selector(glyph_class: GlyphClass) -> Schema:
        if glyph_class in glyph_class_selectors:
            return glyph_class_selectors[glyph_class]
        return glyph_class_selectors.setdefault(glyph_class, Schema(None, GlyphClassSelector(glyph_class), 0))

    def get_glyph_class_selector(schema: Schema) -> Schema:
        return register_glyph_class_selector(schema.glyph_class)

    def register_width_marker(width_markers: MutableMapping[tuple[Incomplete, ...], Schema], digit_path: type[Digit], *args: Incomplete) -> Schema:
        if args not in width_markers:
            width_marker = Schema(None, digit_path(*args), 0)
            width_markers[args] = width_marker
        return width_markers[args]

    width_number_schemas: MutableMapping[WidthNumber[Digit], Schema] = {}

    def get_width_number_schema(width_number: WidthNumber[Digit]) -> Schema:
        if width_number in width_number_schemas:
            return width_number_schemas[width_number]
        return width_number_schemas.setdefault(width_number, Schema(None, width_number, 0))

    width_number_counter: collections.Counter[WidthNumber[Digit]] = collections.Counter()
    minimum_optimizable_width_number_count = 2
    width_numbers: MutableMapping[tuple[type[Digit], int], WidthNumber[Digit]] = {}

    def get_width_number(digit_path: type[Digit], width: float) -> WidthNumber[Digit]:
        width = round(width)
        if (digit_path, width) in width_numbers:
            width_number = width_numbers[(digit_path, width)]
        else:
            width_number = WidthNumber(digit_path, width)
            width_numbers[(digit_path, width)] = width_number
        width_number_counter[width_number] += 1
        if width_number_counter[width_number] == minimum_optimizable_width_number_count:
            add_rule(digit_expansion_lookup, Rule(
                [get_width_number_schema(width_number)],
                width_number.to_digits(functools.partial(register_width_marker, path_to_markers[digit_path])),
            ))
        return width_number

    schemas_needing_width_markers = []
    rules_to_add = []
    for schema in new_schemas:
        if schema not in original_schemas:
            continue
        if schema.glyph is None:
            match schema.path:
                case MarkAnchorSelector():
                    mark_anchor_selectors[schema.path.index] = schema
                case GlyphClassSelector():
                    glyph_class_selectors[schema.glyph_class] = schema
            if not isinstance(schema.path, Space):
                # Not a schema created in `add_shims_for_pseudo_cursive`
                continue
        if schema.might_need_width_markers and (
            schema.glyph_class != GlyphClass.MARK or any(a[0] in anchors.ALL_MARK for a in schema.glyph.anchorPoints)  # type: ignore[union-attr]
        ):
            entry_xs = {}
            exit_xs = {}
            if schema.glyph is None and isinstance(schema.path, Space):
                entry_xs[anchors.CURSIVE] = 0
                exit_xs[anchors.CURSIVE] = schema.size
            else:
                assert schema.glyph is not None
                for anchor_class_name, type, x, _ in schema.glyph.anchorPoints:
                    if type in ['entry', 'mark']:
                        entry_xs[anchor_class_name] = x
                    elif type in ['base', 'basemark', 'exit']:
                        exit_xs[anchor_class_name] = x
            if not (entry_xs or exit_xs):
                # This glyph never appears in the final glyph buffer.
                continue
            entry_xs.setdefault(anchors.CURSIVE, 0)
            if anchors.CURSIVE not in exit_xs:
                exit_xs[anchors.CURSIVE] = exit_xs.get(anchors.CONTINUING_OVERLAP, 0)
            entry_xs.setdefault(anchors.CONTINUING_OVERLAP, entry_xs[anchors.CURSIVE])
            exit_xs.setdefault(anchors.CONTINUING_OVERLAP, exit_xs[anchors.CURSIVE])
            start_x = entry_xs[anchors.CURSIVE if schema.glyph_class == GlyphClass.JOINER else anchor_class_name]
            schemas_needing_width_markers.append((schema, entry_xs, exit_xs, start_x))
    for schema, entry_xs, exit_xs, start_x in schemas_needing_width_markers:
        if schema.glyph is None:
            x_min = x_max = 0.0
        else:
            x_min, _, x_max, _ = schema.glyph.boundingBox()
        if x_min == x_max == 0:
            x_min = entry_xs[anchors.CURSIVE]
            x_max = exit_xs[anchors.CURSIVE]
        if schema.glyph_class == GlyphClass.MARK:
            mark_anchor_selector = [get_mark_anchor_selector(schema)]
        else:
            mark_anchor_selector = []
        glyph_class_selector = get_glyph_class_selector(schema)
        widths = []
        for width, digit_path in [
            (entry_xs[anchors.CURSIVE] - entry_xs[anchors.CONTINUING_OVERLAP], EntryWidthDigit),
            (x_min - start_x, LeftBoundDigit),
            (x_max - start_x, RightBoundDigit),
            *[
                (
                    exit_xs[anchor] - start_x if anchor in exit_xs else 0,
                    AnchorWidthDigit,
                ) for anchor in anchors.ALL_MARK
            ],
            *[
                (
                    exit_xs[anchor] - start_x if schema.glyph_class == GlyphClass.JOINER else 0,
                    AnchorWidthDigit,
                ) for anchor in anchors.ALL_CURSIVE
            ],
        ]:
            assert (width < WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                if width >= 0
                else width >= -WIDTH_MARKER_RADIX ** WIDTH_MARKER_PLACES / 2
                ), f'Glyph {schema} is too wide: {width} units'
            widths.append(get_width_number(digit_path, width))
        lookup = lookups[rule_count * lookups_per_position // len(schemas_needing_width_markers)]
        rule_count += 1
        rules_to_add.append((
            widths,
            (lambda widths,
                    lookup=lookup, glyph_class_selector=glyph_class_selector, mark_anchor_selector=mark_anchor_selector, start=start, schema=schema:
                add_rule(lookup, Rule([schema], [
                    start,
                    glyph_class_selector,
                    *mark_anchor_selector,
                    *hubs[schema.hub_priority],
                    schema,
                    *widths,
                    end,
                ]))
            ),
        ))
    for widths, rule_to_add in rules_to_add:
        final_widths = []
        for width_number in widths:
            if width_number_counter[width_number] >= minimum_optimizable_width_number_count:
                final_widths.append(get_width_number_schema(width_number))
            else:
                final_widths.extend(width_number.to_digits(functools.partial(
                    register_width_marker,
                    path_to_markers[width_number.digit_path],
                )))
        rule_to_add(final_widths)
    return [
        *lookups,
        digit_expansion_lookup,
    ]


def add_end_markers_for_marks(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup('dist', 'dflt')
    end = next(s for s in new_schemas if isinstance(s.path, End))
    for schema in new_schemas:
        if (schema.glyph is not None
            and schema.glyph_class == GlyphClass.MARK
            and not schema.ignored_for_topography
            and not schema.path.invisible()
            and not any(a[0] in anchors.ALL_MARK for a in schema.glyph.anchorPoints)
        ):
            add_rule(lookup, Rule([schema], [schema, end]))
    return [lookup]


def remove_false_end_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
    )
    if 'all' in classes:
        return [lookup]
    dummy = Schema(None, Dummy(), 0)
    end = next(s for s in new_schemas if isinstance(s.path, End))
    classes['all'].append(end)
    add_rule(lookup, Rule([], [end], [end], [dummy]))
    return [lookup]


def clear_entry_width_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
    )
    zeros: list[Optional[Schema]] = [None] * WIDTH_MARKER_PLACES
    if 'zero' not in named_lookups:
        named_lookups['zero'] = Lookup(None, None)
    for schema in schemas:
        match schema.path:
            case EntryWidthDigit():
                classes['all'].append(schema)
                classes['idx'].append(schema)
                if schema.path.digit == 0:
                    zeros[schema.path.place] = schema
            case ContinuingOverlap():
                classes['all'].append(schema)
                continuing_overlap = schema
    for schema in new_schemas:
        if isinstance(schema.path, EntryWidthDigit) and schema.path.digit != 0:
            zero = zeros[schema.path.place]
            assert zero is not None
            add_rule(named_lookups['zero'], Rule([schema], [zero]))
    add_rule(lookup, Rule(
        [continuing_overlap],
        ['idx'] * WIDTH_MARKER_PLACES,
        [],
        lookups=[None] * WIDTH_MARKER_PLACES,
    ))
    add_rule(lookup, Rule(
        [],
        ['idx'] * WIDTH_MARKER_PLACES,
        [],
        lookups=['zero'] * WIDTH_MARKER_PLACES,
    ))
    return [lookup]


_T = TypeVar('_T')


class _AlwaysTrueList(list[_T]):
    def __bool__(self) -> Literal[True]:
        return True


def sum_width_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='all',
        # TODO: `prepending` is a hack.
        prepending=True,
    )
    carry_schema = None
    carry_0_placeholder = object()
    original_carry_schemas = [carry_0_placeholder]
    entry_digit_schemas = {}
    original_entry_digit_schemas = []
    left_digit_schemas = {}
    original_left_digit_schemas = []
    right_digit_schemas = {}
    original_right_digit_schemas = []
    anchor_digit_schemas = {}
    original_anchor_digit_schemas = []
    mark_anchor_selectors: MutableMapping[int, Schema] = {}

    def get_mark_anchor_selector(index: int, class_name: str) -> Schema:
        if index in mark_anchor_selectors:
            rv = mark_anchor_selectors[index]
            classes[class_name].append(rv)
            return rv
        rv = Schema(
            None,
            MarkAnchorSelector(index - len(anchors.ALL_CURSIVE)),
            0,
        )
        classes['all'].append(rv)
        classes[class_name].append(rv)
        return mark_anchor_selectors.setdefault(index, rv)

    glyph_class_selectors: MutableMapping[GlyphClass, Schema] = {}

    def get_glyph_class_selector(glyph_class: GlyphClass, class_name: str) -> Schema:
        if glyph_class in glyph_class_selectors:
            rv = glyph_class_selectors[glyph_class]
            classes[class_name].append(rv)
            return rv
        rv = Schema(
            None,
            GlyphClassSelector(glyph_class),
            0,
        )
        classes['all'].append(rv)
        classes[class_name].append(rv)
        return glyph_class_selectors.setdefault(glyph_class, rv)

    for schema in schemas:
        match schema.path:
            case ContinuingOverlap():
                classes['all'].append(schema)
                continuing_overlap = schema
            case Carry():
                carry_schema = schema
                original_carry_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
            case EntryWidthDigit():
                entry_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_entry_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'idx_{schema.path.place}'].append(schema)
                    classes[f'iadx_{schema.path.place}'].append(schema)
            case LeftBoundDigit():
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_left_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'ldx_{schema.path.place}'].append(schema)
            case RightBoundDigit():
                right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_right_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'rdx_{schema.path.place}'].append(schema)
            case AnchorWidthDigit():
                anchor_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_anchor_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'adx_{schema.path.place}'].append(schema)
                    classes[f'iadx_{schema.path.place}'].append(schema)
            case Dummy():
                dummy = schema
            case MarkAnchorSelector():
                mark_anchor_selectors[schema.path.index] = schema
            case GlyphClassSelector():
                glyph_class_selectors[schema.path.glyph_class] = schema
    for (
        original_augend_schemas,
        augend_letter,
        inner_iterable,
    ) in [(
        original_entry_digit_schemas,
        'i',
        [*[(
            False,
            0,
            i,
            'a',
            original_anchor_digit_schemas,
            anchor_digit_schemas,
            AnchorWidthDigit,
        ) for i, anchor in enumerate(anchors.ALL)], (
            False,
            0,
            0,
            'l',
            original_left_digit_schemas,
            left_digit_schemas,
            LeftBoundDigit,
        ), (
            False,
            0,
            0,
            'r',
            original_right_digit_schemas,
            right_digit_schemas,
            RightBoundDigit,
        )],
    ), (
        original_anchor_digit_schemas,
        'a',
        [*[(
            True,
            i,
            0,
            'i',
            original_entry_digit_schemas,
            entry_digit_schemas,
            EntryWidthDigit,
        ) for i in range(len(anchors.ALL) - 1, -1, -1)], *[(
            False,
            i,
            len(anchors.ALL) - 1 - i,
            'a',
            original_anchor_digit_schemas,
            anchor_digit_schemas,
            AnchorWidthDigit,
        ) for i in range(len(anchors.ALL))]],
    )]:
        for augend_schema in original_augend_schemas:
            augend_is_new = augend_schema in new_schemas
            place = augend_schema.path.place  # type: ignore[attr-defined]
            augend = augend_schema.path.digit  # type: ignore[attr-defined]
            for (
                continuing_overlap_is_relevant,
                augend_skip_backtrack,
                addend_skip_backtrack,
                addend_letter,
                original_addend_schemas,
                addend_schemas,
                addend_path,
            ) in inner_iterable:  # type: ignore[attr-defined]
                for carry_in_schema in original_carry_schemas:
                    carry_in = 0 if carry_in_schema is carry_0_placeholder else 1
                    carry_in_is_new = carry_in_schema in new_schemas
                    for addend_schema in original_addend_schemas:
                        if place != addend_schema.path.place:
                            continue
                        if not (carry_in_is_new or augend_is_new or addend_schema in new_schemas):
                            continue
                        addend = addend_schema.path.digit
                        carry_out, sum_digit = divmod(carry_in + augend + addend, WIDTH_MARKER_RADIX)
                        context_in_lookup_name = f'e{place}_c{carry_in}_{addend_letter}{addend}'
                        if continuing_overlap_is_relevant:
                            classes[context_in_lookup_name].append(continuing_overlap)
                        classes[context_in_lookup_name].extend(classes[f'{augend_letter}dx_{place}'])
                        if (carry_out != 0 and place != WIDTH_MARKER_PLACES - 1) or sum_digit != addend:
                            if carry_out == 0:
                                carry_out_schema = carry_0_placeholder
                            elif carry_schema is not None:
                                carry_out_schema = carry_schema
                            else:
                                assert carry_out == 1, carry_out
                                carry_out_schema = Schema(None, Carry(), 0)
                                carry_schema = carry_out_schema
                            sum_index = place * WIDTH_MARKER_RADIX + sum_digit
                            if sum_index in addend_schemas:
                                sum_digit_schema = addend_schemas[sum_index]
                            else:
                                sum_digit_schema = Schema(None, addend_path(place, sum_digit), 0)
                                addend_schemas[sum_index] = sum_digit_schema
                                classes[f'{addend_letter}dx_{sum_digit_schema.path.place}'].append(sum_digit_schema)
                                classes['all'].append(sum_digit_schema)
                            outputs = ([sum_digit_schema]
                                if carry_out == 0 or place == WIDTH_MARKER_PLACES - 1
                                else [sum_digit_schema, carry_out_schema])
                            sum_lookup_name = str(sum_digit)
                            if sum_lookup_name not in named_lookups:
                                named_lookups[sum_lookup_name] = Lookup(None, None)
                            if context_in_lookup_name not in named_lookups:
                                classes[context_in_lookup_name].append(addend_schema)
                                named_lookups[context_in_lookup_name] = Lookup(
                                    None,
                                    None,
                                    flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                                    mark_filtering_set=context_in_lookup_name,
                                )
                            contexts_in = [carry_in_schema] if isinstance(carry_in_schema, Schema | str) else _AlwaysTrueList()
                            add_rule(lookup, Rule(
                                contexts_in,
                                [addend_schema],
                                [],
                                lookups=[context_in_lookup_name],
                            ))
                            classes[context_in_lookup_name].extend(classes[f'idx_{place}'])
                            if addend_skip_backtrack != 0:
                                classes[context_in_lookup_name].extend(classes[f'{addend_letter}dx_{sum_digit_schema.path.place}'])
                            context_in_lookup_context_in: list[Schema | str] = []
                            if augend_letter == 'i' and addend_letter == 'a':
                                context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.JOINER, context_in_lookup_name))
                            context_in_lookup_context_in.append(augend_schema)
                            context_in_lookup_context_in.extend([f'iadx_{place}'] * augend_skip_backtrack)
                            if augend_letter == 'a' and addend_letter == 'a':
                                context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.MARK, context_in_lookup_name))
                                context_in_lookup_context_in.append(f'iadx_{place}')
                            elif augend_skip_backtrack == 1:
                                context_in_lookup_context_in.append(continuing_overlap)
                            elif augend_letter == 'a' and addend_letter == 'i' and augend_skip_backtrack != 0:
                                context_in_lookup_context_in.append(get_mark_anchor_selector(
                                    len(anchors.ALL) - augend_skip_backtrack - 1,
                                    context_in_lookup_name,
                                ))
                            context_in_lookup_context_in.extend([f'iadx_{sum_digit_schema.path.place}'] * addend_skip_backtrack)
                            add_rule(named_lookups[context_in_lookup_name], Rule(
                                context_in_lookup_context_in,
                                [addend_schema],
                                [],
                                lookups=[sum_lookup_name],
                            ))
                            add_rule(named_lookups[sum_lookup_name], Rule([addend_schema], outputs))
    return [lookup]


def calculate_bound_extrema(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    left_lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='ldx',
    )
    named_lookups['ldx_copy'] = Lookup(
        None,
        None,
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='ldx',
    )
    left_digit_schemas = {}
    right_lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='rdx',
    )
    named_lookups['rdx_copy'] = Lookup(
        None,
        None,
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='rdx',
    )
    right_digit_schemas = {}
    for schema in schemas:
        match schema.path:
            case LeftBoundDigit():
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                if schema in new_schemas:
                    classes['ldx'].append(schema)
            case RightBoundDigit():
                right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                if schema in new_schemas:
                    classes['rdx'].append(schema)
    for place in range(WIDTH_MARKER_PLACES - 1, -1, -1):
        for i in range(0, WIDTH_MARKER_RADIX):
            left_schema_i = left_digit_schemas.get(place * WIDTH_MARKER_RADIX + i)
            right_schema_i = right_digit_schemas.get(place * WIDTH_MARKER_RADIX + i)
            i_signed = i if place != WIDTH_MARKER_PLACES - 1 or i < WIDTH_MARKER_RADIX / 2 else i - WIDTH_MARKER_RADIX
            if left_schema_i is None and right_schema_i is None:
                continue
            for j in range(0, WIDTH_MARKER_RADIX):
                if i == j:
                    continue
                j_signed = j if place != WIDTH_MARKER_PLACES - 1 or j < WIDTH_MARKER_RADIX / 2 else j - WIDTH_MARKER_RADIX
                for schema_i, digit_schemas, lookup, marker_class, copy_lookup_name, compare in [
                    (left_schema_i, left_digit_schemas, left_lookup, 'ldx', 'ldx_copy', int.__gt__),
                    (right_schema_i, right_digit_schemas, right_lookup, 'rdx', 'rdx_copy', int.__lt__),
                ]:
                    assert schema_i is not None
                    schema_j = digit_schemas.get(place * WIDTH_MARKER_RADIX + j)
                    if schema_j is None:
                        continue
                    place_j = schema_j.path.place  # type: ignore[attr-defined]
                    add_rule(lookup, Rule(
                        [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - schema_i.path.place - 1)],  # type: ignore[attr-defined]
                        [*[marker_class] * place_j, schema_j],
                        [],
                        lookups=[None if compare(i_signed, j_signed) else copy_lookup_name] * (place_j + 1)))
                    add_rule(named_lookups[copy_lookup_name], Rule(
                        [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - 1)],
                        [schema_j],
                        [],
                        [schema_i]))
    return [left_lookup, right_lookup]


def remove_false_start_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
        reversed=True,
    )
    dummy = next(s for s in new_schemas if isinstance(s.path, Dummy))
    start = next(s for s in new_schemas if isinstance(s.path, Start))
    classes['all'].append(start)
    add_rule(lookup, Rule([start], [start], [], [dummy]))
    return [lookup]


def mark_hubs_after_initial_secants(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='all',
        reversed=True,
    )
    hubs: OrderedSet[Schema] = OrderedSet()
    for schema in new_schemas:
        if isinstance(schema.path, Hub) and not schema.path.initial_secant:
            hubs.add(schema)
            classes['all'].append(schema)
        elif isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.JOINER:
            classes['secant'].append(schema)
    for hub in hubs:
        assert isinstance(hub.path, Hub)
        initial_secant_hub = hub.clone(path=hub.path.clone(initial_secant=True))
        classes[phases.HUB_CLASS].append(initial_secant_hub)
        classes[phases.CONTINUING_OVERLAP_OR_HUB_CLASS].append(initial_secant_hub)
        add_rule(lookup, Rule(
            ['secant'],
            [hub],
            [],
            [initial_secant_hub],
        ))
    return [lookup]


def find_real_hub(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
    )
    hubs = collections.defaultdict(list)
    for schema in new_schemas:
        match schema.path:
            case Dummy():
                dummy = schema
            case Hub():
                hubs[schema.path.priority].append(schema)
                classes['all'].append(schema)
            case InitialSecantMarker():
                classes['all'].append(schema)
            case ContinuingOverlap():
                continuing_overlap = schema
                classes['all'].append(schema)
    for priority_a, hubs_a in sorted(hubs.items()):
        for priority_b, hubs_b in sorted(hubs.items()):
            for hub_a in hubs_a:
                assert isinstance(hub_a.path, Hub)
                if not hub_a.path.initial_secant:
                    add_rule(lookup, Rule([continuing_overlap], [hub_a], [], [dummy]))
                for hub_b in hubs_b:
                    assert isinstance(hub_b.path, Hub)
                    if hub_b.path.initial_secant:
                        continue
                    if priority_a <= priority_b:
                        add_rule(lookup, Rule([hub_a], [hub_b], [], [dummy]))
                    else:
                        add_rule(lookup, Rule([], [hub_a], [hub_b], [dummy]))
    return [lookup]


def expand_start_markers(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup('dist', 'dflt')
    start = next(s for s in new_schemas if isinstance(s.path, Start))
    add_rule(lookup, Rule([start], [
        start,
        *(Schema(None, LeftBoundDigit(place, 0, DigitStatus.DONE), 0) for place in range(WIDTH_MARKER_PLACES)),
    ]))
    return [lookup]


def mark_maximum_bounds(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    left_lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='ldx',
        reversed=True,
    )
    right_lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='rdx',
        reversed=True,
    )
    anchor_lookup = Lookup(
        'dist',
        'dflt',
        mark_filtering_set='adx',
        reversed=True,
    )
    new_left_bounds = []
    new_right_bounds = []
    new_anchor_widths = []
    end = next(s for s in schemas if isinstance(s.path, End))
    for schema in new_schemas:
        match schema.path:
            case LeftBoundDigit():
                classes['ldx'].append(schema)
                new_left_bounds.append(schema)
            case RightBoundDigit():
                classes['rdx'].append(schema)
                new_right_bounds.append(schema)
            case AnchorWidthDigit():
                classes['adx'].append(schema)
                new_anchor_widths.append(schema)
    for new_digits, lookup, class_name, digit_path, status in [
        (new_left_bounds, left_lookup, 'ldx', LeftBoundDigit, DigitStatus.ALMOST_DONE),
        (new_right_bounds, right_lookup, 'rdx', RightBoundDigit, DigitStatus.DONE),
        (new_anchor_widths, anchor_lookup, 'adx', AnchorWidthDigit, DigitStatus.DONE),
    ]:
        for schema in new_digits:
            if schema.path.status != DigitStatus.NORMAL:  # type: ignore[attr-defined]
                continue
            add_rule(lookup, Rule(
                [],
                [schema],
                [*[class_name] * (WIDTH_MARKER_PLACES - schema.path.place - 1), end],  # type: ignore[attr-defined]
                [Schema(None, digit_path(schema.path.place, schema.path.digit, status), 0)]))  # type: ignore[attr-defined]
    return [left_lookup, right_lookup, anchor_lookup]


def copy_maximum_left_bound_to_start(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'dist',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
    )
    new_left_totals = []
    new_left_start_totals: list[Optional[Schema]] = [None] * WIDTH_MARKER_PLACES
    start = next(s for s in schemas if isinstance(s.path, Start))
    if start not in classes['all']:
        classes['all'].append(start)
    for schema in new_schemas:
        if isinstance(schema.path, LeftBoundDigit):
            if schema.path.status == DigitStatus.ALMOST_DONE:
                new_left_totals.append(schema)
            elif schema.path.status == DigitStatus.DONE and schema.path.digit == 0:
                new_left_start_totals[schema.path.place] = schema
    for total in new_left_totals:
        classes['all'].append(total)
        total_digit = total.path.digit  # type: ignore[attr-defined]
        total_place = total.path.place  # type: ignore[attr-defined]
        if total_digit == 0:
            done = new_left_start_totals[total_place]
            assert done is not None
        else:
            done = Schema(None, LeftBoundDigit(total_place, total_digit, DigitStatus.DONE), 0)
        classes['all'].append(done)
        if total_digit != 0:
            input = new_left_start_totals[total_place]
            assert input is not None
            if input not in classes['all']:
                classes['all'].append(input)
            add_rule(lookup, Rule(
                [start, *['all'] * total_place],
                [input],
                [*['all'] * (WIDTH_MARKER_PLACES - 1), total],
                [done]))
    return [lookup]


def dist(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup('dist', 'dflt')
    for schema in new_schemas:
        if ((isinstance(schema.path, LeftBoundDigit)
                or isinstance(schema.path, RightBoundDigit)
                or isinstance(schema.path, AnchorWidthDigit))
                and schema.path.status == DigitStatus.DONE):
            place = schema.path.place
            digit = schema.path.digit
            if isinstance(schema.path, LeftBoundDigit):
                digit = WIDTH_MARKER_RADIX - 1 - digit
                if place == 0:
                    digit += 1
            if place == WIDTH_MARKER_PLACES - 1 and digit >= WIDTH_MARKER_RADIX / 2:
                digit -= WIDTH_MARKER_RADIX
            x_advance = digit * WIDTH_MARKER_RADIX ** place
            if isinstance(schema.path, AnchorWidthDigit):
                x_advance = -x_advance
            elif place == 0:
                x_advance += DEFAULT_SIDE_BEARING
            if x_advance:
                add_rule(lookup, Rule([], [schema], [], x_advances=[x_advance]))
    return [lookup]


PHASE_LIST = [
    add_shims_for_pseudo_cursive,
    shrink_wrap_enclosing_circle,
    add_width_markers,
    add_end_markers_for_marks,
    remove_false_end_markers,
    clear_entry_width_markers,
    sum_width_markers,
    calculate_bound_extrema,
    remove_false_start_markers,
    mark_hubs_after_initial_secants,
    find_real_hub,
    expand_start_markers,
    mark_maximum_bounds,
    copy_maximum_left_bound_to_start,
    dist,
]
