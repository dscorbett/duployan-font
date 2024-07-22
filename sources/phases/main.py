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
import functools
import itertools
import string
from typing import TYPE_CHECKING
from typing import TypeVar

import fontTools.otlLib.builder

from . import Lookup
from . import Rule
import anchors
import phases
from schema import Ignorability
from schema import MAX_DOUBLE_MARKS
from schema import Schema
from shapes import ChildEdge
from shapes import Circle
from shapes import CircleRole
from shapes import Complex
from shapes import ContextMarker
from shapes import ContinuingOverlap
from shapes import ContinuingOverlapS
from shapes import Curve
from shapes import EqualsSign
from shapes import Grammalogue
from shapes import InitialSecantMarker
from shapes import InvalidDTLS
from shapes import InvalidOverlap
from shapes import InvalidStep
from shapes import Line
from shapes import Ou
from shapes import ParentEdge
from shapes import RootOnlyParentEdge
from shapes import RotatedComplex
from shapes import Space
from shapes import ValidDTLS
from shapes import Wa
from shapes import Wi
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import Context
from utils import EPSILON
from utils import GlyphClass
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import NO_CONTEXT
from utils import OrderedSet
from utils import SMALL_DIGIT_FACTOR
from utils import SUBSCRIPT_DEPTH
from utils import SUPERSCRIPT_HEIGHT
from utils import Type
from utils import mkmk


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence
    from collections.abc import Sequence

    from . import AddRule
    from . import FreezableList
    from duployan import Builder
    from shapes import Shape
    from utils import PrefixView


