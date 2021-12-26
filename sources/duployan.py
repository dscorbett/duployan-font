# Copyright 2018-2019 David Corbett
# Copyright 2019-2021 Google LLC
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

__all__ = ['Builder']

import collections
import enum
import functools
import itertools
import io
import math
import re
import unicodedata

import fontforge
import fontTools.agl
import fontTools.feaLib.ast
import fontTools.feaLib.builder
import fontTools.feaLib.parser
import fontTools.misc.transform
import fontTools.otlLib.builder

import anchors
import schema
from schema import Ignorability
from schema import MAX_DOUBLE_MARKS
from schema import MAX_HUB_PRIORITY
from schema import NO_PHASE_INDEX
from schema import Schema
from shapes import AnchorWidthDigit
from shapes import Bound
from shapes import Carry
from shapes import ChildEdge
from shapes import Circle
from shapes import CircleRole
from shapes import Complex
from shapes import ContextMarker
from shapes import ContinuingOverlap
from shapes import ContinuingOverlapS
from shapes import Curve
from shapes import DigitStatus
from shapes import Dot
from shapes import Dummy
from shapes import End
from shapes import EntryWidthDigit
from shapes import GlyphClassSelector
from shapes import Hub
from shapes import InitialSecantMarker
from shapes import InvalidDTLS
from shapes import InvalidOverlap
from shapes import InvalidStep
from shapes import LINE_FACTOR
from shapes import LeftBoundDigit
from shapes import Line
from shapes import MarkAnchorSelector
from shapes import Notdef
from shapes import Ou
from shapes import ParentEdge
from shapes import RADIUS
from shapes import RightBoundDigit
from shapes import RomanianU
from shapes import RootOnlyParentEdge
from shapes import SeparateAffix
from shapes import Space
from shapes import Start
from shapes import TangentHook
from shapes import ValidDTLS
from shapes import Wa
from shapes import Wi
from shapes import WidthNumber
from shapes import XShape
import sifting
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import CURVE_OFFSET
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import EPSILON
from utils import GlyphClass
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import NO_CONTEXT
from utils import Type
from utils import WIDTH_MARKER_PLACES
from utils import WIDTH_MARKER_RADIX
from utils import mkmk

BRACKET_HEIGHT = 1.27 * CAP_HEIGHT
BRACKET_DEPTH = -0.27 * CAP_HEIGHT
SHADING_FACTOR = 12 / 7
REGULAR_LIGHT_LINE = 70
MINIMUM_STROKE_GAP = 70
STRIKEOUT_POSITION = 258
CONTINUING_OVERLAP_CLASS = 'global..cont'
HUB_CLASS = 'global..hub'
CONTINUING_OVERLAP_OR_HUB_CLASS = 'global..cont_or_hub'
PARENT_EDGE_CLASS = 'global..pe'
CHILD_EDGE_CLASSES = [f'global..ce{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]
INTER_EDGE_CLASSES = [[f'global..edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]

assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'

class FreezableList:
    def __init__(self):
        self._delegate = []

    def freeze(self):
        self._delegate = tuple(self._delegate)

    def __iter__(self):
        return iter(self._delegate)

    def __len__(self):
        return len(self._delegate)

    def insert(self, index, object, /):
        try:
            self._delegate.insert(index, object)
        except AttributeError:
            raise ValueError('Inserting into a frozen list') from None

    def append(self, object, /):
        try:
            self._delegate.append(object)
        except AttributeError:
            raise ValueError('Appending to a frozen list') from None

    def extend(self, iterable, /):
        try:
            self._delegate.extend(iterable)
        except AttributeError:
            raise ValueError('Extending a frozen list') from None

class OrderedSet(dict):
    def __init__(self, iterable=None, /):
        super().__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item, /):
        self[item] = None

    def remove(self, item, /):
        self.pop(item, None)

    def sorted(self, /, *, key=None, reverse=False):
        return sorted(self.keys(), key=key, reverse=reverse)

class AlwaysTrueList(list):
    def __bool__(self):
        return True

class Rule:
    def __init__(
        self,
        a1,
        a2,
        a3=None,
        a4=None,
        /,
        *,
        lookups=None,
        x_placements=None,
        x_advances=None,
    ):
        def _l(glyphs):
            return [glyphs] if isinstance(glyphs, str) else glyphs
        if a4 is None and lookups is None and x_advances is None:
            assert a3 is None, 'Rule takes 2 or 4 inputs, given 3'
            a4 = a2
            a2 = a1
            a1 = []
            a3 = []
        assert (a4 is not None) + (lookups is not None) + (x_placements is not None or x_advances is not None) == 1, (
            'Rule can take exactly one of an output glyph/class list, a lookup list, or a position list')
        self.contexts_in = _l(a1)
        self.inputs = _l(a2)
        self.contexts_out = _l(a3)
        self.outputs = None
        self.lookups = lookups
        self.x_placements = x_placements
        self.x_advances = x_advances
        if lookups is not None:
            assert len(lookups) == len(self.inputs), f'There must be one lookup (or None) per input glyph ({len(lookups)} != {len(self.inputs)})'
        elif a4 is not None:
            self.outputs = _l(a4)
        else:
            if x_placements is not None:
                assert len(x_placements) == len(self.inputs), f'There must be one x placement (or None) per input glyph ({len(x_placements)} != {len(self.inputs)})'
            if x_advances is not None:
                assert len(x_advances) == len(self.inputs), f'There must be one x advance (or None) per input glyph ({len(x_advances)} != {len(self.inputs)})'

    def to_asts(self, class_asts, named_lookup_asts, in_contextual_lookup, in_multiple_lookup, in_reverse_lookup):
        def glyph_to_ast(glyph, unrolling_index=None):
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return fontTools.feaLib.ast.GlyphName(class_asts[glyph].glyphs.glyphs[unrolling_index])
                else:
                    return fontTools.feaLib.ast.GlyphClassName(class_asts[glyph])
            return fontTools.feaLib.ast.GlyphName(str(glyph))
        def glyphs_to_ast(glyphs, unrolling_index=None):
            return [glyph_to_ast(glyph, unrolling_index) for glyph in glyphs]
        def glyph_to_name(glyph, unrolling_index=None):
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return class_asts[glyph].glyphs.glyphs[unrolling_index]
                else:
                    assert not isinstance(glyph, str), f'Glyph classes are not allowed where only glyphs are expected: @{glyph}'
            return str(glyph)
        def glyphs_to_names(glyphs, unrolling_index=None):
            return [glyph_to_name(glyph, unrolling_index) for glyph in glyphs]
        if self.lookups is not None:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions do not support lookup references'
            return [fontTools.feaLib.ast.ChainContextSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                [None if name is None else named_lookup_asts[name] for name in self.lookups],
            )]
        elif self.x_placements is not None or self.x_advances is not None:
            assert not in_reverse_lookup, 'There is no reverse positioning lookup type'
            assert len(self.inputs) == 1, 'Only single adjustment positioning has been implemented'
            return [fontTools.feaLib.ast.SinglePosStatement(
                list(zip(
                    glyphs_to_ast(self.inputs),
                    [
                        fontTools.feaLib.ast.ValueRecord(x_placement, xAdvance=x_advance)
                            for x_placement, x_advance in itertools.zip_longest(
                                self.x_placements or [None] * len(self.inputs),
                                self.x_advances or [None] * len(self.inputs),
                            )
                    ],
                )),
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.contexts_out),
                in_contextual_lookup,
            )]
        elif len(self.inputs) == 1:
            if len(self.outputs) == 1 and not in_multiple_lookup:
                if in_reverse_lookup:
                    return [fontTools.feaLib.ast.ReverseChainSingleSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs),
                    )]
                else:
                    return [fontTools.feaLib.ast.SingleSubstStatement(
                        glyphs_to_ast(self.inputs),
                        glyphs_to_ast(self.outputs),
                        glyphs_to_ast(self.contexts_in),
                        glyphs_to_ast(self.contexts_out),
                        in_contextual_lookup,
                    )]
            else:
                assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
                input = self.inputs[0]
                if isinstance(input, str) and any(isinstance(output, str) for output in self.outputs):
                    # Allow classes in multiple substitution output by unrolling all uses of
                    # the class in parallel with the input class.
                    asts = []
                    for i, glyph_name in enumerate(class_asts[input].glyphs.glyphs):
                        asts.append(fontTools.feaLib.ast.MultipleSubstStatement(
                            glyphs_to_ast(self.contexts_in),
                            glyph_name,
                            glyphs_to_ast(self.contexts_out),
                            glyphs_to_names(self.outputs, i),
                            in_contextual_lookup,
                        ))
                    return asts
                else:
                    return [fontTools.feaLib.ast.MultipleSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        glyph_to_name(input),
                        glyphs_to_ast(self.contexts_out),
                        glyphs_to_names(self.outputs),
                        in_contextual_lookup,
                    )]
        else:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions only support single substitutions'
            output = self.outputs[0]
            if isinstance(output, str):
                # Allow a class in ligature substitution output that is the same length
                # as the only class in the input by unrolling all uses of the classes in
                # parallel.
                input_class = None
                input_class_index = -1
                for i, input in enumerate(self.inputs):
                    if isinstance(input, str):
                        assert input_class is None, 'A ligature substitution with a glyph class output may only have one glyph class input'
                        assert len(class_asts[input].glyphs.glyphs) == len(class_asts[output].glyphs.glyphs), (
                            'Parallel glyph classes must have the same length')
                        input_class = input
                        input_class_index = i
                assert input_class is not None, 'A ligature substitution with a glyph class output must have a glyph class input'
                asts = []
                for input_glyph_name, output_glyph_name in zip(class_asts[input_class].glyphs.glyphs, class_asts[output].glyphs.glyphs):
                    asts.append(fontTools.feaLib.ast.LigatureSubstStatement(
                        glyphs_to_ast(self.contexts_in),
                        [
                            *glyphs_to_ast(self.inputs[:input_class_index]),
                            fontTools.feaLib.ast.GlyphName(input_glyph_name),
                            *glyphs_to_ast(self.inputs[input_class_index + 1:]),
                        ],
                        glyphs_to_ast(self.contexts_out),
                        glyph_to_name(fontTools.feaLib.ast.GlyphName(output_glyph_name)),
                        in_contextual_lookup,
                    ))
                return asts
            else:
                return [fontTools.feaLib.ast.LigatureSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyphs_to_ast(self.inputs),
                    glyphs_to_ast(self.contexts_out),
                    glyph_to_name(output),
                    in_contextual_lookup,
                )]

    def is_contextual(self):
        return bool(self.contexts_in or self.contexts_out)

    def is_multiple(self):
        return len(self.inputs) == 1 and self.outputs is not None and len(self.outputs) != 1

class Lookup:
    _DISCRETIONARY_FEATURES = {
        'afrc',
        'calt',
        'clig',
        'cswh',
        *{f'cv{x:02}' for x in range(1, 100)},
        'dlig',
        'hist',
        'hlig',
        'kern',
        'liga',
        'lnum',
        'onum',
        'ordn',
        'pnum',
        'salt',
        'sinf',
        *{f'ss{x:02}' for x in range(1, 21)},
        'subs',
        'sups',
        'swsh',
        'titl',
        'tnum',
        'zero',
    }
    _REQUIRED_SCRIPT_FEATURES = {
        'DFLT': {
            'abvm',
            'blwm',
            'curs',
            'dist',
            'locl',
            'mark',
            'mkmk',
            'rclt',
            'rlig',
        },
        'dupl': {
            'abvm',
            'abvs',
            'blwm',
            'blws',
            'curs',
            'dist',
            'haln',
            'mark',
            'mkmk',
            'pres',
            'psts',
            'rclt',
            'rlig',
        },
    }
    KNOWN_SCRIPTS = sorted(_REQUIRED_SCRIPT_FEATURES)

    def __init__(
            self,
            feature,
            scripts,
            language,
            *,
            flags=0,
            mark_filtering_set=None,
            reversed=False,
            prepending=False,
    ):
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
             flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        self.feature = feature
        if scripts is not None:
            scripts = [scripts] if isinstance(scripts, str) else sorted(scripts)
            self.required = set()
        else:
            scripts = []
            self.required = {False}
        self.scripts = scripts
        self.language = language
        for script in self.scripts:
            assert len(script) == 4, f"Script tag must be 4 characters long: '{script}'"
        assert language is None or len(language) == 4, f"Language tag must be 4 characters long: '{language}'"
        assert feature is None or len(feature) == 4, f"Feature tag must be 4 characters long: '{feature}'"
        self.flags = flags
        self.mark_filtering_set = mark_filtering_set
        self.reversed = reversed
        self.prepending = prepending
        self.rules = FreezableList()
        assert (feature is None) == (not scripts) == (language is None), 'Not clear whether this is a named or a normal lookup'
        for script in scripts:
            if feature in self._DISCRETIONARY_FEATURES:
                required = False
            else:
                try:
                    script_features = self._REQUIRED_SCRIPT_FEATURES[script]
                except KeyError:
                    raise ValueError(f"Unrecognized script tag: '{script}'")
                assert feature in script_features, f"The phase system does not support the feature '{feature}' for the script '{script}'"
                required = True
            self.required.add(required)
        assert len(self.required) == 1, f"""Scripts {{{
                ', '.join("'{script}'" for script in scripts)
            }}} disagree about whether the feature '{feature}' is required"""
        self.required = next(iter(self.required))

    def to_asts(self, class_asts, named_lookup_asts, name):
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        if isinstance(name, str):
            lookup_block = fontTools.feaLib.ast.LookupBlock(name)
            asts = [lookup_block]
        else:
            lookup_block = fontTools.feaLib.ast.LookupBlock(f'lookup_{name}')
            feature_block = fontTools.feaLib.ast.FeatureBlock(self.feature)
            for script in self.scripts:
                feature_block.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
                feature_block.statements.append(fontTools.feaLib.ast.LanguageStatement(self.language))
                feature_block.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup_block))
            asts = [lookup_block, feature_block]
        lookup_block.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
            self.flags,
            markFilteringSet=fontTools.feaLib.ast.GlyphClassName(class_asts[self.mark_filtering_set])
                if self.mark_filtering_set
                else None))
        lookup_block.statements.extend({
                ast.asFea(): ast
                    for r in self.rules
                    for ast in r.to_asts(class_asts, named_lookup_asts, contextual, multiple, self.reversed)
            }.values())
        return asts

    def freeze(self):
        self.rules.freeze()

    def append(self, rule):
        self.rules.append(rule)

    def extend(self, other):
        assert self.feature == other.feature, f"Incompatible features: '{self.feature}' != '{other.feature}'"
        assert self.scripts == other.scripts, f'''Incompatible script sets: {{{
                ', '.join(f"'{script}'" for script in self.scripts)
            }}} != {{{
                ', '.join(f"'{script}'" for script in other.scripts)
            }}}'''
        assert self.language == other.language, f"Incompatible languages: '{self.language}' != '{other.language}'"
        assert self.prepending == other.prepending, f'Incompatible prepending values: {self.prepending} != {other.prepending}'
        if self.prepending:
            for rule in other.rules:
                self.rules.insert(0, rule)
        else:
            for rule in other.rules:
                self.append(rule)

def make_trees(node, edge, maximum_depth, *, top_widths=None, prefix_depth=None):
    if maximum_depth <= 0:
        return []
    trees = []
    if prefix_depth is None:
        subtrees = make_trees(node, edge, maximum_depth - 1)
        for width in range(MAX_TREE_WIDTH + 1) if top_widths is None else top_widths:
            for index_set in itertools.product(range(len(subtrees)), repeat=width):
                tree = [node, *[edge] * width] if top_widths is None else []
                for i in index_set:
                    tree.extend(subtrees[i])
                trees.append(tree)
    elif prefix_depth == 1:
        trees.append([])
    else:
        shallow_subtrees = make_trees(node, edge, maximum_depth - 2)
        deep_subtrees = make_trees(node, edge, maximum_depth - 1, prefix_depth=prefix_depth - 1)
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

