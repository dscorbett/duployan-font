# Copyright 2018-2019, 2022-2023 David Corbett
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

r"""The phase system.

A phase is a function that generates a sequence of lookups. It takes the
schemas from the previous phase, does some phase-specific computation,
and produces some lookups. If the lookups are GSUB lookups, this may
change the set of schemas that the next phase will handle.

A phase is run iteratively until its output is stable. That means the
output schemas of one iteration may be the input schemas of the next
iteration. See `run_phases` for what stability entails.

The parameters of a phase are as follows, though the specific parameter
names don’t matter.

1. ``builder``: A ``Builder``.

2. ``original_schemas``: An iterable containing all the schemas that
   existed before this phase was ever run. This is always a subset of
   ``schemas``.

3. ``schemas``: An iterable containing all the schemas that are inputs
   to the current iteration of this phase.

4. ``new_schemas``: An iterable containing all the schemas that have not
   been passed to previous iterations of this phase. This is always a
   subset of ``schemas``. This is equal to ``original_schemas`` on the
   first iteration.

5. ``classes``: The dictionary of all the font’s glyph classes, wrapped
   in a `PrefixView` whose prefix uniquely identifies this phase among
   all phases. The keys are arbitrary strings that can serve as valid
   FEA class names. Some global (i.e. not phase-specific) keys are
   defined in this module. The values are lists of schemas. ``classes``
   is a `collections.defaultdict` whose default value is an empty list.

6. ``named_lookups``: The dictionary of all the font’s named lookups,
   wrapped in a `PrefixView` whose prefix uniquely identifies this phase
   among all phases. The keys are arbitrary strings that can serve as
   valid FEA lookup names. The values are named `Lookup`\ s.

7. ``add_rule``: A function that this phase should call to add a rule to
   a lookup. It takes two arguments: a `Lookup` and a `Rule`. The lookup
   can be anonymous or named.

The return value of a phase is a list of lookups. The lists returned
from all iterations of the same phase must contain the same number of
lookups. Rules in a lookup returned from a non-first iteration are
merged with the lookup at the same index from the previous iteration. In
other words, the first iteration defines how many anonymous lookups the
phase generates, and subsequent iterations can only add more rules to
those lookups. (It is always possible to create new named lookups in
later iterations.)

A phase should never delete or remove anything from a class or named
lookup from a previous iteration of the same phase.

Any call to ``add_rule`` may freeze some of the classes and named
lookups used in the rule, meaning that no more schemas can be added to
such classes and no more rules can be added to such named lookups. This
restriction is necessary to verify that a certain optimization related
to tracking output schemas is valid.

..
    TODO: Document the exact circumstances of freezing a class or named
    lookup.

This module does not define any phases. Phases are defined in the other
modules in this package.
"""


from __future__ import annotations


__all__ = [
    'CHILD_EDGE_CLASSES',
    'CONTINUING_OVERLAP_CLASS',
    'CONTINUING_OVERLAP_OR_HUB_CLASS',
    'HUB_CLASS',
    'INTER_EDGE_CLASSES',
    'Lookup',
    'PARENT_EDGE_CLASS',
    'Rule',
    'run_phases',
]


import collections
from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from collections.abc import MutableSet
from collections.abc import Sequence
import itertools
import functools
from typing import Any
from typing import ClassVar
from typing import Final
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import Set
from typing import Tuple
from typing import TypeVar
from typing import Union
from typing import cast
from typing import overload


import fontTools.agl
import fontTools.feaLib.ast
import fontTools.otlLib.builder


import schema
from utils import GlyphClass
from utils import KNOWN_SCRIPTS
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import OrderedSet
from utils import PrefixView
from utils import REQUIRED_SCRIPT_FEATURES
from utils import cps_to_scripts


# TODO: Document the edge class name constants better with reference to
# `categorize_edges`.
#: The name of the glyph class containing all parent edges and all
#: children. This is used to connect parent edges with children while
#: ignoring other marks.
PARENT_EDGE_CLASS: Final[str] = 'global..pe'