def dont_ignore_default_ignorables(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup_1 = Lookup('abvm', 'dflt')
    lookup_2 = Lookup('abvm', 'dflt')
    for schema in schemas:
        if schema.ignorability == Ignorability.OVERRIDDEN_NO:
            add_rule(lookup_1, Rule([schema], [schema, schema]))
            add_rule(lookup_2, Rule([schema, schema], [schema]))
    return [lookup_1, lookup_2]


def reversed_circle_kludge(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('rlig', 'dflt')
    cgj = next(s for s in schemas if s.cmap == 0x034F)
    for schema in new_schemas:
        if schema.cmap in {0x1BC44, 0x1BC53, 0x1BC5A, 0x1BC5B, 0x1BC5C, 0x1BC5D, 0x1BC5E, 0x1BC5F, 0x1BC60}:
            assert isinstance(schema.path, Circle | Curve | Ou | Wa | Wi)
            add_rule(lookup, Rule(
                [schema, cgj, cgj, cgj],
                [schema.clone(
                    cmap=None,
                    cps=[*schema.cps, 0x034F, 0x034F, 0x034F],
                    path=schema.path.clone(
                            angle_out=(2 * schema.path.angle_in - schema.path.angle_out) % 360,
                            clockwise=not schema.path.clockwise,
                            secondary=None,
                        ) if isinstance(schema.path, Curve) else schema.path.as_reversed(),
                )],
            ))
    return [lookup]


def validate_shading(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='independent_mark',
        reverse=True,
    )
    if len(new_schemas) == len(schemas):
        invalid_dtls = next(s for s in schemas if isinstance(s.path, InvalidDTLS))
        valid_dtls = invalid_dtls.clone(cmap=None, path=ValidDTLS())
        for schema in new_schemas:
            if schema.anchor:
                if schema.cmap is not None:
                    classes['independent_mark'].append(schema)
            elif schema.shading_allowed and schema.path.is_shadable():
                classes['c'].append(schema)
        add_rule(lookup, Rule(['c'], [invalid_dtls], [], [valid_dtls]))
    return [lookup]


def validate_double_marks(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='double_mark',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    double_mark = next(s for s in original_schemas if s.cps == (0x1BC9E,))
    classes['double_mark'].append(double_mark)
    new_maximums = set()
    for schema in new_schemas:
        maximum = schema.max_double_marks
        new_maximums.add(maximum)
        classes[str(maximum)].append(schema)
    for maximum in sorted(new_maximums, reverse=True):
        for i in range(maximum):
            add_rule(lookup, Rule([str(maximum)] + [double_mark] * i, [double_mark], [], lookups=[None]))
    guideline = Schema(None, Line(0, dots=7), 1.5, Type.NON_JOINING, maximum_tree_width=MAX_TREE_WIDTH)
    add_rule(lookup, Rule([double_mark], [guideline, double_mark]))
    return [lookup]


def decompose(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('abvm', 'dflt')
    for schema in schemas:
        if schema.marks and schema in new_schemas:
            add_rule(lookup, Rule([schema], [schema.without_marks, *schema.marks]))
    return [lookup]


def expand_secants(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
    named_lookups['non_initial_secant'] = Lookup()
    for schema in new_schemas:
        if schema.is_secant:
            assert isinstance(schema.path, Line)
            add_rule(named_lookups['non_initial_secant'], Rule(
                [schema],
                [schema.clone(
                    cmap=None,
                    path=schema.path.clone(secant_curvature_offset=-schema.path.secant_curvature_offset),
                    anchor=anchors.SECANT,
                    widthless=False,
                )],
            ))
            classes['secant'].append(schema)
        elif schema.can_take_secant:
            classes['base'].append(schema)
    add_rule(lookup, Rule('base', 'secant', [], lookups=['non_initial_secant']))
    initial_secant_marker = Schema(None, InitialSecantMarker(), 0, side_bearing=0)
    add_rule(lookup, Rule(
        ['secant'],
        ['secant', continuing_overlap, initial_secant_marker],
    ))
    return [lookup]


def validate_overlap_controls(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='overlap',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    named_lookups['validate'] = Lookup()
    new_classes = {}
    global_max_tree_width = 0
    for schema in new_schemas:
        if isinstance(schema.path, InvalidOverlap):
            if schema.path.continuing:
                continuing_overlap = schema
            else:
                letter_overlap = schema
        elif not schema.anchor and (max_tree_width := schema.max_tree_width()):
            global_max_tree_width = max(global_max_tree_width, max_tree_width)
            classes['base'].append(schema)
            new_class = f'base_{max_tree_width}'
            classes[new_class].append(schema)
            new_classes[max_tree_width] = new_class
    assert global_max_tree_width == MAX_TREE_WIDTH
    classes['invalid'].append(letter_overlap)
    classes['invalid'].append(continuing_overlap)
    valid_letter_overlap = letter_overlap.clone(cmap=None, path=ChildEdge(lineage=((1, 0),)), side_bearing=0)
    valid_continuing_overlap = continuing_overlap.clone(cmap=None, path=ContinuingOverlap(), side_bearing=0)
    classes['valid'].append(valid_letter_overlap)
    classes['valid'].append(valid_continuing_overlap)
    classes['overlap'].append(valid_letter_overlap)
    classes['overlap'].append(valid_continuing_overlap)
    add_rule(lookup, Rule('invalid', 'invalid', [], lookups=[None]))
    add_rule(named_lookups['validate'], Rule('invalid', 'valid'))
    add_rule(lookup, Rule('valid', 'invalid', [], lookups=['validate']))
    for i in range(global_max_tree_width - 2):
        add_rule(lookup, Rule([], [letter_overlap], [*[letter_overlap] * i, continuing_overlap, 'invalid'], lookups=[None]))
    if global_max_tree_width > 1:
        add_rule(lookup, Rule([], [continuing_overlap], 'invalid', lookups=[None]))
    for max_tree_width, new_class in new_classes.items():
        add_rule(lookup, Rule([new_class], 'invalid', ['invalid'] * max_tree_width, lookups=[None]))
    classes['base'].append(valid_letter_overlap)
    classes['base'].append(valid_continuing_overlap)
    add_rule(lookup, Rule('base', 'invalid', [], lookups=['validate']))
    classes[phases.CHILD_EDGE_CLASSES[0]].append(valid_letter_overlap)
    classes[phases.INTER_EDGE_CLASSES[0][0]].append(valid_letter_overlap)
    classes[phases.CONTINUING_OVERLAP_CLASS].append(valid_continuing_overlap)
    classes[phases.CONTINUING_OVERLAP_OR_HUB_CLASS].append(valid_continuing_overlap)
    return [lookup]


def add_parent_edges(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('blwm', 'dflt')
    root_parent_edge = Schema(None, ParentEdge([]), 0, Type.NON_JOINING, side_bearing=0)
    root_only_parent_edge = Schema(None, RootOnlyParentEdge(), 0, Type.NON_JOINING, side_bearing=0)
    for child_index in range(MAX_TREE_WIDTH):
        if root_parent_edge not in classes[phases.CHILD_EDGE_CLASSES[child_index]]:
            classes[phases.CHILD_EDGE_CLASSES[child_index]].append(root_parent_edge)
        for layer_index in range(MAX_TREE_DEPTH):
            if root_parent_edge not in classes[phases.INTER_EDGE_CLASSES[layer_index][child_index]]:
                classes[phases.INTER_EDGE_CLASSES[layer_index][child_index]].append(root_parent_edge)
    for schema in new_schemas:
        if schema.glyph_class == GlyphClass.JOINER:
            classes['root' if schema.can_be_child() else 'root_only'].append(schema)
    add_rule(lookup, Rule(['root'], [root_parent_edge, 'root']))
    add_rule(lookup, Rule(['root_only'], [root_only_parent_edge, root_parent_edge, 'root_only']))
    return [lookup]


_E = TypeVar('_E')


_N = TypeVar('_N')


def _make_trees(
    node: _N,
    edge: _E,
    maximum_depth: int,
    *,
    top_widths: Iterable[int] | None = None,
    prefix_depth: int | None = None,
) -> Sequence[Sequence[_E | _N]]:
    if maximum_depth <= 0:
        return []
    trees = []
    if prefix_depth is None:
        subtrees = _make_trees(node, edge, maximum_depth - 1)
        for width in range(MAX_TREE_WIDTH + 1) if top_widths is None else top_widths:
            for index_set in itertools.product(range(len(subtrees)), repeat=width):
                tree: MutableSequence[_E | _N] = [node, *[edge] * width] if top_widths is None else []
                for i in index_set:
                    tree.extend(subtrees[i])
                trees.append(tree)
    elif prefix_depth == 1:
        trees.append([])
    else:
        shallow_subtrees = _make_trees(node, edge, maximum_depth - 2)
        deep_subtrees = _make_trees(node, edge, maximum_depth - 1, prefix_depth=prefix_depth - 1)
        for width in range(1, MAX_TREE_WIDTH + 1) if top_widths is None else top_widths:
            for shallow_index_set in itertools.product(range(len(shallow_subtrees)), repeat=width - 1):
                for deep_subtree in deep_subtrees:
                    for edge_count in [width] if prefix_depth == 2 else range(width, MAX_TREE_WIDTH + 1):
                        tree = [node, *[edge] * edge_count] if top_widths is None else []
                        for i in shallow_index_set:
                            tree.extend(shallow_subtrees[i])
                        tree.extend(deep_subtree)
                        trees.append(tree)
    return trees


def invalidate_overlap_controls(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
        reverse=True,
    )
    for schema in new_schemas:
        match schema.path:
            case ParentEdge():
                node = schema
                classes['all'].append(schema)
            case RootOnlyParentEdge():
                classes['all'].append(schema)
            case ChildEdge():
                valid_letter_overlap = schema
                classes['all'].append(schema)
            case ContinuingOverlap():
                valid_continuing_overlap = schema
                classes['all'].append(schema)
            case InvalidOverlap(continuing=True):
                invalid_continuing_overlap = schema
            case InvalidOverlap():
                invalid_letter_overlap = schema
    classes['valid'].append(valid_letter_overlap)
    classes['valid'].append(valid_continuing_overlap)
    classes['invalid'].append(invalid_letter_overlap)
    classes['invalid'].append(invalid_continuing_overlap)
    add_rule(lookup, Rule([], 'valid', 'invalid', 'invalid'))
    for older_sibling_count in range(MAX_TREE_WIDTH - 1, -1, -1):
        # A continuing overlap not at the top level must be licensed by an
        # ancestral continuing overlap.
        for subtrees in _make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count]):
            for older_sibling_count_of_continuing_overlap in range(MAX_TREE_WIDTH):
                add_rule(lookup, Rule(
                    [valid_letter_overlap] * older_sibling_count,
                    [valid_letter_overlap],
                    [*subtrees, node, *[valid_letter_overlap] * older_sibling_count_of_continuing_overlap, valid_continuing_overlap],
                    [invalid_letter_overlap],
                ))
        # Trees have a maximum depth of `MAX_TREE_DEPTH` letters.
        # TODO: Optimization: Why use a nested `for` loop? Can a combination of
        # `top_width` and `prefix_depth` work?
        for subtrees in _make_trees(node, valid_letter_overlap, MAX_TREE_DEPTH, top_widths=range(older_sibling_count + 1)):
            for deep_subtree in _make_trees(node, 'valid', MAX_TREE_DEPTH, prefix_depth=MAX_TREE_DEPTH):
                add_rule(lookup, Rule(
                    [valid_letter_overlap] * older_sibling_count,
                    'valid',
                    [*subtrees, *deep_subtree],
                    'invalid',
                ))
        # Anything valid needs to be explicitly kept valid, since there might
        # not be enough context to tell that an invalid overlap is invalid.
        for subtrees in _make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count + 1]):
            add_rule(lookup, Rule(
                [valid_letter_overlap] * older_sibling_count if older_sibling_count else [node],
                'valid',
                subtrees,
                'valid',
            ))
    # If an overlap gets here without being kept valid, it is invalid.
    # FIXME: This should be just one rule, without context, but `add_rule`
    # is broken: it does not take into account what rules precede it in the
    # lookup when determining the possible output schemas.
    add_rule(lookup, Rule([], 'valid', 'valid', 'valid'))
    add_rule(lookup, Rule([node], 'valid', [], 'invalid'))
    add_rule(lookup, Rule('valid', 'valid', [], 'invalid'))
    return [lookup]


def add_secant_guidelines(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('abvs', 'dflt')
    if len(original_schemas) != len(schemas):
        return [lookup]
    invalid_continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
    valid_continuing_overlap = next(s for s in schemas if isinstance(s.path, ContinuingOverlap))
    dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
    initial_secant_marker = next(s for s in schemas if isinstance(s.path, InitialSecantMarker))
    named_lookups['prepend_zwnj'] = Lookup()
    for schema in new_schemas:
        if (isinstance(schema.path, Line)
            and schema.path.secant
            and schema.glyph_class == GlyphClass.JOINER
            and schema in original_schemas
        ):
            classes['secant'].append(schema)
            zwnj = Schema(None, Space(0, margins=True), 0, Type.NON_JOINING, side_bearing=0)
            guideline_angle = schema.path.get_guideline_angle()
            lookup_name = f'add_guideline_{guideline_angle}'
            if lookup_name not in named_lookups:
                guideline = Schema(None, Line(guideline_angle, dots=7), 1.5, maximum_tree_width=MAX_TREE_WIDTH)
                named_lookups[f'{lookup_name}_and_dtls'] = Lookup()
                named_lookups[lookup_name] = Lookup()
                add_rule(named_lookups[f'{lookup_name}_and_dtls'], Rule([invalid_continuing_overlap], [dtls, valid_continuing_overlap, guideline]))
                add_rule(named_lookups[lookup_name], Rule([invalid_continuing_overlap], [valid_continuing_overlap, guideline]))
            add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [initial_secant_marker, dtls], lookups=[f'{lookup_name}_and_dtls']))
            add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [], lookups=[lookup_name]))
    add_rule(named_lookups['prepend_zwnj'], Rule('secant', [zwnj, 'secant']))
    add_rule(lookup, Rule([], 'secant', [], lookups=['prepend_zwnj']))
    return [lookup]


