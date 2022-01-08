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

from __future__ import annotations


__all__ = [
    'BRACKET_DEPTH',
    'BRACKET_HEIGHT',
    'CAP_HEIGHT',
    'CLONE_DEFAULT',
    'CURVE_OFFSET',
    'Context',
    'EPSILON',
    'GlyphClass',
    'MAX_TREE_DEPTH',
    'MAX_TREE_WIDTH',
    'MINIMUM_STROKE_GAP',
    'NO_CONTEXT',
    'OrderedSet',
    'PrefixView',
    'REGULAR_LIGHT_LINE',
    'SHADING_FACTOR',
    'STRIKEOUT_POSITION',
    'Type',
    'WIDTH_MARKER_PLACES',
    'WIDTH_MARKER_RADIX',
    'mkmk',
]


from collections.abc import Collection
from collections.abc import ItemsView
from collections.abc import MutableMapping
import enum
from typing import Callable
from typing import ClassVar
from typing import Final
from typing import Generic
from typing import Iterable
from typing import Optional
from typing import TypeVar


CAP_HEIGHT: Final[float] = 714


BRACKET_DEPTH: Final[float] = -0.27 * CAP_HEIGHT


BRACKET_HEIGHT: Final[float] = 1.27 * CAP_HEIGHT


CLONE_DEFAULT = object()


CURVE_OFFSET: Final[float] = 75


DEFAULT_SIDE_BEARING: Final[float] = 85


EPSILON: Final[float] = 1e-5


MAX_TREE_DEPTH: Final[int] = 3


MAX_TREE_WIDTH: Final[int] = 2


MINIMUM_STROKE_GAP: Final[float] = 70


REGULAR_LIGHT_LINE: Final[float] = 70


SHADING_FACTOR: Final[float] = 12 / 7


STRIKEOUT_POSITION: Final[float] = 258


WIDTH_MARKER_PLACES: Final[int] = 7


WIDTH_MARKER_RADIX: Final[int] = 4


assert WIDTH_MARKER_RADIX % 2 == 0, 'WIDTH_MARKER_RADIX must be even'


def mkmk(anchor: str) -> str:
    return f'mkmk_{anchor}'


class GlyphClass:
    BLOCKER = 'baseglyph'
    JOINER = 'baseligature'
    MARK = 'mark'


class Type(enum.Enum):
    JOINING = enum.auto()
    ORIENTING = enum.auto()
    NON_JOINING = enum.auto()


class Context:
    def __init__(
        self,
        angle: Optional[float] = None,
        clockwise: Optional[bool] = None,
        *,
        minor: bool = False,
        ignorable_for_topography: bool = False,
        diphthong_start: bool = False,
        diphthong_end: bool = False,
    ) -> None:
        assert clockwise is not None or not ignorable_for_topography
        self.angle: Final = float(angle) if angle is not None else None
        self.clockwise: Final = clockwise
        self.minor: Final = minor
        self.ignorable_for_topography: Final = ignorable_for_topography
        self.diphthong_start: Final = diphthong_start
        self.diphthong_end: Final = diphthong_end

    def clone(
        self,
        *,
        angle=CLONE_DEFAULT,
        clockwise=CLONE_DEFAULT,
        minor=CLONE_DEFAULT,
        ignorable_for_topography=CLONE_DEFAULT,
        diphthong_start=CLONE_DEFAULT,
        diphthong_end=CLONE_DEFAULT,
    ):
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            ignorable_for_topography=self.ignorable_for_topography if ignorable_for_topography is CLONE_DEFAULT else ignorable_for_topography,
            diphthong_start=self.diphthong_start if diphthong_start is CLONE_DEFAULT else diphthong_start,
            diphthong_end=self.diphthong_end if diphthong_end is CLONE_DEFAULT else diphthong_end,
        )

    def __repr__(self):
        return f'''Context({
                self.angle
            }, {
                self.clockwise
            }, minor={
                self.minor
            }, ignorable_for_topography={
                self.ignorable_for_topography
            }, diphthong_start={
                self.diphthong_start
            }, diphthong_end={
                self.diphthong_end
            })'''

    def __str__(self):
        if self.angle is None:
            return ''
        return f'''{
            self.angle
        }{
            '' if self.clockwise is None else 'neg' if self.clockwise else 'pos'
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

    def __eq__(self, other: object) -> bool:
        return (isinstance(self, type(other))
            and isinstance(other, type(self))
            and self.angle == other.angle
            and self.clockwise == other.clockwise
            and self.minor == other.minor
            and self.ignorable_for_topography == other.ignorable_for_topography
            and self.diphthong_start == other.diphthong_start
            and self.diphthong_end == other.diphthong_end
        )

    def __ne__(self, other: object) -> bool:
        return not self == other

    def __hash__(self) -> int:
        return (
            hash(self.angle)
            ^ hash(self.clockwise)
            ^ hash(self.minor)
            ^ hash(self.ignorable_for_topography)
            ^ hash(self.diphthong_start)
            ^ hash(self.diphthong_end)
        )

    def reversed(self) -> Context:
        return self.clone(
            angle=None if self.angle is None else (self.angle + 180) % 360,
            clockwise=None if self.clockwise is None else not self.clockwise,
        )

    def has_clockwise_loop_to(self, other: Context) -> bool:
        if self.angle is None or other.angle is None:
            return False
        angle_in = self.angle
        angle_out = other.angle
        if self.clockwise:
            angle_in += CURVE_OFFSET
        elif self.clockwise is False:
            angle_in -= CURVE_OFFSET
        if other.clockwise:
            angle_out -= CURVE_OFFSET
        elif other.clockwise is False:
            angle_out += CURVE_OFFSET
        da = abs(angle_out - angle_in)
        return da % 180 != 0 and (da >= 180) != (angle_out > angle_in)


NO_CONTEXT: Final[Context] = Context()


_T = TypeVar('_T')


class OrderedSet(dict[_T, None]):
    def __init__(
        self,
        iterable: Optional[Iterable[_T]] = None,
        /,
    ) -> None:
        super().__init__()
        if iterable:
            for item in iterable:
                self.add(item)

    def add(self, item: _T, /) -> None:
        self[item] = None

    def remove(self, item: _T, /) -> None:
        self.pop(item, None)

    def sorted(self, /, *, key=None, reverse: bool = False) -> list[_T]:
        return sorted(self.keys(), key=key, reverse=reverse)


class PrefixView(Generic[_T]):
    def __init__(self, source: Callable, delegate: MutableMapping[str, _T]) -> None:
        self.prefix: Final = f'{source.__name__}..'
        self._delegate: Final = delegate

    def _prefixed(self, key: str) -> str:
        is_global = key.startswith('global..')
        assert len(key.split('..')) == 1 + is_global, f'Invalid key: {key!r}'
        return key if is_global else self.prefix + key

    def __getitem__(self, key: str, /) -> _T:
        return self._delegate[self._prefixed(key)]

    def __setitem__(self, key: str, value: _T, /) -> None:
        self._delegate[self._prefixed(key)] = value

    def __contains__(self, item: str, /) -> bool:
        return self._prefixed(item) in self._delegate

    def keys(self) -> Collection[str]:
        return self._delegate.keys()

    def items(self) -> ItemsView[str, _T]:
        return self._delegate.items()
