# Copyright 2018-2019, 2022-2025 David Corbett
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

"""Miscellaneous constants, functions, and classes.
"""


from __future__ import annotations

from collections.abc import MutableMapping
import enum
import functools
from typing import Final
from typing import Literal
from typing import Self
from typing import TYPE_CHECKING
from typing import overload
from typing import override

import fontTools.subset
import uharfbuzz


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import ItemsView
    from collections.abc import Iterable
    from collections.abc import Iterator
    from collections.abc import KeysView
    from collections.abc import Mapping
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet

    from _typeshed import SupportsRichComparison


#: The regular font’s cap height.
CAP_HEIGHT: Final[float] = 714


#: The factor of the cap height in the regular font by which brackets
#: and related punctuation reach above the cap height or below the
#: baseline.
BRACKET_Y_FACTOR: Final[float] = 0.27


#: The lowest point of brackets and related punctuation in the regular
#: font.
BRACKET_DEPTH: Final[float] = -BRACKET_Y_FACTOR * CAP_HEIGHT


#: The highest point of brackets and related punctuation in the regular
#: font.
BRACKET_HEIGHT: Final[float] = (1 + BRACKET_Y_FACTOR) * CAP_HEIGHT


#: The lowest point of crosses and related symbols in the regular font.
CROSS_DEPTH: Final[float] = -0.4 * CAP_HEIGHT


#: The highest point of crosses and related symbols in the regular font.
CROSS_HEIGHT: Final[float] = 1.1 * CAP_HEIGHT


#: The factor of the cap height in the regular font by which pictographs
#: reach above the cap height or below the baseline.
PICTOGRAPH_Y_FACTOR: Final[float] = 0.5


#: The lowest point of pictographs in the regular font.
PICTOGRAPH_DEPTH: Final[float] = -PICTOGRAPH_Y_FACTOR * CAP_HEIGHT


#: The highest point of pictographs in the regular font.
PICTOGRAPH_HEIGHT: Final[float] = (1 + PICTOGRAPH_Y_FACTOR) * CAP_HEIGHT


#: The factor of the cap height in the regular font by which to scale
#: digits to get their numerator, denominator, superscript, and
#: subscript forms.
SMALL_DIGIT_FACTOR: Final[float] = 0.633


#: The factor of the cap height in the regular font by which
#: superscripts and subscripts reach above the cap height or below the
#: baseline.
SCRIPT_Y_FACTOR: Final[float] = 0.18


#: The lowest point of subscripts in the regular font.
SUBSCRIPT_DEPTH: Final[float] = -SCRIPT_Y_FACTOR * CAP_HEIGHT


#: The highest point of superscripts in the regular font.
SUPERSCRIPT_HEIGHT: Final[float] = (1 + SCRIPT_Y_FACTOR) * CAP_HEIGHT


#: The regular font’s x height.
X_HEIGHT: Final[float] = 507


class CloneDefault(enum.Enum):
    """The type of `CLONE_DEFAULT`.
    """

    _CLONE_DEFAULT = enum.auto()


#: An object that various classes’ ``clone`` methods interpret as the
#: value of the relevant attribute in the object being cloned.
CLONE_DEFAULT: Final = CloneDefault._CLONE_DEFAULT


#: The non-negative angle by which to offset the angle at the endpoint
#: of a curve when checking whether lines intersect. For example, a
#: counterclockwise curve that starts out going 0° should be treated
#: like a ``CURVE_OFFSET``° line at the entry point. Clockwise curves
#: are offset in the opposite direction from counterclockwise curves.
#: Curves at exit points are offset in the opposite direction from
#: curves at entry points.
CURVE_OFFSET: Final[float] = 75


#: The default side bearing of a glyph.
DEFAULT_SIDE_BEARING: Final[float] = 85


#: A small positive number.
EPSILON: Final[float] = 1e-5