def add_placeholders_for_missing_children(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'blwm',
        'dflt',
        mark_filtering_set='valid_final_overlap',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    base_classes = {}
    for schema in new_schemas:
        if isinstance(schema.path, ChildEdge):
            valid_letter_overlap = schema
            classes['valid_final_overlap'].append(schema)
        elif isinstance(schema.path, ContinuingOverlap):
            classes['valid_final_overlap'].append(schema)
        elif (schema.glyph_class == GlyphClass.JOINER
            and (max_tree_width := schema.max_tree_width()) > 1
        ):
            new_class = f'base_{max_tree_width}'
            classes[new_class].append(schema)
            base_classes[max_tree_width] = new_class
    root_parent_edge = next(s for s in schemas if isinstance(s.path, ParentEdge))
    placeholder = Schema(None, Space(0), 0, Type.JOINING, side_bearing=0, child=True)
    for max_tree_width, base_class in base_classes.items():
        inputs = [valid_letter_overlap] * (max_tree_width - 1) + ['valid_final_overlap']
        add_rule(lookup, Rule(
            [base_class],
            inputs,
            [],
            lookups=[None] * len(inputs),
        ))
        for sibling_count in range(max_tree_width - 1, 0, -1):
            backtrack_list = [base_class] + [valid_letter_overlap] * (sibling_count - 1)
            input_1: str | Schema = 'valid_final_overlap' if sibling_count > 1 else valid_letter_overlap
            add_rule(lookup, Rule(
                backtrack_list,
                [input_1],
                [],
                [valid_letter_overlap, input_1] + [root_parent_edge, placeholder] * sibling_count,
            ))
    return [lookup]


def categorize_edges(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'blwm',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
        mark_filtering_set='all',
    )
    old_groups = [s.path.group() for s in classes['all']]
    child_edges: MutableMapping[Sequence[tuple[int, int]], Schema] = {}
    parent_edges: MutableMapping[Sequence[tuple[int, int]], Schema] = {}

    def get_child_edge(lineage: Sequence[tuple[int, int]]) -> Schema:
        lineage = tuple(lineage)
        child_edge = child_edges.get(lineage)
        if child_edge is None:
            assert isinstance(default_child_edge.path, ChildEdge)
            child_edge = default_child_edge.clone(cmap=None, path=default_child_edge.path.clone(lineage=lineage))
            child_edges[lineage] = child_edge
        return child_edge

    def get_parent_edge(lineage: Sequence[tuple[int, int]]) -> Schema:
        lineage = tuple(lineage)
        parent_edge = parent_edges.get(lineage)
        if parent_edge is None:
            assert isinstance(default_parent_edge.path, ParentEdge)
            parent_edge = default_parent_edge.clone(cmap=None, path=default_parent_edge.path.clone(lineage=lineage))
            parent_edges[lineage] = parent_edge
        return parent_edge

    for schema in schemas:
        if isinstance(schema.path, ChildEdge):
            child_edges[tuple(schema.path.lineage)] = schema
            if (len(schema.path.lineage) == 1
                and schema.path.lineage[0][0] == 1
            ):
                default_child_edge = schema
        elif isinstance(schema.path, ParentEdge):
            parent_edges[tuple(schema.path.lineage)] = schema
            if not schema.path.lineage:
                default_parent_edge = schema
    for schema in new_schemas:
        if isinstance(schema.path, ChildEdge | ParentEdge):
            classes['all'].append(schema)
    for edge in new_schemas:
        if edge.path.group() not in old_groups:
            if isinstance(edge.path, ChildEdge):
                lineage = list(edge.path.lineage)
                lineage[-1] = (lineage[-1][0] + 1, 0)
                if lineage[-1][0] <= MAX_TREE_WIDTH:
                    new_child_edge = get_child_edge(lineage)
                    classes[phases.CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                    classes[phases.INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                    add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                lineage = list(edge.path.lineage)
                lineage[-1] = (1, lineage[-1][0])
                new_parent_edge = get_parent_edge(lineage)
                classes[phases.PARENT_EDGE_CLASS].append(new_parent_edge)
                classes[phases.INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
            elif isinstance(edge.path, ParentEdge) and edge.path.lineage:
                lineage = list(edge.path.lineage)
                if len(lineage) < MAX_TREE_DEPTH - 1:
                    lineage.append((1, lineage[-1][0]))
                    new_child_edge = get_child_edge(lineage)
                    classes[phases.CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                    classes[phases.INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                    add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                lineage = list(edge.path.lineage)
                while lineage and lineage[-1][0] == lineage[-1][1]:
                    lineage.pop()
                if lineage:
                    lineage[-1] = (lineage[-1][0] + 1, lineage[-1][1])
                    if lineage[-1][0] <= MAX_TREE_WIDTH:
                        new_parent_edge = get_parent_edge(lineage)
                        classes[phases.PARENT_EDGE_CLASS].append(new_parent_edge)
                        classes[phases.INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                        add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
    return [lookup]


def promote_final_letter_overlap_to_continuing_overlap(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('rclt', 'dflt')
    for schema in new_schemas:
        match schema.path:
            case ChildEdge():
                classes['overlap'].append(schema)
                if all(x[0] == x[1] for x in schema.path.lineage[:-1]):
                    classes['final_letter_overlap'].append(schema)
            case ContinuingOverlap():
                continuing_overlap = schema
                classes['overlap'].append(schema)
            case ParentEdge(lineage=[]):
                root_parent_edge = schema
                classes['secant_or_root_parent_edge'].append(schema)
            case Line() if schema.path.secant and schema.glyph_class == GlyphClass.MARK:
                classes['secant_or_root_parent_edge'].append(schema)
    add_rule(lookup, Rule([], 'final_letter_overlap', 'overlap', lookups=[None]))
    named_lookups['promote'] = Lookup()
    add_rule(named_lookups['promote'], Rule('final_letter_overlap', [continuing_overlap]))
    for overlap in classes['final_letter_overlap']:
        overlap_name = overlap.path.get_name(overlap.size, overlap.joining_type)
        named_lookups[f'promote_{overlap_name}_and_parent'] = Lookup(
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set=overlap_name,
        )
        classes[overlap_name].append(overlap)
        assert isinstance(overlap.path, ChildEdge)
        for parent_edge in new_schemas:
            if (isinstance(parent_edge.path, ParentEdge)
                and parent_edge.path.lineage
                and overlap.path.lineage[:-1] == parent_edge.path.lineage[:-1]
                and overlap.path.lineage[-1][0] == parent_edge.path.lineage[-1][0] == parent_edge.path.lineage[-1][1]
            ):
                classes[overlap_name].append(parent_edge)
                classes[f'parent_for_{overlap_name}'].append(parent_edge)
        add_rule(named_lookups['promote'], Rule(f'parent_for_{overlap_name}', [root_parent_edge]))
        add_rule(named_lookups[f'promote_{overlap_name}_and_parent'], Rule(
            [],
            [overlap, f'parent_for_{overlap_name}'],
            [],
            lookups=['promote', 'promote'],
        ))
        named_lookups[f'check_and_promote_{overlap_name}'] = Lookup(
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='secant_or_root_parent_edge',
        )
        add_rule(named_lookups[f'check_and_promote_{overlap_name}'], Rule([], [overlap], 'secant_or_root_parent_edge', lookups=[None]))
        add_rule(named_lookups[f'check_and_promote_{overlap_name}'], Rule([], [overlap], [], lookups=[f'promote_{overlap_name}_and_parent']))
        add_rule(lookup, Rule([], [overlap], [], lookups=[f'check_and_promote_{overlap_name}']))
    return [lookup]


def reposition_chinook_jargon_overlap_points(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    # TODO: This should be a general thing, not limited to specific Chinook
    # Jargon abbreviations and a few similar patterns.
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='all',
        reverse=True,
    )
    line_classes = {}
    for schema in schemas:
        if schema.glyph_class == GlyphClass.MARK:
            if isinstance(schema.path, ChildEdge):
                classes['all'].append(schema)
                classes['overlap'].append(schema)
                classes['letter_overlap'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                classes['all'].append(schema)
                classes['overlap'].append(schema)
                classes['continuing_overlap'].append(schema)
            elif not schema.path.invisible():
                classes['all'].append(schema)
        elif schema.glyph_class == GlyphClass.JOINER:
            if schema.max_tree_width() == 0:
                continue
            if (isinstance(schema.path, Line)
                and (schema.size == 1 or schema.cps == (0x1BC07,))
                and not schema.path.secant
                and not schema.path.dots
            ):
                angle = schema.path.angle % 180
                max_tree_width = schema.max_tree_width()
                line_class = f'line_{angle}_{max_tree_width}'
                classes['line'].append(schema)
                classes[line_class].append(schema)
                line_classes[line_class] = (angle, max_tree_width)
            elif (isinstance(schema.path, Curve)
                and schema.cps in {(0x1BC1B,), (0x1BC1C,)}
                and schema.size == 6
                and schema.joining_type == Type.JOINING
                and (schema.path.angle_in, schema.path.angle_out) in {(90, 270), (270, 90)}
            ):
                classes['curve'].append(schema)
    if len(original_schemas) == len(schemas):
        for width in range(1, MAX_TREE_WIDTH + 1):
            add_rule(lookup, Rule(['line', *['letter_overlap'] * (width - 1), 'overlap'], 'curve', 'overlap', 'curve'))
    for curve in classes['curve']:
        if curve in new_schemas:
            assert isinstance(curve.path, Curve)
            for line_class, (angle, _) in line_classes.items():
                curve_output = curve.clone(cmap=None, path=curve.path.clone(overlap_angle=angle))
                for width in range(1, curve.max_tree_width() + 1):
                    add_rule(lookup, Rule(
                        [],
                        [curve],
                        [*['overlap'] * width, line_class],
                        [curve_output],
                    ))
                if angle == 90:
                    for curve_0 in classes['curve']:
                        assert isinstance(curve_0.path, Curve)
                        if curve_0 in new_schemas and curve_0.cps == (0x1BC1C,) and curve.cps == (0x1BC1B,):
                            for width in range(1, curve_0.max_tree_width() + 1):
                                add_rule(lookup, Rule(
                                    [],
                                    [curve_0],
                                    [*['overlap'] * width, curve_output],
                                    [curve_0.clone(cmap=None, path=curve_0.path.clone(overlap_angle=angle))],
                                ))
    for curve_child in classes['curve']:
        if curve_child in new_schemas:
            assert isinstance(curve_child.path, Curve)
            for line_class, (angle, max_tree_width) in line_classes.items():
                for width in range(1, max_tree_width + 1):
                    add_rule(lookup, Rule(
                        [line_class, *['letter_overlap'] * (width - 1), 'overlap'],
                        [curve_child],
                        [],
                        [curve_child.clone(cmap=None, path=curve_child.path.clone(overlap_angle=angle))],
                    ))
    return [lookup]


def make_mark_variants_of_children(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('blwm', 'dflt')
    old_child_count = len(classes['child'])
    for schema in new_schemas:
        if isinstance(schema.path, ParentEdge) and schema.path.lineage:
            classes['all'].append(schema)
        elif schema.glyph_class == GlyphClass.JOINER and schema.can_be_child():
            classes['child_to_be'].append(schema)
    for i, child_to_be in enumerate(classes['child_to_be']):
        if i < old_child_count:
            continue
        child = child_to_be.clone(cmap=None, child=True)
        classes['child'].append(child)
        classes[phases.PARENT_EDGE_CLASS].append(child)
        for child_index in range(MAX_TREE_WIDTH):
            classes[phases.CHILD_EDGE_CLASSES[child_index]].append(child)
    add_rule(lookup, Rule('all', 'child_to_be', [], 'child'))
    return [lookup]


def interrupt_overlong_primary_curve_sequences(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
    )
    dotted_circle = next(s for s in schemas if s.cmap == 0x25CC)
    deltas_by_size: collections.defaultdict[float, OrderedSet[float]] = collections.defaultdict(OrderedSet)
    new_deltas_by_size = collections.defaultdict(set)
    for schema in schemas:
        if schema.glyph_class == GlyphClass.MARK:
            continue
        if (schema.joining_type == Type.ORIENTING
            and isinstance(schema.path, Curve)
        ):
            if schema.path.hook:
                continue
            delta = abs(schema.path.get_da())
            assert delta != 360, f'{schema!r}'
            class_name = f'{schema.size}_{delta}'
            if schema.path.secondary:
                classes[f'secondary_{class_name}'].append(schema)
            else:
                deltas_by_size[schema.size].add(delta)
                if class_name not in classes:
                    new_deltas_by_size[schema.size].add(delta)
                classes[class_name].append(schema)
        elif (schema.joining_type != Type.NON_JOINING
            and not isinstance(schema.path, Space)
            and not (isinstance(schema.path, Line) and schema.path.secant)
            and not schema.pseudo_cursive
        ):
            classes['c'].append(schema)

    def find_overlong_sequences(
        deltas: Iterable[float],
        overlong_sequences: MutableSequence[Sequence[float]],
        sequence: Sequence[float],
    ) -> None:
        delta_so_far = sum(sequence)
        for delta in deltas:
            new_sequence = [*sequence, delta]
            if abs(delta_so_far + delta) >= 360:
                overlong_sequences.append(new_sequence)
            else:
                find_overlong_sequences(deltas, overlong_sequences, new_sequence)

    overlong_class_sequences: MutableSequence[Sequence[str]] = []
    for size, deltas in deltas_by_size.items():
        overlong_sequences: MutableSequence[Sequence[float]] = []
        find_overlong_sequences(deltas, overlong_sequences, [])
        overlong_class_sequences.extend(
            [f'{size}_{d}' for d in s]
                for s in overlong_sequences
                if any(d in new_deltas_by_size[size] for d in s)
        )
    if overlong_class_sequences:
        named_lookups['prepend_dotted_circle'] = Lookup()
    for overlong_class_sequence in overlong_class_sequences:
        add_rule(named_lookups['prepend_dotted_circle'], Rule(
            overlong_class_sequence[-1],
            [dotted_circle, overlong_class_sequence[-1]],
        ))
        add_rule(lookup, Rule(
            overlong_class_sequence[:-1],
            overlong_class_sequence[-1],
            [],
            lookups=['prepend_dotted_circle'],
        ))
        secondary_class_name_0 = f'secondary_{overlong_class_sequence[0]}'
        secondary_class_name_n1 = f'secondary_{overlong_class_sequence[-1]}'
        if secondary_class_name_0 in classes:
            add_rule(named_lookups['prepend_dotted_circle'], Rule(
                overlong_class_sequence[-1],
                [dotted_circle, overlong_class_sequence[-1]],
            ))
            add_rule(lookup, Rule(
                ['c', secondary_class_name_0, *overlong_class_sequence[1:-1]],
                overlong_class_sequence[-1],
                [],
                lookups=['prepend_dotted_circle'],
            ))
        if secondary_class_name_n1 in classes:
            add_rule(lookup, Rule(
                ['c', *overlong_class_sequence[:-1]],
                secondary_class_name_n1,
                [],
                lookups=[None],
            ))
            add_rule(named_lookups['prepend_dotted_circle'], Rule(
                secondary_class_name_n1,
                [dotted_circle, secondary_class_name_n1],
            ))
            add_rule(lookup, Rule(
                overlong_class_sequence[:-1],
                secondary_class_name_n1,
                'c',
                lookups=['prepend_dotted_circle'],
            ))
        if secondary_class_name_0 in classes:
            add_rule(lookup, Rule(
                [secondary_class_name_0, *overlong_class_sequence[1:-1]],
                overlong_class_sequence[-1],
                'c',
                lookups=[None],
            ))
            add_rule(named_lookups['prepend_dotted_circle'], Rule(
                overlong_class_sequence[-1],
                [dotted_circle, overlong_class_sequence[-1]],
            ))
            add_rule(lookup, Rule(
                [secondary_class_name_0, *overlong_class_sequence[1:-1]],
                overlong_class_sequence[-1],
                [],
                lookups=['prepend_dotted_circle'],
            ))
    return [lookup]


def reposition_stenographic_period(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    for schema in new_schemas:
        if (isinstance(schema.path, InvalidStep)
            or isinstance(schema.path, Space) and schema.joining_type == Type.JOINING
        ) and schema.glyph_class != GlyphClass.MARK:
            classes['c'].append(schema)
        elif schema.cmap == 0x2E3C:
            period = schema
    zwnj = Schema(None, Space(0, margins=True), 0, Type.NON_JOINING, side_bearing=0)
    joining_period = period.clone(cmap=None, joining_type=Type.JOINING)
    add_rule(lookup, Rule('c', [period], [], [joining_period, zwnj]))
    return [lookup]


def disjoin_grammalogues(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='all',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    grammalogues = []
    for schema in new_schemas:
        match schema:
            case Schema(path=EqualsSign() | Grammalogue()):
                grammalogues.append(schema)
            case Schema(glyph_class=GlyphClass.JOINER):
                classes['joiner'].append(schema)
            case Schema(path=ContinuingOverlap()):
                continuing_overlap = schema
                classes['all'].append(continuing_overlap)
            case Schema(path=ParentEdge(lineage=[])):
                root_parent_edge = schema
                classes['all'].append(root_parent_edge)
    zwnj = Schema(None, Space(0, margins=True), 0, Type.NON_JOINING, side_bearing=0)
    for root in grammalogues:
        if root.max_tree_width() == 0:
            continue
        add_rule(lookup, Rule([root], [zwnj, root]))
        if trees := _make_trees('joiner', None, MAX_TREE_DEPTH, top_widths=range(root.max_tree_width() + 1)):
            if 'prepend_zwnj' not in named_lookups:
                named_lookups['prepend_zwnj'] = Lookup()
                add_rule(named_lookups['prepend_zwnj'], Rule([root_parent_edge], [zwnj, root_parent_edge]))
            for tree in trees:
                add_rule(lookup, Rule([root, *filter(None, tree)], [root_parent_edge], [], lookups=['prepend_zwnj']))
    for child in grammalogues:
        if not child.can_be_child():
            continue
        add_rule(lookup, Rule([continuing_overlap, root_parent_edge], [child], [], [child, zwnj]))
        add_rule(lookup, Rule([root_parent_edge], [child], [], [zwnj, child, zwnj]))
        add_rule(lookup, Rule([child], [child, zwnj]))
    return [lookup]


def join_with_next_step(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        reverse=True,
    )
    old_input_count = len(classes['i'])
    for schema in new_schemas:
        if isinstance(schema.path, InvalidStep):
            classes['i'].append(schema)
            if schema.path.angle == 90:
                classes['i_up'].append(schema)
            elif schema.path.angle == 270:
                classes['i_down'].append(schema)
            else:
                raise ValueError(f'Unsupported step angle: {schema.path.angle}')
        if isinstance(schema.path, Space) and schema.hub_priority == 0:
            if schema.path.angle == 90:
                classes['c_up'].append(schema)
            elif schema.path.angle == 270:
                classes['c_down'].append(schema)
            else:
                raise ValueError(f'Unsupported step angle: {schema.path.angle}')
        elif schema.glyph_class == GlyphClass.JOINER:
            classes['c'].append(schema)
    new_context = 'o' not in classes
    for i, target_schema in enumerate(classes['i']):
        if new_context or i >= old_input_count:
            output_schema = target_schema.contextualize(NO_CONTEXT, NO_CONTEXT).clone(
                size=800,
                joining_type=Type.JOINING,
                side_bearing=0,
            )
            classes['o'].append(output_schema)
            if target_schema in classes['i_up']:
                classes['o_up'].append(output_schema)
            if target_schema in classes['i_down']:
                classes['o_down'].append(output_schema)
    if new_context:
        add_rule(lookup, Rule([], 'i', 'c', 'o'))
        add_rule(lookup, Rule([], 'i_up', 'c_up', 'o_up'))
        add_rule(lookup, Rule([], 'i_down', 'c_down', 'o_down'))
    return [lookup]


def separate_subantiparallel_lines(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
    )
    lines_by_angle = collections.defaultdict(list)
    for schema in new_schemas:
        if schema.glyph_class != GlyphClass.JOINER:
            continue
        if (isinstance(schema.path, Line)
            and schema.path.dots is None
            and schema.path.secant is None
            and schema.path.original_angle is None
            or isinstance(schema.path, Complex) and issubclass(schema.original_shape, Line)
        ):
            angle = schema.path_context_in().angle
            assert angle is not None
            lines_by_angle[angle].append(schema)
        elif schema.joining_type == Type.ORIENTING:
            match schema.path:
                case Circle():
                    clockwise = schema.path.clockwise
                    loop = False
                case Curve():
                    clockwise = schema.path.clockwise
                    loop = not (schema.diphthong_1 or schema.diphthong_2 or schema.path.reversed_circle or issubclass(schema.original_shape, Curve))
                case Complex() if (first_curve_op := next((op for op in schema.path.instructions if not callable(op) and isinstance(op.shape, Circle | Curve)), None)) is not None:
                    clockwise = first_curve_op.shape.clockwise  # type: ignore[attr-defined]
                    loop = isinstance(schema.path, Ou) or not isinstance(schema.path, Wi) and schema.is_primary
                case _:
                    continue
            classes[f'clockwise_{clockwise}_i'].append(schema)
            classes[f'clockwise_{clockwise}_o'].append(schema)
            if isinstance(schema.path, Wa | Wi):
                classes[f'clockwise_{not clockwise}_i'].append(schema)
            if loop:
                classes['loop'].append(schema)
    closeness_threshold = 20

    def axis_alignment(x: float) -> float:
        return abs(x % 90 - 45)

    for a1, lines_1 in lines_by_angle.items():
        for a2, lines_2 in lines_by_angle.items():
            if (axis_alignment(a1) < axis_alignment(a2)
                and Curve.in_degree_range(
                    a1,
                    (a2 + 180 - (closeness_threshold - EPSILON)) % 360,
                    (a2 + 180 + closeness_threshold - EPSILON) % 360,
                    False,
                )
            ):
                classes[f'i_{a1}_{a2}'].extend(lines_1)
                classes[f'c_{a1}_{a2}'].extend(lines_2)
                for line_1 in lines_1:
                    new_angle = (a2 + 180 + 46.5 * (-1 if (a2 + 180) % 360 > a1 else 1)) % 360
                    if isinstance(line_1.path, Line):
                        new_path: Shape = line_1.path.clone(angle=new_angle, original_angle=line_1.path.angle)
                    else:
                        assert isinstance(line_1.path, Complex)
                        line_1_line_op = line_1.path.instructions[0]
                        assert not callable(line_1_line_op)
                        line_1_line = line_1_line_op.shape
                        assert isinstance(line_1_line, Line)
                        line_1_tick_op = line_1.path.instructions[1]
                        assert not callable(line_1_tick_op)
                        line_1_tick = line_1_tick_op.shape
                        assert isinstance(line_1_tick, Line)
                        new_path = line_1.path.clone(instructions=[
                            line_1_line_op._replace(shape=line_1_line.clone(angle=new_angle, original_angle=line_1_line.angle)),
                            line_1_tick_op._replace(shape=line_1_tick.clone(angle=line_1_tick.angle + new_angle - line_1_line.angle)),
                            *line_1.path.instructions[2:],
                        ])
                    classes[f'o_{a1}_{a2}'].append(line_1.clone(cmap=None, path=new_path))
                clockwise_from_a1_to_a2 = Context(a1).has_clockwise_loop_to(Context(a2))
                add_rule(lookup, Rule(f'clockwise_{not clockwise_from_a1_to_a2}_i', f'i_{a1}_{a2}', f'c_{a1}_{a2}', f'o_{a1}_{a2}'))
                add_rule(lookup, Rule([], f'i_{a1}_{a2}', [f'c_{a1}_{a2}', f'clockwise_{not clockwise_from_a1_to_a2}_o'], f'o_{a1}_{a2}'))
                add_rule(lookup, Rule(f'c_{a1}_{a2}', f'i_{a1}_{a2}', f'clockwise_{clockwise_from_a1_to_a2}_o', f'o_{a1}_{a2}'))
                add_rule(lookup, Rule([f'clockwise_{clockwise_from_a1_to_a2}_i', f'c_{a1}_{a2}'], f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
                add_rule(lookup, Rule([], f'i_{a1}_{a2}', ['loop', f'c_{a1}_{a2}'], f'o_{a1}_{a2}'))
                add_rule(lookup, Rule([f'c_{a1}_{a2}', 'loop'], f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
    return [lookup]


def prepare_for_secondary_diphthong_ligature(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        reverse=True,
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    for schema in new_schemas:
        if isinstance(schema.path, Ou) or not schema.can_become_part_of_diphthong:
            continue
        if isinstance(schema.path, Curve):
            if schema.is_primary:
                classes['primary_semicircle'].append(schema)
        else:
            assert isinstance(schema.path, Circle)
            if schema.path.reversed_circle:
                classes['reversed_circle'].append(schema)
                classes['pinned_circle'].append(schema.clone(cmap=None, path=schema.path.clone(pinned=True)))
    add_rule(lookup, Rule([], 'reversed_circle', 'primary_semicircle', 'pinned_circle'))
    return [lookup]


def join_with_previous(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup_1 = Lookup(
        'rclt',
        'dflt',
    )
    lookup_2 = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='all',
        reverse=True,
    )
    if len(original_schemas) != len(schemas):
        return [lookup_1, lookup_2]
    contexts_in: OrderedSet[Schema] = OrderedSet()

    @functools.cache
    def get_context_marker(context: Context) -> Schema:
        return Schema(None, ContextMarker(False, context), 0)

    for schema in original_schemas:
        if schema.glyph_class == GlyphClass.JOINER and not (isinstance(schema.path, Line) and schema.path.secant):
            if (schema.joining_type == Type.ORIENTING
                and schema.context_in == NO_CONTEXT
            ):
                classes['i'].append(schema)
            if (context_in := schema.path_context_out()) != NO_CONTEXT:
                if context_in.ignorable_for_topography:
                    context_in = context_in.clone(angle=0)
                context_in_marker = get_context_marker(context_in)
                classes['all'].append(context_in_marker)
                classes['i2'].append(schema)
                classes['o2'].append(context_in_marker)
                contexts_in.add(context_in_marker)
    classes['all'].extend(classes[phases.CONTINUING_OVERLAP_CLASS])
    add_rule(lookup_1, Rule('i2', ['i2', 'o2']))
    for j, context_in_marker in enumerate(contexts_in):
        assert isinstance(context_in_marker.path, ContextMarker)
        for target_schema in classes['i']:
            classes[f'o_{j}'].append(target_schema.contextualize(context_in_marker.path.context, target_schema.context_out))
        add_rule(lookup_2, Rule([context_in_marker], 'i', [], f'o_{j}'))
    return [lookup_1, lookup_2]


def unignore_last_orienting_glyph_in_initial_sequence(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='i',
    )
    for schema in new_schemas:
        if schema.ignored_for_topography:
            classes['i'].append(schema)
            classes['o'].append(schema.clone(
                path=schema.path.clone(role=CircleRole.LEADER, _initial=True, _isolated=False) if isinstance(schema.path, Ou) else CLONE_DEFAULT,
                ignored_for_topography=False,
            ))
        elif (schema.glyph_class == GlyphClass.JOINER
            and not isinstance(schema.path, Space)
            and not (isinstance(schema.path, Line) and schema.path.secant)
            and not schema.pseudo_cursive
        ):
            if (schema.joining_type == Type.ORIENTING
                and schema.can_be_ignored_for_topography()
            ):
                classes['first'].append(schema)
            else:
                classes['c'].append(schema)
                if schema.can_lead_orienting_sequence and not isinstance(schema.path, Line):
                    classes['fixed_form'].append(schema)
    named_lookups['check_previous'] = Lookup(flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS)
    add_rule(named_lookups['check_previous'], Rule(['c', 'first'], 'i', [], lookups=[None]))
    add_rule(named_lookups['check_previous'], Rule('c', 'i', [], lookups=[None]))
    add_rule(named_lookups['check_previous'], Rule([], 'i', 'fixed_form', lookups=[None]))
    add_rule(named_lookups['check_previous'], Rule('i', 'o'))
    add_rule(lookup, Rule([], 'i', 'c', lookups=['check_previous']))
    return [lookup]


def ignore_first_orienting_glyph_in_initial_sequence(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        reverse=True,
    )
    for schema in new_schemas:
        if (schema.glyph_class != GlyphClass.JOINER
            or schema.is_secant
            or schema.pseudo_cursive
            or schema.path.invisible()
        ):
            continue
        classes['joiner'].append(schema)
        if (schema.can_lead_orienting_sequence
            and schema.can_be_ignored_for_topography()
        ):
            classes['c'].append(schema)
            if schema.joining_type == Type.ORIENTING:
                if isinstance(schema.path, Ou):
                    circle_op = schema.path.instructions[0]
                    assert not callable(circle_op)
                    path = circle_op.shape
                else:
                    path = schema.path
                assert isinstance(path, Circle | Curve)
                classes['i'].append(schema)
                angle_out = path.angle_out - path.angle_in
                path = path.clone(
                    angle_in=0,
                    angle_out=(angle_out if path.clockwise else -angle_out) % 360,
                    clockwise=True,
                    **({} if isinstance(schema.path, Curve) else {'role': CircleRole.DEPENDENT}),  # type: ignore[arg-type]
                )
                if isinstance(schema.path, Ou):
                    assert not callable(circle_op)
                    path = schema.path.clone(instructions=[circle_op._replace(shape=path)])
                classes['o'].append(schema.clone(
                    cmap=None,
                    path=path,
                    ignored_for_topography=True,
                    context_in=None,
                    context_out=None,
                ))
    add_rule(lookup, Rule('joiner', 'i', [], 'i'))
    add_rule(lookup, Rule([], 'i', 'c', 'o'))
    return [lookup]


def tag_main_glyph_in_orienting_sequence(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='dependent',
    )
    if len(original_schemas) != len(schemas):
        return [lookup]
    for schema in new_schemas:
        if schema.ignored_for_topography:
            classes['dependent'].append(schema)
        elif (schema.joining_type == Type.ORIENTING
            and schema.glyph_class == GlyphClass.JOINER
            and (isinstance(schema.path, Circle | Ou)
                and schema.path.role == CircleRole.INDEPENDENT
            )
        ):
            classes['i'].append(schema)
            classes['o'].append(schema.clone(cmap=None, path=schema.path.clone(role=CircleRole.LEADER)))
    add_rule(lookup, Rule('dependent', 'i', [], 'o'))
    add_rule(lookup, Rule([], 'i', 'dependent', 'o'))
    return [lookup]


def join_with_next(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    pre_lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set=phases.CONTINUING_OVERLAP_CLASS,
        reverse=True,
    )
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set=phases.CONTINUING_OVERLAP_CLASS,
        reverse=True,
    )
    post_lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='continuing_overlap_after_secant',
        reverse=True,
    )
    contexts_out: OrderedSet[Context] = OrderedSet()
    new_contexts_out = set()
    old_input_count = len(classes['i'])
    if old_input_count == 0:
        for schema in original_schemas:
            if (schema.glyph_class == GlyphClass.JOINER
                and schema.joining_type == Type.ORIENTING
                and schema.context_out == NO_CONTEXT
            ):
                classes['i'].append(schema)
                if isinstance(schema.path, Line) and schema.path.secant:
                    classes['secant_i'].append(schema)
                    classes['secant_o'].append(schema)
        continuing_overlap = next(iter(classes[phases.CONTINUING_OVERLAP_CLASS]))
        continuing_overlap_after_secant = Schema(None, ContinuingOverlapS(), 0)
        classes['continuing_overlap_after_secant'].append(continuing_overlap_after_secant)
        add_rule(pre_lookup, Rule('secant_i', [continuing_overlap], [], [continuing_overlap_after_secant]))
    for schema in new_schemas:
        if (schema.glyph_class == GlyphClass.JOINER
            and (
                old_input_count == 0
                or not (
                    isinstance(schema.path, Curve | Circle)
                    or isinstance(schema.path, Complex) and not any(not callable(op) and op.tick for op in schema.path.instructions)
                )
            )
            and not (isinstance(schema.path, Line) and schema.path.secant)
            and (context_out := schema.path.context_in()) != NO_CONTEXT
        ):
            contexts_out.add(context_out)
            if schema not in (context_out_class := classes[f'c_{context_out}']):
                if not context_out_class:
                    new_contexts_out.add(context_out)
                context_out_class.append(schema)
    for context_out in contexts_out:
        output_class_name = f'o_{context_out}'
        new_context = context_out in new_contexts_out
        for i, target_schema in enumerate(classes['i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(target_schema.context_in, context_out)
                classes[output_class_name].append(output_schema)
                if isinstance(output_schema.path, Line) and output_schema.path.secant:
                    classes['secant_o'].append(output_schema)
        if new_context:
            add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
    if old_input_count == 0:
        # FIXME: This rule shouldn’t need to be contextual, but without the
        # context, fontTools throws a `KeyError` in `buildCoverage`.
        add_rule(post_lookup, Rule(['secant_o'], [continuing_overlap_after_secant], [], [continuing_overlap]))
    return [pre_lookup, lookup, post_lookup]


def join_circle_with_adjacent_nonorienting_glyph(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='ignored_for_topography',
        reverse=True,
    )
    contexts_out: OrderedSet[Context] = OrderedSet()
    for schema in new_schemas:
        if schema.ignored_for_topography:
            if schema.context_out == NO_CONTEXT and isinstance(schema.path, Circle):
                classes['i'].append(schema)
            classes['ignored_for_topography'].append(schema)
        elif (schema.glyph_class == GlyphClass.JOINER
            and (not schema.can_lead_orienting_sequence
                or (not schema.path.secant if isinstance(schema.path, Line) else schema.original_shape == Line)
            )
            and (context_out := schema.path.context_in()) != NO_CONTEXT
        ):
            context_out = Context(context_out.angle)
            contexts_out.add(context_out)
            classes[f'c_{context_out}'].append(schema)
    for context_out in contexts_out:
        output_class_name = f'o_{context_out}'
        for circle in classes['i']:
            classes[output_class_name].append(circle.clone(cmap=None, context_out=context_out))
        add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
    return [lookup]


def ligate_diphthongs(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='ignored_for_topography',
        reverse=True,
    )
    diphthong_1_classes: OrderedSet[tuple[str, bool, bool, str]] = OrderedSet()
    diphthong_2_classes: OrderedSet[tuple[str, bool, bool, str]] = OrderedSet()
    for schema in new_schemas:
        if schema.ignored_for_topography:
            classes['ignored_for_topography'].append(schema)
        if not schema.can_become_part_of_diphthong:
            continue
        assert isinstance(schema.path, Circle | Curve)
        is_circle_letter = isinstance(schema.path, Circle) or bool(schema.path.reversed_circle)
        is_ignored = schema.ignored_for_topography
        is_primary = schema.is_primary
        if is_ignored and not is_primary:
            continue
        input_class_name = f'i1_{is_circle_letter}_{is_ignored}'
        classes[input_class_name].append(schema)
        output_class_name = f'o1_{is_circle_letter}_{is_ignored}'
        output_schema = schema.clone(cmap=None, diphthong_1=True)
        classes[output_class_name].append(output_schema)
        diphthong_1_classes.add((
            input_class_name,
            is_circle_letter,
            is_ignored,
            output_class_name,
        ))
        if output_schema.ignored_for_topography:
            classes['ignored_for_topography'].append(output_schema)
        input_class_name = f'i2_{is_circle_letter}_{is_ignored}'
        classes[input_class_name].append(schema)
        output_class_name = f'o2_{is_circle_letter}_{is_ignored}'
        output_schema = schema.clone(cmap=None, diphthong_2=True)
        classes[output_class_name].append(output_schema)
        diphthong_2_classes.add((
            input_class_name,
            is_circle_letter,
            is_ignored,
            output_class_name,
        ))
        if output_schema.ignored_for_topography:
            classes['ignored_for_topography'].append(output_schema)
    for input_1, is_circle_1, is_ignored_1, output_1 in diphthong_1_classes:
        for input_2, is_circle_2, is_ignored_2, output_2 in diphthong_2_classes:
            if is_circle_1 != is_circle_2 and (is_ignored_1 or is_ignored_2):
                add_rule(lookup, Rule(input_1, input_2, [], output_2))
                add_rule(lookup, Rule([], input_1, output_2, output_1))
    return [lookup]


def thwart_what_would_flip(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='all',
    )
    for schema in new_schemas:
        if isinstance(schema.path, Curve) and schema.path.would_flip:
            classes['i'].append(schema)
            classes['o'].append(schema.clone(path=schema.path.clone(early_exit=True)))
        elif isinstance(schema.path, ParentEdge) and not schema.path.lineage:
            classes['root_parent_edge'].append(schema)
            classes['all'].append(schema)
        elif schema.ignored_for_topography and (
            schema.context_in.angle is None or schema.context_in.ignorable_for_topography
        ):
            classes['tail'].append(schema)
            classes['all'].append(schema)
    add_rule(lookup, Rule([], 'i', ['root_parent_edge', 'tail'], lookups=[None]))
    add_rule(lookup, Rule([], 'i', 'root_parent_edge', 'o'))
    return [lookup]


def unignore_noninitial_orienting_sequences(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='i',
    )
    contexts_in: OrderedSet[Context] = OrderedSet()
    new_contexts_in = set()
    old_input_count = len(classes['i'])
    for schema in new_schemas:
        if schema.ignored_for_topography and (
            schema.context_in.angle is None or schema.context_in.ignorable_for_topography
        ):
            classes['i'].append(schema)
        elif (schema.glyph_class == GlyphClass.JOINER
            and schema.can_lead_orienting_sequence
            and ((schema.path.angle_out - schema.path.angle_in) % 180 == 0
                or schema.phase_index < builder.phase_index(join_circle_with_adjacent_nonorienting_glyph)
                if isinstance(schema.path, Circle)
                else schema.can_be_ignored_for_topography())
        ):
            context_in = schema.path_context_out().clone(diphthong_start=False, diphthong_end=False)
            contexts_in.add(context_in)
            if schema not in (context_in_class := classes[f'c_{context_in}']):
                if not context_in_class:
                    new_contexts_in.add(context_in)
                context_in_class.append(schema)
    for context_in in contexts_in:
        output_class_name = f'o_{context_in}'
        new_context = context_in in new_contexts_in
        for i, target_schema in enumerate(classes['i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(context_in, target_schema.context_out, ignore_dependent_schemas=False)
                classes[output_class_name].append(output_schema)
        if new_context:
            add_rule(lookup, Rule(f'c_{context_in}', 'i', [], output_class_name))
    return [lookup]


def unignore_initial_orienting_sequences(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rclt',
        'dflt',
        mark_filtering_set='i',
        reverse=True,
    )
    contexts_out: OrderedSet[Context] = OrderedSet()
    new_contexts_out = set()
    old_input_count = len(classes['i'])
    for schema in new_schemas:
        if schema.ignored_for_topography and (
            schema.context_out.angle is None or schema.context_out.ignorable_for_topography
        ):
            classes['i'].append(schema)
        elif (schema.glyph_class == GlyphClass.JOINER
            and schema.can_lead_orienting_sequence
            and ((schema.path.angle_out - schema.path.angle_in) % 180 == 0
                or schema.phase_index < builder.phase_index(join_circle_with_adjacent_nonorienting_glyph)
                if isinstance(schema.path, Circle)
                else schema.can_be_ignored_for_topography())
        ):
            context_out = schema.path_context_in().clone(diphthong_start=False, diphthong_end=False)
            contexts_out.add(context_out)
            if schema not in (context_out_class := classes[f'c_{context_out}']):
                if not context_out_class:
                    new_contexts_out.add(context_out)
                context_out_class.append(schema)
    for context_out in contexts_out:
        output_class_name = f'o_{context_out}'
        new_context = context_out in new_contexts_out
        for i, target_schema in enumerate(classes['i']):
            if new_context or i >= old_input_count:
                output_schema = target_schema.contextualize(target_schema.context_in, context_out, ignore_dependent_schemas=False)
                classes[output_class_name].append(output_schema)
        if new_context:
            add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
    return [lookup]


def join_double_marks(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='all',
    )
    for schema in new_schemas:
        if schema.cps == (0x1BC9E,):
            assert isinstance(schema.path, Line)
            classes['all'].append(schema)
            for i in range(2, MAX_DOUBLE_MARKS + 1):
                add_rule(lookup, Rule([schema] * i, [schema.clone(
                    cmap=None,
                    cps=[*schema.cps] * i,
                    path=RotatedComplex([
                        (1, schema.path),
                        (500, Space((schema.path.angle + 180) % 360)),
                        (250, Space((schema.path.angle - 90) % 360)),
                    ] * i),
                )]))
    return [lookup]


def rotate_diacritics(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='all',
    )
    base_anchors_and_contexts: OrderedSet[tuple[str, Context]] = OrderedSet()
    new_base_anchors_and_contexts = set()
    for schema in new_schemas:
        if schema.anchor:
            if schema.base_angle is None and schema.joining_type == Type.ORIENTING:
                classes['all'].append(schema)
                classes[f'i_{schema.anchor}'].append(schema)
        elif not schema.ignored_for_topography:
            for base_anchor, base_angle in schema.diacritic_angles.items():
                base_context = schema.path_context_out()
                base_context = Context(base_angle, base_context.clockwise, ignorable_for_topography=base_context.ignorable_for_topography)
                base_anchor_and_context = (base_anchor, base_context)
                base_anchors_and_contexts.add(base_anchor_and_context)
                if schema not in (base_anchor_and_context_class := classes[f'c_{base_anchor}_{base_context}']):
                    if not base_anchor_and_context_class:
                        new_base_anchors_and_contexts.add(base_anchor_and_context)
                    base_anchor_and_context_class.append(schema)
                    if schema.glyph_class == GlyphClass.MARK:
                        classes['all'].append(schema)
    for base_anchor_and_context in base_anchors_and_contexts:
        if base_anchor_and_context in new_base_anchors_and_contexts:
            anchor, context = base_anchor_and_context
            output_class_name = f'o_{anchor}_{context}'
            for target_schema in classes[f'i_{anchor}']:
                if anchor == target_schema.anchor:
                    output_schema = target_schema.rotate_diacritic(context)
                    classes[output_class_name].append(output_schema)
            add_rule(lookup, Rule(f'c_{anchor}_{context}', f'i_{anchor}', [], output_class_name))
    return [lookup]


def shade(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
        mark_filtering_set='independent_mark',
    )
    dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
    classes['independent_mark'].append(dtls)
    for schema in new_schemas:
        if schema.anchor and not (isinstance(schema.path, Line) and schema.path.secant):
            if schema.cmap is not None:
                classes['independent_mark'].append(schema)
        elif (schema in original_schemas
            and not schema.ignored_for_topography
            and schema.shading_allowed
            and schema.path.is_shadable()
        ):
            classes['i'].append(schema)
            classes['o'].append(schema.clone(cmap=None, cps=[*schema.cps, *dtls.cps]))
            if schema.glyph_class == GlyphClass.MARK:
                classes['independent_mark'].append(schema)
    add_rule(lookup, Rule(['i', dtls], 'o'))
    return [lookup]


def create_diagonal_fractions(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup_numr = Lookup('numr', 'dflt')
    lookup_dnom = Lookup('dnom', 'dflt')
    lookup_rlig = Lookup('rlig', 'dflt')
    if len(original_schemas) != len(schemas):
        return [lookup_numr, lookup_dnom, lookup_rlig]
    for schema in new_schemas:
        if schema.cmap is not None and chr(schema.cmap) in string.digits:
            classes['digit'].append(schema)
            classes['digit_or_slash'].append(schema)
            assert schema.y_max is not None
            assert schema.y_min is not None
            dnom = schema.clone(cmap=None, y_max=SMALL_DIGIT_FACTOR * CAP_HEIGHT)
            numr = schema.clone(cmap=None, y_min=(1 - SMALL_DIGIT_FACTOR) * CAP_HEIGHT)
            classes['dnom'].append(dnom)
            classes['numr'].append(numr)
            classes['dnom_or_slash'].append(dnom)
        elif schema.cmap == 0x2044:
            slash = schema
            classes['digit_or_slash'].append(schema)
    valid_slash = slash.clone(cmap=None, side_bearing=-250)
    classes['dnom_or_slash'].append(valid_slash)
    add_rule(lookup_numr, Rule('digit', 'numr'))
    add_rule(lookup_dnom, Rule('digit', 'dnom'))
    add_rule(lookup_rlig, Rule('numr', [slash], [], [valid_slash]))
    add_rule(lookup_rlig, Rule('dnom_or_slash', 'numr', [], 'dnom'))
    add_rule(lookup_rlig, Rule('digit_or_slash', 'dnom', [], 'digit'))
    return [lookup_numr, lookup_dnom, lookup_rlig]


def create_superscripts_and_subscripts(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup_sups = Lookup('sups', 'dflt')
    lookup_subs = Lookup('subs', 'dflt')
    for schema in new_schemas:
        if schema.cmap is not None and chr(schema.cmap) in string.digits:
            classes['i'].append(schema)
            assert schema.y_max is not None
            classes['o_sups'].append(schema.clone(
                cmap=None,
                y_min=SUPERSCRIPT_HEIGHT - SMALL_DIGIT_FACTOR * CAP_HEIGHT,
                y_max=SUPERSCRIPT_HEIGHT,
            ))
            classes['o_subs'].append(schema.clone(
                cmap=None,
                y_min=SUBSCRIPT_DEPTH,
                y_max=SUBSCRIPT_DEPTH + SMALL_DIGIT_FACTOR * CAP_HEIGHT,
            ))
    add_rule(lookup_sups, Rule('i', 'o_sups'))
    add_rule(lookup_subs, Rule('i', 'o_subs'))
    return [lookup_sups, lookup_subs]


def make_widthless_variants_of_marks(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    lookup = Lookup('rlig', 'dflt')
    first_iteration = 'i' not in classes
    for schema in new_schemas:
        if schema.glyph_class == GlyphClass.MARK:
            if schema.anchor and schema.widthless is None and not schema.path.invisible():
                classes['i'].append(schema)
                widthless_variant = schema.clone(cmap=None, widthless=True)
                classes['o'].append(widthless_variant)
                classes['c'].append(widthless_variant)
        elif schema.joining_type == Type.NON_JOINING:
            classes['c'].append(schema)
    if first_iteration:
        add_rule(lookup, Rule('c', 'i', [], 'o'))
    return [lookup]


def classify_marks_for_trees(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[FreezableList[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> Sequence[Lookup]:
    for schema in schemas:
        for anchor in anchors.ALL_MKMK:
            if schema.glyph_class == GlyphClass.MARK and (
                schema.child
                or schema.anchor == anchor
                or isinstance(schema.path, Line) and schema.path.secant
            ):
                classes[f'global..{mkmk(anchor)}'].append(schema)
    return []


PHASE_LIST = [
    create_diagonal_fractions,
    dont_ignore_default_ignorables,
    reversed_circle_kludge,
    validate_shading,
    validate_double_marks,
    decompose,
    expand_secants,
    validate_overlap_controls,
    add_parent_edges,
    invalidate_overlap_controls,
    add_secant_guidelines,
    add_placeholders_for_missing_children,
    categorize_edges,
    disjoin_grammalogues,
    promote_final_letter_overlap_to_continuing_overlap,
    reposition_chinook_jargon_overlap_points,
    make_mark_variants_of_children,
    interrupt_overlong_primary_curve_sequences,
    reposition_stenographic_period,
    join_with_next_step,
    prepare_for_secondary_diphthong_ligature,
    join_with_previous,
    unignore_last_orienting_glyph_in_initial_sequence,
    ignore_first_orienting_glyph_in_initial_sequence,
    tag_main_glyph_in_orienting_sequence,
    join_with_next,
    join_circle_with_adjacent_nonorienting_glyph,
    ligate_diphthongs,
    thwart_what_would_flip,
    unignore_noninitial_orienting_sequences,
    unignore_initial_orienting_sequences,
    join_double_marks,
    separate_subantiparallel_lines,
    rotate_diacritics,
    shade,
    create_superscripts_and_subscripts,
    make_widthless_variants_of_marks,
    classify_marks_for_trees,
]