#: A list of the names of the glyph classes used to connect children
#: with child edges while ignoring other marks.
CHILD_EDGE_CLASSES: Final[Sequence[str]] = [f'global..ce{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]


#: A list of lists of the names of glyph classes connecting child edges
#: with parent edges while ignoring other marks.
INTER_EDGE_CLASSES: Final[Sequence[Sequence[str]]] = [[f'global..edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]


#: The name of the glyph class containing all valid continuing overlaps.
CONTINUING_OVERLAP_CLASS: Final[str] = 'global..cont'


#: The name of the glyph class containing all hubs.
HUB_CLASS: Final[str] = 'global..hub'


#: The name of the glyph class that is the union of the classes named by
#: `CONTINUING_OVERLAP_CLASS` and `HUB_CLASS`.
CONTINUING_OVERLAP_OR_HUB_CLASS: Final[str] = 'global..cont_or_hub'


_T = TypeVar('_T')


class _FreezableList(Generic[_T], Collection[_T]):
    """A list that can be frozen, making it immutable.

    This is not a `list` in the Python sense, but it is analogous.
    """

    def __init__(self) -> None:
        self._delegate: Sequence[_T] = []

    def freeze(self) -> None:
        """Makes this list immutable.
        """
        self._delegate = tuple(self._delegate)

    def __contains__(self, key: object, /) -> bool:
        """Returns whether this list contains an object.

        Args:
            key: An object to search for.
        """
        return key in self._delegate

    def __iter__(self) -> Iterator[_T]:
        """Returns an iterator over this list.
        """
        return iter(self._delegate)

    def __len__(self) -> int:
        """Returns the length of this list.
        """
        return len(self._delegate)

    def insert(self, index: int, object: _T, /) -> None:
        """Inserts something into this list.

        Args:
            index: The index to insert `object` at in the same manner
                as `list.insert`.
            object: The element to insert.

        Raises:
            ValueError: If this list is frozen.
        """
        if isinstance(self._delegate, MutableSequence):
            self._delegate.insert(index, object)
        else:
            raise ValueError('Inserting into a frozen list') from None

    def append(self, object: _T, /) -> None:
        """Appends something to this list.

        Args:
            object: The element to append.

        Raises:
            ValueError: If this list is frozen.
        """
        if isinstance(self._delegate, MutableSequence):
            self._delegate.append(object)
        else:
            raise ValueError('Appending to a frozen list') from None

    def extend(self, iterable: Iterable[_T], /) -> None:
        """Extends this list.

        Args:
            iterable: The iterable containing the elements to append to
                this list.

        Raises:
            ValueError: If this list is frozen.
        """
        if isinstance(self._delegate, MutableSequence):
            self._delegate.extend(iterable)
        else:
            raise ValueError('Extending a frozen list') from None


class Rule:
    """One or more OpenType Layout rules.

    A `Rule` has attributes to support both GSUB and GPOS rules, but a
    single `Rule` can’t have non-``None`` GSUB and GPOS attributes.

    The various sequence attributes contain schemas and strings. Strings
    represent classes. `lookups` contains strings representing named
    lookups. A rule that uses a class is therefore only interpretable in
    the context of something that maps class and lookup names to their
    meanings.

    A `Rule` can represent multiple OpenType Layout rules in two ways.
    First, it actually represents a sequence of FEA rules (see
    `to_asts`). Second, each FEA rule can represent multiple OpenType
    Layout rules.

    Attributes:
        contexts_in: The backtrack sequence.
        inputs: The input sequence.
        contexts_out: The lookahead sequence.
        outputs: The output sequence, if a GSUB rule.
        lookups: The names of the named lookups used by this rule, if
            any, with one element per element of `outputs`. An element
            of `lookups` may be ``None`` if there is no named lookup to
            apply at that position. Named lookups are applied in
            increasing order by index.
        x_placements: The x placements to apply, if any and if a GPOS
            rule, with one element per element of `inputs`.
        x_advances: The x advances to apply, if any and if a GPOS rule,
            with one element per element of `inputs`.
    """

    @overload
    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        /,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        a3: Union[str, Sequence[Union[schema.Schema, str]]],
        a4: Union[str, Sequence[Union[schema.Schema, str]]],
        /,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        a3: Optional[Union[str, Sequence[Union[schema.Schema, str]]]],
        /,
        *,
        lookups: Sequence[Optional[str]],
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        a3: Optional[Union[str, Sequence[Union[schema.Schema, str]]]],
        /,
        *,
        x_placements: Sequence[Optional[float]],
        x_advances: Optional[Sequence[Optional[float]]],
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        a3: Optional[Union[str, Sequence[Union[schema.Schema, str]]]],
        /,
        *,
        x_advances: Sequence[Optional[float]],
    ) -> None:
        ...

    def __init__(
        self,
        a1: Union[str, Sequence[Union[schema.Schema, str]]],
        a2: Union[str, Sequence[Union[schema.Schema, str]]],
        a3: Optional[Union[str, Sequence[Union[schema.Schema, str]]]] = None,
        a4: Optional[Union[str, Sequence[Union[schema.Schema, str]]]] = None,
        /,
        *,
        lookups: Optional[Sequence[Optional[str]]] = None,
        x_placements: Optional[Sequence[Optional[float]]] = None,
        x_advances: Optional[Sequence[Optional[float]]] = None,
    ) -> None:
        """Initializes this `Rule`.

        As a convenient shorthand, a non-contextual GSUB rule can be
        initialized with the input and output sequences as the first two
        arguments. The full form for a GSUB rule interprets the first
        four arguments as the backtrack, input, lookahead, and output
        sequences. There is no similar shorthand for GPOS rules.

        Another shorthand is that a sequence containing just a class can
        be specified as just the class name, rather than as a list
        containing only that class name.

        Args:
            a1: The backtrack sequence, or the input sequence in the
                shorthand form.
            a2: The input sequence, or the output sequence in the
                shorthand form.
            a3: The lookahead sequence, if using the full form.
            a4: The output sequence, if using the full form.
            lookups: The ``lookups`` attribute.
            x_placements: The ``x_placements`` attribute.
            x_advances: The ``x_advances`` attribute.
        """
        @overload
        def _l(glyphs: None) -> None:
            ...

        @overload
        def _l(glyphs: Union[str, Sequence[Union[schema.Schema, str]]]) -> Sequence[Union[schema.Schema, str]]:
            ...

        def _l(glyphs: Optional[Union[str, Sequence[Union[schema.Schema, str]]]]) -> Optional[Sequence[Union[schema.Schema, str]]]:
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

    def to_asts(
        self,
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        in_contextual_lookup: bool,
        in_multiple_lookup: bool,
        in_reverse_lookup: bool,
    ) -> Sequence[fontTools.feaLib.ast.Element]:
        """Converts this rule to fontTools feaLib ASTs.

        A `Rule` usually represents a single feaLib statement AST, but
        it may desugar to multiple statement ASTs if FEA syntax is
        missing a necessary feature.

        ..
            TODO: Document that syntactic sugar.

        Args:
            class_asts: A map to glyph classes from their names.
            named_lookup_asts: A map to named lookup ASTs from their
                names.
            in_contextual_lookup: Whether this rule is in a contextual
                lookup.
            in_multiple_lookup: Whether this rule is in a multiple
                substitution lookup. This disambiguates a rule with a
                single input and a single output between a single
                substitution rule and a multiple substitution rule,
                which have different ASTs but otherwise look identical.
            in_reverse_lookup: Whether this rule is in a reverse lookup.

        Returns:
            A sequence of fontTools feaLib ASTs corresponding to this
            rule.
        """
        def glyph_to_ast(
            glyph: Union[str, schema.Schema],
            unrolling_index: Optional[int] = None,
        ) -> Union[fontTools.feaLib.ast.GlyphClassName, fontTools.feaLib.ast.GlyphName]:
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return fontTools.feaLib.ast.GlyphName(class_asts[glyph].glyphs.glyphs[unrolling_index])
                else:
                    return fontTools.feaLib.ast.GlyphClassName(class_asts[glyph])
            return fontTools.feaLib.ast.GlyphName(str(glyph))

        def glyphs_to_ast(
            glyphs: Iterable[Union[str, schema.Schema]],
            unrolling_index: Optional[int] = None,
        ) -> Sequence[Union[fontTools.feaLib.ast.GlyphClassName, fontTools.feaLib.ast.GlyphName]]:
            return [glyph_to_ast(glyph, unrolling_index) for glyph in glyphs]

        def glyph_to_name(
            glyph: Union[str, schema.Schema],
            unrolling_index: Optional[int] = None,
        ) -> str:
            if isinstance(glyph, str):
                if unrolling_index is not None:
                    return cast(Sequence[str], class_asts[glyph].glyphs.glyphs)[unrolling_index]
                else:
                    assert not isinstance(glyph, str), f'Glyph classes are not allowed where only glyphs are expected: @{glyph}'
            return str(glyph)

        def glyphs_to_names(
            glyphs: Iterable[Union[str, schema.Schema]],
            unrolling_index: Optional[int] = None,
        ) -> Sequence[str]:
            return [glyph_to_name(glyph, unrolling_index) for glyph in glyphs]

        if self.lookups is not None:
            assert not in_reverse_lookup, 'Reverse chaining contextual substitutions do not support lookup references'
            assert self.contexts_out is not None
            return [fontTools.feaLib.ast.ChainContextSubstStatement(
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.inputs),
                glyphs_to_ast(self.contexts_out),
                [None if name is None else named_lookup_asts[name] for name in self.lookups],
            )]
        elif self.x_placements is not None or self.x_advances is not None:
            assert not in_reverse_lookup, 'There is no reverse positioning lookup type'
            assert len(self.inputs) == 1, 'Only single adjustment positioning has been implemented'
            assert self.contexts_out is not None
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
                    strict=True,
                )),
                glyphs_to_ast(self.contexts_in),
                glyphs_to_ast(self.contexts_out),
                in_contextual_lookup,
            )]
        elif len(self.inputs) == 1:
            assert self.outputs is not None
            assert self.contexts_out is not None
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
                if isinstance(input, str) and (not self.outputs or any(isinstance(output, str) for output in self.outputs)):
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
            assert self.outputs is not None
            assert self.contexts_out is not None
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
                for input_glyph_name, output_glyph_name in zip(class_asts[input_class].glyphs.glyphs, class_asts[output].glyphs.glyphs, strict=True):
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

    def is_contextual(self) -> bool:
        """Returns whether this rule is contextual.
        """
        return bool(self.contexts_in or self.contexts_out)

    def is_multiple(self) -> bool:
        """Returns whether this rule can only appear in a multiple
        substitution lookup.
        """
        return len(self.inputs) == 1 and self.outputs is not None and len(self.outputs) != 1