#: The maximum depth of a shorthand overlap sequence, i.e. the maximum
#: number of overlap controls connecting a child letter to the root of
#: the tree, plus one for the root itself. The maximum known attested
#: depth is 3, but there is no reason an overlap sequence could not be
#: arbitrarily deep, especially when using U+1BCA1 SHORTHAND FORMAT
#: CONTINUING OVERLAP.
MAX_TREE_DEPTH: Final[int] = 3


#: The maximum width of a shorthand overlap sequence, i.e. the maximum
#: number of overlap controls that can immediately follow a letter. The
#: maximum known attested depth in any mode supposedly supported by
#: Unicode is 2. Another much more than that would not be practical.
MAX_TREE_WIDTH: Final[int] = 2


#: The minimum distance between two different strokes.
MINIMUM_STROKE_GAP: Final[float] = 70


#: The thickness of a light line in the regular font.
REGULAR_LIGHT_LINE: Final[float] = 70


#: The factor by which to scale the light line’s thickness to get the
#: shaded line’s thickness.
SHADING_FACTOR: Final[float] = 12 / 7


#: The strikeout height (yStrikeoutPosition in OS/2).
STRIKEOUT_POSITION: Final[float] = 258


#: The number of digits to use in the fixed-width integers used for x
#: offsets. This is somewhat arbitrary. Higher values let the font
#: support wider stenograms without overflow, but they are less
#: efficient and can make the GSUB table too big to compile.
WIDTH_MARKER_PLACES: Final[int] = 7


#: The radix of the fixed-width integers used for x offsets. The value
#: must be a positive even integer but is otherwise somewhat arbitrary.
#: Higher values allow for lower `WIDTH_MARKER_PLACES` values with the
#: same supported x offset range. Lower values imply a smaller Cartesian
#: product of the set of possible digit values, which means fewer
#: substitution rules. Both are efficient and inefficient in different
#: ways; the current value seems like a good trade-off.
WIDTH_MARKER_RADIX: Final[int] = 4


assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'


_INITIAL_STAGES: Final[Sequence[AbstractSet[str]]] = [
    {
        'rvrn',
    },
    {
        'dnom',
        'frac',
        'numr',
    },
]