def add_rule(autochthonous_schemas, output_schemas, classes, named_lookups, lookup, rule, track_possible_outputs=True):
    def ignored(schema):
        glyph_class = schema.glyph_class
        return (
            glyph_class == GlyphClass.BLOCKER and lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_BASE_GLYPHS
            or glyph_class == GlyphClass.JOINER and lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES
            or glyph_class == GlyphClass.MARK and (
                lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS
                or lookup.mark_filtering_set and schema not in classes[lookup.mark_filtering_set]
            )
        )

    def check_ignored(target_part):
        for s in target_part:
            if isinstance(s, str):
                ignored_schema = next(filter(ignored, classes[s]), None)
                assert ignored_schema is None, f'''At least one glyph in @{s} ({
                        ignored_schema
                    }) appears in a substitution where it is ignored'''
            else:
                assert not ignored(s), f'{s} appears in a substitution where it is ignored'

    check_ignored(rule.contexts_in)
    if lookup.feature is None:
        # The first item in a named lookup’s input sequence is immune to that
        # named lookup’s lookup flags. It is guaranteed to (try to) match the
        # glyph at the targeted position in the rule that references the named
        # lookup.
        inputs = iter(rule.inputs)
        next(inputs)
        check_ignored(inputs)
    else:
        check_ignored(rule.inputs)
    check_ignored(rule.contexts_out)

    for input in rule.inputs:
        if isinstance(input, str):
            if all(s in autochthonous_schemas for s in classes[input]):
                classes[input].freeze()
                return
        elif input in autochthonous_schemas:
            return

    def is_prefix(maybe_prefix, full):
        return len(maybe_prefix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(maybe_prefix, full)))
    def is_suffix(maybe_suffix, full):
        return len(maybe_suffix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(reversed(maybe_suffix), reversed(full))))
    if not lookup.prepending and any(r.is_contextual() for r in lookup.rules):
        # TODO: Check prepending lookups too.
        for i, previous_rule in enumerate(lookup.rules):
            if lookup.prepending:
                previous_rule, rule = rule, previous_rule
            if (previous_rule.inputs == rule.inputs
                and is_suffix(previous_rule.contexts_in, rule.contexts_in)
                and is_prefix(previous_rule.contexts_out, rule.contexts_out)
                and (previous_rule.contexts_in != rule.contexts_in or previous_rule.contexts_out != rule.contexts_out)
            ):
                return
    lookup.append(rule)

    # FIXME: `track_possible_outputs` is a manual workaround for this function’s
    # inability to track possible outputs between rules in the same lookup.
    if (track_possible_outputs
        and lookup.required
        and not rule.contexts_in
        and not rule.contexts_out
        and len(rule.inputs) == 1
    ):
        input = rule.inputs[0]
        if isinstance(input, str):
            for i in classes[input]:
                output_schemas.remove(i)
        else:
            output_schemas.remove(input)

    registered_lookups = {None}
    def register_output_schemas(rule):
        if rule.outputs is not None:
            froze = False
            for output in rule.outputs:
                if isinstance(output, str):
                    must_freeze = False
                    for o in classes[output]:
                        if o not in output_schemas:
                            must_freeze = True
                            output_schemas.add(o)
                    if must_freeze:
                        classes[output].freeze()
                        froze = True
                else:
                    output_schemas.add(output)
            return froze
        elif rule.lookups is not None:
            for lookup in rule.lookups:
                if lookup not in registered_lookups:
                    registered_lookups.add(lookup)
                    froze = False
                    for rule in named_lookups[lookup].rules:
                        if register_output_schemas(rule):
                            froze = True
                    if froze:
                        named_lookups[lookup].freeze()
            return False

    register_output_schemas(rule)

class PrefixView:
    def __init__(self, source, delegate):
        self.prefix = f'{source.__name__}..'
        self._delegate = delegate

    def _prefixed(self, key):
        is_global = key.startswith('global..')
        assert len(key.split('..')) == 1 + is_global, f'Invalid key: {key!r}'
        return key if is_global else self.prefix + key

    def __getitem__(self, key, /):
        return self._delegate[self._prefixed(key)]

    def __setitem__(self, key, value, /):
        self._delegate[self._prefixed(key)] = value

    def __contains__(self, item, /):
        return self._prefixed(item) in self._delegate

    def keys(self):
        return self._delegate.keys()

    def items(self):
        return self._delegate.items()

def rename_schemas(grouper, phase_index):
    for group in grouper.groups():
        if not any(map(lambda s: s.phase_index >= phase_index, group)):
            continue
        group.sort(key=Schema.sort_key)
        canonical_schema = next(filter(lambda s: s.phase_index < phase_index, group), None)
        if canonical_schema is None:
            canonical_schema = group[0]
        for schema in list(group):
            if schema.phase_index >= phase_index:
                schema.canonical_schema = canonical_schema
                if grouper.group_of(schema):
                    grouper.remove_item(group, schema)

