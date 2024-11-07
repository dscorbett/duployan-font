# Copyright 2018-2019, 2022-2024 David Corbett
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

The parameters of a phase are as follows.

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

import collections
import functools
import itertools
from typing import Final
from typing import TYPE_CHECKING
from typing import overload
from typing import override

import fontTools.feaLib.ast
import fontTools.otlLib.builder

import schema
from utils import GlyphClass
from utils import KNOWN_FEATURES
from utils import KNOWN_SCRIPTS
from utils import KNOWN_SHAPE_PLANS
from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH
from utils import OrderedSet
from utils import PrefixView
from utils import REQUIRED_FEATURES
from utils import SUBSET_FEATURES


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Mapping
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence
    from collections.abc import MutableSet
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet
    from typing import Self
    from typing import SupportsIndex

    from _typeshed import SupportsRichComparison
    from mypy_extensions import Arg

    from duployan import Builder


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
INTER_EDGE_CLASSES: Final[Sequence[Sequence[str]]] = [
    [f'global..edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]
    for layer_index in range(MAX_TREE_DEPTH)
]


#: The name of the glyph class containing all valid continuing overlaps.
CONTINUING_OVERLAP_CLASS: Final[str] = 'global..cont'


#: The name of the glyph class containing all hubs.
HUB_CLASS: Final[str] = 'global..hub'


#: The name of the glyph class that is the union of the classes named by
#: `CONTINUING_OVERLAP_CLASS` and `HUB_CLASS`.
CONTINUING_OVERLAP_OR_HUB_CLASS: Final[str] = 'global..cont_or_hub'


class FreezableList[T](list[T]):
    """A list that can be frozen, making it immutable.
    """

    def __init__(self, iterable: Sequence[T] = (), /) -> None:
        super().__init__(iterable)
        self._frozen: bool = False

    def freeze(self) -> None:
        """Makes this list immutable.
        """
        self._frozen = True

    @override
    def __delitem__(self, index: SupportsIndex | slice, /) -> None:
        """Deletes the element(s) at an index or range of indices.

        Args:
            index: The index, or range of indices, of the element(s) to
                delete.

        Raises:
            IndexError: If `index` is out of range.
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().__delitem__(index)

    @overload
    def __setitem__(self, index: SupportsIndex, value: T, /) -> None:
        ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[T], /) -> None:
        ...

    @override
    def __setitem__(self, index: SupportsIndex | slice, value: T | Iterable[T], /) -> None:
        """Sets the element(s) at an index or range of indices.

        Args:
            index: The index, or range of indices, of the element(s) to
                set.
            value: The new value(s) of the element(s) at `index`.

        Raises:
            IndexError: If the index is out of range.
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().__setitem__(index, value)  # type: ignore[assignment, index]

    @override
    def insert(self, index: SupportsIndex, value: T, /) -> None:
        """Inserts something into this list.

        Args:
            index: The index to insert `value` at in the same manner as
                `list.insert`.
            value: The element to insert.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().insert(index, value)

    @override
    def append(self, value: T, /) -> None:
        """Appends something to this list.

        Args:
            value: The element to append.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().append(value)

    @override
    def clear(self, /) -> None:
        """Removes all elements from this list.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().clear()

    @override
    def __iadd__(self, iterable: Iterable[T], /) -> Self:  # type: ignore[override]
        """Extends this list.

        Args:
            iterable: The iterable containing the elements to append to
                this list.

        Returns:
            This list.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().__iadd__(iterable)
        return self

    @override
    def extend(self, iterable: Iterable[T], /) -> None:
        """Extends this list.

        Args:
            iterable: The iterable containing the elements to append to
                this list.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().extend(iterable)

    @override
    def __imul__(self, value: SupportsIndex, /) -> Self:
        """Updates this list with its contents repeated.

        Args:
            value: How many times to repeat this list’s elements.

        Returns:
            This list.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        return super().__imul__(value)

    @override
    def pop(self, index: SupportsIndex = -1, /) -> T:
        """Returns the element at an index and removes it from this
        list.

        Args:
            index: The index of the element to return.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        return super().pop(index)

    @override
    def remove(self, value: T, /) -> None:
        """Removes an element from this list.

        Args:
            value: The element to remove.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().remove(value)

    @override
    def reverse(self) -> None:
        """Reverses this list in place.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().reverse()

    @override
    def sort(self, /, *, key: Callable[[T], SupportsRichComparison] | None = None, reverse: bool = False) -> None:
        """Sorts this list in place.

        Args:
            key: A function to apply to each element to get its sort
                key, or ``None`` for the identity function.
            reverse: Whether to sort in descending order.

        Raises:
            ValueError: If this list is frozen.
        """
        if self._frozen:
            raise ValueError('Modifying a frozen list')
        super().sort(key=key, reverse=reverse)


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
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        /,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        a3: str | Sequence[schema.Schema | str],
        a4: str | Sequence[schema.Schema | str],
        /,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        a3: str | Sequence[schema.Schema | str] | None,
        /,
        *,
        lookups: Sequence[str | None],
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        a3: str | Sequence[schema.Schema | str] | None,
        /,
        *,
        x_placements: Sequence[float | None],
        x_advances: Sequence[float | None] | None = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        a3: str | Sequence[schema.Schema | str] | None,
        /,
        *,
        x_advances: Sequence[float | None],
    ) -> None:
        ...

    def __init__(
        self,
        a1: str | Sequence[schema.Schema | str],
        a2: str | Sequence[schema.Schema | str],
        a3: str | Sequence[schema.Schema | str] | None = None,
        a4: str | Sequence[schema.Schema | str] | None = None,
        /,
        *,
        lookups: Sequence[str | None] | None = None,
        x_placements: Sequence[float | None] | None = None,
        x_advances: Sequence[float | None] | None = None,
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
        def _l(glyphs: str | Sequence[schema.Schema | str]) -> Sequence[schema.Schema | str]:
            ...

        def _l(glyphs: str | Sequence[schema.Schema | str] | None) -> Sequence[schema.Schema | str] | None:
            return [glyphs] if isinstance(glyphs, str) else glyphs

        if a4 is None and lookups is None and x_advances is None:
            assert a3 is None, 'Rule takes 2 or 4 inputs, given 3'
            a4 = a2
            a2 = a1
            a1 = []
            a3 = []
        assert (a4 is not None) + (lookups is not None) + (x_placements is not None or x_advances is not None) == 1, (
            'Rule can take exactly one of an output glyph/class list, a lookup list, or a position list')
        self.contexts_in: Final = _l(a1)
        self.inputs: Final = _l(a2)
        self.contexts_out: Final = _l(a3)
        self.outputs: Final = _l(a4)
        self.lookups: Final = lookups
        self.x_placements: Final = x_placements
        self.x_advances: Final = x_advances
        if lookups is not None:
            assert len(lookups) == len(self.inputs), f'There must be one lookup (or None) per input glyph ({len(lookups)} != {len(self.inputs)})'
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

        The only such missing feature is for a class in a ligature
        substitution’s output that is the same length as the only class
        in the input. If FEA supported it, an example would be::

            @INPUT = [i j];
            @OUTPUT = [f_i f_j];
            sub f @INPUT by @OUTPUT;

        This is desugared by unrolling all uses of the classes in
        parallel. For example::

            sub f i by f_i;
            sub f j by f_j;

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
            glyph: str | schema.Schema,
        ) -> fontTools.feaLib.ast.GlyphClassName | fontTools.feaLib.ast.GlyphName:
            if isinstance(glyph, str):
                return fontTools.feaLib.ast.GlyphClassName(class_asts[glyph])
            return fontTools.feaLib.ast.GlyphName(str(glyph))

        def glyphs_to_ast(
            glyphs: Iterable[str | schema.Schema],
        ) -> Sequence[fontTools.feaLib.ast.GlyphClassName | fontTools.feaLib.ast.GlyphName]:
            return [glyph_to_ast(glyph) for glyph in glyphs]

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
                return [fontTools.feaLib.ast.MultipleSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyph_to_ast(self.inputs[0]),
                    glyphs_to_ast(self.contexts_out),
                    glyphs_to_ast(self.outputs),
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
                        output_glyph_name,
                        in_contextual_lookup,
                    ))
                return asts
            else:
                return [fontTools.feaLib.ast.LigatureSubstStatement(
                    glyphs_to_ast(self.contexts_in),
                    glyphs_to_ast(self.inputs),
                    glyphs_to_ast(self.contexts_out),
                    str(output),
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

    def get_scripts(
        self,
        classes: Mapping[str, Sequence[schema.Schema]],
    ) -> AbstractSet[str]:
        """Returns the minimal set of script tags relevant to this rule.

        Args:
            classes: A mapping to glyph classes from their names.
        """
        def s_to_scripts(
            s: schema.Schema | str,
        ) -> AbstractSet[str]:
            if isinstance(s, str):
                scripts = set()
                for s_schema in classes[s]:
                    scripts |= s_schema.scripts
                return scripts
            return s.scripts

        def target_to_scripts(
            target: Sequence[schema.Schema | str] | None,
        ) -> AbstractSet[str]:
            scripts = set(KNOWN_SCRIPTS)
            if target:
                for s in target:
                    scripts &= s_to_scripts(s)
            return scripts

        return (target_to_scripts(self.contexts_in)
            & target_to_scripts(self.inputs)
            & target_to_scripts(self.contexts_out)
        )


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
        reverse: Whether this lookup is applied in reverse order. (The
            only reverse lookup type is the reverse chaining contextual
            single substitution, but this would cover other reverse
            lookup types if they existed.)
        rules: The list of rules.
    """

    @overload
    def __init__(
            self,
            feature: str,
            language: str,
            *,
            flags: int = ...,
            mark_filtering_set: str | None = ...,
            reverse: bool = ...,
    ) -> None:
        ...

    @overload
    def __init__(
            self,
            feature: None = ...,
            language: None = ...,
            *,
            flags: int = ...,
            mark_filtering_set: str | None = ...,
            reverse: bool = ...,
    ) -> None:
        ...

    def __init__(
            self,
            feature: str | None = None,
            language: str | None = None,
            *,
            flags: int = 0,
            mark_filtering_set: str | None = None,
            reverse: bool = False,
    ) -> None:
        """Initializes this `Lookup`.

        Args:
            feature: The ``feature`` attribute.
            language: The ``language`` attribute.
            flags: The ``flags`` attribute, except that the
                ``UseMarkFilteringSet`` flag must not be set, even if
                there is a mark filtering set.
            mark_filtering_set: The ``mark_filtering_set`` attribute.
            reverse: The ``reverse`` attribute.
        """
        assert flags & fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET == 0, 'UseMarkFilteringSet is added automatically'
        assert mark_filtering_set is None or flags & fontTools.otlLib.builder.LOOKUP_FLAG_IGNORE_MARKS == 0, 'UseMarkFilteringSet is not useful with IgnoreMarks'
        if mark_filtering_set:
            flags |= fontTools.otlLib.builder.LOOKUP_FLAG_USE_MARK_FILTERING_SET
        assert language is None or len(language) == 4, f"Language tag must be 4 characters long: '{language}'"
        assert feature is None or len(feature) == 4, f"Feature tag must be 4 characters long: '{feature}'"
        assert (feature is None) == (language is None), 'Not clear whether this is a named or a normal lookup'
        assert feature is None or feature in KNOWN_FEATURES
        self.feature: Final = feature
        self.language: Final = language
        self.flags: Final = flags
        self.mark_filtering_set: Final = mark_filtering_set
        self.required: Final = feature in REQUIRED_FEATURES
        self.reverse: Final = reverse
        self.rules: Final[FreezableList[Rule]] = FreezableList()

    def get_scripts(
        self,
        classes: Mapping[str, Sequence[schema.Schema]],
    ) -> AbstractSet[str]:
        """Returns the minimal set of script tags relevant to this
        lookup.

        Args:
            classes: A mapping to glyph classes from their names.
        """
        scripts: MutableSet[str] = set()
        for rule in self.rules:
            scripts |= rule.get_scripts(classes)
        return scripts

    def _get_sorted_scripts(self, features_to_scripts: Mapping[str, AbstractSet[str]]) -> Iterable[str]:
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
        if __debug__ and self.required:
            for script in scripts:
                assert any(self.feature in stage and self.feature in REQUIRED_FEATURES
                    for stage in KNOWN_SHAPE_PLANS[script]), (
                    f"The phase system does not support the feature '{self.feature}' for the script '{script}'")
        return scripts

    @overload
    def to_asts(
        self,
        features_to_scripts: None,
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: str,
    ) -> fontTools.feaLib.ast.LookupBlock:
        ...

    @overload
    def to_asts(
        self,
        features_to_scripts: Mapping[str, AbstractSet[str]],
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: int,
    ) -> tuple[fontTools.feaLib.ast.LookupBlock, fontTools.feaLib.ast.FeatureBlock]:
        ...

    def to_asts(
        self,
        features_to_scripts: Mapping[str, AbstractSet[str]] | None,
        class_asts: Mapping[str, fontTools.feaLib.ast.GlyphClassDefinition],
        named_lookup_asts: Mapping[str, fontTools.feaLib.ast.LookupBlock],
        name: str | int,
    ) -> fontTools.feaLib.ast.LookupBlock | tuple[fontTools.feaLib.ast.LookupBlock, fontTools.feaLib.ast.FeatureBlock]:
        """Converts this lookup to fontTools feaLib ASTs.

        Args:
            features_to_scripts: A mapping from feature tags to sets of
                script tags, if this lookup is anonymous, or else
                ``None``. If this is an anonymous lookup, the mapping
                must contain this lookup’s feature tag. The associated
                script tags, which must be a superset of what
                ``self.get_scripts`` returns for the classes
                corresponding to `class_asts`, are used in the second
                returned AST.
            class_asts: A map to glyph classes from their names.
            named_lookup_asts: A map to named lookup ASTs from their
                names.
            name: The name of this lookup, if it is a named lookup, or
                else an arbitrary number uniquely identifying this
                lookup among all anonymous lookups.

        Returns:
            One or two fontTools feaLib ASTs corresponding to this
            lookup. The first (or only) AST is a
            `fontTools.feaLib.ast.LookupBlock`. If this is an anonymous
            lookup, the return value is a tuple, whose second AST is a
            `fontTools.feaLib.ast.FeatureBlock`.
        """
        named_lookup = self.feature is None
        assert named_lookup == isinstance(name, str) == (features_to_scripts is None)
        contextual = any(r.is_contextual() for r in self.rules)
        multiple = any(r.is_multiple() for r in self.rules)
        if named_lookup:
            lookup_block = fontTools.feaLib.ast.LookupBlock(name)
            asts: fontTools.feaLib.ast.LookupBlock | tuple[fontTools.feaLib.ast.LookupBlock, fontTools.feaLib.ast.FeatureBlock] = lookup_block
        else:
            lookup_block = fontTools.feaLib.ast.LookupBlock(f'lookup_{name}')
            feature_block = fontTools.feaLib.ast.FeatureBlock(self.feature)
            assert features_to_scripts is not None
            for script in self._get_sorted_scripts(features_to_scripts):
                feature_block.statements.append(fontTools.feaLib.ast.ScriptStatement(script))
                feature_block.statements.append(fontTools.feaLib.ast.LanguageStatement(self.language))
                feature_block.statements.append(fontTools.feaLib.ast.LookupReferenceStatement(lookup_block))
            asts = (lookup_block, feature_block)
        lookup_block.statements.append(fontTools.feaLib.ast.LookupFlagStatement(
            self.flags,
            markFilteringSet=fontTools.feaLib.ast.GlyphClassName(class_asts[self.mark_filtering_set])
                if self.mark_filtering_set
                else None))
        lookup_block.statements.extend({
                ast.asFea(): ast
                    for r in self.rules
                    for ast in r.to_asts(class_asts, named_lookup_asts, contextual, multiple, self.reverse)
            }.values())
        return asts

    def freeze(self) -> None:
        """Freezes the list of rules.
        """
        self.rules.freeze()

    def append(self, rule: Rule) -> None:
        """Adds a rule to the end of the list of rules.

        Args:
            rule: A rule.

        Raises:
            ValueError: If the list of rules is frozen.
        """
        self.rules.append(rule)

    def extend(self, other: Lookup) -> None:
        """Extends this lookup with rules from another lookup.

        Rules are added to the end of this lookup’s list, ending up in
        the same order as they are in `other`.

        The lookups must agree in their features and languages, or lack
        thereof, and in whether they are required and are reversed.

        Args:
            other: A lookup.

        Raises:
            ValueError: If the list of rules is frozen.
        """
        assert self.feature == other.feature, f"Incompatible features: '{self.feature}' != '{other.feature}'"
        assert self.language == other.language, f"Incompatible languages: '{self.language}' != '{other.language}'"
        assert self.required == other.required, f'Incompatible required values: {self.required} != {other.required}'
        assert self.reverse == other.reverse, f'Incompatible reverse values: {self.reverse} != {other.reverse}'
        self.rules.extend(other.rules)


if TYPE_CHECKING:
    AddRule = Callable[[Lookup, Rule], None]


def _add_rule(
    autochthonous_schemas: Iterable[schema.Schema],
    output_schemas: OrderedSet[schema.Schema],
    classes: Mapping[str, FreezableList[schema.Schema]],
    named_lookups: Mapping[str, Lookup],
    lookup: Lookup,
    rule: Rule,
) -> None:
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
    """
    assert rule.contexts_out is not None

    if __debug__:
        if lookup.mark_filtering_set:
            for mark in classes[lookup.mark_filtering_set]:
                assert mark.glyph_class == GlyphClass.MARK, f'''{mark} has GDEF class {mark.glyph_class}, but it appears in {
                    lookup.mark_filtering_set}, a mark filtering set'''

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
                ,
            )

        def check_ignored(target_part: Iterable[schema.Schema | str]) -> None:
            """Asserts that a rule part contains no ignored schemas.

            It is not useful for a rule to mention an ignored schema. It
            is probably a bug if one does.

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
        check_ignored(rule.contexts_out)

    if not rule.get_scripts(classes):
        # If a rule has no scripts, its pieces must have non-overlapping script
        # sets, so the rule can never apply and should be skipped. As an
        # exception, if a class in the rule is empty, the phase is probably not
        # done populating its classes, so don’t skip the rule yet.
        rule_pieces = [*rule.contexts_in, *rule.inputs, *rule.contexts_out]
        if not any(isinstance(s, str) and not classes[s] for s in rule_pieces):
            for s in rule_pieces:
                if isinstance(s, str):
                    classes[s].freeze()
            return

    for input in rule.inputs:
        if isinstance(input, str):
            if all(s in autochthonous_schemas for s in classes[input]):
                classes[input].freeze()
                return
        elif input in autochthonous_schemas:
            return

    def is_prefix(maybe_prefix: Sequence[schema.Schema | str], full: Sequence[schema.Schema | str]) -> bool:
        return len(maybe_prefix) <= len(full) and all(mp_f[0] == mp_f[1] for mp_f in zip(maybe_prefix, full, strict=False))

    def is_suffix(maybe_suffix: Sequence[schema.Schema | str], full: Sequence[schema.Schema | str]) -> bool:
        return len(maybe_suffix) <= len(full) and all(mp_f[0] == mp_f[1] for mp_f in zip(reversed(maybe_suffix), reversed(full), strict=False))

    if any(r.is_contextual() for r in lookup.rules):
        for previous_rule in lookup.rules:
            assert previous_rule.contexts_out is not None
            if (previous_rule.inputs == rule.inputs
                and is_suffix(previous_rule.contexts_in, rule.contexts_in)
                and is_prefix(previous_rule.contexts_out, rule.contexts_out)
                and (previous_rule.contexts_in != rule.contexts_in or previous_rule.contexts_out != rule.contexts_out)
            ):
                return

    def remove_unconditionally_substituted_schemas() -> None:
        """Removes schemas from `output_schemas` that are
        unconditionally substituted by `rule`.

        A schema is unconditionally substituted by `rule` if `rule` is a
        non-contextual rule of a required lookup, the input of `rule`
        contains only one element which either is or contains that
        schema, and no other preceding rule in the same lookup uses that
        schema in its input.
        """
        if not (lookup.required
            and not rule.contexts_in
            and not rule.contexts_out
            and len(rule.inputs) == 1
        ):
            return
        input = rule.inputs[0]
        unconditionally_substituted_schemas = set(classes[input]) if isinstance(input, str) else {input}
        for previous_rule in lookup.rules:
            for previous_input in previous_rule.inputs:
                if isinstance(previous_input, str):
                    unconditionally_substituted_schemas.difference_update(classes[previous_input])
                else:
                    unconditionally_substituted_schemas.discard(previous_input)
        for schema_to_remove in unconditionally_substituted_schemas:
            output_schemas.remove(schema_to_remove)

    remove_unconditionally_substituted_schemas()
    lookup.append(rule)

    registered_lookups: MutableSet[str | None] = {None}

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
            for named_lookup in rule.lookups:
                if named_lookup not in registered_lookups:
                    assert named_lookup is not None
                    registered_lookups.add(named_lookup)
                    froze = False
                    for named_lookup_rule in named_lookups[named_lookup].rules:
                        if register_output_schemas(named_lookup_rule):
                            froze = True
                    if froze:
                        named_lookups[named_lookup].freeze()
        return False

    register_output_schemas(rule)


if TYPE_CHECKING:
    Phase = Callable[
        [
            Arg(Builder, 'builder'),
            Arg(OrderedSet[schema.Schema], 'original_schemas'),
            Arg(OrderedSet[schema.Schema], 'schemas'),
            Arg(OrderedSet[schema.Schema], 'new_schemas'),
            Arg(PrefixView[FreezableList[schema.Schema]], 'classes'),
            Arg(PrefixView[Lookup], 'named_lookups'),
            Arg(AddRule, 'add_rule'),
        ],
        Sequence[Lookup],
    ]


def run_phases(
    builder: Builder,
    all_input_schemas: Iterable[schema.Schema],
    phases: Iterable[Phase],
    all_classes: collections.defaultdict[str, FreezableList[schema.Schema]] | None = None,
) -> tuple[
    OrderedSet[schema.Schema],
    Iterable[schema.Schema],
    MutableSequence[tuple[Lookup, Phase]],
    collections.defaultdict[str, FreezableList[schema.Schema]],
    MutableMapping[str, tuple[Lookup, Phase]],
]:
    """Runs a sequence of phases.

    Args:
        builder: The source of everything.
        all_input_schemas: The input schemas for the first iteration of
            the first phase.
        phases: The phases to run.
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
    previous_feature = None
    all_schemas = OrderedSet(all_input_schemas)
    all_input_schemas = OrderedSet(all_input_schemas)
    all_lookups_with_phases: MutableSequence[tuple[Lookup, Phase]] = []
    if all_classes is None:
        all_classes = collections.defaultdict(FreezableList)
    all_named_lookups_with_phases: dict[str, tuple[Lookup, Phase]] = {}
    for phase_index, phase in enumerate(phases, start=schema.CURRENT_PHASE_INDEX + 1):
        schema.CURRENT_PHASE_INDEX = phase_index
        all_output_schemas: OrderedSet[schema.Schema] = OrderedSet()
        autochthonous_schemas: OrderedSet[schema.Schema] = OrderedSet()
        original_input_schemas = OrderedSet(all_input_schemas)
        new_input_schemas = OrderedSet(all_input_schemas)
        output_schemas = OrderedSet(all_input_schemas)
        classes = PrefixView(phase, all_classes)
        named_lookups: PrefixView[Lookup] = PrefixView(phase, {})
        lookups: Sequence[Lookup] | None = None
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
            if builder.unjoined and any(lookup.feature not in SUBSET_FEATURES for lookup in output_lookups):
                assert all(lookup.feature not in SUBSET_FEATURES for lookup in output_lookups), (
                    f'Mix of subset and non-subset features: {[lookup.feature for lookup in output_lookups]}')
                output_lookups = []
                break
            if lookups is None:
                lookups = output_lookups
                for lookup in lookups:
                    previous_feature_index = -1
                    feature_index = -1
                    for shape_plan in KNOWN_SHAPE_PLANS.values():
                        for i, stage in enumerate(shape_plan):
                            if previous_feature in stage:
                                previous_feature_index = i
                            if lookup.feature in stage:
                                feature_index = i
                    assert previous_feature_index <= feature_index, f"Feature '{previous_feature}' must not follow feature '{lookup.feature}'"
                    previous_feature = lookup.feature
            else:
                assert len(lookups) == len(output_lookups), f'Incompatible lookup counts for phase {phase.__name__}'
                for i, lookup in enumerate(lookups):
                    lookup.extend(output_lookups[i])
            match output_lookups:
                case []:
                    might_have_feedback = False
                case [lookup]:
                    might_have_feedback = False
                    for rule in lookup.rules:
                        if rule.contexts_out if lookup.reverse else rule.contexts_in:
                            might_have_feedback = True
                            break
                case _:
                    might_have_feedback = True
            features: set[str] = {lookup.feature for lookup in lookups}  # type: ignore[misc]
            for output_schema in output_schemas:
                all_output_schemas.add(output_schema)
            new_input_schemas = OrderedSet()
            if might_have_feedback:
                for output_schema in output_schemas:
                    if output_schema not in all_input_schemas:
                        all_input_schemas.add(output_schema)
                        autochthonous_schemas.add(output_schema)
                        new_input_schemas.add(output_schema)
                        output_schema.features = features
            else:
                for output_schema in output_schemas:
                    if output_schema not in all_input_schemas:
                        output_schema.features = features
        if lookups is None:
            continue
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