_COMMON_DISCRETIONARY_FEATURES: Final[AbstractSet[str]] = {
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


_COMMON_REQUIRED_FEATURES: Final[AbstractSet[str]] = {
    'abvm',
    'blwm',
    'curs',
    'dist',
    'mark',
    'mkmk',
    'rclt',
    'rlig',
}


#: The set of features that are not necessarily applied automatically to
#: all characters by any shaper that enables them. This includes
#: features like 'dlig' that are meant to be enabled by the user, as
#: well as features like 'dnom' that may be enabled automatically but
#: not to all characters.
DISCRETIONARY_FEATURES: Final[AbstractSet[str]] = {
    *_COMMON_DISCRETIONARY_FEATURES,
    'dnom',
    'numr',
}


#: The set of features that are guaranteed to be applied to all
#: characters by any shaper that enables them. (This assumes no required
#: features are disabled by the user, which is technically possible but
#: not recommended).
REQUIRED_FEATURES: Final[AbstractSet[str]] = {
    *_COMMON_REQUIRED_FEATURES,
    'abvs',
    'blws',
    'haln',
    'locl',
    'pres',
    'psts',
    'rvrn',
}


#: The union of `DISCRETIONARY_FEATURES` and `REQUIRED_FEATURES`.
KNOWN_FEATURES: Final[AbstractSet[str]] = DISCRETIONARY_FEATURES | REQUIRED_FEATURES


#: A mapping from script tags to their features, organized by shape
#: plan. This includes all features, required or discretionary. A shape
#: plan is represented as a list of stages, where a stage is a set of
#: feature tags. All the features in one stage are applied before the
#: features in the next stage.
KNOWN_SHAPE_PLANS: Final[Mapping[str, Sequence[AbstractSet[str]]]] = {
    'DFLT': [
        *_INITIAL_STAGES,
        {
            *_COMMON_DISCRETIONARY_FEATURES,
            *_COMMON_REQUIRED_FEATURES,
            'locl',
        },
    ],
    'dupl': [
        *_INITIAL_STAGES,
        {
            *_COMMON_DISCRETIONARY_FEATURES,
            *_COMMON_REQUIRED_FEATURES,
            'abvs',
            'blws',
            'haln',
            'pres',
            'psts',
        },
    ],
}


assert all(
        sum(map(len, shape_plan)) == len(set().union(*shape_plan))
        for shape_plan in KNOWN_SHAPE_PLANS.values()
    ), 'A shape plan in `KNOWN_SHAPE_PLANS` contains two stages that share the same feature'


if __debug__:
    _really_known_features = {feature for shape_plan in KNOWN_SHAPE_PLANS.values() for stage in shape_plan for feature in stage}
    assert KNOWN_FEATURES <= _really_known_features, (
        f'''`KNOWN_FEATURES` contains extra features: {', '.join(f"'{feature}'" for feature in KNOWN_FEATURES - _really_known_features)}''')


#: The list of script tags that can appear in the generated font.
KNOWN_SCRIPTS: Final[Iterable[str]] = sorted(KNOWN_SHAPE_PLANS)


#: The set of features that should be included in the subsetted font.
SUBSET_FEATURES: AbstractSet[str] = (frozenset(fontTools.subset.Options().layout_features)
    - {'abvs', 'blwm', 'curs', 'dist', 'rclt'}
    | {'subs', 'sups'}
)


@functools.cache
def cps_to_scripts(cps: Sequence[int]) -> set[str]:
    """Converts a code point sequence to its set of script tags.

    Args:
        cps: A code point sequence. It is assumed that the code points
            all appear in the same item, meaning they have at most one
            distinct script tag.

    Returns:
        The set of all script tags such that a rule in a lookup
        associated with one of those tags could possibly apply to a
        glyph that corresponds to those code points. The return value is
        a subset of the full set of known script tags (`KNOWN_SCRIPTS`).

        If `cps` contains only script-neutral code points, the full set
        is returned; otherwise, the returned set contains a single tag.
        That single tag is ``'DFLT'`` if `KNOWN_SCRIPTS` does not
        contain the true specific script tag.
    """
    buffer = uharfbuzz.Buffer()
    buffer.add_codepoints([*cps])
    buffer.guess_segment_properties()
    if buffer.script is None:
        return set(KNOWN_SCRIPTS)
    script = buffer.script.lower()
    if script not in KNOWN_SCRIPTS:
        return {'DFLT'}
    return {script}


def mkmk(anchor: str) -> str:
    """Returns the name of a 'mkmk' anchor that is analogous to a 'mark'
    anchor.

    Args:
        anchor: The name of a 'mark' anchor.
    """
    return f'mkmk_{anchor}'


@enum.unique
class GlyphClass(enum.StrEnum):
    """A glyph class.

    The members’ values are all valid values for the ``glyphclass``
    attribute of a ``fontforge.glyph`` object.
    """

    #: The class of a spacing glyph that does not participate in cursive
    #: joining.
    BLOCKER = 'noclass'

    #: The class of a spacing glyph that participates in cursive
    #: joining.
    JOINER = 'baseligature'

    #: The class of a mark glyph.
    MARK = 'mark'


class Type(enum.Enum):
    """How a character cursively joins to adjacent characters.

    This is analogous to Unicode’ Joining_Type property but specific
    to Duployan.
    """

    #: The type of a character that cursively joins to adjacent
    #: characters without changing its orientation.
    JOINING = enum.auto()

    #: The type of a character that changes its orientation when
    #: cursively joining to adjacent characters.
    ORIENTING = enum.auto()

    #: The type of a character that does not cursively join to adjacent
    #: characters.
    NON_JOINING = enum.auto()


class Context:
    """Everything about a shape’s endpoint that is relevant to
    contextualization.

    A shape has two endpoints: the entry and the exit. Each endpoint has
    certain properties which influence the contextual forms of adjacent
    shapes, which are all together called its context. A context ignores
    everything about the shape that is not right at the end or very
    close to it.

    Attributes:
        angle: The angle at which the notional pen is traveling at the
            endpoint. If this is ``None``, that indicates that no context
            information is available, and the other fields must all have
            their default values.
        clockwise: Whether the pen is curving clockwise, or ``None`` if
            the pen is not curving at all.
        ou: Whether this is the endpoint of the inner curve of U+1BC5B
            DUPLOYAN LETTER OU or similar.
        minor: Whether the fields of this context are only applicable to
            a very small bit near the end of the shape, suggesting that
            whatever implications they would normally apply to do not
            necessarily hold. This is currently only used for U+1BC50
            DUPLOYAN LETTER YE, indicating that, although it looks at
            its endpoints like a line letter, it is not, and therefore
            does not induce a tick in adjacent letters.
        ignorable_for_topography: Whether the shape can appear in an
            orienting sequence. In an orienting sequence, one character
            determines how the rest are oriented, and the rest are
            ignored by the main topographical phases.
        diphthong_start: Whether the shape is a non-final element of a
            diphthong ligature.
        diphthong_end: Whether the shape is a non-initial element of a
            diphthong ligature.
    """

    @overload
    def __init__(
        self,
        angle: float,
        clockwise: bool | None = ...,
        *,
        ou: bool = ...,
        minor: bool = ...,
        ignorable_for_topography: bool = ...,
        diphthong_start: bool = ...,
        diphthong_end: bool = ...,
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        angle: None = ...,
        clockwise: Literal[False] = ...,
        *,
        ou: Literal[False] = ...,
        minor: Literal[False] = ...,
        ignorable_for_topography: Literal[False] = ...,
        diphthong_start: Literal[False] = ...,
        diphthong_end: Literal[False] = ...,
    ) -> None:
        ...

    def __init__(
        self,
        angle: float | None = None,
        clockwise: bool | None = None,
        *,
        ou: bool = False,
        minor: bool = False,
        ignorable_for_topography: bool = False,
        diphthong_start: bool = False,
        diphthong_end: bool = False,
    ) -> None:
        """Initializes this `Context`.

        Args:
            angle: The ``angle`` attribute.
            clockwise: The ``clockwise`` attribute.
            ou: The ``ou`` attribute.
            minor: The ``minor`` attribute.
            ignorable_for_topography: The ``ignorable_for_topography``
                attribute.
            diphthong_start: The ``diphthong_start`` attribute.
            diphthong_end: The ``diphthong_end`` attribute.
        """
        assert clockwise is not None or not ignorable_for_topography
        self.angle: Final = float(angle) if angle is not None else None
        self.clockwise: Final = clockwise
        self.ou: Final = ou
        self.minor: Final = minor
        self.ignorable_for_topography: Final = ignorable_for_topography
        self.diphthong_start: Final = diphthong_start
        self.diphthong_end: Final = diphthong_end

    def clone(
        self,
        *,
        angle: CloneDefault | float | None = CLONE_DEFAULT,
        clockwise: CloneDefault | bool | None = CLONE_DEFAULT,
        ou: CloneDefault | bool = CLONE_DEFAULT,
        minor: CloneDefault | bool = CLONE_DEFAULT,
        ignorable_for_topography: CloneDefault | bool = CLONE_DEFAULT,
        diphthong_start: CloneDefault | bool = CLONE_DEFAULT,
        diphthong_end: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,  # type: ignore[arg-type]
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            ou=self.ou if ou is CLONE_DEFAULT else ou,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            ignorable_for_topography=self.ignorable_for_topography if ignorable_for_topography is CLONE_DEFAULT else ignorable_for_topography,
            diphthong_start=self.diphthong_start if diphthong_start is CLONE_DEFAULT else diphthong_start,
            diphthong_end=self.diphthong_end if diphthong_end is CLONE_DEFAULT else diphthong_end,
        )

    @override
    def __repr__(self) -> str:
        return f'''Context({
                self.angle
            }, {
                self.clockwise
            }, ou={
                self.ou
            }, minor={
                self.minor
            }, ignorable_for_topography={
                self.ignorable_for_topography
            }, diphthong_start={
                self.diphthong_start
            }, diphthong_end={
                self.diphthong_end
            })'''

    @override
    def __str__(self) -> str:
        if self.angle is None:
            return ''
        return f'''{
            self.angle
        }{
            '' if self.clockwise is None else 'neg' if self.clockwise else 'pos'
        }{
            '.ou' if self.ou else ''
        }{
            '.minor' if self.minor else ''
        }{
            '.ori' if self.ignorable_for_topography else ''
        }{
            '.diph' if self.diphthong_start or self.diphthong_end else ''
        }{
            '1' if self.diphthong_start else ''
        }{
            '2' if self.diphthong_end else ''
        }'''

    @override
    def __eq__(self, other: object) -> bool:
        if not (isinstance(self, type(other)) and isinstance(other, type(self))):
            return NotImplemented
        return (self.angle == other.angle
            and self.clockwise == other.clockwise
            and self.ou == other.ou
            and self.minor == other.minor
            and self.ignorable_for_topography == other.ignorable_for_topography
            and self.diphthong_start == other.diphthong_start
            and self.diphthong_end == other.diphthong_end
        )

    @override
    def __ne__(self, other: object) -> bool:
        eq = self == other
        return eq if eq is NotImplemented else not eq

    @override
    def __hash__(self) -> int:
        return (
            hash(self.angle)
            ^ hash(self.clockwise)
            ^ hash(self.ou)
            ^ hash(self.minor)
            ^ hash(self.ignorable_for_topography)
            ^ hash(self.diphthong_start)
            ^ hash(self.diphthong_end)
        )

    def as_reversed(self) -> Self:
        """Returns the reversed form of this context.

        The reversed form is the context where the notional pen travels
        the same path as in this context but in reverse.
        """
        return self.clone(
            angle=None if self.angle is None else (self.angle + 180) % 360,
            clockwise=None if self.clockwise is None else not self.clockwise,
        )

    def has_clockwise_loop_to(self, other: Context) -> bool:
        """Returns whether the shortest loop to another context is
        clockwise.

        There are always two possible loops going from this context (the
        entry) to the other (the exit). This method returns whether the
        shorter one, measured in terms of the arc it describes, is
        clockwise. If both loops’ arcs are equal in magnitude, it
        returns ``False``.

        If this context is curved, it is offset by ``CURVE_OFFSET``. The
        same goes for the other one.

        Args:
            other: A context.
        """
        if self.angle is None or other.angle is None:
            return False
        da = (other.angle - self.angle) % 360
        maximum_da = 180.0
        if self.clockwise:
            maximum_da += CURVE_OFFSET
        elif self.clockwise is False:
            maximum_da -= CURVE_OFFSET
        if other.clockwise:
            maximum_da += CURVE_OFFSET
        elif other.clockwise is False:
            maximum_da -= CURVE_OFFSET
        return 0 < da < maximum_da


#: The context representing a lack of contextual information.
NO_CONTEXT: Final[Context] = Context()


class OrderedSet[T](dict[T, None]):
    """An ordered set.

    It is a `dict` where the values are all ``None``, with a set-like
    API on top.
    """

    def __init__(
        self,
        iterable: Iterable[T] | None = None,
        /,
    ) -> None:
        """Initializes this `OrderedSet`.

        Args:
            iterable: An optional iterable whose items are to be added
                to this set in the iterable’s natural iteration order.
        """
        super().__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item: T, /) -> None:
        """Adds an item to this set.

        Args:
            item: An item.
        """
        self[item] = None

    def remove(self, item: T, /) -> None:
        """Removes an item from this set.

        If the item is not present in this set, nothing happens.

        Args:
            item: An item.
        """
        self.pop(item, None)

    def sorted(self, /, *, key: Callable[[T], SupportsRichComparison] | None = None, reverse: bool = False) -> list[T]:
        """Returns a sorted list of the elements in this set.

        The sort is stable.

        Args:
            key: An optional key function by which to sort the items.
                This must be given if the items are not inherently
                ordered.
            reverse: Whether to sort in descending order.
        """
        return sorted(self.keys(), key=key, reverse=reverse)  # type: ignore[arg-type, type-var]