class Builder:
    def __init__(self, font, bold, noto):
        self.font = font
        self._fea = fontTools.feaLib.ast.FeatureFile()
        self._anchors = {}
        self._initialize_phases(noto)
        self.light_line = 101 if bold else REGULAR_LIGHT_LINE
        self.shaded_line = SHADING_FACTOR * self.light_line
        self.stroke_gap = max(MINIMUM_STROKE_GAP, self.light_line)
        code_points = collections.defaultdict(int)
        self._initialize_schemas(noto, self.light_line, self.stroke_gap)
        for schema in self._schemas:
            if schema.cmap is not None:
                code_points[schema.cmap] += 1
        for glyph in font.glyphs():
            if glyph.unicode != -1 and glyph.unicode not in code_points:
                self._schemas.append(Schema(glyph.unicode, SFDGlyphWrapper(glyph.glyphname), 0, Type.NON_JOINING))
        code_points = {cp: count for cp, count in code_points.items() if count > 1}
        assert not code_points, ('Duplicate code points:\n    '
            + '\n    '.join(map(hex, sorted(code_points.keys()))))

    def _initialize_phases(self, noto):
        self._phases = [
            self._dont_ignore_default_ignorables,
        ]
        if not noto:
            self._phases += [
                self._reversed_circle_kludge,
            ]
        self._phases += [
            self._validate_shading,
            self._validate_double_marks,
            self._decompose,
            self._expand_secants,
            self._validate_overlap_controls,
            self._add_parent_edges,
            self._invalidate_overlap_controls,
            self._add_secant_guidelines,
            self._add_placeholders_for_missing_children,
            self._categorize_edges,
            self._promote_final_letter_overlap_to_continuing_overlap,
            self._reposition_chinook_jargon_overlap_points,
            self._make_mark_variants_of_children,
            self._interrupt_overlong_primary_curve_sequences,
            self._reposition_stenographic_period,
            self._disjoin_equals_sign,
            self._join_with_next_step,
            self._separate_subantiparallel_lines,
            self._prepare_for_secondary_diphthong_ligature,
            self._join_with_previous,
            self._unignore_last_orienting_glyph_in_initial_sequence,
            self._ignore_first_orienting_glyph_in_initial_sequence,
            self._tag_main_glyph_in_orienting_sequence,
            self._join_with_next,
            self._join_circle_with_adjacent_nonorienting_glyph,
            self._ligate_diphthongs,
            self._thwart_what_would_flip,
            self._unignore_noninitial_orienting_sequences,
            self._unignore_initial_orienting_sequences,
            self._join_double_marks,
            self._rotate_diacritics,
            self._shade,
            self._create_diagonal_fractions,
            self._create_superscripts_and_subscripts,
            self._make_widthless_variants_of_marks,
            self._classify_marks_for_trees,
        ]

        self._middle_phases = [
            self._merge_lookalikes,
        ]

        self._marker_phases = [
            self._add_shims_for_pseudo_cursive,
            self._shrink_wrap_enclosing_circle,
            self._add_width_markers,
            self._add_end_markers_for_marks,
            self._remove_false_end_markers,
            self._clear_entry_width_markers,
            self._sum_width_markers,
            self._calculate_bound_extrema,
            self._remove_false_start_markers,
            self._mark_hubs_after_initial_secants,
            self._find_real_hub,
            self._expand_start_markers,
            self._mark_maximum_bounds,
            self._copy_maximum_left_bound_to_start,
            self._dist,
        ]

    def _initialize_schemas(self, noto, light_line, stroke_gap):
        notdef = Notdef()
        space = Space(0, margins=True)
        h = Dot()
        exclamation = Complex([(1, h), (201, Space(90)), (1.109, Line(90))])
        dollar = Complex([(2.58, Curve(180 - 18, 180 + 26, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (2.88, Curve(180 + 26, 360 - 8, clockwise=False, stretch=0.5, long=True, relative_stretch=False)), (0.0995, Line(360 - 8)), (2.88, Curve(360 - 8, 180 + 26, clockwise=True, stretch=0.5, long=True, relative_stretch=False)), (2.58, Curve(180 + 26, 180 - 18, clockwise=True, stretch=2.058, long=True, relative_stretch=False)), (151.739, Space(328.952)), (1.484, Line(90)), (140, Space(0)), (1.484, Line(270))])
        asterisk = Complex([(310, Space(90)), (0.467, Line(90)), (0.467, Line(198)), (0.467, Line(18), False), (0.467, Line(126)), (0.467, Line(306), False), (0.467, Line(54)), (0.467, Line(234), False), (0.467, Line(342))])
        plus = Complex([(146, Space(90)), (0.828, Line(90)), (0.414, Line(270)), (0.414, Line(180)), (0.828, Line(0))])
        comma = Complex([(35, Space(0)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True))])
        slash = Line(60)
        zero = Circle(180, 180, clockwise=False, stretch=132 / 193, long=True)
        one = Complex([(1.288, Line(90)), (0.416, Line(218))])
        two = Complex([(3.528, Curve(42, 25, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232)), (0.7, Line(0))])
        three = Complex([(3, Curve(36, 0, clockwise=True, stretch=0.2, long=True)), (3, Curve(0, 180, clockwise=True, stretch=0.2, long=True)), (0.15, Line(180)), (0.15, Line(0)), (3.36, Curve(0, 180, clockwise=True, stretch=0.375, long=True)), (3.42, Curve(180, 155, clockwise=True, stretch=0.937, long=True))])
        four = Complex([(1.296, Line(90)), (1.173, Line(235)), (0.922, Line(0))])
        five = Complex([(3.72, Curve(330, 0, clockwise=False, stretch=0.196, long=True)), (3.72, Curve(0, 180, clockwise=False, stretch=13 / 93, long=True)), (3.72, Curve(180, 210, clockwise=False, stretch=0.196, long=True)), (0.565, Line(86.145)), (0.572, Line(0))])
        six = Complex([(3.88, Circle(90, 90, clockwise=True)), (19.5, Curve(90, 70, clockwise=True, stretch=0.45)), (4, Curve(65, 355, clockwise=True))])
        seven = Complex([(0.818, Line(0)), (1.36, Line(246))])
        eight = Complex([(2.88, Curve(180, 90, clockwise=True)), (2.88, Curve(90, 270, clockwise=True)), (2.88, Curve(270, 180, clockwise=True)), (3.16, Curve(180, 270, clockwise=False)), (3.16, Curve(270, 90, clockwise=False)), (3.16, Curve(90, 180, clockwise=False))])
        nine = Complex([(3.5, Circle(270, 270, clockwise=True)), (35.1, Curve(270, 260, clockwise=True, stretch=0.45)), (4, Curve(255, 175, clockwise=True))])
        colon = Complex([(1, h), (509, Space(90)), (1, h)])
        semicolon = Complex([*comma.instructions, (3, Curve(41, 101, clockwise=False), True), (0.5, Circle(101, 180, clockwise=False), True), (416, Space(90)), (1, h)])
        question = Complex([(1, h), (201, Space(90)), (4.162, Curve(90, 45, clockwise=True)), (0.16, Line(45)), (4.013, Curve(45, 210, clockwise=False))])
        less_than = Complex([(1, Line(153)), (1, Line(27))])
        equal = Complex([(305, Space(90)), (1, Line(0)), (180, Space(90)), (1, Line(180)), (90, Space(270)), (1, Line(0), True)], maximum_tree_width=1)
        greater_than = Complex([(1, Line(27)), (1, Line(153))])
        left_bracket = Complex([(0.45, Line(180)), (2.059, Line(90)), (0.45, Line(0))])
        right_bracket = Complex([(0.45, Line(0)), (2.059, Line(90)), (0.45, Line(180))])
        guillemet_vertical_space = (75, Space(90))
        guillemet_horizontal_space = (200, Space(0))
        left_guillemet = [(0.524, Line(129.89)), (0.524, Line(50.11))]
        right_guillemet = [*reversed(left_guillemet)]
        left_guillemet += [(op[0], op[1].reversed(), True) for op in left_guillemet]
        right_guillemet += [(op[0], op[1].reversed(), True) for op in right_guillemet]
        left_double_guillemet = Complex([guillemet_vertical_space, *left_guillemet, guillemet_horizontal_space, *left_guillemet])
        right_double_guillemet = Complex([guillemet_vertical_space, *right_guillemet, guillemet_horizontal_space, *right_guillemet])
        left_single_guillemet = Complex([guillemet_vertical_space, *left_guillemet])
        right_single_guillemet = Complex([guillemet_vertical_space, *right_guillemet])
        enclosing_circle = Circle(180, 180, clockwise=False)
        masculine_ordinal_indicator = Complex([(625.5, Space(90)), (2.3, Circle(180, 180, clockwise=False, stretch=0.078125, long=True)), (370, Space(270)), (105, Space(180)), (0.42, Line(0))])
        multiplication = Complex([(1, Line(315)), (0.5, Line(135), False), (0.5, Line(225)), (1, Line(45))])
        grave = Line(150)
        acute = Line(45)
        circumflex = Complex([(1, Line(25)), (1, Line(335))])
        macron = Line(0)
        breve = Curve(270, 90, clockwise=False, stretch=0.2)
        diaeresis = Line(0, dots=2)
        caron = Complex([(1, Line(335)), (1, Line(25))])
        inverted_breve = Curve(90, 270, clockwise=False, stretch=0.2)
        en_dash = Complex([(395, Space(90)), (1, Line(0))])
        high_left_quote = Complex([(755, Space(90)), (3, Curve(221, 281, clockwise=False)), (0.5, Circle(281, 281, clockwise=False)), (160, Space(0)), (0.5, Circle(101, 101, clockwise=True)), (3, Curve(101, 41, clockwise=True))])
        high_right_quote = Complex([(742, Space(90)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        low_right_quote = Complex([(35, Space(0)), (0.5, Circle(281, 281, clockwise=True)), (3, Curve(281, 221, clockwise=True)), (160, Space(0)), (3, Curve(41, 101, clockwise=False)), (0.5, Circle(101, 180, clockwise=False))])
        ellipsis = Complex([(1, h), (148, Space(0)), (1, h), (148, Space(0)), (1, h)])
        nnbsp = Space(0)
        dotted_circle = Complex([(33, Space(90)), (1, h), (446, Space(90)), (1, h), (223, Space(270)), (223, Space(60)), (1, h), (446, Space(240)), (1, h), (223, Space(60)), (223, Space(30)), (1, h), (446, Space(210)), (1, h), (223, Space(30)), (223, Space(0)), (1, h), (446, Space(180)), (1, h), (223, Space(0)), (223, Space(330)), (1, h), (446, Space(150)), (1, h), (223, Space(330)), (223, Space(300)), (1, h), (446, Space(120)), (1, h)])
        skull_and_crossbones = Complex([(7, Circle(180, 180, clockwise=False, stretch=0.4, long=True)), (7 * 2 * 1.4 * RADIUS * 0.55, Space(270)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(120)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(0)), (0.5, Circle(180, 180, clockwise=False)), (7 * 2 * 1.4 * RADIUS / math.sqrt(3) / 2.5, Space(240)), (7 * 2 * 1.4 * RADIUS * 0.3, Space(270)), (1, h), (150, Space(160)), (1, h), (150, Space(340)), (150, Space(20)), (1, h), (150, Space(200)), (7 * 2 * 1.4 * RADIUS / 2, Space(270)), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), False), (2.1, Curve(60, 90, clockwise=False), True), (2.1, Curve(270, 210, clockwise=True)), (2.1, Curve(30, 60, clockwise=False), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(330)), (2.1, Curve(60, 30, clockwise=True), True), (2.1, Curve(210, 270, clockwise=False)), (2.1, Curve(90, 60, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(150), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR / 2, Line(30), True), (2.1, Curve(120, 90, clockwise=True)), (2.1, Curve(270, 330, clockwise=False)), (2.1, Curve(150, 120, clockwise=True), True), (7 * 2 * 1.4 * RADIUS / LINE_FACTOR, Line(210)), (2.1, Curve(120, 150, clockwise=False), True), (2.1, Curve(330, 270, clockwise=True)), (2.1, Curve(90, 120, clockwise=False), True)])
        stenographic_period = Complex([(0.5, Line(135)), *multiplication.instructions])
        double_hyphen = Complex([(305, Space(90)), (0.5, Line(0)), (179, Space(90)), (0.5, Line(180))])
        bound = Bound()
        cross_knob_line_factor = 0.42
        cross_knob_factor = cross_knob_line_factor * LINE_FACTOR / RADIUS
        cross_knob_instructions = [(cross_knob_line_factor, Line(270), True), (cross_knob_factor, Circle(180, 180, clockwise=True)), (cross_knob_line_factor / 2, Line(90), True), (cross_knob_factor / 2, Circle(180, 180, clockwise=True)), (cross_knob_line_factor / 2, Line(90), True)]
        cross_pommy = Complex([*cross_knob_instructions, (3 + 2 * cross_knob_line_factor, Line(270)), *cross_knob_instructions, (2 + cross_knob_line_factor, Line(90), True), (1 + cross_knob_line_factor, Line(180), True), *cross_knob_instructions, (2 + 2 * cross_knob_line_factor, Line(0)), *cross_knob_instructions])
        cross = Complex([(3, Line(270)), (2, Line(90), True), (1, Line(180), True), (2, Line(0))])
        sacred_heart = Complex([(3.528, Curve(42, 25, clockwise=True, stretch=0.346, long=True)), (3.528, Curve(25, 232, clockwise=True, stretch=0.036, long=True)), (0.904, Line(232)), (0.904, Line(128)), (3.528, Curve(128, 335, clockwise=True, stretch=0.036, long=True)), (3.528, Curve(335, 318, clockwise=True, stretch=0.346, long=True)), (7.5, Space(0)), (1, cross.instructions[0][1].reversed(), True), *[(op[0] / 3, op[1]) for op in cross.instructions]])
        x = XShape([(2, Curve(30, 130, clockwise=False)), (2, Curve(130, 30, clockwise=True))])
        p = Line(270, stretchy=True)
        p_reverse = Line(90, stretchy=True)
        t = Line(0, stretchy=True)
        t_reverse = Line(180, stretchy=True)
        f = Line(300, stretchy=True)
        f_reverse = Line(120, stretchy=True)
        k = Line(240, stretchy=True)
        k_reverse = Line(60, stretchy=True)
        l = Line(45, stretchy=True)
        l_reverse = Line(225, stretchy=True)
        m = Curve(180, 0, clockwise=False, stretch=0.2)
        m_reverse = Curve(180, 0, clockwise=True, stretch=0.2)
        n = Curve(0, 180, clockwise=True, stretch=0.2)
        n_reverse = Curve(0, 180, clockwise=False, stretch=0.2)
        j = Curve(90, 270, clockwise=True, stretch=0.2)
        j_reverse = Curve(90, 270, clockwise=False, stretch=0.2)
        s = Curve(270, 90, clockwise=False, stretch=0.2)
        s_reverse = Curve(270, 90, clockwise=True, stretch=0.2)
        m_s = Curve(180, 0, clockwise=False, stretch=0.8)
        n_s = Curve(0, 180, clockwise=True, stretch=0.8)
        j_s = Curve(90, 270, clockwise=True, stretch=0.8)
        s_s = Curve(270, 90, clockwise=False, stretch=0.8)
        s_t = Curve(270, 0, clockwise=False)
        s_p = Curve(270, 180, clockwise=True)
        t_s = Curve(0, 270, clockwise=True)
        w = Curve(180, 270, clockwise=False)
        s_n = Curve(0, 90, clockwise=False, secondary=True)
        k_r_s = Curve(90, 180, clockwise=False)
        s_k = Curve(90, 0, clockwise=True, secondary=False)
        j_n = Complex([(1, s_k), (1, n)], maximum_tree_width=1)
        j_n_s = Complex([(3, s_k), (4, n_s)], maximum_tree_width=1)
        o = Circle(90, 90, clockwise=False)
        o_reverse = o.as_reversed()
        ie = Curve(180, 0, clockwise=False)
        short_i = Curve(0, 180, clockwise=True)
        ui = Curve(90, 270, clockwise=True)
        ee = Curve(270, 90, clockwise=False, secondary=True)
        ye = Complex([(0.47, Line(0, minor=True)), (0.385, Line(242)), (0.47, t), (0.385, Line(242)), (0.47, t), (0.385, Line(242)), (0.47, t)])
        u_n = Curve(90, 180, clockwise=True)
        long_u = Curve(225, 45, clockwise=False, stretch=4, long=True)
        romanian_u = RomanianU([(1, Curve(180, 0, clockwise=False)), lambda c: c, (0.5, Curve(0, 180, clockwise=False))], hook=True)
        uh = Circle(45, 45, clockwise=False, reversed=False, stretch=2)
        ou = Ou([(1, Circle(180, 145, clockwise=False)), lambda c: c, (5 / 9, Curve(145, 270, clockwise=False))])
        ou_reverse = ou.as_reversed()
        wa = Wa([(4, Circle(180, 180, clockwise=False)), (2, Circle(180, 180, clockwise=False))])
        wo = Wa([(4, Circle(180, 180, clockwise=False)), (2.5, Circle(180, 180, clockwise=False))])
        wi = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (5 / 3, m)])
        wei = Wi([(4, Circle(180, 180, clockwise=False)), lambda c: c, (1, m), lambda c: c.clone(clockwise=not c.clockwise), (1, n)])
        left_horizontal_secant = Line(0, secant=2 / 3)
        mid_horizontal_secant = Line(0, secant=0.5)
        right_horizontal_secant = Line(0, secant=1 / 3)
        low_vertical_secant = Line(90, secant=2 / 3)
        mid_vertical_secant = Line(90, secant=0.5)
        high_vertical_secant = Line(90, secant=1 / 3)
        rtl_secant = Line(240, secant=0.5, secant_curvature_offset=55)
        ltr_secant = Line(310, secant=0.5, secant_curvature_offset=55)
        tangent = Complex([lambda c: Context(None if c.angle is None else (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360), (0.25, Line(270)), lambda c: Context((c.angle + 180) % 360), (0.5, Line(90))], hook=True)
        e_hook = Curve(90, 270, clockwise=True, hook=True)
        i_hook = Curve(180, 0, clockwise=False, hook=True)
        tangent_hook = TangentHook([(1, Curve(180, 270, clockwise=False)), Context.reversed, (1, Curve(90, 270, clockwise=True))])
        high_acute = SeparateAffix([(0.5, Line(45))])
        high_tight_acute = SeparateAffix([(0.5, Line(45))], tight=True)
        high_grave = SeparateAffix([(0.5, Line(315))])
        high_long_grave = SeparateAffix([(0.4, Line(300)), (0.75, Line(0))])
        high_dot = SeparateAffix([(1, Dot(centered=True))])
        high_circle = SeparateAffix([(2, Circle(0, 0, clockwise=False))])
        high_line = SeparateAffix([(0.5, Line(0))])
        high_wave = SeparateAffix([(2, Curve(90, 315, clockwise=True)), (RADIUS * math.sqrt(2) / LINE_FACTOR, Line(315)), (2, Curve(315, 90, clockwise=False))])
        high_vertical = SeparateAffix([(0.5, Line(90))])
        low_acute = high_acute.clone(low=True)
        low_tight_acute = high_tight_acute.clone(low=True)
        low_grave = high_grave.clone(low=True)
        low_long_grave = high_long_grave.clone(low=True)
        low_dot = high_dot.clone(low=True)
        low_circle = high_circle.clone(low=True)
        low_line = high_line.clone(low=True)
        low_wave = high_wave.clone(low=True)
        low_vertical = high_vertical.clone(low=True)
        low_arrow = SeparateAffix([(0.4, Line(0)), (0.4, Line(240))], low=True)
        likalisti = Complex([(5, Circle(0, 0, clockwise=False)), (375, Space(90)), (0.5, p), (math.hypot(125, 125), Space(135)), (0.5, Line(0))])
        dotted_square = [(152, Space(270)), (0.26 - light_line / 1000, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.264 - light_line / LINE_FACTOR, Line(90)), (58 + light_line, Space(90)), (0.26 - light_line / 1000, Line(90)), (0.26 - light_line / 1000, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.264 - light_line / LINE_FACTOR, Line(0)), (58 + light_line, Space(0)), (0.26 - light_line / 1000, Line(0)), (0.26 - light_line / 1000, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.264 - light_line / LINE_FACTOR, Line(270)), (58 + light_line, Space(270)), (0.26 - light_line / 1000, Line(270)), (0.26 - light_line / 1000, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.264 - light_line / LINE_FACTOR, Line(180)), (58 + light_line, Space(180)), (0.26 - light_line / 1000, Line(180))]
        dtls = InvalidDTLS(instructions=dotted_square + [(341, Space(0)), (173, Space(90)), (0.238, Line(180)), (0.412, Line(90)), (130, Space(90)), (0.412, Line(90)), (0.18, Line(0)), (2.06, Curve(0, 180, clockwise=True, stretch=-27 / 115, long=True, relative_stretch=False)), (0.18, Line(180)), (369, Space(0)), (0.412, Line(90)), (0.148, Line(180), True), (0.296, Line(0)), (341, Space(270)), (14.5, Space(180)), (.345 * 2.58, Curve(164, 196, clockwise=False, stretch=2.058, long=True, relative_stretch=False)), (.345 * 2.88, Curve(196, 341, clockwise=False, stretch=0.25, long=True, relative_stretch=False)), (.345 *0.224, Line(341)), (.345 * 2.88, Curve(341, 196, clockwise=True, stretch=0.25, long=True, relative_stretch=False)), (.345 * 2.58, Curve(196, 164, clockwise=True, stretch=2.058, long=True, relative_stretch=False))])
        chinook_period = Complex([(100, Space(90)), (1, Line(0)), (179, Space(90)), (1, Line(180))])
        overlap = InvalidOverlap(continuing=False, instructions=dotted_square + [(162.5, Space(0)), (397, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (1.134, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220)), (170, Space(180)), (0.4116, Line(90))])
        continuing_overlap = InvalidOverlap(continuing=True, instructions=dotted_square + [(189, Space(0)), (522, Space(90)), (0.192, Line(90)), (0.096, Line(270), True), (0.726, Line(0)), (124, Space(180)), (145, Space(90)), (0.852, Line(270)), (0.552, Line(0)), (0.32, Line(140)), (0.32, Line(320), True), (0.32, Line(220))])
        down_step = InvalidStep(270, dotted_square + [(444, Space(0)), (749, Space(90)), (1.184, Line(270)), (0.32, Line(130)), (0.32, Line(310), True), (0.32, Line(50))])
        up_step = InvalidStep(90, dotted_square + [(444, Space(0)), (157, Space(90)), (1.184, Line(90)), (0.32, Line(230)), (0.32, Line(50), True), (0.32, Line(310))])
        line = Line(0)

        dot_1 = Schema(None, h, 1, anchor=anchors.RELATIVE_1)
        dot_2 = Schema(None, h, 1, anchor=anchors.RELATIVE_2)
        line_2 = Schema(None, line, 0.35, Type.ORIENTING, anchor=anchors.RELATIVE_2)
        line_middle = Schema(None, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE)

        self._schemas = [
            Schema(None, notdef, 1, Type.NON_JOINING, side_bearing=95, y_max=CAP_HEIGHT),
            Schema(0x0020, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x0021, exclamation, 1, Type.NON_JOINING, encirclable=True, y_max=CAP_HEIGHT),
            Schema(0x0024, dollar, 7 / 8, Type.NON_JOINING, y_max=CAP_HEIGHT),
            Schema(0x002A, asterisk, 1, Type.NON_JOINING),
            Schema(0x002B, plus, 1, Type.NON_JOINING),
            Schema(0x002C, comma, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x002E, h, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x002F, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x0030, zero, 3.882, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0031, one, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0032, two, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0033, three, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0034, four, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0035, five, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0036, six, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0037, seven, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0038, eight, 1.064, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x0039, nine, 1.021, Type.NON_JOINING, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x003A, colon, 0.856, Type.NON_JOINING, encirclable=True, shading_allowed=False),
            Schema(0x003B, semicolon, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x003C, less_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003D, equal, 1),
            Schema(0x003E, greater_than, 2, Type.NON_JOINING, shading_allowed=False),
            Schema(0x003F, question, 1, Type.NON_JOINING, y_max=CAP_HEIGHT, encirclable=True),
            Schema(0x005B, left_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x005D, right_bracket, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x00A0, space, 260, Type.NON_JOINING, side_bearing=260),
            Schema(0x00AB, left_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00B0, enclosing_circle, 2.3, Type.NON_JOINING, y_min=None, y_max=CAP_HEIGHT, shading_allowed=False),
            Schema(0x00BA, masculine_ordinal_indicator, 1, Type.NON_JOINING),
            Schema(0x00BB, right_double_guillemet, 1, Type.NON_JOINING),
            Schema(0x00D7, multiplication, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x0300, grave, 0.2, anchor=anchors.ABOVE),
            Schema(0x0301, acute, 0.2, anchor=anchors.ABOVE),
            Schema(0x0302, circumflex, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x0304, macron, 0.2, anchor=anchors.ABOVE),
            Schema(0x0306, breve, 1, anchor=anchors.ABOVE),
            Schema(0x0307, h, 1, anchor=anchors.ABOVE),
            Schema(0x0308, diaeresis, 0.2, anchor=anchors.ABOVE),
            Schema(0x030C, caron, 0.2, Type.NON_JOINING, anchor=anchors.ABOVE),
            Schema(0x0316, grave, 0.2, anchor=anchors.BELOW),
            Schema(0x0317, acute, 0.2, anchor=anchors.BELOW),
            Schema(0x0323, h, 1, anchor=anchors.BELOW),
            Schema(0x0324, diaeresis, 0.2, anchor=anchors.BELOW),
            Schema(0x032F, inverted_breve, 1, anchor=anchors.BELOW),
            Schema(0x0331, macron, 0.2, anchor=anchors.BELOW),
            Schema(0x034F, space, 0, Type.NON_JOINING, side_bearing=0, ignorability=Ignorability.DEFAULT_YES),
            Schema(0x2001, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x2003, space, 1500, Type.NON_JOINING, side_bearing=1500),
            Schema(0x200C, space, 0, Type.NON_JOINING, side_bearing=0, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x2013, en_dash, 1, Type.NON_JOINING, encirclable=True),
            Schema(0x201C, high_left_quote, 1, Type.NON_JOINING),
            Schema(0x201D, high_right_quote, 1, Type.NON_JOINING),
            Schema(0x201E, low_right_quote, 1, Type.NON_JOINING),
            Schema(0x2026, ellipsis, 1, Type.NON_JOINING, shading_allowed=False),
            Schema(0x202F, nnbsp, 200 - 2 * DEFAULT_SIDE_BEARING, side_bearing=200 - 2 * DEFAULT_SIDE_BEARING),
            Schema(0x2039, left_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x203A, right_single_guillemet, 1, Type.NON_JOINING),
            Schema(0x2044, slash, 1, Type.NON_JOINING, y_min=BRACKET_DEPTH, y_max=BRACKET_HEIGHT, shading_allowed=False),
            Schema(0x20DD, enclosing_circle, 10, anchor=anchors.MIDDLE),
            Schema(0x25CC, dotted_circle, 1, Type.NON_JOINING),
            Schema(0x2620, skull_and_crossbones, 1, Type.NON_JOINING, y_max=1.5 * CAP_HEIGHT, y_min=-0.5 * CAP_HEIGHT),
            Schema(0x271D, cross, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT, shading_allowed=False),
            Schema(0x2E3C, stenographic_period, 0.5, Type.NON_JOINING, shading_allowed=False),
            Schema(0x2E40, double_hyphen, 1, Type.NON_JOINING),
            Schema(0xE000, bound, 1, Type.NON_JOINING, side_bearing=0),
            Schema(0xE001, cross_pommy, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT, shading_allowed=False),
            Schema(0xE003, sacred_heart, 1, Type.NON_JOINING, y_max=1.1 * CAP_HEIGHT, y_min=-0.4 * CAP_HEIGHT),
            Schema(0xEC02, p_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC03, t_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC04, f_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC05, k_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC06, l_reverse, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0xEC19, m_reverse, 6, shading_allowed=False),
            Schema(0xEC1A, n_reverse, 6, shading_allowed=False),
            Schema(0xEC1B, j_reverse, 6, shading_allowed=False),
            Schema(0xEC1C, s_reverse, 6, shading_allowed=False),
            Schema(0x1BC00, h, 1, shading_allowed=False),
            Schema(0x1BC01, x, 0.75, shading_allowed=False),
            Schema(0x1BC02, p, 1, Type.ORIENTING),
            Schema(0x1BC03, t, 1, Type.ORIENTING),
            Schema(0x1BC04, f, 1, Type.ORIENTING),
            Schema(0x1BC05, k, 1, Type.ORIENTING),
            Schema(0x1BC06, l, 1, Type.ORIENTING),
            Schema(0x1BC07, p, 2, Type.ORIENTING),
            Schema(0x1BC08, t, 2, Type.ORIENTING),
            Schema(0x1BC09, f, 2, Type.ORIENTING),
            Schema(0x1BC0A, k, 2, Type.ORIENTING),
            Schema(0x1BC0B, l, 2, Type.ORIENTING),
            Schema(0x1BC0C, p, 3, Type.ORIENTING),
            Schema(0x1BC0D, t, 3, Type.ORIENTING),
            Schema(0x1BC0E, f, 3, Type.ORIENTING),
            Schema(0x1BC0F, k, 3, Type.ORIENTING),
            Schema(0x1BC10, l, 3, Type.ORIENTING),
            Schema(0x1BC11, t, 1, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC12, t, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC13, t, 2, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC14, k, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC15, k, 2, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC16, l, 1, Type.ORIENTING, marks=[dot_1]),
            Schema(0x1BC17, l, 1, Type.ORIENTING, marks=[dot_2]),
            Schema(0x1BC18, l, 2, Type.ORIENTING, marks=[dot_1, dot_2]),
            Schema(0x1BC19, m, 6),
            Schema(0x1BC1A, n, 6),
            Schema(0x1BC1B, j, 6),
            Schema(0x1BC1C, s, 6),
            Schema(0x1BC1D, m, 6, marks=[line_middle]),
            Schema(0x1BC1E, n, 6, marks=[line_middle]),
            Schema(0x1BC1F, j, 6, marks=[line_middle]),
            Schema(0x1BC20, s, 6, marks=[line_middle]),
            Schema(0x1BC21, m, 6, marks=[dot_1]),
            Schema(0x1BC22, n, 6, marks=[dot_1]),
            Schema(0x1BC23, j, 6, marks=[dot_1]),
            Schema(0x1BC24, j, 6, marks=[dot_1, dot_2]),
            Schema(0x1BC25, s, 6, marks=[dot_1]),
            Schema(0x1BC26, s, 6, marks=[dot_2]),
            Schema(0x1BC27, m_s, 8),
            Schema(0x1BC28, n_s, 8),
            Schema(0x1BC29, j_s, 8),
            Schema(0x1BC2A, s_s, 8),
            Schema(0x1BC2B, m_s, 8, marks=[line_middle]),
            Schema(0x1BC2C, n_s, 8, marks=[line_middle]),
            Schema(0x1BC2D, j_s, 8, marks=[line_middle]),
            Schema(0x1BC2E, s_s, 8, marks=[line_middle]),
            Schema(0x1BC2F, j_s, 8, marks=[dot_1]),
            Schema(0x1BC30, j_n, 6, shading_allowed=False),
            Schema(0x1BC31, j_n_s, 2, shading_allowed=False),
            Schema(0x1BC32, s_t, 8),
            Schema(0x1BC33, s_t, 12),
            Schema(0x1BC34, s_p, 8),
            Schema(0x1BC35, s_p, 12),
            Schema(0x1BC36, t_s, 8),
            Schema(0x1BC37, t_s, 12),
            Schema(0x1BC38, w, 8),
            Schema(0x1BC39, w, 8, marks=[dot_1]),
            Schema(0x1BC3A, w, 12),
            Schema(0x1BC3B, s_n, 8),
            Schema(0x1BC3C, s_n, 12),
            Schema(0x1BC3D, k_r_s, 8, shading_allowed=False),
            Schema(0x1BC3E, k_r_s, 12, shading_allowed=False),
            Schema(0x1BC3F, s_k, 8),
            Schema(0x1BC40, s_k, 12),
            Schema(0x1BC41, o, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC42, o_reverse, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC43, o, 2.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC44, o, 3, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC45, o, 3.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC46, ie, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC47, ee, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC48, ie, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC49, short_i, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4A, ui, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4B, ee, 2, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC4C, ee, 2, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC4D, ee, 2, Type.ORIENTING, marks=[dot_2], shading_allowed=False),
            Schema(0x1BC4E, ee, 2, Type.ORIENTING, marks=[line_2], shading_allowed=False),
            Schema(0x1BC4F, k, 0.5, Type.ORIENTING),
            Schema(0x1BC50, ye, 1, shading_allowed=False),
            Schema(0x1BC51, s_t, 6, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC52, s_p, 6, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC53, s_t, 6, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC54, u_n, 3, shading_allowed=False),
            Schema(0x1BC55, long_u, 2, shading_allowed=False),
            Schema(0x1BC56, romanian_u, 3, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC57, uh, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC58, uh, 2, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC59, uh, 2, Type.ORIENTING, marks=[dot_2], shading_allowed=False),
            Schema(0x1BC5A, o, 3, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC5B, ou, 3, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC5C, wa, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5D, wo, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5E, wi, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC5F, wei, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC60, wo, 1, Type.ORIENTING, marks=[dot_1], shading_allowed=False),
            Schema(0x1BC61, s_t, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC62, s_n, 3.2, Type.ORIENTING),
            Schema(0x1BC63, t_s, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC64, s_k, 3.2, Type.ORIENTING),
            Schema(0x1BC65, s_p, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC66, w, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC67, s_t, 3.2, can_lead_orienting_sequence=True, marks=[dot_1]),
            Schema(0x1BC68, s_t, 3.2, can_lead_orienting_sequence=True, marks=[dot_2]),
            Schema(0x1BC69, s_k, 3.2, can_lead_orienting_sequence=True, marks=[dot_2]),
            Schema(0x1BC6A, s_k, 3.2, can_lead_orienting_sequence=True),
            Schema(0x1BC70, left_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC71, mid_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC72, right_horizontal_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC73, low_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC74, mid_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC75, high_vertical_secant, 2, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC76, rtl_secant, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC77, ltr_secant, 1, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC78, tangent, 0.5, Type.ORIENTING, shading_allowed=False),
            Schema(0x1BC79, n_reverse, 6, shading_allowed=False),
            Schema(0x1BC7A, e_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True, shading_allowed=False),
            Schema(0x1BC7B, i_hook, 2, Type.ORIENTING, can_lead_orienting_sequence=True),
            Schema(0x1BC7C, tangent_hook, 2, Type.ORIENTING, shading_allowed=False, can_lead_orienting_sequence=True),
            Schema(0x1BC80, high_acute, 1),
            Schema(0x1BC81, high_tight_acute, 1),
            Schema(0x1BC82, high_grave, 1),
            Schema(0x1BC83, high_long_grave, 1),
            Schema(0x1BC84, high_dot, 1),
            Schema(0x1BC85, high_circle, 1),
            Schema(0x1BC86, high_line, 1),
            Schema(0x1BC87, high_wave, 1),
            Schema(0x1BC88, high_vertical, 1),
            Schema(0x1BC90, low_acute, 1),
            Schema(0x1BC91, low_tight_acute, 1),
            Schema(0x1BC92, low_grave, 1),
            Schema(0x1BC93, low_long_grave, 1),
            Schema(0x1BC94, low_dot, 1),
            Schema(0x1BC95, low_circle, 1),
            Schema(0x1BC96, low_line, 1),
            Schema(0x1BC97, low_wave, 1),
            Schema(0x1BC98, low_vertical, 1),
            Schema(0x1BC99, low_arrow, 1),
            Schema(0x1BC9C, likalisti, 1, Type.NON_JOINING),
            Schema(0x1BC9D, dtls, 1, Type.NON_JOINING),
            Schema(0x1BC9E, line, 0.45, Type.ORIENTING, anchor=anchors.MIDDLE),
            Schema(0x1BC9F, chinook_period, 1, Type.NON_JOINING),
            Schema(0x1BCA0, overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA1, continuing_overlap, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA2, down_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
            Schema(0x1BCA3, up_step, 1, Type.NON_JOINING, ignorability=Ignorability.OVERRIDDEN_NO),
        ]
        if noto:
            self._schemas = [
                s for s in self._schemas
                if s.cmap is None or not (
                    s.cmap == 0x034F
                    or unicodedata.category(chr(s.cmap)) == 'Co'
                    or unicodedata.category(chr(s.cmap)) == 'Zs' and s.joining_type != Type.NON_JOINING
                )
            ]

    def _dont_ignore_default_ignorables(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup('abvm', {'DFLT', 'dupl'}, 'dflt')
        lookup_2 = Lookup('abvm', {'DFLT', 'dupl'}, 'dflt')
        for schema in schemas:
            if schema.ignorability == Ignorability.OVERRIDDEN_NO:
                add_rule(lookup_1, Rule([schema], [schema, schema]))
                add_rule(lookup_2, Rule([schema, schema], [schema]))
        return [lookup_1, lookup_2]

    def _reversed_circle_kludge(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('rlig', {'DFLT', 'dupl'}, 'dflt')
        cgj = next(s for s in schemas if s.cmap == 0x034F)
        for schema in new_schemas:
            if schema.cmap in [0x1BC44, 0x1BC5A, 0x1BC5B, 0x1BC5C, 0x1BC5D, 0x1BC5E, 0x1BC5F, 0x1BC60]:
                add_rule(lookup, Rule(
                    [schema, cgj, cgj, cgj],
                    [schema.clone(cmap=None, cps=[*schema.cps, 0x034F, 0x034F, 0x034F], path=schema.path.as_reversed())],
                ))
        return [lookup]

    def _validate_shading(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            'dupl',
            'dflt',
            mark_filtering_set='independent_mark',
            reversed=True,
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

    def _validate_double_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            'dupl',
            'dflt',
            mark_filtering_set='double_mark',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        double_mark = next(s for s in original_schemas if s.cps == [0x1BC9E])
        classes['double_mark'].append(double_mark)
        new_maximums = set()
        for schema in new_schemas:
            maximum = schema.max_double_marks()
            new_maximums.add(maximum)
            classes[str(maximum)].append(schema)
        for maximum in sorted(new_maximums, reverse=True):
            for i in range(0, maximum):
                add_rule(lookup, Rule([str(maximum)] + [double_mark] * i, [double_mark], [], lookups=[None]))
        guideline = Schema(None, Line(0, dots=7), 1.5, Type.NON_JOINING)
        add_rule(lookup, Rule([double_mark], [guideline, double_mark]))
        return [lookup]

    def _decompose(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('abvs', 'dupl', 'dflt')
        for schema in schemas:
            if schema.marks and schema in new_schemas:
                add_rule(lookup, Rule([schema], [schema.without_marks] + schema.marks))
        return [lookup]

    def _expand_secants(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'abvs',
            'dupl',
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
        named_lookups['non_initial_secant'] = Lookup(None, None, None)
        for schema in new_schemas:
            if isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.JOINER:
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
            elif schema.glyph_class == GlyphClass.JOINER and schema.path.can_take_secant():
                classes['base'].append(schema)
        add_rule(lookup, Rule('base', 'secant', [], lookups=['non_initial_secant']))
        initial_secant_marker = Schema(None, InitialSecantMarker(), 0, side_bearing=0)
        add_rule(lookup, Rule(
            ['secant'],
            ['secant', continuing_overlap, initial_secant_marker],
        ))
        return [lookup]

    def _validate_overlap_controls(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='overlap',
        )
        new_classes = {}
        global_max_tree_width = 0
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                return [lookup]
            if isinstance(schema.path, InvalidOverlap):
                classes['overlap'].append(schema)
                if schema.path.continuing:
                    continuing_overlap = schema
                else:
                    letter_overlap = schema
            elif not schema.anchor:
                if max_tree_width := schema.path.max_tree_width(schema.size):
                    if max_tree_width > global_max_tree_width:
                        global_max_tree_width = max_tree_width
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
        add_rule(lookup, Rule('valid', 'invalid', [], 'valid'))
        for i in range(global_max_tree_width - 2):
            add_rule(lookup, Rule([], [letter_overlap], [*[letter_overlap] * i, continuing_overlap, 'invalid'], lookups=[None]))
        if global_max_tree_width > 1:
            add_rule(lookup, Rule([], [continuing_overlap], 'invalid', lookups=[None]))
        for max_tree_width, new_class in new_classes.items():
            add_rule(lookup, Rule([new_class], 'invalid', ['invalid'] * max_tree_width, lookups=[None]))
        add_rule(lookup, Rule(['base'], [letter_overlap], [], [valid_letter_overlap]))
        classes['base'].append(valid_letter_overlap)
        add_rule(lookup, Rule(['base'], [continuing_overlap], [], [valid_continuing_overlap]))
        classes['base'].append(valid_continuing_overlap)
        classes[CHILD_EDGE_CLASSES[0]].append(valid_letter_overlap)
        classes[INTER_EDGE_CLASSES[0][0]].append(valid_letter_overlap)
        classes[CONTINUING_OVERLAP_CLASS].append(valid_continuing_overlap)
        classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(valid_continuing_overlap)
        return [lookup]

    def _add_parent_edges(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('blwm', {'DFLT', 'dupl'}, 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        root_parent_edge = Schema(None, ParentEdge([]), 0, Type.NON_JOINING, side_bearing=0)
        root_only_parent_edge = Schema(None, RootOnlyParentEdge(), 0, Type.NON_JOINING, side_bearing=0)
        for child_index in range(MAX_TREE_WIDTH):
            if root_parent_edge not in classes[CHILD_EDGE_CLASSES[child_index]]:
                classes[CHILD_EDGE_CLASSES[child_index]].append(root_parent_edge)
            for layer_index in range(MAX_TREE_DEPTH):
                if root_parent_edge not in classes[INTER_EDGE_CLASSES[layer_index][child_index]]:
                    classes[INTER_EDGE_CLASSES[layer_index][child_index]].append(root_parent_edge)
        for schema in new_schemas:
            if schema.glyph_class == GlyphClass.JOINER:
                classes['root' if schema.path.can_be_child(schema.size) else 'root_only'].append(schema)
        add_rule(lookup, Rule(['root'], [root_parent_edge, 'root']))
        add_rule(lookup, Rule(['root_only'], [root_only_parent_edge, root_parent_edge, 'root_only']))
        return [lookup]

    def _invalidate_overlap_controls(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
            reversed=True,
        )
        for schema in new_schemas:
            if isinstance(schema.path, ParentEdge):
                node = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, RootOnlyParentEdge):
                root_only_parent_edge = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, ChildEdge):
                valid_letter_overlap = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                valid_continuing_overlap = schema
                classes['all'].append(schema)
            elif isinstance(schema.path, InvalidOverlap):
                if schema.path.continuing:
                    invalid_continuing_overlap = schema
                else:
                    invalid_letter_overlap = schema
        classes['valid'].append(valid_letter_overlap)
        classes['valid'].append(valid_continuing_overlap)
        classes['invalid'].append(invalid_letter_overlap)
        classes['invalid'].append(invalid_continuing_overlap)
        add_rule(lookup, Rule([], 'valid', 'invalid', 'invalid'))
        for older_sibling_count in range(MAX_TREE_WIDTH - 1, -1, -1):
            # A continuing overlap not at the top level must be licensed by an
            # ancestral continuing overlap.
            # TODO: Optimization: All but the youngest child can use
            # `valid_letter_overlap` instead of `'valid'`.
            for subtrees in make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count]):
                for older_sibling_count_of_continuing_overlap in range(MAX_TREE_WIDTH):
                    add_rule(lookup, Rule(
                        [valid_letter_overlap] * older_sibling_count,
                        [valid_letter_overlap],
                        [*subtrees, node, *[valid_letter_overlap] * older_sibling_count_of_continuing_overlap, valid_continuing_overlap],
                        [invalid_letter_overlap]
                    ))
            # Trees have a maximum depth of `MAX_TREE_DEPTH` letters.
            # TODO: Optimization: Why use a nested `for` loop? Can a combination of
            # `top_width` and `prefix_depth` work?
            for subtrees in make_trees(node, valid_letter_overlap, MAX_TREE_DEPTH, top_widths=range(older_sibling_count + 1)):
                for deep_subtree in make_trees(node, 'valid', MAX_TREE_DEPTH, prefix_depth=MAX_TREE_DEPTH):
                    add_rule(lookup, Rule(
                        [valid_letter_overlap] * older_sibling_count,
                        'valid',
                        [*subtrees, *deep_subtree],
                        'invalid',
                    ))
            # Anything valid needs to be explicitly kept valid, since there might
            # not be enough context to tell that an invalid overlap is invalid.
            # TODO: Optimization: The last subtree can just be one node instead of
            # the full subtree.
            for subtrees in make_trees(node, 'valid', MAX_TREE_DEPTH, top_widths=[older_sibling_count + 1]):
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

    def _add_secant_guidelines(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('abvs', 'dupl', 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        invalid_continuing_overlap = next(s for s in schemas if isinstance(s.path, InvalidOverlap) and s.path.continuing)
        valid_continuing_overlap = next(s for s in schemas if isinstance(s.path, ContinuingOverlap))
        dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
        initial_secant_marker = next(s for s in schemas if isinstance(s.path, InitialSecantMarker))
        named_lookups['prepend_zwnj'] = Lookup(None, None, None)
        for schema in new_schemas:
            if (isinstance(schema.path, Line)
                and schema.path.secant
                and schema.glyph_class == GlyphClass.JOINER
                and schema in original_schemas
            ):
                classes['secant'].append(schema)
                zwnj = Schema(None, Space(0, margins=True), 0, Type.NON_JOINING, side_bearing=0)
                guideline_angle = 270 if 45 <= (schema.path.angle + 90) % 180 < 135 else 0
                guideline = Schema(None, Line(guideline_angle, dots=7), 1.5)
                add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [initial_secant_marker, dtls], [dtls, valid_continuing_overlap, guideline]))
                add_rule(lookup, Rule([schema], [invalid_continuing_overlap], [], [valid_continuing_overlap, guideline]))
        add_rule(named_lookups['prepend_zwnj'], Rule('secant', [zwnj, 'secant']))
        add_rule(lookup, Rule([], 'secant', [], lookups=['prepend_zwnj']))
        return [lookup]

    def _add_placeholders_for_missing_children(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='valid_final_overlap',
        )
        lookup_2 = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='valid_final_overlap',
        )
        if len(original_schemas) != len(schemas):
            return [lookup_1, lookup_2]
        base_classes = {}
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                valid_letter_overlap = schema
                classes['valid_final_overlap'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                valid_continuing_overlap = schema
                classes['valid_final_overlap'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and (max_tree_width := schema.path.max_tree_width(schema.size)) > 1
            ):
                new_class = f'base_{max_tree_width}'
                classes[new_class].append(schema)
                base_classes[max_tree_width] = new_class
        root_parent_edge = next(s for s in schemas if isinstance(s.path, ParentEdge))
        placeholder = Schema(None, Space(0), 0, Type.JOINING, side_bearing=0, child=True)
        for max_tree_width, base_class in base_classes.items():
            add_rule(lookup_1, Rule(
                [base_class],
                [valid_letter_overlap],
                [valid_letter_overlap] * (max_tree_width - 2) + ['valid_final_overlap'],
                lookups=[None],
            ))
            add_rule(lookup_2, Rule(
                [],
                [base_class],
                [valid_letter_overlap] * (max_tree_width - 1) + ['valid_final_overlap'],
                lookups=[None],
            ))
            for sibling_count in range(max_tree_width - 1, 0, -1):
                input_1 = 'valid_final_overlap' if sibling_count > 1 else valid_letter_overlap
                add_rule(lookup_1, Rule(
                    [base_class] + [valid_letter_overlap] * (sibling_count - 1),
                    [input_1],
                    [],
                    [input_1] + [root_parent_edge, placeholder] * sibling_count,
                ))
                add_rule(lookup_2, Rule(
                    [],
                    [base_class],
                    [valid_letter_overlap] * (sibling_count - 1) + [input_1],
                    [base_class] + [valid_letter_overlap] * sibling_count,
                ))
        return [lookup_1, lookup_2]

    def _categorize_edges(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'blwm',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        old_groups = [s.path.group() for s in classes['all']]
        child_edges = {}
        parent_edges = {}
        def get_child_edge(lineage):
            lineage = tuple(lineage)
            child_edge = child_edges.get(lineage)
            if child_edge is None:
                child_edge = default_child_edge.clone(cmap=None, path=default_child_edge.path.clone(lineage=lineage))
                child_edges[lineage] = child_edge
            return child_edge
        def get_parent_edge(lineage):
            lineage = tuple(lineage)
            parent_edge = parent_edges.get(lineage)
            if parent_edge is None:
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
            if isinstance(schema.path, ChildEdge):
                classes['all'].append(schema)
            elif isinstance(schema.path, ParentEdge):
                classes['all'].append(schema)
        for edge in new_schemas:
            if edge.path.group() not in old_groups:
                if isinstance(edge.path, ChildEdge):
                    lineage = list(edge.path.lineage)
                    lineage[-1] = (lineage[-1][0] + 1, 0)
                    if lineage[-1][0] <= MAX_TREE_WIDTH:
                        new_child_edge = get_child_edge(lineage)
                        classes[CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                        classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                        add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                    lineage = list(edge.path.lineage)
                    lineage[-1] = (1, lineage[-1][0])
                    new_parent_edge = get_parent_edge(lineage)
                    classes[PARENT_EDGE_CLASS].append(new_parent_edge)
                    classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                    add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
                elif isinstance(edge.path, ParentEdge) and edge.path.lineage:
                    lineage = list(edge.path.lineage)
                    if len(lineage) < MAX_TREE_DEPTH:
                        lineage.append((1, lineage[-1][0]))
                        new_child_edge = get_child_edge(lineage)
                        classes[CHILD_EDGE_CLASSES[lineage[-1][0] - 1]].append(new_child_edge)
                        classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_child_edge)
                        add_rule(lookup, Rule([edge], [default_child_edge], [], [new_child_edge]))
                    lineage = list(edge.path.lineage)
                    while lineage and lineage[-1][0] == lineage[-1][1]:
                        lineage.pop()
                    if lineage:
                        lineage[-1] = (lineage[-1][0] + 1, lineage[-1][1])
                        if lineage[-1][0] <= MAX_TREE_WIDTH:
                            new_parent_edge = get_parent_edge(lineage)
                            classes[PARENT_EDGE_CLASS].append(new_parent_edge)
                            classes[INTER_EDGE_CLASSES[len(lineage) - 1][lineage[-1][0] - 1]].append(new_parent_edge)
                            add_rule(lookup, Rule([edge], [default_parent_edge], [], [new_parent_edge]))
        return [lookup]

    def _promote_final_letter_overlap_to_continuing_overlap(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('rclt', {'DFLT', 'dupl'}, 'dflt')
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if isinstance(schema.path, ChildEdge):
                classes['overlap'].append(schema)
                if all(x[0] == x[1] for x in schema.path.lineage[:-1]):
                    classes['final_letter_overlap'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                continuing_overlap = schema
                classes['overlap'].append(schema)
            elif isinstance(schema.path, ParentEdge) and not schema.path.lineage:
                root_parent_edge = schema
                classes['secant_or_root_parent_edge'].append(schema)
            elif isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.MARK:
                classes['secant_or_root_parent_edge'].append(schema)
        add_rule(lookup, Rule([], 'final_letter_overlap', 'overlap', lookups=[None]))
        named_lookups['promote'] = Lookup(None, None, None)
        add_rule(named_lookups['promote'], Rule('final_letter_overlap', [continuing_overlap]))
        for overlap in classes['final_letter_overlap']:
            named_lookups[f'promote_{overlap.path}_and_parent'] = Lookup(
                None,
                None,
                None,
                flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                mark_filtering_set=str(overlap.path),
            )
            classes[str(overlap.path)].append(overlap)
            for parent_edge in new_schemas:
                if (isinstance(parent_edge.path, ParentEdge)
                    and parent_edge.path.lineage
                    and overlap.path.lineage[:-1] == parent_edge.path.lineage[:-1]
                    and overlap.path.lineage[-1][0] == parent_edge.path.lineage[-1][0] == parent_edge.path.lineage[-1][1]
                ):
                    classes[str(overlap.path)].append(parent_edge)
                    classes[f'parent_for_{overlap.path}'].append(parent_edge)
            add_rule(named_lookups['promote'], Rule(f'parent_for_{overlap.path}', [root_parent_edge]))
            add_rule(named_lookups[f'promote_{overlap.path}_and_parent'], Rule(
                [],
                [overlap, f'parent_for_{overlap.path}'],
                [],
                lookups=['promote', 'promote'],
            ))
            named_lookups[f'check_and_promote_{overlap.path}'] = Lookup(
                None,
                None,
                None,
                flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                mark_filtering_set='secant_or_root_parent_edge',
            )
            add_rule(named_lookups[f'check_and_promote_{overlap.path}'], Rule([], [overlap], 'secant_or_root_parent_edge', lookups=[None]))
            add_rule(named_lookups[f'check_and_promote_{overlap.path}'], Rule([], [overlap], [], lookups=[f'promote_{overlap.path}_and_parent']))
            add_rule(lookup, Rule([], [overlap], [], lookups=[f'check_and_promote_{overlap.path}']), track_possible_outputs=False)
        return [lookup]

    def _reposition_chinook_jargon_overlap_points(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        # TODO: This should be a general thing, not limited to specific Chinook
        # Jargon abbreviations and a few similar patterns.
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
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
                if schema.path.max_tree_width(schema.size) == 0:
                    continue
                if (isinstance(schema.path, Line)
                    and (schema.size == 1 or schema.cps == [0x1BC07])
                    and not schema.path.secant
                    and not schema.path.dots
                ):
                    angle = schema.path.angle
                    max_tree_width = schema.path.max_tree_width(schema.size)
                    line_class = f'line_{angle}_{max_tree_width}'
                    classes['line'].append(schema)
                    classes[line_class].append(schema)
                    line_classes[line_class] = (angle, max_tree_width)
                elif (isinstance(schema.path, Curve)
                    and schema.cps in [[0x1BC1B], [0x1BC1C]]
                    and schema.size == 6
                    and schema.joining_type == Type.JOINING
                    and (schema.path.angle_in, schema.path.angle_out) in [(90, 270), (270, 90)]
                ):
                    classes['curve'].append(schema)
        if len(original_schemas) == len(schemas):
            for width in range(1, MAX_TREE_WIDTH + 1):
                add_rule(lookup, Rule(['line', *['letter_overlap'] * (width - 1), 'overlap'], 'curve', 'overlap', 'curve'))
        for curve in classes['curve']:
            if curve in new_schemas:
                for line_class, (angle, _) in line_classes.items():
                    for width in range(1, curve.path.max_tree_width(curve.size) + 1):
                        add_rule(lookup, Rule(
                            [],
                            [curve],
                            [*['overlap'] * width, line_class],
                            [curve.clone(cmap=None, path=curve.path.clone(overlap_angle=angle))],
                        ))
        for curve_child in classes['curve']:
            if curve_child in new_schemas:
                for line_class, (angle, max_tree_width) in line_classes.items():
                    for width in range(1, max_tree_width + 1):
                        add_rule(lookup, Rule(
                            [line_class, *['letter_overlap'] * (width - 1), 'overlap'],
                            [curve_child],
                            [],
                            [curve_child.clone(cmap=None, path=curve_child.path.clone(overlap_angle=angle))],
                        ))
        return [lookup]

    def _make_mark_variants_of_children(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('blwm', {'DFLT', 'dupl'}, 'dflt')
        children_to_be = []
        old_child_count = len(classes['child'])
        for schema in new_schemas:
            if isinstance(schema.path, ParentEdge) and schema.path.lineage:
                classes['all'].append(schema)
            elif schema.glyph_class == GlyphClass.JOINER and schema.path.can_be_child(schema.size):
                classes['child_to_be'].append(schema)
        for i, child_to_be in enumerate(classes['child_to_be']):
            if i < old_child_count:
                continue
            child = child_to_be.clone(cmap=None, child=True)
            classes['child'].append(child)
            classes[PARENT_EDGE_CLASS].append(child)
            for child_index in range(MAX_TREE_WIDTH):
                classes[CHILD_EDGE_CLASSES[child_index]].append(child)
        add_rule(lookup, Rule('all', 'child_to_be', [], 'child'))
        return [lookup]

    def _interrupt_overlong_primary_curve_sequences(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        dotted_circle = next(s for s in schemas if s.cmap == 0x25CC)
        deltas_by_size = collections.defaultdict(OrderedSet)
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
        def find_overlong_sequences(deltas, overlong_sequences, sequence):
            delta_so_far = sum(sequence)
            for delta in deltas:
                new_sequence = [*sequence, delta]
                if abs(delta_so_far + delta) >= 360:
                    overlong_sequences.append(new_sequence)
                else:
                    find_overlong_sequences(deltas, overlong_sequences, new_sequence)
        overlong_class_sequences = []
        for size, deltas in deltas_by_size.items():
            overlong_sequences = []
            find_overlong_sequences(deltas, overlong_sequences, [])
            overlong_class_sequences.extend(
                [f'{size}_{d}' for d in s]
                    for s in overlong_sequences
                    if any(d in new_deltas_by_size[size] for d in s)
            )
        for overlong_class_sequence in overlong_class_sequences:
            add_rule(lookup, Rule(
                overlong_class_sequence[:-1],
                overlong_class_sequence[-1],
                [],
                [dotted_circle, overlong_class_sequence[-1]],
            ))
            secondary_class_name_0 = f'secondary_{overlong_class_sequence[0]}'
            secondary_class_name_n1 = f'secondary_{overlong_class_sequence[-1]}'
            if secondary_class_name_0 in classes:
                add_rule(lookup, Rule(
                    ['c', secondary_class_name_0, *overlong_class_sequence[1:-1]],
                    overlong_class_sequence[-1],
                    [],
                    [dotted_circle, overlong_class_sequence[-1]],
                ))
            if secondary_class_name_n1 in classes:
                add_rule(lookup, Rule(
                    ['c', *overlong_class_sequence[:-1]],
                    secondary_class_name_n1,
                    [],
                    lookups=[None],
                ))
                add_rule(lookup, Rule(
                    overlong_class_sequence[:-1],
                    secondary_class_name_n1,
                    'c',
                    [dotted_circle, secondary_class_name_n1],
                ))
            if secondary_class_name_0 in classes:
                add_rule(lookup, Rule(
                    [secondary_class_name_0, *overlong_class_sequence[1:-1]],
                    overlong_class_sequence[-1],
                    'c',
                    lookups=[None],
                ))
                add_rule(lookup, Rule(
                    [secondary_class_name_0, *overlong_class_sequence[1:-1]],
                    overlong_class_sequence[-1],
                    [],
                    [dotted_circle, overlong_class_sequence[-1]],
                ))
        return [lookup]

    def _reposition_stenographic_period(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
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

    def _disjoin_equals_sign(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        equals_sign = next(s for s in schemas if s.cmap == 0x003D)
        continuing_overlap = next(s for s in schemas if isinstance(s.path, ContinuingOverlap))
        root_parent_edge = next(s for s in schemas if isinstance(s.path, ParentEdge) and not s.path.lineage)
        zwnj = Schema(None, Space(0, margins=True), 0, Type.NON_JOINING, side_bearing=0)
        classes['all'].append(continuing_overlap)
        classes['all'].append(root_parent_edge)
        add_rule(lookup, Rule([equals_sign], [zwnj, equals_sign]))
        add_rule(lookup, Rule([equals_sign, continuing_overlap], [root_parent_edge], [], lookups=[None]))
        add_rule(lookup, Rule([equals_sign], [root_parent_edge], [], [zwnj, root_parent_edge]))
        return [lookup]

    def _join_with_next_step(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
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
                    assert False, f'Unsupported step angle: {schema.path.angle}'
            if isinstance(schema.path, Space) and schema.hub_priority == 0:
                if schema.path.angle == 90:
                    classes['c_up'].append(schema)
                elif schema.path.angle == 270:
                    classes['c_down'].append(schema)
                else:
                    assert False, f'Unsupported step angle: {schema.path.angle}'
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

    def _separate_subantiparallel_lines(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        lines_by_angle = collections.defaultdict(list)
        for schema in new_schemas:
            if schema.glyph_class != GlyphClass.JOINER:
                continue
            if isinstance(schema.path, Line):
                if (schema.path.dots is None
                    and schema.path.secant is None
                    and schema.path.original_angle is None
                ):
                    lines_by_angle[schema.path.angle].append(schema)
            elif (isinstance(schema.path, Circle) and schema.is_primary
                or isinstance(schema.path, (RomanianU, Ou, Wa, Wi))
            ):
                classes['vowel'].append(schema)
        closeness_threshold = 20
        def axis_alignment(x):
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
                        classes[f'o_{a1}_{a2}'].append(line_1.clone(
                            cmap=None,
                            path=line_1.path.clone(
                                angle=(a2 + 180 + 50 * (-1 if (a2 + 180) % 360 > a1 else 1)) % 360,
                                original_angle=line_1.path.angle,
                            ),
                        ))
                    add_rule(lookup, Rule([], f'i_{a1}_{a2}', f'c_{a1}_{a2}', f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule(f'c_{a1}_{a2}', f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule([], f'i_{a1}_{a2}', ['vowel', f'c_{a1}_{a2}'], f'o_{a1}_{a2}'))
                    add_rule(lookup, Rule([f'c_{a1}_{a2}', 'vowel'], f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
                    # TODO: Once `Line.context_in` and `Line_context_out` report the true angle, add
                    # the following rule.
                    #add_rule(lookup, Rule(f'o_{a1}_{a2}', f'i_{a1}_{a2}', [], f'o_{a1}_{a2}'))
        return [lookup]

    def _prepare_for_secondary_diphthong_ligature(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        for schema in new_schemas:
            if isinstance(schema.path, Ou) or not schema.can_become_part_of_diphthong:
                continue
            if isinstance(schema.path, Curve):
                if schema.is_primary:
                    classes['primary_semicircle'].append(schema)
            elif schema.path.reversed:
                classes['reversed_circle'].append(schema)
                classes['pinned_circle'].append(schema.clone(cmap=None, path=schema.path.clone(pinned=True)))
        add_rule(lookup, Rule([], 'reversed_circle', 'primary_semicircle', 'pinned_circle'))
        return [lookup]

    def _join_with_previous(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_1 = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        lookup_2 = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [lookup_1, lookup_2]
        contexts_in = OrderedSet()
        @functools.cache
        def get_context_marker(context):
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
                    context_in = get_context_marker(context_in)
                    classes['all'].append(context_in)
                    classes['i2'].append(schema)
                    classes['o2'].append(context_in)
                    contexts_in.add(context_in)
        classes['all'].extend(classes[CONTINUING_OVERLAP_CLASS])
        add_rule(lookup_1, Rule('i2', ['i2', 'o2']))
        for j, context_in in enumerate(contexts_in):
            for i, target_schema in enumerate(classes['i']):
                classes[f'o_{j}'].append(target_schema.contextualize(context_in.path.context, target_schema.context_out))
            add_rule(lookup_2, Rule([context_in], 'i', [], f'o_{j}'))
        return [lookup_1, lookup_2]

    def _unignore_last_orienting_glyph_in_initial_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        if 'check_previous' in named_lookups:
            return [lookup]
        for schema in new_schemas:
            if schema.ignored_for_topography:
                classes['i'].append(schema)
                classes['o'].append(schema.clone(ignored_for_topography=False))
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
        named_lookups['check_previous'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        add_rule(named_lookups['check_previous'], Rule(['c', 'first'], 'i', [], lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule('c', 'i', [], lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule([], 'i', 'fixed_form', lookups=[None]))
        add_rule(named_lookups['check_previous'], Rule('i', 'o'))
        add_rule(lookup, Rule([], 'i', 'c', lookups=['check_previous']))
        return [lookup]

    def _ignore_first_orienting_glyph_in_initial_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
            reversed=True,
        )
        for schema in new_schemas:
            if (schema.glyph_class != GlyphClass.JOINER
                or schema.pseudo_cursive
                or isinstance(schema.path, Line) and schema.path.secant
            ):
                continue
            classes['joiner'].append(schema)
            if isinstance(schema.path, Ou):
                classes['c'].append(schema)
            if (schema.can_lead_orienting_sequence
                and schema.can_be_ignored_for_topography()
            ):
                classes['c'].append(schema)
                if schema.joining_type == Type.ORIENTING and not isinstance(schema.path, Ou):
                    classes['i'].append(schema)
                    angle_out = schema.path.angle_out - schema.path.angle_in
                    path = schema.path.clone(
                        angle_in=0,
                        angle_out=(angle_out if schema.path.clockwise else -angle_out) % 360,
                        clockwise=True,
                        **({'role': CircleRole.DEPENDENT} if isinstance(schema.path, Circle) else {})
                    )
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

    def _tag_main_glyph_in_orienting_sequence(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
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
                and (isinstance(schema.path, (Circle, Ou))
                    and schema.path.role == CircleRole.INDEPENDENT
                )
            ):
                classes['i'].append(schema)
                classes['o'].append(schema.clone(cmap=None, path=schema.path.clone(role=CircleRole.LEADER)))
        add_rule(lookup, Rule('dependent', 'i', [], 'o'))
        add_rule(lookup, Rule([], 'i', 'dependent', 'o'))
        return [lookup]

    def _join_with_next(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        pre_lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set=CONTINUING_OVERLAP_CLASS,
        )
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set=CONTINUING_OVERLAP_CLASS,
            reversed=True,
        )
        post_lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='continuing_overlap_after_secant',
            reversed=True,
        )
        contexts_out = OrderedSet()
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
            continuing_overlap = next(iter(classes[CONTINUING_OVERLAP_CLASS]))
            continuing_overlap_after_secant = Schema(None, ContinuingOverlapS(), 0)
            classes['continuing_overlap_after_secant'].append(continuing_overlap_after_secant)
            add_rule(pre_lookup, Rule('secant_i', [continuing_overlap], [], [continuing_overlap_after_secant]))
        for schema in new_schemas:
            if (schema.glyph_class == GlyphClass.JOINER
                and (old_input_count == 0 or not isinstance(schema.path, (Curve, Circle, Complex)))
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

    def _join_circle_with_adjacent_nonorienting_glyph(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ignored_for_topography',
        )
        if len(original_schemas) != len(schemas):
            return [lookup]
        contexts_out = OrderedSet()
        for schema in new_schemas:
            if schema.ignored_for_topography:
                if isinstance(schema.path, Circle):
                    classes['i'].append(schema)
                classes['ignored_for_topography'].append(schema)
            elif (schema.glyph_class == GlyphClass.JOINER
                and (not schema.can_lead_orienting_sequence
                    or isinstance(schema.path, Line) and not schema.path.secant
                )
            ):
                if (context_out := schema.path.context_in()) != NO_CONTEXT:
                    context_out = Context(context_out.angle)
                    contexts_out.add(context_out)
                    classes[f'c_{context_out}'].append(schema)
        for context_out in contexts_out:
            output_class_name = f'o_{context_out}'
            for circle in classes['i']:
                classes[output_class_name].append(circle.clone(cmap=None, context_out=context_out))
            add_rule(lookup, Rule([], 'i', f'c_{context_out}', output_class_name))
        return [lookup]

    def _ligate_diphthongs(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ignored_for_topography',
            reversed=True,
        )
        diphthong_1_classes = OrderedSet()
        diphthong_2_classes = OrderedSet()
        for schema in new_schemas:
            if not schema.can_become_part_of_diphthong:
                continue
            is_circle_letter = isinstance(schema.path, Circle) or schema.path.reversed_circle
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
            if schema.ignored_for_topography:
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
            if schema.ignored_for_topography:
                classes['ignored_for_topography'].append(schema)
                classes['ignored_for_topography'].append(output_schema)
        for input_1, is_circle_1, is_ignored_1, output_1 in diphthong_1_classes.keys():
            for input_2, is_circle_2, is_ignored_2, output_2 in diphthong_2_classes.keys():
                if is_circle_1 != is_circle_2 and (is_ignored_1 or is_ignored_2):
                    add_rule(lookup, Rule(input_1, input_2, [], output_2))
                    add_rule(lookup, Rule([], input_1, output_2, output_1))
        return [lookup]

    def _thwart_what_would_flip(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
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

    def _unignore_noninitial_orienting_sequences(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        contexts_in = OrderedSet()
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
                    or schema.phase_index < self._phases.index(self._join_circle_with_adjacent_nonorienting_glyph)
                    if isinstance(schema.path, Circle)
                    else isinstance(schema.path, Ou) or schema.can_be_ignored_for_topography())
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

    def _unignore_initial_orienting_sequences(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
            reversed=True,
        )
        contexts_out = OrderedSet()
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
                    or schema.phase_index < self._phases.index(self._join_circle_with_adjacent_nonorienting_glyph)
                    if isinstance(schema.path, Circle)
                    else isinstance(schema.path, Ou) or schema.can_be_ignored_for_topography())
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

    def _join_double_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            'dupl',
            'dflt',
            mark_filtering_set='all',
        )
        for schema in new_schemas:
            if schema.cps == [0x1BC9E]:
                classes['all'].append(schema)
                for i in range(2, MAX_DOUBLE_MARKS + 1):
                    add_rule(lookup, Rule([schema] * i, [schema.clone(
                        cmap=None,
                        cps=schema.cps * i,
                        path=Complex([
                            (1, schema.path),
                            (500, Space((schema.path.angle + 180) % 360)),
                            (250, Space((schema.path.angle - 90) % 360)),
                        ] * i),
                    )]))
        return [lookup]

    def _rotate_diacritics(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        base_anchors_and_contexts = OrderedSet()
        new_base_anchors_and_contexts = set()
        for schema in original_schemas:
            if schema.anchor:
                if (schema.joining_type == Type.ORIENTING
                        and schema.base_angle is None
                        and schema in new_schemas):
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

    def _shade(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rlig',
            'dupl',
            'dflt',
            mark_filtering_set='independent_mark',
        )
        dtls = next(s for s in schemas if isinstance(s.path, ValidDTLS))
        classes['independent_mark'].append(dtls)
        if new_schemas:
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
                    classes['o'].append(schema.clone(cmap=None, cps=schema.cps + dtls.cps))
                    if schema.glyph_class == GlyphClass.MARK:
                        classes['independent_mark'].append(schema)
            add_rule(lookup, Rule(['i', dtls], 'o'))
        return [lookup]

    def _create_diagonal_fractions(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_slash = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        lookup_dnom = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        lookup_numr = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            reversed=True,
        )
        if len(original_schemas) != len(schemas):
            return [lookup_slash, lookup_dnom, lookup_numr]
        for schema in new_schemas:
            if schema.cmap in range(0x0030, 0x0039 + 1):
                classes['i'].append(schema)
                dnom = schema.clone(cmap=None, y_max=0.6 * schema.y_max)
                numr = schema.clone(cmap=None, size=0.6 * schema.size, y_min=None)
                classes['dnom'].append(dnom)
                classes['numr'].append(numr)
                classes['dnom_or_slash'].append(dnom)
                classes['numr_or_slash'].append(numr)
            elif schema.cmap == 0x2044:
                slash = schema
        valid_slash = slash.clone(cmap=None, side_bearing=-250)
        classes['dnom_or_slash'].append(valid_slash)
        classes['numr_or_slash'].append(valid_slash)
        add_rule(lookup_slash, Rule('i', [slash], 'i', [valid_slash]))
        add_rule(lookup_dnom, Rule('dnom_or_slash', 'i', [], 'dnom'))
        add_rule(lookup_dnom, Rule('dnom', [valid_slash], [], [slash]))
        add_rule(lookup_numr, Rule([], 'i', 'numr_or_slash', 'numr'))
        return [lookup_slash, lookup_dnom, lookup_numr]

    def _create_superscripts_and_subscripts(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup_sups = Lookup('sups', {'DFLT', 'dupl'}, 'dflt')
        lookup_subs = Lookup('subs', {'DFLT', 'dupl'}, 'dflt')
        for schema in new_schemas:
            if schema.cmap in range(0x0030, 0x0039 + 1):
                classes['i'].append(schema)
                classes['o_sups'].append(schema.clone(cmap=None, size=0.6 * schema.size, y_min=None, y_max=1.18 * schema.y_max))
                classes['o_subs'].append(schema.clone(cmap=None, size=0.6 * schema.size, y_min=-0.18 * schema.y_max, y_max=None))
        add_rule(lookup_sups, Rule('i', 'o_sups'))
        add_rule(lookup_subs, Rule('i', 'o_subs'))
        return [lookup_sups, lookup_subs]

    def _make_widthless_variants_of_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('rclt', {'DFLT', 'dupl'}, 'dflt')
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

    def _classify_marks_for_trees(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        for schema in schemas:
            for anchor in anchors.ALL_MARK:
                if schema.child or schema.anchor == anchor:
                    classes[f'global..{mkmk(anchor)}'].append(schema)
        return []

    def _merge_lookalikes(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
        )
        grouper = sifting.group_schemas(new_schemas)
        for group in grouper.groups():
            group.sort(key=Schema.sort_key)
            group_iter = iter(group)
            lookalike_schema = next(group_iter)
            if not lookalike_schema.might_need_width_markers:
                continue
            lookalike_schema.lookalike_group = group
            for schema in group_iter:
                add_rule(lookup, Rule([schema], [lookalike_schema]))
                schema.lookalike_group = group
        return [lookup]

    def _add_shims_for_pseudo_cursive(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        marker_lookup = Lookup(
            'abvm',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS,
        )
        space_lookup = Lookup(
            'abvm',
            {'DFLT', 'dupl'},
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
        def get_shim(width, height):
            return Schema(
                None,
                Space(width and math.degrees(math.atan(height / width)) % 360),
                math.hypot(width, height),
                side_bearing=width,
            )
        marker = get_shim(0, 0)
        def round_with_base(number, base, minimum):
            return max(minimum, base * round(number / base), key=abs)
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
            exit_classes = {}
            exit_classes_containing_pseudo_cursive_schemas = set()
            exit_classes_containing_true_cursive_schemas = set()
            entry_classes = {}
            for prefix, e_schemas, e_classes, pseudo_cursive_x_bound, height_sign, get_distance_to_edge in [
                ('exit', exit_schemas, exit_classes, pseudo_cursive_left_bound, -1, lambda bounds, x: bounds[1] - x),
                ('entry', entry_schemas, entry_classes, pseudo_cursive_right_bound, 1, lambda bounds, x: x - bounds[0]),
            ]:
                for e_schema, x, y in e_schemas:
                    bounds = e_schema.glyph.foreground.xBoundsAtY(y + pseudo_cursive_bottom_bound, y + pseudo_cursive_top_bound)
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
                    shim_height = round_with_base(shim_height, rounding_base, 0)
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

    def _shrink_wrap_enclosing_circle(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'rclt',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='i',
        )
        dist_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
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
            if schema.widthless and schema.cps == [0x20DD]:
                assert circle_schema is None
                circle_schema = schema
                classes['i'].append(circle_schema)
            elif schema.encirclable:
                x_min, y_min, x_max, y_max = schema.glyph.boundingBox()
                dx = x_max - x_min
                dy = y_max - y_min
                class_name = f'c_{dx}_{dy}'
                classes[class_name].append(schema)
                punctuation[class_name] = (dx, dy, schema.glyph.width)
        for class_name, (dx, dy, width) in punctuation.items():
            dx += 3 * self.stroke_gap + self.light_line
            dy += 3 * self.stroke_gap + self.light_line
            if dx > dy:
                dy = max(dy, dx * 0.75)
            elif dx < dy:
                dx = max(dx, dy * 0.75)
            new_circle_schema = circle_schema.clone(
                cmap=None,
                path=circle_schema.path.clone(stretch=max(dx, dy) / min(dx, dy) - 1, long=dx < dy),
                size=min(dx, dy) / 100,
            )
            add_rule(lookup, Rule(class_name, [circle_schema], [], [new_circle_schema]))
            classes['o'].append(new_circle_schema)
            side_bearing = round((dx + 2 * DEFAULT_SIDE_BEARING - width) / 2)
            add_rule(dist_lookup, Rule([], [class_name], [new_circle_schema], x_placements=[side_bearing], x_advances=[side_bearing]))
            add_rule(dist_lookup, Rule([class_name], [new_circle_schema], [], x_advances=[side_bearing]))
        return [lookup, dist_lookup]

    def _add_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookups_per_position = 6
        lookups = [
            Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
            for _ in range(lookups_per_position)
        ]
        digit_expansion_lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        carry_expansion_lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        rule_count = 0
        entry_width_markers = {}
        left_bound_markers = {}
        right_bound_markers = {}
        anchor_width_markers = {}
        path_to_markers = {
            EntryWidthDigit: entry_width_markers,
            LeftBoundDigit: left_bound_markers,
            RightBoundDigit: right_bound_markers,
            AnchorWidthDigit: anchor_width_markers,
        }
        start = Schema(None, Start(), 0)
        hubs = {-1: []}
        for hub_priority in range(0, MAX_HUB_PRIORITY + 1):
            hub = next((s for s in schemas if isinstance(s.path, Hub) and s.path.priority == hub_priority), None)
            if hub is None:
                hub = Schema(None, Hub(hub_priority), 0)
                classes[HUB_CLASS].append(hub)
                classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(hub)
            hubs[hub_priority] = [hub]
        end = Schema(None, End(), 0)
        mark_anchor_selectors = {}
        def get_mark_anchor_selector(schema):
            only_anchor_class_name = None
            for anchor_class_name, type, _, _ in schema.glyph.anchorPoints:
                if type == 'mark' and anchor_class_name in anchors.ALL_MARK:
                    assert only_anchor_class_name is None, f'{schema} has multiple anchors: {only_anchor_class_name} and {anchor_class_name}'
                    only_anchor_class_name = anchor_class_name
            index = anchors.ALL_MARK.index(only_anchor_class_name)
            if index in mark_anchor_selectors:
                return mark_anchor_selectors[index]
            return mark_anchor_selectors.setdefault(index, Schema(None, MarkAnchorSelector(index), 0))
        glyph_class_selectors = {}
        def get_glyph_class_selector(schema):
            glyph_class = schema.glyph_class
            if glyph_class in glyph_class_selectors:
                return glyph_class_selectors[glyph_class]
            return glyph_class_selectors.setdefault(glyph_class, Schema(None, GlyphClassSelector(glyph_class), 0))
        def register_width_marker(width_markers, digit_path, *args):
            if args not in width_markers:
                width_marker = Schema(None, digit_path(*args), 0)
                width_markers[args] = width_marker
            return width_markers[args]
        width_number_schemas = {}
        def get_width_number_schema(width_number):
            if width_number in width_number_schemas:
                return width_number_schemas[width_number]
            return width_number_schemas.setdefault(width_number, Schema(None, width_number, 0))
        width_number_counter = collections.Counter()
        minimum_optimizable_width_number_count = 2
        width_numbers = {}
        def get_width_number(digit_path, width):
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
        rules_to_add = []
        for schema in new_schemas:
            if schema not in original_schemas:
                continue
            if schema.glyph is None:
                if isinstance(schema.path, MarkAnchorSelector):
                    mark_anchor_selectors[schema.path.index] = schema
                elif isinstance(schema.path, GlyphClassSelector):
                    glyph_class_selectors[schema.glyph_class] = schema
                if not isinstance(schema.path, Space):
                    # Not a schema created in `add_shims_for_pseudo_cursive`
                    continue
            if schema.might_need_width_markers and (
                schema.glyph_class != GlyphClass.MARK or any(a[0] in anchors.ALL_MARK for a in schema.glyph.anchorPoints)
            ):
                entry_xs = {}
                exit_xs = {}
                if schema.glyph is None and isinstance(schema.path, Space):
                    entry_xs[anchors.CURSIVE] = 0
                    exit_xs[anchors.CURSIVE] = schema.size
                else:
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
                if schema.glyph is None:
                    x_min = x_max = 0
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
                lookup = lookups[rule_count % lookups_per_position]
                rule_count += 1
                rules_to_add.append((
                    widths,
                    (lambda widths,
                            lookup=lookup, glyph_class_selector=glyph_class_selector, mark_anchor_selector=mark_anchor_selector, schema=schema:
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
            for width in widths:
                if width_number_counter[width] >= minimum_optimizable_width_number_count:
                    final_widths.append(get_width_number_schema(width))
                else:
                    final_widths.extend(width.to_digits(functools.partial(register_width_marker, path_to_markers[width.digit_path])))
            rule_to_add(final_widths)
            rule_count -= 1
        return [
            *lookups,
            digit_expansion_lookup,
        ]

    def _add_end_markers_for_marks(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
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

    def _remove_false_end_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
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

    def _clear_entry_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        zeros = [None] * WIDTH_MARKER_PLACES
        if 'zero' not in named_lookups:
            named_lookups['zero'] = Lookup(None, None, None)
        for schema in schemas:
            if isinstance(schema.path, EntryWidthDigit):
                classes['all'].append(schema)
                classes[str(schema.path.place)].append(schema)
                if schema.path.digit == 0:
                    zeros[schema.path.place] = schema
            elif isinstance(schema.path, ContinuingOverlap):
                classes['all'].append(schema)
                continuing_overlap = schema
        for schema in new_schemas:
            if isinstance(schema.path, EntryWidthDigit) and schema.path.digit != 0:
                add_rule(named_lookups['zero'], Rule([schema], [zeros[schema.path.place]]))
        add_rule(lookup, Rule(
            [continuing_overlap],
            [*map(str, range(WIDTH_MARKER_PLACES))],
            [],
            lookups=[None] * WIDTH_MARKER_PLACES,
        ))
        add_rule(lookup, Rule(
            [],
            [*map(str, range(WIDTH_MARKER_PLACES))],
            [],
            lookups=['zero'] * WIDTH_MARKER_PLACES,
        ))
        return [lookup]

    def _sum_width_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='all',
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
        mark_anchor_selectors = {}
        def get_mark_anchor_selector(index, class_name):
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
        glyph_class_selectors = {}
        def get_glyph_class_selector(glyph_class, class_name):
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
            if isinstance(schema.path, ContinuingOverlap):
                classes['all'].append(schema)
                continuing_overlap = schema
            elif isinstance(schema.path, Carry):
                carry_schema = schema
                original_carry_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
            elif isinstance(schema.path, EntryWidthDigit):
                entry_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_entry_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'idx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, LeftBoundDigit):
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_left_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'ldx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, RightBoundDigit):
                right_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_right_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'rdx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, AnchorWidthDigit):
                anchor_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                original_anchor_digit_schemas.append(schema)
                if schema in new_schemas:
                    classes['all'].append(schema)
                    classes[f'adx_{schema.path.place}'].append(schema)
            elif isinstance(schema.path, Dummy):
                dummy = schema
            elif isinstance(schema.path, MarkAnchorSelector):
                mark_anchor_selectors[schema.path.index] = schema
            elif isinstance(schema.path, GlyphClassSelector):
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
                place = augend_schema.path.place
                augend = augend_schema.path.digit
                for (
                    continuing_overlap_is_relevant,
                    augend_skip_backtrack,
                    addend_skip_backtrack,
                    addend_letter,
                    original_addend_schemas,
                    addend_schemas,
                    addend_path,
                ) in inner_iterable:
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
                            classes[context_in_lookup_name].extend(classes[f'{augend_letter}dx_{augend_schema.path.place}'])
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
                                    named_lookups[sum_lookup_name] = Lookup(None, None, None)
                                if context_in_lookup_name not in named_lookups:
                                    classes[context_in_lookup_name].append(addend_schema)
                                    named_lookups[context_in_lookup_name] = Lookup(
                                        None,
                                        None,
                                        None,
                                        flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                                        mark_filtering_set=context_in_lookup_name,
                                    )
                                add_rule(lookup, Rule(
                                    AlwaysTrueList() if carry_in == 0 else [carry_in_schema],
                                    [addend_schema],
                                    [],
                                    lookups=[context_in_lookup_name],
                                ))
                                classes[context_in_lookup_name].extend(classes[f'idx_{augend_schema.path.place}'])
                                if addend_skip_backtrack != 0:
                                    classes[context_in_lookup_name].extend(classes[f'{addend_letter}dx_{sum_digit_schema.path.place}'])
                                context_in_lookup_context_in = []
                                if augend_letter == 'i' and addend_letter == 'a':
                                    context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.JOINER, context_in_lookup_name))
                                context_in_lookup_context_in.append(augend_schema)
                                context_in_lookup_context_in.extend([f'{augend_letter}dx_{augend_schema.path.place}'] * augend_skip_backtrack)
                                if augend_letter == 'a' and addend_letter == 'a':
                                    context_in_lookup_context_in.append(get_glyph_class_selector(GlyphClass.MARK, context_in_lookup_name))
                                    context_in_lookup_context_in.append(f'idx_{augend_schema.path.place}')
                                elif augend_skip_backtrack == 1:
                                    context_in_lookup_context_in.append(continuing_overlap)
                                elif augend_letter == 'a' and addend_letter == 'i' and augend_skip_backtrack != 0:
                                    context_in_lookup_context_in.append(get_mark_anchor_selector(
                                        len(anchors.ALL) - augend_skip_backtrack - 1,
                                        context_in_lookup_name,
                                    ))
                                context_in_lookup_context_in.extend([f'{addend_letter}dx_{sum_digit_schema.path.place}'] * addend_skip_backtrack)
                                add_rule(named_lookups[context_in_lookup_name], Rule(
                                    context_in_lookup_context_in,
                                    [addend_schema],
                                    [],
                                    lookups=[sum_lookup_name],
                                ))
                                add_rule(named_lookups[sum_lookup_name], Rule([addend_schema], outputs))
        return [lookup]

    def _calculate_bound_extrema(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        left_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='ldx',
        )
        named_lookups['ldx_copy'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='ldx',
        )
        left_digit_schemas = {}
        right_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='rdx',
        )
        named_lookups['rdx_copy'] = Lookup(
            None,
            None,
            None,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='rdx',
        )
        right_digit_schemas = {}
        for schema in schemas:
            if isinstance(schema.path, LeftBoundDigit):
                left_digit_schemas[schema.path.place * WIDTH_MARKER_RADIX + schema.path.digit] = schema
                if schema in new_schemas:
                    classes['ldx'].append(schema)
            elif isinstance(schema.path, RightBoundDigit):
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
                        schema_j = digit_schemas.get(place * WIDTH_MARKER_RADIX + j)
                        if schema_j is None:
                            continue
                        add_rule(lookup, Rule(
                            [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - schema_i.path.place - 1)],
                            [*[marker_class] * schema_j.path.place, schema_j],
                            [],
                            lookups=[None if compare(i_signed, j_signed) else copy_lookup_name] * (schema_j.path.place + 1)))
                        add_rule(named_lookups[copy_lookup_name], Rule(
                            [schema_i, *[marker_class] * (WIDTH_MARKER_PLACES - 1)],
                            [schema_j],
                            [],
                            [schema_i]))
        return [left_lookup, right_lookup]

    def _remove_false_start_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
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

    def _mark_hubs_after_initial_secants(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            'dupl',
            'dflt',
            mark_filtering_set='all',
            reversed=True,
        )
        hubs = OrderedSet()
        needed_hub_priorities = set()
        for schema in new_schemas:
            if isinstance(schema.path, Hub) and not schema.path.initial_secant:
                hubs.add(schema)
                classes['all'].append(schema)
            elif isinstance(schema.path, Line) and schema.path.secant and schema.glyph_class == GlyphClass.JOINER:
                classes['secant'].append(schema)
        for hub in hubs:
            initial_secant_hub = hub.clone(path=hub.path.clone(initial_secant=True))
            classes[HUB_CLASS].append(initial_secant_hub)
            classes[CONTINUING_OVERLAP_OR_HUB_CLASS].append(initial_secant_hub)
            add_rule(lookup, Rule(
                ['secant'],
                [hub],
                [],
                [initial_secant_hub],
            ))
        return [lookup]

    def _find_real_hub(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        hubs = collections.defaultdict(list)
        for schema in new_schemas:
            if isinstance(schema.path, Dummy):
                dummy = schema
            elif isinstance(schema.path, Hub):
                hubs[schema.path.priority].append(schema)
                classes['all'].append(schema)
            elif isinstance(schema.path, InitialSecantMarker):
                classes['all'].append(schema)
            elif isinstance(schema.path, ContinuingOverlap):
                continuing_overlap = schema
                classes['all'].append(schema)
        for priority_a, hubs_a in sorted(hubs.items()):
            for priority_b, hubs_b in sorted(hubs.items()):
                for hub_a in hubs_a:
                    if not hub_a.path.initial_secant:
                        add_rule(lookup, Rule([continuing_overlap], [hub_a], [], [dummy]))
                    for hub_b in hubs_b:
                        if hub_b.path.initial_secant:
                            continue
                        if priority_a <= priority_b:
                            add_rule(lookup, Rule([hub_a], [hub_b], [], [dummy]))
                        else:
                            add_rule(lookup, Rule([], [hub_a], [hub_b], [dummy]))
        return [lookup]

    def _expand_start_markers(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        start = next(s for s in new_schemas if isinstance(s.path, Start))
        add_rule(lookup, Rule([start], [
            start,
            *(Schema(None, LeftBoundDigit(place, 0, DigitStatus.DONE), 0) for place in range(WIDTH_MARKER_PLACES)),
        ]))
        return [lookup]

    def _mark_maximum_bounds(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        left_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='ldx',
            reversed=True,
        )
        right_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='rdx',
            reversed=True,
        )
        anchor_lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            mark_filtering_set='adx',
            reversed=True,
        )
        new_left_bounds = []
        new_right_bounds = []
        new_anchor_widths = []
        end = next(s for s in schemas if isinstance(s.path, End))
        for schema in new_schemas:
            if isinstance(schema.path, LeftBoundDigit):
                classes['ldx'].append(schema)
                new_left_bounds.append(schema)
            elif isinstance(schema.path, RightBoundDigit):
                classes['rdx'].append(schema)
                new_right_bounds.append(schema)
            elif isinstance(schema.path, AnchorWidthDigit):
                classes['adx'].append(schema)
                new_anchor_widths.append(schema)
        for new_digits, lookup, class_name, digit_path, status in [
            (new_left_bounds, left_lookup, 'ldx', LeftBoundDigit, DigitStatus.ALMOST_DONE),
            (new_right_bounds, right_lookup, 'rdx', RightBoundDigit, DigitStatus.DONE),
            (new_anchor_widths, anchor_lookup, 'adx', AnchorWidthDigit, DigitStatus.DONE),
        ]:
            for schema in new_digits:
                if schema.path.status != DigitStatus.NORMAL:
                    continue
                skipped_schemas = [class_name] * schema.path.place
                add_rule(lookup, Rule(
                    [],
                    [schema],
                    [*[class_name] * (WIDTH_MARKER_PLACES - schema.path.place - 1), end],
                    [Schema(None, digit_path(schema.path.place, schema.path.digit, status), 0)]))
        return [left_lookup, right_lookup, anchor_lookup]

    def _copy_maximum_left_bound_to_start(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup(
            'dist',
            {'DFLT', 'dupl'},
            'dflt',
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
            mark_filtering_set='all',
        )
        new_left_totals = []
        new_left_start_totals = [None] * WIDTH_MARKER_PLACES
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
            if total.path.digit == 0:
                done = new_left_start_totals[total.path.place]
            else:
                done = Schema(None, LeftBoundDigit(total.path.place, total.path.digit, DigitStatus.DONE), 0)
            classes['all'].append(done)
            if total.path.digit != 0:
                input = new_left_start_totals[total.path.place]
                if input not in classes['all']:
                    classes['all'].append(input)
                add_rule(lookup, Rule(
                    [start, *['all'] * total.path.place],
                    [input],
                    [*['all'] * (WIDTH_MARKER_PLACES - 1), total],
                    [done]))
        return [lookup]

    def _dist(self, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
        lookup = Lookup('dist', {'DFLT', 'dupl'}, 'dflt')
        for schema in new_schemas:
            if ((isinstance(schema.path, LeftBoundDigit)
                    or isinstance(schema.path, RightBoundDigit)
                    or isinstance(schema.path, AnchorWidthDigit))
                    and schema.path.status == DigitStatus.DONE):
                digit = schema.path.digit
                if schema.path.place == WIDTH_MARKER_PLACES - 1 and digit >= WIDTH_MARKER_RADIX / 2:
                    digit -= WIDTH_MARKER_RADIX
                x_advance = digit * WIDTH_MARKER_RADIX ** schema.path.place
                if not isinstance(schema.path, RightBoundDigit):
                    x_advance = -x_advance
                if schema.path.place == 0 and not isinstance(schema.path, AnchorWidthDigit):
                    x_advance += DEFAULT_SIDE_BEARING
                if x_advance:
                    add_rule(lookup, Rule([], [schema], [], x_advances=[x_advance]))
        return [lookup]

    def _run_phases(self, all_input_schemas, phases, all_classes=None):
        all_schemas = OrderedSet(all_input_schemas)
        all_input_schemas = OrderedSet(all_input_schemas)
        all_lookups_with_phases = []
        if all_classes is None:
            all_classes = collections.defaultdict(FreezableList)
        all_named_lookups_with_phases = {}
        for phase_index, phase in enumerate(phases):
            schema.CURRENT_PHASE_INDEX = phase_index
            all_output_schemas = OrderedSet()
            autochthonous_schemas = OrderedSet()
            original_input_schemas = OrderedSet(all_input_schemas)
            new_input_schemas = OrderedSet(all_input_schemas)
            output_schemas = OrderedSet(all_input_schemas)
            classes = PrefixView(phase, all_classes)
            named_lookups = PrefixView(phase, {})
            lookups = None
            while new_input_schemas:
                output_lookups = phase(
                    original_input_schemas,
                    all_input_schemas,
                    new_input_schemas,
                    classes,
                    named_lookups,
                    functools.partial(
                        add_rule,
                        autochthonous_schemas,
                        output_schemas,
                        classes,
                        named_lookups,
                     ),
                 )
                if lookups is None:
                    lookups = output_lookups
                else:
                    assert len(lookups) == len(output_lookups), f'Incompatible lookup counts for phase {phase.__name__}'
                    for i, lookup in enumerate(lookups):
                        lookup.extend(output_lookups[i])
                if len(output_lookups) == 1:
                    might_have_feedback = False
                    for rule in (lookup := output_lookups[0]).rules:
                        if rule.contexts_out if lookup.reversed else rule.contexts_in:
                            might_have_feedback = True
                            break
                else:
                    might_have_feedback = True
                for output_schema in output_schemas:
                    all_output_schemas.add(output_schema)
                new_input_schemas = OrderedSet()
                if might_have_feedback:
                    for output_schema in output_schemas:
                        if output_schema not in all_input_schemas:
                            all_input_schemas.add(output_schema)
                            autochthonous_schemas.add(output_schema)
                            new_input_schemas.add(output_schema)
            all_input_schemas = all_output_schemas
            all_schemas |= all_input_schemas
            all_lookups_with_phases.extend((lookup, phase) for lookup in lookups)
            all_named_lookups_with_phases |= ((name, (lookup, phase)) for name, lookup in named_lookups.items())
        return (
            all_schemas,
            all_input_schemas,
            all_lookups_with_phases,
            all_classes,
            all_named_lookups_with_phases,
        )

    def _add_lookup(
        self,
        feature_tag,
        anchor_class_name,
        *,
        flags,
        mark_filtering_set=None,
    ):
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
        for script in Lookup.KNOWN_SCRIPTS:
            feature.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
            feature.statements.append(fontTools.feaLib.ast.LanguageStatement('dflt'))
            feature.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup))
        self._fea.statements.append(feature)

    def _add_lookups(self, class_asts):
        parent_edge_lookup = None
        child_edge_lookups = [None] * MAX_TREE_WIDTH
        self._add_lookup(
                'abvm',
                anchors.PARENT_EDGE,
                flags=0,
                mark_filtering_set=class_asts[PARENT_EDGE_CLASS],
            )
        for layer_index in range(MAX_TREE_DEPTH):
            if layer_index < 2:
                for child_index in range(MAX_TREE_WIDTH):
                    self._add_lookup(
                            'blwm',
                            anchors.CHILD_EDGES[layer_index][child_index],
                            flags=0,
                            mark_filtering_set=class_asts[CHILD_EDGE_CLASSES[child_index]],
                        )
            for child_index in range(MAX_TREE_WIDTH):
                self._add_lookup(
                    'mkmk',
                    anchors.INTER_EDGES[layer_index][child_index],
                    flags=fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES,
                    mark_filtering_set=class_asts[INTER_EDGE_CLASSES[layer_index][child_index]],
                )
        self._add_lookup(
            'curs',
            anchors.CONTINUING_OVERLAP,
            flags=0,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.CURSIVE,
            flags=0,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CONTINUING_OVERLAP,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.PRE_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
        )
        self._add_lookup(
            'curs',
            anchors.POST_HUB_CURSIVE,
            flags=fontTools.otlLib.builder.LOOKUP_FLAG_RIGHT_TO_LEFT,
            mark_filtering_set=class_asts[CONTINUING_OVERLAP_OR_HUB_CLASS],
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

    def _add_altuni(self, uni, glyph_name):
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

    def _draw_glyph(self, glyph, schema, scalar=1):
        assert not schema.marks
        pen = glyph.glyphPen()
        invisible = schema.path.invisible()
        floating = schema.path.draw(
            glyph,
            not invisible and pen,
            scalar * (self.light_line if invisible or schema.cmap is not None or schema.cps[-1:] != [0x1BC9D] else self.shaded_line),
            scalar * self.light_line,
            scalar * self.stroke_gap,
            schema.size,
            schema.anchor,
            schema.joining_type,
            schema.child,
            schema.context_in == NO_CONTEXT and schema.diphthong_1 and isinstance(schema.path, Circle),
            schema.context_out == NO_CONTEXT and schema.diphthong_2 and isinstance(schema.path, Circle),
            schema.diphthong_1,
            schema.diphthong_2,
        )
        if schema.joining_type == Type.NON_JOINING:
            glyph.left_side_bearing = scalar * schema.side_bearing
        else:
            entry_x = next(
                (x for anchor_class_name, type, x, _ in glyph.anchorPoints
                    if anchor_class_name == anchors.CURSIVE and type == 'entry'),
                0,
            )
            glyph.transform(fontTools.misc.transform.Offset(-entry_x, 0))
        if not floating:
            _, y_min, _, y_max = glyph.boundingBox()
            if y_min != y_max:
                if schema.y_min is not None:
                    if schema.y_max is not None:
                        if (desired_to_actual_ratio := (schema.y_max - schema.y_min) / (y_max - y_min)) != 1:
                            if scalar == 1:
                                glyph.clear()
                                self._draw_glyph(glyph, schema, 1 / desired_to_actual_ratio)
                            else:
                                glyph.transform(fontTools.misc.transform.Offset(0, -y_min)
                                    .scale(desired_to_actual_ratio)
                                )
                        _, y_min, _, _ = glyph.boundingBox()
                        glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
                    else:
                        glyph.transform(fontTools.misc.transform.Offset(0, schema.y_min - y_min))
                elif schema.y_max is not None:
                    glyph.transform(fontTools.misc.transform.Offset(0, schema.y_max - y_max))
        if schema.glyph_class == GlyphClass.MARK:
            glyph.width = 0
        else:
            glyph.right_side_bearing = scalar * schema.side_bearing

    def _create_glyph(self, schema, *, drawing):
        if schema.path.name_in_sfd():
            return self.font[schema.path.name_in_sfd()]
        glyph_name = str(schema)
        uni = -1 if schema.cmap is None else schema.cmap
        if glyph_name in self.font:
            return self._add_altuni(uni, glyph_name)
        glyph = self.font.createChar(uni, glyph_name)
        glyph.glyphclass = schema.glyph_class
        glyph.temporary = schema
        if drawing:
            self._draw_glyph(glyph, schema)
        else:
            glyph.width = glyph.width
        return glyph

    def _create_marker(self, schema):
        assert schema.cmap is None, f'A marker has the code point U+{schema.cmap:04X}'
        glyph = self._create_glyph(schema, drawing=True)
        glyph.width = 0

    def _complete_gpos(self):
        mark_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        base_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        basemark_positions = collections.defaultdict(lambda: collections.defaultdict(fontTools.feaLib.ast.GlyphClass))
        cursive_positions = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))
        for glyph in self.font.glyphs():
            for anchor_class_name, type, x, y in glyph.anchorPoints:
                x = round(x)
                y = round(y)
                glyph_name = glyph.glyphname
                if type == 'mark':
                    mark_positions[anchor_class_name][(x, y)].append(glyph_name)
                elif type == 'base':
                    base_positions[anchor_class_name][(x, y)].append(glyph_name)
                elif type == 'basemark':
                    basemark_positions[anchor_class_name][(x, y)].append(glyph_name)
                elif type == 'entry':
                    cursive_positions[anchor_class_name][glyph_name][0] = fontTools.feaLib.ast.Anchor(x, y)
                elif type == 'exit':
                    cursive_positions[anchor_class_name][glyph_name][1] = fontTools.feaLib.ast.Anchor(x, y)
                else:
                    raise RuntimeError('Unknown anchor type: {}'.format(type))
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

    def _recreate_gdef(self):
        bases = []
        marks = []
        ligatures = []
        for glyph in self.font.glyphs():
            glyph_class = glyph.glyphclass
            if glyph_class == GlyphClass.BLOCKER:
                bases.append(glyph.glyphname)
            elif glyph_class == GlyphClass.MARK:
                marks.append(glyph.glyphname)
            elif glyph_class == GlyphClass.JOINER:
                ligatures.append(glyph.glyphname)
        gdef = fontTools.feaLib.ast.TableBlock('GDEF')
        gdef.statements.append(fontTools.feaLib.ast.GlyphClassDefStatement(
            fontTools.feaLib.ast.GlyphClass(bases),
            fontTools.feaLib.ast.GlyphClass(marks),
            fontTools.feaLib.ast.GlyphClass(ligatures),
            ()))
        self._fea.statements.append(gdef)

    @staticmethod
    def _glyph_to_schema(glyph):
        if glyph.temporary is None:
            schema = Schema(glyph.unicode if glyph.unicode != -1 else None, SFDGlyphWrapper(glyph.glyphname), 0, Type.NON_JOINING)
        else:
            schema = glyph.temporary
            glyph.temporary = None
        schema.glyph = glyph
        return schema

    def convert_classes(self, classes):
        class_asts = {}
        for name, schemas in classes.items():
            class_ast = fontTools.feaLib.ast.GlyphClassDefinition(
                name,
                fontTools.feaLib.ast.GlyphClass([*map(str, schemas)]),
            )
            self._fea.statements.append(class_ast)
            class_asts[name] = class_ast
        return class_asts

    def convert_named_lookups(self, named_lookups_with_phases, class_asts):
        named_lookup_asts = {}
        named_lookups_to_do = [*named_lookups_with_phases.keys()]
        while named_lookups_to_do:
            new_named_lookups_to_do = []
            for name, (lookup, phase) in named_lookups_with_phases.items():
                if name not in named_lookups_to_do:
                    continue
                try:
                    named_lookup_ast = lookup.to_asts(
                        PrefixView(phase, class_asts),
                        PrefixView(phase, named_lookup_asts),
                        name,
                    )
                    assert len(named_lookup_ast) == 1, f'A named lookup should generate 1 AST, not {len(named_lookup_ast)}'
                    named_lookup_ast = named_lookup_ast[0]
                except KeyError:
                    new_named_lookups_to_do.append(name)
                    continue
                self._fea.statements.append(named_lookup_ast)
                assert name not in named_lookup_asts.keys(), name
                named_lookup_asts[name] = named_lookup_ast
            assert len(new_named_lookups_to_do) < len(named_lookups_to_do)
            named_lookups_to_do = new_named_lookups_to_do
        return named_lookup_asts

    def _merge_schemas(self, schemas, lookups_with_phases, classes, named_lookups_with_phases):
        grouper = sifting.group_schemas(schemas)
        previous_phase = None
        for lookup, phase in reversed(lookups_with_phases):
            if phase is not previous_phase is not None:
                rename_schemas(grouper, self._phases.index(previous_phase))
            previous_phase = phase
            prefix_classes = PrefixView(phase, classes)
            prefix_named_lookups_with_phases = PrefixView(phase, named_lookups_with_phases)
            sifting.sift_groups(grouper, lookup, prefix_classes, prefix_named_lookups_with_phases)
        rename_schemas(grouper, NO_PHASE_INDEX)

    def augment(self):
        (
            schemas,
            output_schemas,
            lookups_with_phases,
            classes,
            named_lookups_with_phases,
        ) = self._run_phases(self._schemas, self._phases)
        self._merge_schemas(schemas, lookups_with_phases, classes, named_lookups_with_phases)
        class_asts = self.convert_classes(classes)
        named_lookup_asts = self.convert_named_lookups(named_lookups_with_phases, class_asts)
        (
            _,
            more_output_schemas,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = self._run_phases([schema for schema in output_schemas if schema.canonical_schema is schema], self._middle_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for schema in schemas.sorted(key=lambda schema: not (schema in output_schemas and schema in more_output_schemas)):
            self._create_glyph(
                schema,
                drawing=schema in output_schemas and schema in more_output_schemas and not schema.ignored_for_topography,
            )
        for schema in schemas:
            if name_in_sfd := schema.path.name_in_sfd():
                self.font[name_in_sfd].temporary = schema
                self.font[name_in_sfd].glyphname = str(schema)
        (
            schemas,
            _,
            more_lookups_with_phases,
            more_classes,
            more_named_lookups_with_phases,
        ) = self._run_phases([*map(self._glyph_to_schema, self.font.glyphs())], self._marker_phases, classes)
        lookups_with_phases += more_lookups_with_phases
        for schema in schemas:
            if schema.glyph is None:
                self._create_marker(schema)
        class_asts |= self.convert_classes(more_classes)
        named_lookup_asts |= self.convert_named_lookups(more_named_lookups_with_phases, class_asts)
        for i, lp in enumerate(lookups_with_phases):
            for statement in lp[0].to_asts(PrefixView(lp[1], class_asts), PrefixView(lp[1], named_lookup_asts), i):
                self._fea.statements.append(statement)
        self._add_lookups(class_asts)
        self.font.selection.all()
        self.font.round()
        self.font.simplify(3, ('smoothcurves',))

    def merge_features(self, tt_font, old_fea):
        self._fea.statements.extend(
            fontTools.feaLib.parser.Parser(
                io.StringIO(old_fea),
                tt_font.getReverseGlyphMap())
            .parse().statements)
        self._complete_gpos()
        self._recreate_gdef()
        fontTools.feaLib.builder.addOpenTypeFeatures(
                tt_font,
                self._fea,
                ['GDEF', 'GPOS', 'GSUB'])