class Lookup:
    """An OpenType Layout lookup.

    If `feature` and `language` are ``None``, this is a named lookup.
    Otherwise, it is an anonymous lookup directly associated with a
    feature.

    Attributes:
        feature: This lookup’s feature tag, if anonymous.
        language: This lookup’s language system tag, if anonymous.
        flags: The lookup flags.
        mark_filtering_set: The name of the glyph class used for the
            mark filtering set, if any.
        required: Whether the shaper is guaranteed to apply this lookup,
            regardless of which script the itemizer chooses. This
            ignores the fact that it is technically possible to disable
            any feature; there are some features that are not *meant* to
            be disabled.
        reversed: Whether this lookup is reversed. (The only reversed
            lookup type is the reverse chaining contextual single
            substitution, but this would cover other reversed lookup
            types if they existed.)
        prepending: Whether new rules should be added to the beginning
            instead of the end.
        rules: The list of rules.
    """

    _DISCRETIONARY_FEATURES: ClassVar[Set[str]] = {
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

    @overload
    def __init__(
            self,
            feature: str,
            language: str,
            *,
            flags: int,
            mark_filtering_set: Optional[str],
            reversed: bool,
            prepending: bool,
    ) -> None:
        ...

    @overload
    def __init__(
            self,
            feature: None,
            language: None,
            *,
            flags: int,
            mark_filtering_set: Optional[str],
            reversed: bool,
            prepending: bool,
    ) -> None:
        ...

    def __init__(
            self,
            feature: Optional[str],
            language: Optional[str],
            *,
            flags: int = 0,
            mark_filtering_set: Optional[str] = None,
            reversed: bool = False,
            prepending: bool = False,
    ) -> None:
        """Initializes this `Lookup`.

        Args:
            feature: The ``feature`` attribute.
            language: The ``language`` attribute.
            flags: The ``flags`` attribute, except that the
                ``UseMarkFilteringSet`` flag must not be set, even if
                there is a mark filtering set.
            mark_filtering_set: The ``mark_filtering_set`` attribute.
            reversed: The ``reversed`` attribute.
            prepending: The ``prepending`` attribute.
        """
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
            flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        self.feature = feature
        self.language = language
        assert language is None or len(language) == 4, f"Language tag must be 4 characters long: '{language}'"
        assert feature is None or len(feature) == 4, f"Feature tag must be 4 characters long: '{feature}'"
        self.flags = flags
        self.mark_filtering_set = mark_filtering_set
        self.required = feature is not None and feature not in self._DISCRETIONARY_FEATURES
        self.reversed = reversed
        self.prepending = prepending
        self.rules: _FreezableList[Rule] = _FreezableList()
        assert (feature is None) == (language is None), 'Not clear whether this is a named or a normal lookup'

    def get_scripts(
        self,
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
    ) -> Set[str]:
        """Returns the minimal set of script tags relevant to this
        lookup.

        Args:
            class_asts: A map to glyph classes from their names.
        """
        def glyph_name_to_scripts(glyph_name: str) -> Set[str]:
            return cps_to_scripts(tuple(map(ord, fontTools.agl.toUnicode(glyph_name))))

        def class_to_scripts(
            cls: str,
            class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        ) -> Set[str]:
            scripts: Set[str] = set()
            for glyph_name in class_asts[cls].glyphs.glyphs:
                scripts |= glyph_name_to_scripts(glyph_name)
            return scripts

        def schema_to_scripts(schema: schema.Schema) -> Set[str]:
            return cps_to_scripts(tuple(schema.cps))

        def s_to_scripts(
            s: Union[schema.Schema, str],
            class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        ) -> Set[str]:
            if isinstance(s, str):
                return class_to_scripts(s, class_asts)
            else:
                return schema_to_scripts(s)

        def target_to_scripts(
            target: Optional[Sequence[Union[schema.Schema, str]]],
            class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        ) -> Set[str]:
            scripts = set(KNOWN_SCRIPTS)
            if target:
                for s in target:
                    scripts &= s_to_scripts(s, class_asts)
            assert scripts
            return scripts

        def rule_to_scripts(
            rule: Rule,
            class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        ) -> Set[str]:
            scripts = (target_to_scripts(rule.contexts_in, class_asts)
                & target_to_scripts(rule.inputs, class_asts)
                & target_to_scripts(rule.contexts_out, class_asts)
            )
            assert scripts
            return scripts

        scripts = set()
        for rule in self.rules:
            scripts |= rule_to_scripts(rule, class_asts)
        return scripts

    def _get_sorted_scripts(self, features_to_scripts: Mapping[str, Set[str]]) -> Iterable[str]:
        """Returns the script tags to use for this lookup.

        If this lookup is marked as required, this method validates that
        all the returned scripts do in fact enable this lookup’s
        feature.

        Args:
            features_to_scripts: A mapping from feature tags to sets of
                script tags. The mapping must contain this lookup’s
                feature tag.
        """
        assert self.feature is not None
        scripts = sorted(features_to_scripts[self.feature])
        if self.required:
            for script in scripts:
                assert self.feature in REQUIRED_SCRIPT_FEATURES[script], (
                    f"The phase system does not support the feature '{self.feature}' for the script '{script}'")
        return scripts

    @overload
    def to_asts(
        self,
        features_to_scripts: None,
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: str,
    ) -> Sequence[fontTools.feaLib.ast.Block]:
        ...

    @overload
    def to_asts(
        self,
        features_to_scripts: Mapping[str, Set[str]],
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: int,
    ) -> Sequence[fontTools.feaLib.ast.Block]:
        ...

    def to_asts(
        self,
        features_to_scripts: Optional[Mapping[str, Set[str]]],
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: Union[str, int],
    ) -> Sequence[fontTools.feaLib.ast.Block]:
        """Converts this lookup to fontTools feaLib ASTs.

        Args:
            features_to_scripts: A mapping from feature tags to sets of
                script tags, if this lookup is anonymous, or else
                ``None``. If this is an anonymous lookup, the mapping
                must contain this lookup’s feature tag. The associated
                script tags, which must be a superset of
                ``self.get_scripts(class_asts)``, are used in the second
                returned AST.
            class_asts: A map to glyph classes from their names.
            named_lookup_asts: A map to named lookup ASTs from their
                names.
            name: The name of this lookup, if it is a named lookup, or
                else an arbitrary number uniquely identifying this
                lookup among all anonymous lookups.

        Returns:
            A list of one or two fontTools feaLib ASTs corresponding to
            this lookup. The first AST is always a
            `fontTools.feaLib.ast.LookupBlock`. If this is an anonymous
            lookup, the second AST is a
            `fontTools.feaLib.ast.FeatureBlock`.
        """
        named_lookup = self.feature is None
        assert named_lookup == isinstance(name, str) == (features_to_scripts is None)
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        if named_lookup:
            lookup_block = fontTools.feaLib.ast.LookupBlock(name)
            asts = [lookup_block]
        else:
            lookup_block = fontTools.feaLib.ast.LookupBlock(f'lookup_{name}')
            feature_block = fontTools.feaLib.ast.FeatureBlock(self.feature)
            assert features_to_scripts is not None
            for script in self._get_sorted_scripts(features_to_scripts):
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

    def freeze(self) -> None:
        """Freezes the list of rules.
        """
        self.rules.freeze()

    def append(self, rule: Rule) -> None:
        """Adds a rule to the end of the list of rules.

        This method ignores ``prepending``.

        Raises:
            ValueError: If the list of rules is frozen.
        """
        self.rules.append(rule)

    def extend(self, other: Lookup) -> None:
        """Extends this lookup with rules from another lookup.

        If prepending, `other`’s rules are added to the front of the
        list, ending up in reverse order from how they are in `other`.
        Otherwise, they are added to the end, ending up in the same
        order.

        The lookups must agree in their features and languages, or lack
        thereof, and in whether they prepend, are required, and are
        reversed.

        Args:
            other: A lookup.
        """
        assert self.feature == other.feature, f"Incompatible features: '{self.feature}' != '{other.feature}'"
        assert self.language == other.language, f"Incompatible languages: '{self.language}' != '{other.language}'"
        assert self.prepending == other.prepending, f'Incompatible prepending values: {self.prepending} != {other.prepending}'
        assert self.required == other.required, f'Incompatible required values: {self.required} != {other.required}'
        assert self.reversed == other.reversed, f'Incompatible reversed values: {self.reversed} != {other.reversed}'
        if self.prepending:
            for rule in other.rules:
                self.rules.insert(0, rule)
        else:
            for rule in other.rules:
                self.append(rule)


def _add_rule(
    autochthonous_schemas: Iterable[schema.Schema],
    output_schemas: OrderedSet[schema.Schema],
    classes: Mapping[str, _FreezableList[schema.Schema]],
    named_lookups: Mapping[str, Lookup],
    lookup: Lookup,
    rule: Rule,
    track_possible_outputs: bool = True,
):
    """Adds a rule to a lookup.

    It only makes sense to call this function in the context of a phase
    iteration. The phase is implicit.

    Args:
        autochthonous_schemas: All the schemas ever created in the
            current phase.
        output_schemas: All the schemas that could possibly be the
            output of rule generated by this phase. This function may
            add or remove schemas from the list.
        classes: A mapping to glyph classes from their names. This
            function may freeze any class but not otherwise modify it.
        named_lookups: A mapping to named lookups from their names. This
            function may freeze any named lookup but not otherwise
            modify it.
        lookup: The lookup to add `rule` to.
        rule: The rule to add.
        track_possible_outputs: Whether to allow removing schemas from
            `output_schemas`. Tracking is usually the right thing to do,
            but it can sometimes cause a crash in fontTools, so it can
            be disabled.
    """
    def ignored(schema: schema.Schema) -> bool:
        """Returns whether `rule` would ignore a schema.

        Args:
            schema: The schema that might be ignored.
        """
        glyph_class = schema.glyph_class
        return bool(
            glyph_class == GlyphClass.JOINER and lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_LIGATURES
            or glyph_class == GlyphClass.MARK and (
                lookup.flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS
                or lookup.mark_filtering_set and schema not in classes[lookup.mark_filtering_set]
            )
        )

    def check_ignored(target_part: Iterable[Union[schema.Schema, str]]) -> None:
        """Asserts that a rule part contains no ignored schemas.

        It is not useful for a rule to mention an ignored schema. It is
        probably a bug if one does.

        Args:
            target_part: Part of the rule being added.
        """
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
    assert rule.contexts_out is not None
    check_ignored(rule.contexts_out)

    for input in rule.inputs:
        if isinstance(input, str):
            if all(s in autochthonous_schemas for s in classes[input]):
                classes[input].freeze()
                return
        elif input in autochthonous_schemas:
            return

    def is_prefix(maybe_prefix: Sequence[Union[schema.Schema, str]], full: Sequence[Union[schema.Schema, str]]) -> bool:
        return len(maybe_prefix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(maybe_prefix, full)))

    def is_suffix(maybe_suffix: Sequence[Union[schema.Schema, str]], full: Sequence[Union[schema.Schema, str]]) -> bool:
        return len(maybe_suffix) <= len(full) and all(map(lambda mp_f: mp_f[0] == mp_f[1], zip(reversed(maybe_suffix), reversed(full))))

    if not lookup.prepending and any(r.is_contextual() for r in lookup.rules):
        # TODO: Check prepending lookups too.
        for i, previous_rule in enumerate(lookup.rules):
            if lookup.prepending:
                previous_rule, rule = rule, previous_rule  # type: ignore[unreachable]
            assert previous_rule.contexts_out is not None
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
            for s in classes[input]:
                output_schemas.remove(s)
        else:
            output_schemas.remove(input)

    registered_lookups: MutableSet[Optional[str]] = {None}

    def register_output_schemas(rule: Rule) -> bool:
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
                    assert lookup is not None
                    registered_lookups.add(lookup)
                    froze = False
                    for rule in named_lookups[lookup].rules:
                        if register_output_schemas(rule):
                            froze = True
                    if froze:
                        named_lookups[lookup].freeze()
        return False

    register_output_schemas(rule)