class PrefixView[T](MutableMapping[str, T]):
    """A mutable view of a string-keyed mapping with a prefix applied to
    all keys.

    This sort of view is useful for sharing a single mapping between
    multiple functions where each function’s values should be namespaced
    by that function. There is a “global” escape hatch for values that
    should be shared between functions.

    Every key in the underlying mapping has a prefix. This view allows
    the user to omit the prefix for all normal operations (getting,
    setting, etc.) and the prefix is added internally.

    There are two possible prefixes in a given view’s underlying
    mapping. One is derived from the name of a given function plus
    ``".."``. The other is ``"global.."``. Only the former is
    automatically added by this view. If a key has the global prefix,
    the view passes it through to the underlying mapping unchanged;
    otherwise, a key passed to a method of a view must not contain
    ``".."``.
    """

    def __init__(
        self,
        source: function,  # noqa: F821
        delegate: MutableMapping[str, T],
    ) -> None:
        """Initializes this `PrefixView`.

        Args:
            source: A function from which to derive the prefix.
            delegate: The mapping to wrap.
        """
        self._prefix: Final = f'{source.__module__}.{source.__qualname__}..'
        self._delegate: Final = delegate

    def _prefixed(self, key: str) -> str:
        """Returns a key with the prefix prepended to it if necessary.

        It is not necessary to prepend the prefix if the key already
        uses the global prefix.

        Args:
            key: The key to which to prepend the prefix.
        """
        is_global = key.startswith('global..')
        assert len(key.split('..')) == 1 + is_global, f'Invalid key: {key!r}'
        return key if is_global else self._prefix + key

    @override
    def __getitem__(self, key: str, /) -> T:
        """Returns the item associated with a prefixed key.

        Args:
            key: The key to which to prepend the prefix.
        """
        return self._delegate[self._prefixed(key)]

    @override
    def __setitem__(self, key: str, value: T, /) -> None:
        """Maps a prefixed key to a value.

        Args:
            key: The key to which to prepend the prefix.
            value: An item.
        """
        self._delegate[self._prefixed(key)] = value

    @override
    def __delitem__(self, key: str, /) -> None:
        """Deletes an entry from this mapping.

        Args:
            key: The key to which to prepend the prefix.

        Raises:
            KeyError: If the prefixed key is not mapped to anything.
        """
        del self._delegate[self._prefixed(key)]

    @override
    def __contains__(self, item: object, /) -> bool:
        """Returns whether a prefixed key is mapped to a value.

        Args:
            item: The possible key to which to prepend the prefix.
        """
        return isinstance(item, str) and self._prefixed(item) in self._delegate

    @override
    def __iter__(self, /) -> Iterator[str]:
        return iter(self._delegate)

    @override
    def __len__(self, /) -> int:
        return len(self._delegate)

    @override
    def keys(self) -> KeysView[str]:
        return self._delegate.keys()

    @override
    def items(self) -> ItemsView[str, T]:
        return self._delegate.items()
