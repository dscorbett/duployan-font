# Copyright 2018-2019 David Corbett
# Copyright 2020-2021 Google LLC
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

__all__ = [
    'FreezableList',
    'Lookup',
    'Rule',
    'add_rule',
]


import itertools


import fontTools.feaLib.ast
import fontTools.otlLib.builder


from utils import GlyphClass


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