def run_phases(
    builder,
    all_input_schemas: Iterable[schema.Schema],
    phases: Iterable,
    all_classes: Optional[collections.defaultdict[str, Collection[schema.Schema]]] = None,
) -> Tuple[
    OrderedSet[schema.Schema],
    Iterable[schema.Schema],
    MutableSequence[Tuple[Lookup, Any]],
    collections.defaultdict[str, Collection[schema.Schema]],
    MutableMapping[str, Tuple[Lookup, Any]],
]:
    """Runs a sequence of phases.

    Args:
        builder (Builder): The source of everything.
        all_input_schemas: The input schemas for the first iteration of
            the first phase.
        phases (Iterable[Phase]): The phases to run.
        all_classes: The font’s global mapping to classes from their
            names. If ``None``, this method starts with a new empty mapping.

    Returns:
        A tuple of five elements.

        1. An iterable of all the schemas input to or output from any
           phase.
        2. An iterable of the output schemas of the last phase.
        3. A list of 2-tuples of each lookup along with the phase that
           generated it.
        4. The font’s global mapping to classes from their names.
        5. A mapping from named lookups’ names to 2-tuples of named
           lookups and their generating phases.
    """
    all_schemas = OrderedSet(all_input_schemas)
    all_input_schemas = OrderedSet(all_input_schemas)
    all_lookups_with_phases: MutableSequence[Tuple[Lookup, Any]] = []
    if all_classes is None:
        all_classes = collections.defaultdict(_FreezableList)
    all_named_lookups_with_phases: dict[str, Tuple[Lookup, Any]] = {}
    for phase_index, phase in enumerate(phases):
        schema.CURRENT_PHASE_INDEX = phase_index
        all_output_schemas: OrderedSet[schema.Schema] = OrderedSet()
        autochthonous_schemas: OrderedSet[schema.Schema] = OrderedSet()
        original_input_schemas = OrderedSet(all_input_schemas)
        new_input_schemas = OrderedSet(all_input_schemas)
        output_schemas = OrderedSet(all_input_schemas)
        classes = PrefixView(phase, all_classes)
        named_lookups: PrefixView[Lookup] = PrefixView(phase, {})
        lookups: Optional[Sequence[Lookup]] = None
        while new_input_schemas:
            output_lookups = phase(
                # TODO: `builder` is only used to check which phase generated a schema,
                # and only in a few phases. Refactor them so this doesn’t need to pass
                # the whole `Builder` around.
                builder,
                original_input_schemas,
                all_input_schemas,
                new_input_schemas,
                classes,
                named_lookups,
                functools.partial(
                    _add_rule,
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
        assert lookups is not None
        all_lookups_with_phases.extend((lookup, phase) for lookup in lookups)
        all_named_lookups_with_phases |= ((name, (lookup, phase)) for name, lookup in named_lookups.items())
    return (
        all_schemas,
        all_input_schemas,
        all_lookups_with_phases,
        all_classes,
        all_named_lookups_with_phases,
    )
