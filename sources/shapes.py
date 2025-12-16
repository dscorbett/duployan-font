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

"""Shapes and related things.
"""


from __future__ import annotations

import collections
from collections.abc import Callable
from collections.abc import Sequence
import enum
import functools
import math
from typing import Final
from typing import Literal
from typing import NamedTuple
from typing import Self
from typing import TYPE_CHECKING
from typing import override

import fontTools.misc.transform
import fontforge

import anchors
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import CURVE_OFFSET
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import EPSILON
from utils import GlyphClass
from utils import NO_CONTEXT
from utils import Type
from utils import WIDTH_MARKER_PLACES
from utils import WIDTH_MARKER_RADIX
from utils import mkmk


if TYPE_CHECKING:
    from collections.abc import Hashable
    from collections.abc import Mapping
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence

    from _typeshed import Unused

    from schema import Schema
    from utils import CloneDefault


LINE_FACTOR: Final[float] = 500


RADIUS: Final[float] = 50


def _rect(r: float, theta: float) -> tuple[float, float]:
    """Converts from polar to rectangular coordinates.

    Args:
        r: The radius.
        theta: The angle, where 0° points right and 90° points up.

    Returns:
        A tuple of the x and y coordinates corresponding to `r` and
        `theta`.
    """
    return (r * math.cos(theta), r * math.sin(theta))


def _scale_angle(theta: float, scale_x: float, scale_y: float) -> float:
    """Scales an angle.

    Args:
        theta: The angle.
        scale_x: How much to scale `theta` along the x axis.
        scale_y: How much to scale `theta` along the y axis.

    Returns:
        The angle that a bearing of `theta` degrees would have after
        being scaled by `scale_x` and `scale_y`.
    """
    theta = math.radians(theta)
    return math.degrees(math.atan2(scale_y * math.sin(theta), scale_x * math.cos(theta))) % 360


class Shape:
    """The part of a schema directly related to what the glyph looks
    like.

    Some of ``Shape``’s methods raise `NotImplementedError`. These
    should be overridden in subclasses except when the method is not
    relevant to the subclass and would never be called.
    """

    def clone(self) -> Self:
        raise NotImplementedError

    def get_name(self, size: float, joining_type: Type) -> str:
        """Returns the piece of a glyph name derived from this shape.

        Args:
            size: The size of the schema that this is the shape of.
            joining_type: This shape’s schema’s joining type.
        """
        raise NotImplementedError

    @staticmethod
    def name_implies_type() -> bool:
        """Returns whether the string returned by `get_name` identifies
        which subclass of `Shape` this is.

        This is used to suppress redundant information in the glyph
        name. It doesn’t need to be unambiguous: it is okay for two
        subclasses for which this method returns ``True`` to be able to
        return the same glyph name piece.
        """
        return False

    def group(self) -> Hashable:
        """Returns this shape’s group.

        See `Schema.group` for details.
        """
        raise NotImplementedError

    def invisible(self) -> bool:
        """Returns whether this shape is invisible.

        An invisible shape has no contour points.
        """
        return False

    def can_take_secant(self) -> bool:
        """Returns whether this shape may be the base for a secant
        (U+1BC70..U+1BC77).
        """
        return False

    def hub_priority(self, size: float) -> int:
        """Returns this shape’s hub priority.

        Args:
            size: The size of the schema that this is the shape of.

        Returns:
            This shape’s hub priority (see `Hub`), or -1 if it should
            never be placed on the baseline.
        """
        return 0 if self.invisible() else -1

    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        """Draws this shape to a FontForge glyph.

        Args:
            glyph: The FontForge glyph to add contour points and anchor
                points to.
            stroke_width: The diameter of the circular nib with which to
                stroke the path traced by `pen` to get the final
                contours of the glyph.
            light_line: The width of a light line.
            stroke_gap: The minimum distance between two different
                strokes.
            size: A scalar for the size of the contour before it is
                stroked.
            anchor: The anchor to generate anchor points for, if any.
            joining_type: This shape’s schema’s joining type.
            initial_circle_diphthong: Whether this shape is a circle at
                the beginning of a diphthong ligature.
            final_circle_diphthong: Whether this shape is a circle at
                the end of a diphthong ligature.
            diphthong_1: Whether this shape is a non-final element of a
                diphthong ligature.
            diphthong_2: Whether this shape is a non-initial element of
                a diphthong ligature.

        Returns:
            The effective bounding box if it overrides the real bounding
            box, or else ``None``. The effective bounding box may differ
            from the real bounding box by ignoring overshoots, optical
            corrections, and small ascenders or descenders that can be
            ignored when repositioning or rescaling.
        """
        if not self.invisible():
            raise NotImplementedError
        return None

    def fixed_y(self) -> bool:
        """Returns whether the drawn glyph has a fixed y position.

        If its y position is fixed, it should *not* be repositioned or
        rescaled to align to the schema’s ``y_min`` and ``y_max``.
        """
        return False

    def can_be_child(self, size: float) -> bool:
        """Returns whether this shape can belong to a child schema.

        Args:
            size: The size of the schema.
        """
        return False

    def max_tree_width(self, size: float) -> int:
        """Returns the maximum width of a shorthand overlap sequence
        following a character with this shape.

        Args:
            size: The size of the schema.
        """
        return 0

    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        """Returns the maximum number of consecutive instances of
        U+1BC9E DUPLOYAN DOUBLE MARK supported after this shape’s glyph.

        Args:
            size: The size of the schema.
            joining_type: The joining type of the schema.
            marks: The sequence of marks of the schema.
        """
        return 0

    def is_pseudo_cursive(self, size: float) -> bool:
        """Returns whether this shape can join pseudo-cursively.

        Args:
            size: The size of the schema.
        """
        return False

    def is_shadable(self) -> bool:
        """Returns whether this shape may be followed by U+1BC9D
        DUPLOYAN THICK LETTER SELECTOR.
        """
        return False

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        """Returns the shape that this shape becomes between two
        contexts.

        Args:
            context_in: The exit context of the preceding schema, or
                ``NO_CONTEXT`` if there is none.
            context_out: The entry context of the following schema, or
                ``NO_CONTEXT`` if there is none.
        """
        raise NotImplementedError

    def context_in(self) -> Context:
        """Returns this shape’s entry context.
        """
        raise NotImplementedError

    def context_out(self) -> Context:
        """Returns this shape’s exit context.
        """
        raise NotImplementedError

    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        """Returns a map of this shape’s diacritic angles.

        The keys are anchor names. The values are angles by which this
        shape should be rotated at each anchor.
        """
        return {}

    def guaranteed_glyph_class(self) -> GlyphClass | None:
        """Returns the glyph class that any schema with this shape is
        guaranteed to have, or ``None`` if there is no guarantee.
        """
        return None


class ContextMarker(Shape):
    """The reification of a `Context` as a glyph.

    Attributes:
        context: The context this marker represents.
        is_context_in: Whether this marker represents an entry context.
    """

    @override
    def __init__(
        self,
        context: Context,
        *,
        is_context_in: bool,
    ) -> None:
        """Initializes this `ContextMarker`.

        Args:
            context: The ``context`` attribute.
            is_context_in: The ``is_context_in`` attribute.
        """
        self.context: Final = context
        self.is_context_in: Final = is_context_in

    @override
    def clone(
        self,
        *,
        context: CloneDefault | Context = CLONE_DEFAULT,
        is_context_in: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            context=self.context if context is CLONE_DEFAULT else context,
            is_context_in=self.is_context_in if is_context_in is CLONE_DEFAULT else is_context_in,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                'in' if self.is_context_in else 'out'
            }.{
                self.context
            }'''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return self.get_name(0, Type.ORIENTING)

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class Dummy(Shape):
    """A marker representing nothing.

    Sometimes a substitution needs to delete a glyph. ``Dummy`` can
    simulate that.
    """
    # TODO: The OpenType spec does not allow deleting glyphs in multiple
    # substitutions, but apparently everything allows it anyway.
    # Consider deleting glyphs instead of using `Dummy`. `Dummy` might
    # still be more efficient in some cases.

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return ''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class Start(Shape):
    """The start of a cursively joined sequence.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'START'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', 0, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class Hub(Shape):
    """A candidate for which letter to place on the baseline.

    A hub precedes each candidate for which letter to place on the
    baseline. Each hub has a priority level. The first hub at the most
    visually prominent priority level in a stenogram defines the
    baseline. The levels (by decreasing prominence) are:

    1. Dotted guidelines and most non-orienting letters
    2. Orienting letters and U+1BC01 DUPLOYAN LETTER X
    3. U+1BC03 DUPLOYAN LETTER T and its cognates and U+1BC00 DUPLOYAN
       LETTER H

    Anything else (like secants) or anything following an overlap
    control is ignored for determining the baseline.

    Attributes:
        priority: The priority level. Lower numbers have higher
            priority and represent greater visual prominence.
        initial_secant: Whether this hub marks a letter after an initial
            secant. This determines which set of cursive anchors to use.
    """

    @override
    def __init__(
        self,
        priority: int,
        *,
        initial_secant: bool = False,
    ) -> None:
        """Initializes this `Hub`.

        Args:
            priority: The ``priority`` attribute.
            initial_secant: The ``initial_secant`` attribute.
        """
        self.priority: Final = priority
        self.initial_secant: Final = initial_secant

    @override
    def clone(
        self,
        *,
        priority: CloneDefault | int = CLONE_DEFAULT,
        initial_secant: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            priority=self.priority if priority is CLONE_DEFAULT else priority,
            initial_secant=self.initial_secant if initial_secant is CLONE_DEFAULT else initial_secant,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'HUB.{self.priority}{"s" if self.initial_secant else ""}'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if self.initial_secant:
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'exit', 0, 0)
        else:
            glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'exit', 0, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class End(Shape):
    """The end of a cursively joined sequence.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'END'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER


class Carry(Shape):
    """A marker for the carry digit 1 when adding width digits.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'c'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class DigitStatus(enum.Enum):
    """What stage of calculating the width a digit is in.
    """

    #: The start state. The calculation is still in progress.
    NORMAL = enum.auto()

    #: An intermediate state, only for `LeftBoundDigit`. The calculation
    #: is done but the digits still need to be copied to their final
    #: position.
    ALMOST_DONE = enum.auto()

    #: The final state. The calculation is done. A visible advance may
    #: be inserted according to the digit’s value.
    DONE = enum.auto()


class EntryWidthDigit(Shape):
    """A digit of an encoded x distance from a glyph’s overlap entry
    point to its normal cursive entry point.

    This digit contributes ``digit * WIDTH_MARKER_RADIX ** place`` to
    the full encoded x distance.

    Attributes:
        place: The digit’s positional index.
        digit: The digit’s value.
    """

    @override
    def __init__(self, place: int, digit: int) -> None:
        """Initializes this `EntryWidthDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
        """
        self.place: Final = place
        self.digit: Final = digit

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'idx.{self.digit}e{self.place}'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class LeftBoundDigit(Shape):
    """A digit of an encoded x distance from a glyph’s normal cursive
    entry point to the left edge of its bounding box.

    This digit contributes ``digit * WIDTH_MARKER_RADIX ** place`` to
    the full encoded x distance.

    Attributes:
        place: The digit’s positional index.
        digit: The digit’s value.
        status: What stage of calculating the width a digit is in.
    """

    @override
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `LeftBoundDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place: Final = place
        self.digit: Final = digit
        self.status: Final = status

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                "LDX" if self.status == DigitStatus.DONE else "ldx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER if self.status == DigitStatus.DONE else GlyphClass.MARK


class RightBoundDigit(Shape):
    """A digit of an encoded x distance from a glyph’s normal cursive
    entry point to the right edge of its bounding box.

    This digit contributes ``digit * WIDTH_MARKER_RADIX ** place`` to
    the full encoded x distance.

    Attributes:
        place: The digit’s positional index.
        digit: The digit’s value.
        status: What stage of calculating the width a digit is in.
    """

    @override
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `RightBoundDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place: Final = place
        self.digit: Final = digit
        self.status: Final = status

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                "RDX" if self.status == DigitStatus.DONE else "rdx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if self.place == 0 and self.status == DigitStatus.DONE:
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER if self.status == DigitStatus.DONE else GlyphClass.MARK


class AnchorWidthDigit(Shape):
    """A digit of an encoded x distance from a glyph’s normal cursive
    entry point to another anchor point.

    This digit contributes ``digit * WIDTH_MARKER_RADIX ** place`` to
    the full encoded x distance.

    Attributes:
        place: The digit’s positional index.
        digit: The digit’s value.
        status: What stage of calculating the width a digit is in.
    """

    @override
    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `AnchorWidthDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place: Final = place
        self.digit: Final = digit
        self.status: Final = status

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                "ADX" if self.status == DigitStatus.DONE else "adx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER if self.status == DigitStatus.DONE else GlyphClass.MARK


type Digit = AnchorWidthDigit | EntryWidthDigit | LeftBoundDigit | RightBoundDigit


class WidthNumber[D: Digit](Shape):
    """An encoded x distance between two of a glyph’s anchor points.

    Attributes:
        digit_path: The class to instantiate to get each digit of the
            number.
        width: The x distance.
    """

    @override
    def __init__(
        self,
        digit_path: type[D],
        width: int,
    ) -> None:
        """Initializes this `WidthNumber`.

        Args:
            digit_path: The ``digit_path`` attribute.
            width: The ``width`` attribute.
        """
        self.digit_path: Final = digit_path
        self.width: Final = width

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                'ilra'[[EntryWidthDigit, LeftBoundDigit, RightBoundDigit, AnchorWidthDigit].index(self.digit_path)]
            }dx.{self.width}'''.replace('-', 'n')

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK

    def to_digits(
        self,
        register_width_marker: Callable[[type[D], int, int], Schema],
    ) -> Sequence[Schema]:
        """Converts this number to a sequence of digits.

        Args:
            register_width_marker: A callback that takes a digit
                initializer, a positional index, and a digit value as
                arguments, initializes a digit marker accordingly,
                possibly does something with it as a side effect, and
                returns it.

        Returns:
            The number as a sequence of digit markers.
        """
        digits = []
        quotient = self.width
        for i in range(WIDTH_MARKER_PLACES):
            quotient, remainder = divmod(quotient, WIDTH_MARKER_RADIX)
            digits.append(register_width_marker(self.digit_path, i, remainder))
        return digits


class MarkAnchorSelector(Shape):
    """A marker for which anchor in `anchors.ALL_MARK` a mark glyph
    attaches to. Not every anchor in `anchors.ALL_MARK` gets a
    ``MarkAnchorSelector``.

    Attributes:
        anchor: The anchor.
    """

    @override
    def __init__(self, anchor: str) -> None:
        """Initializes this `MarkAnchorSelector`.

        Args:
            anchor: The ``anchor`` attribute.
        """
        self.anchor: Final = anchor

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'anchor.{self.anchor}'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class GlyphClassSelector(Shape):
    """The reification of a `GlyphClass` as a glyph.

    Attributes:
        glyph_class: The glyph class.
    """

    @override
    def __init__(self, glyph_class: GlyphClass) -> None:
        """Initializes this `GlyphClassSelector`.

        Args:
            glyph_class: The ``glyph_class`` attribute.
        """
        self.glyph_class: Final = glyph_class

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'gc.{self.glyph_class.name}'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class InitialSecantMarker(Shape):
    """A marker inserted after an initial secant.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'SECANT'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class Notdef(Shape):
    """The shape of the .notdef glyph.
    """

    @override
    def clone(self) -> Self:
        return self

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'notdef'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        pen = glyph.glyphPen()
        stroke_width = 51
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2 * 1.9, stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER


class Space(Shape):
    """A space.

    Attributes:
        angle: The angle from the cursive entry point to the cursive
            exit point. If this is not the shape of a cursive glyph, the
            value does not matter.
        margins: Whether to include left and right margins when drawing
            the glyph. Each margin is 1 stroke width wide.
    """

    @override
    def __init__(
        self,
        angle: float,
        *,
        margins: bool = False,
    ) -> None:
        """Initializes this `Space`.

        Args:
            angle: The ``angle`` attribute.
            margins: The ``margins`` attribute.
        """
        self.angle: Final = angle
        self.margins: Final = margins

    @override
    def clone(
        self,
        *,
        angle: CloneDefault | float = CLONE_DEFAULT,
        margins: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            margins=self.margins if margins is CLONE_DEFAULT else margins,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if self.angle % 180 == 90:
            return ''
        return f'''{
                int(size * math.cos(math.radians(self.angle)))
            }.{
                int(size * math.sin(math.radians(self.angle)))
            }'''.replace('-', 'n')

    @override
    def group(self) -> Hashable:
        return (
            self.angle,
            self.margins,
        )

    @override
    def invisible(self) -> bool:
        return True

    @override
    def hub_priority(self, size: float) -> int:
        return 0 if self.angle % 180 == 90 else -1

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', (size + self.margins * (2 * DEFAULT_SIDE_BEARING + stroke_width)), 0)
            glyph.transform(
                fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
                ('round',),
            )
        return None

    @override
    def is_pseudo_cursive(self, size: float) -> bool:
        return bool(size) and self.hub_priority(size) == -1

    @override
    def context_in(self) -> Context:
        return NO_CONTEXT

    @override
    def context_out(self) -> Context:
        return NO_CONTEXT


class InvisibleMark(Shape):
    """An invisible combining mark.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return ''

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass:
        return GlyphClass.MARK


class Bound(Shape):
    """The shape of a special glyph used in tests to indicate the
    precise left and right bounds of a test string’s rendered form.

    The glyph is two squares, one on the baseline and on at cap height.
    """

    @override
    def clone(self) -> Self:
        return self

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return ''

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        pen = glyph.glyphPen()
        stroke_width = 75
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        pen.moveTo((stroke_width / 2, CAP_HEIGHT - stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER


class ValidDTLS(Shape):
    """A marker for a valid instance of U+1BC9D DUPLOYAN THICK LETTER
    SELECTOR.

    An instance of U+1BC9D is valid if it is syntactically valid (it
    follows a character) and the preceding character supports shading.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return ''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class ChildEdge(Shape):
    """A marker for a non-continuing edge pointing from a glyph to its
    child in an overlap tree.

    This corresponds to a syntactically valid, supported instance of
    U+1BCA0 SHORTHAND FORMAT LETTER OVERLAP.

    Attributes:
        lineage: The non-empty path from the root of the tree to this
            edge. Each step of the path is a pair of two numbers. The
            first number is the child’s index, starting at 1. The second
            number is the total number of children at that branch in the
            tree. For example, if a glyph A is the root of a tree, and A
            has children B, C, and D, and C has a child E, and E has
            children F and G, then the ``ChildEdge`` pointing from E to
            F has the lineage ``[(2, 3), (1, 1), (1, 2)]``.
    """

    @override
    def __init__(self, lineage: Sequence[tuple[int, int]]) -> None:
        """Initializes this `ChildEdge`.

        Args:
            lineage: The ``lineage`` attribute.
        """
        assert lineage, 'A lineage may not be empty'
        self.lineage: Final = lineage

    @override
    def clone(
        self,
        *,
        lineage: CloneDefault | Sequence[tuple[int, int]] = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''{
                '_'.join(str(x[0]) for x in self.lineage)
            }.{
                '_' if len(self.lineage) == 1 else '_'.join(str(x[1]) for x in self.lineage[:-1])
            }'''

    @override
    def group(self) -> Hashable:
        return self.get_name(0, Type.ORIENTING)

    @override
    def invisible(self) -> bool:
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        layer_index = len(self.lineage) - 1
        child_index = self.lineage[-1][0] - 1
        glyph.addAnchorPoint(anchors.CHILD_EDGES[min(1, layer_index)][child_index], 'mark', 0, 0)
        glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'basemark', 0, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class ContinuingOverlapS(Shape):
    """A marker for a continuing edge pointing from a glyph to its child
    in an overlap tree.

    This corresponds to an instance of U+1BCA1 SHORTHAND FORMAT
    CONTINUING OVERLAP, to an instance of U+1BCA0 SHORTHAND FORMAT
    LETTER OVERLAP promoted to U+1BCA1, or to a glyph inserted after an
    initial secant character.
    """

    @override
    def clone(self) -> Self:
        return type(self)()

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return ''

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class ContinuingOverlap(ContinuingOverlapS):
    """A ``ContinuingOverlapS`` that corresponds to a character in the
    input string.
    """


class ParentEdge(Shape):
    """A marker for an edge pointing from a glyph to its parent in an
    overlap tree.

    Attributes:
        lineage: The path from the root of the tree to this edge; see
            `ChildEdge` for details of the format. If the lineage is
            empty, it represents the root of a tree.
    """

    @override
    def __init__(self, lineage: Sequence[tuple[int, int]]) -> None:
        """Initializes this `ParentEdge`.

        Args:
            lineage: The ``lineage`` attribute.
        """
        self.lineage: Final = lineage

    @override
    def clone(
        self,
        *,
        lineage: CloneDefault | Sequence[tuple[int, int]] = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'''pe.{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_'.join(str(x[1]) for x in self.lineage) if self.lineage else '0'
            }'''

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return self.get_name(0, Type.ORIENTING)

    @override
    def invisible(self) -> bool:
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if self.lineage:
            layer_index = len(self.lineage) - 1
            child_index = self.lineage[-1][0] - 1
            glyph.addAnchorPoint(anchors.PARENT_EDGE, 'basemark', 0, 0)
            glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'mark', 0, 0)
        return None

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class RootOnlyParentEdge(Shape):
    """A marker for a character that can only be the root of an overlap
    tree, not a child.
    """

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return 'pe'

    @staticmethod
    @override
    def name_implies_type() -> bool:
        return True

    @override
    def group(self) -> Hashable:
        return ()

    @override
    def invisible(self) -> bool:
        return True

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.MARK


class Dot(Shape):
    """A dot.

    Attributes:
        size_exponent: The exponent to use when determining the actual
            stroke width. The actual stroke width is the nominal stroke
            width multiplied by `SCALAR` raised to the power of
            `size_exponent`. A standalone dot should normally be scaled
            up lest it be hard to see at small font sizes.
    """

    #: The factor to use when determining the actual stroke width. See
    #: the ``size_exponent`` attribute.
    SCALAR: Final[float] = 2 ** 0.5

    @override
    def __init__(
        self,
        size_exponent: float = 1,
    ) -> None:
        """Initializes this `Dot`.

        Args:
            size_exponent: The ``size_exponent`` attribute.
        """
        self.size_exponent: Final = size_exponent

    @override
    def clone(
        self,
        *,
        size_exponent: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            size_exponent=self.size_exponent if size_exponent is CLONE_DEFAULT else size_exponent,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return f'{int(self.size_exponent)}'

    @override
    def group(self) -> Hashable:
        return (
            self.size_exponent,
        )

    @override
    def hub_priority(self, size: float) -> int:
        return 2

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        pen = glyph.glyphPen()
        scaled_stroke_width = stroke_width * self.SCALAR ** self.size_exponent
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', scaled_stroke_width, 'round')
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        match anchor:
            case None:
                if joining_type != Type.NON_JOINING:
                    glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'exit', 0, 0)
                    glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
                    glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', 0, 0)
            case anchors.ABOVE:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            case anchors.BELOW:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            case _:
                glyph.addAnchorPoint(anchor, 'mark', *_rect(0, 0))
        return None

    @override
    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    @override
    def is_shadable(self) -> bool:
        return True

    @override
    def context_in(self) -> Context:
        return NO_CONTEXT

    @override
    def context_out(self) -> Context:
        return NO_CONTEXT


class Line(Shape):
    """A line segment.

    Attributes:
        angle: The angle from the entry of the stroke to the exit.
        minor: Whether this shape is minor in the sense of `Context`.
        stretchy: Whether the size of this shape refers to the y offset
            between entry and exit as opposed to the stroke length.
        secant: How far along the stroke the secant overlap point is as
            a proportion of the full stroke length, or ``None`` if this
            is not a secant.
        secant_curvature_offset: If this shape is a diacritic, the
            offset for a curved base character’s angle. The diacritic is
            rotated as if the base character had a straight context
            whose angle is the true angle plus or minus this offset. The
            offset is added if the base context is clockwise and
            subtracted if the base context is counterclockwise.
        dots: How many evenly spaced dots to draw along the length of
            this line segment, or ``None`` if it should be drawn
            continuously.
        original_angle: The original `angle` of the shape from which
            this shape is derived through some number of phases, or
            ``None`` if `angle` is the original angle.
    """

    @override
    def __init__(
        self,
        angle: float,
        *,
        minor: bool = False,
        stretchy: bool = False,
        secant: float | None = None,
        secant_curvature_offset: float = 45,
        dots: int | None = None,
        original_angle: float | None = None,
    ) -> None:
        """Initializes this `Line`.

        Args:
            angle: The ``angle`` attribute.
            minor: The ``minor`` attribute.
            stretchy: The ``stretchy`` attribute.
            secant: The ``secant`` attribute.
            secant_curvature_offset: The ``secant_curvature_offset``
                attribute.
            dots: The ``dots`` attribute.
            original_angle: The ``original_angle`` attribute.
        """
        self.angle: Final = angle
        self.minor: Final = minor
        self.stretchy: Final = stretchy
        self.secant: Final = secant
        self.secant_curvature_offset: Final = secant_curvature_offset
        self.dots: Final = dots
        self.original_angle: Final = original_angle

    @override
    def clone(
        self,
        *,
        angle: CloneDefault | float = CLONE_DEFAULT,
        minor: CloneDefault | bool = CLONE_DEFAULT,
        stretchy: CloneDefault | bool = CLONE_DEFAULT,
        secant: CloneDefault | float | None = CLONE_DEFAULT,
        secant_curvature_offset: CloneDefault | float = CLONE_DEFAULT,
        dots: CloneDefault | int | None = CLONE_DEFAULT,
        original_angle: CloneDefault | float | None = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            stretchy=self.stretchy if stretchy is CLONE_DEFAULT else stretchy,
            secant=self.secant if secant is CLONE_DEFAULT else secant,
            secant_curvature_offset=self.secant_curvature_offset if secant_curvature_offset is CLONE_DEFAULT else secant_curvature_offset,
            dots=self.dots if dots is CLONE_DEFAULT else dots,
            original_angle=self.original_angle if original_angle is CLONE_DEFAULT else original_angle,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if self.dots or not self.stretchy and joining_type == Type.ORIENTING:
            s = str(int(self.angle))
            if self.dots:
                s += '.dotted'
            return s
        return ''

    @override
    def group(self) -> Hashable:
        return (
            self.angle,
            self.stretchy,
            self.secant,
            self.secant_curvature_offset,
            self.dots,
            self.original_angle if self.original_angle != self.angle else None,
        )

    @override
    def can_take_secant(self) -> bool:
        return True

    @override
    def hub_priority(self, size: float) -> int:
        if self.dots:
            return 0
        if self.secant:
            return -1
        if self.angle % 180 == 0:
            return 2
        if size >= 1:
            return 0
        return -1

    def _get_length(self, size: float) -> int:
        """Returns the length of this line segment.

        If this shape is very close to horizontal or is not stretchy,
        the length is proportional to the size. Otherwise, the height is
        proportional to the size, and the length can be derived
        trigonometrically.

        Args:
            size: The size of the shape.
        """
        if self.stretchy:
            length_denominator = abs(math.sin(math.radians(self.angle if self.original_angle is None else self.original_angle)))
            if length_denominator < EPSILON:
                length_denominator = 1
        else:
            length_denominator = 1
        return int(LINE_FACTOR * size / length_denominator)

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        pen = glyph.glyphPen()
        end_y = 0
        length: float = self._get_length(size)
        pen.moveTo((0, 0))
        if self.dots:
            dot_interval = length / (self.dots - 1)
            for dot_index in range(1, self.dots):
                pen.endPath()
                pen.moveTo((dot_interval * dot_index, 0))
        else:
            pen.lineTo((length, 0))
        if anchor:
            if (joining_type == Type.ORIENTING
                or self.angle % 180 == 0
                or anchor not in {anchors.ABOVE, anchors.BELOW}
            ):
                length *= self.secant or 0.5
            elif (anchor == anchors.ABOVE) == (self.angle < 180):
                length = 0
            glyph.addAnchorPoint(anchor, 'mark', length, end_y)
        elif self.secant:
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
        else:
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = length / (max_tree_width + 2)
                for child in [0, 1]:
                    for child_index in range(max_tree_width):
                        glyph.addAnchorPoint(
                            anchors.CHILD_EDGES[child][child_index],
                            'base',
                            child_interval * (child_index + 2),
                            0,
                        )
                glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', child_interval, 0)
                glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', child_interval, 0)
                glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', child_interval * (max_tree_width + 1), 0)
                glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
                glyph.addAnchorPoint(anchors.CURSIVE, 'exit', length, end_y)
                glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', child_interval, 0)
                if self.hub_priority(size) != -1:
                    glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
                if self.hub_priority(size) != 0:
                    glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', length, end_y)
                glyph.addAnchorPoint(anchors.SECANT, 'base', child_interval * (max_tree_width + 1), 0)
            if size == 2 and 0 < self.angle <= 45:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(anchors.RELATIVE_1, 'base', length / 2 - (light_line + stroke_gap), -(stroke_width + Dot.SCALAR * light_line) / 2)
                glyph.addAnchorPoint(anchors.RELATIVE_2, 'base', length / 2 + light_line + stroke_gap, -(stroke_width + Dot.SCALAR * light_line) / 2)
            else:
                glyph.addAnchorPoint(anchors.RELATIVE_1, 'base', length / 2, (stroke_width + Dot.SCALAR * light_line) / 2)
                glyph.addAnchorPoint(anchors.RELATIVE_2, 'base', length / 2, -(stroke_width + Dot.SCALAR * light_line) / 2)
            glyph.addAnchorPoint(anchors.MIDDLE, 'base', length / 2, 0)
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
            ('round',),
        )
        glyph.stroke('circular', stroke_width, 'round')
        if anchor is None or self.secant:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchors.ABOVE, 'base', x_center, y_max + stroke_width / 2 + 2 * stroke_gap + light_line / 2)
            glyph.addAnchorPoint(anchors.BELOW, 'base', x_center, y_min - (stroke_width / 2 + 2 * stroke_gap + light_line / 2))
            if self.secant is not None and self.angle % 90 == 0:
                y_offset = 2 * LINE_FACTOR * (2 * self.secant - 1)
                if self.get_guideline_angle() % 180 == 90:
                    glyph.transform(fontTools.misc.transform.Offset(y=y_offset + stroke_width / 2))
                else:
                    glyph.transform(fontTools.misc.transform.Offset(y=-y_offset - LINE_FACTOR + stroke_width / 2))
        return None

    @override
    def fixed_y(self) -> bool:
        return self.secant is not None and self.angle % 90 == 0

    @override
    def can_be_child(self, size: float) -> bool:
        return not (self.secant or self.dots)

    @override
    def max_tree_width(self, size: float) -> int:
        return 2 if size == 2 and not self.secant else 1

    @override
    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        return (0
            if self.secant or any(
                m.anchor in {anchors.RELATIVE_1, anchors.RELATIVE_2, anchors.MIDDLE}
                    for m in marks
            ) else int(self._get_length(size) // (250 * 0.45)) - 1)

    @override
    def is_shadable(self) -> bool:
        return not self.dots

    @staticmethod
    @functools.cache
    def get_context_instruction(angle: float) -> Callable[[Context], Context]:
        r"""Returns a function that takes a `Context` and returns a clone
        of it with its angle set.

        This is useful when creating `Complex`\ es that should have the
        same group. If two `Complex`\ es have different callable
        instances, they have different groups, even if the callables are
        indistinguishable. This function is cached by `angle` so such
        `Complex`\ es can have the same callable instance.

        Args:
            angle: An angle.
        """
        return lambda c: c.clone(angle=angle)

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if self.secant:
            if context_out != NO_CONTEXT:
                return self.rotate_diacritic(context_out)
        elif self.stretchy:
            if context_out == Context(self.angle):
                return Complex([
                    (1, self),
                    (0.2, Line(angle=(self.angle + 90 if 90 < self.angle <= 270 else self.angle - 90) % 360), False, True),
                    self.get_context_instruction(self.angle),
                ])
        elif context_in != NO_CONTEXT:
            return self.clone(angle=context_in.angle)  # type: ignore[arg-type]
        return self

    @override
    def context_in(self) -> Context:
        return Context(self.angle, minor=self.minor)

    @override
    def context_out(self) -> Context:
        return Context(self.angle, minor=self.minor)

    def rotate_diacritic(self, context: Context) -> Self:
        angle = context.angle
        assert angle is not None
        if self.secant:
            clockwise = context.clockwise
            if clockwise is None:
                minimum_da = 30
            else:
                minimum_da = 0 if context.ignorable_for_topography else 45
                angle -= self.secant_curvature_offset * (1 if clockwise else -1)
            da = (self.angle % 180) - (angle % 180)
            if da > 90:
                da -= 180
            elif da < -90:
                da += 180
            if abs(da) >= minimum_da:
                return self
            if da > 0:
                new_da = minimum_da - da
            else:
                new_da = -minimum_da - da
            ltr = 90 < self.angle % 180
            rtl = self.angle % 180 < 90
            new_ltr = 90 < (self.angle + new_da) % 180
            new_rtl = (self.angle + new_da) % 180 < 90
            if ltr != new_ltr and rtl != new_rtl:
                if da > 0:
                    new_da = -minimum_da
                else:
                    new_da = minimum_da
            angle = (self.angle + new_da) % 360
        return self.clone(angle=angle)

    @override
    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        angle = float(self.angle % 180)
        return {
            anchors.RELATIVE_1: angle,
            anchors.RELATIVE_2: angle,
            anchors.MIDDLE: (angle + 90) % 180,
            anchors.SECANT: angle,
        }

    def as_reversed(self) -> Self:
        """Returns a `Line` that is the same as this one but with the
        opposite angle.
        """
        return self.clone(angle=(self.angle + 180) % 360)

    def get_guideline_angle(self) -> float:
        """Returns the angle of the guideline to display this line on,
        assuming that this line is a secant.
        """
        return 270 if 45 <= (self.angle + 90) % 180 < 135 else 0


class StretchAxis(enum.Enum):
    """The axis along which a `Curve` is stretched.
    """

    #: The y axis.
    ABSOLUTE = enum.auto()

    #: The `Curve`’s `angle_in`.
    ANGLE_IN = enum.auto()

    #: The `Curve`’s `angle_out`.
    ANGLE_OUT = enum.auto()


class Curve(Shape):
    """An arc of an ellipse.

    Attributes:
        angle_in: The angle tangent to this curve at its entry point.
        angle_out: The angle tangent to this curve at its exit point.
        clockwise: Whether this curve turns clockwise.
        stretch: How much to stretch this curve in one axis, as a
            proportion of the other axis. If ``stretch == 0``, this
            curve is an arc of a circle. It must be greater than -1.
        long: Whether to stretch this curve along the axis perpendicular
            to the one indicated by `stretch_axis`. This has no effect
            if ``stretch == 0``.
        stretch_axis: The axis along which this curve is stretched.
        hook: Whether this curve represents a hook character. A hook is
            contextualized with an angle against its leader. In medial
            position, it has no angle against the following letter.
        reversed_circle: If this curve represents a reversed circle
            character, a positive scalar to apply to the size of the
            swash line; otherwise, 0. If ``0 < reversed_circle < 1``,
            the swash line is truncated to the length of the nominal
            (unstretched) radius.
        overlap_angle: The angle from the ellipse’s center to the point
            at which this curve overlaps a parent glyph. If this
            attribute is ``None``, it uses the default angle. This may
            only be non-``None`` for semiellipses; there is no
            geometrical reason for this, but this attribute is a hack
            that only happens to be needed for semiellipses.
        secondary: Whether this curve represents a secondary curve
            character.
        may_reposition_cursive_endpoints: Whether this curve, or any
            curve contextualized from it, may have an `entry_position`
            or `exit_position` less than 1. Repositioned cursive
            endpoints are meant for curve letters, not for curves that
            appear in `Complex` components or as contextualized circle
            letters.
        entry_position: How far along the curve to place the entry
            point. 0 means the end of the curve and 1 means the start.
            If a hook letter is in a context where it would look
            confusingly like a loop, i.e. like a circle letter, it can
            be clearer to shift the entry point later.
        exit_position: How far along the curve to place the exit point.
            0 means the start of the curve and 1 means the end. If a
            curve letter is in a context where it would look confusingly
            like a loop, i.e. like a circle letter, it can be clearer to
            shift the exit point earlier.
        smooth_1: Whether the exit part of this curve is modified to
            create a more gradual inflection with the following shape.
        smooth_2: Whether the entry part of this curve is modified to
            create a more gradual inflection with the preceding shape.
    """

    @override
    def __init__(
        self,
        angle_in: float,
        angle_out: float,
        *,
        clockwise: bool,
        stretch: float = 0,
        long: bool = False,
        stretch_axis: StretchAxis = StretchAxis.ANGLE_IN,
        hook: bool = False,
        reversed_circle: float = 0,
        overlap_angle: float | None = None,
        secondary: bool | None = None,
        may_reposition_cursive_endpoints: bool = False,
        entry_position: float = 1,
        exit_position: float = 1,
        smooth_1: bool = False,
        smooth_2: bool = False,
    ) -> None:
        """Initializes this `Curve`.

        Args:
            angle_in: The ``angle_in`` attribute.
            angle_out: The ``angle_out`` attribute.
            clockwise: The ``clockwise`` attribute.
            stretch: The ``stretch`` attribute.
            long: The ``long`` attribute.
            stretch_axis: The ``stretch_axis`` attribute.
            hook: The ``hook`` attribute.
            reversed_circle: The ``reversed_circle`` attribute.
            overlap_angle: The ``overlap_angle`` attribute.
            secondary: The ``secondary`` attribute, or ``None`` to mean
                `clockwise`.
            may_reposition_cursive_endpoints: The ``may_reposition_cursive_endpoints`` attribute.
            entry_position: The ``entry_position`` attribute.
            exit_position: The ``exit_position`` attribute.
            smooth_1: The ``smooth_1`` attribute.
            smooth_2: The ``smooth_2`` attribute.
        """
        assert overlap_angle is None or abs(angle_out - angle_in) == 180, 'Only a semicircle may have an overlap angle'
        assert stretch > -1
        assert entry_position == 1 or may_reposition_cursive_endpoints, f'{entry_position=}'
        assert exit_position == 1 or may_reposition_cursive_endpoints, f'{exit_position=}'
        assert 0 <= entry_position <= 1
        assert 0 <= exit_position <= 1
        self.angle_in: Final = angle_in
        self.angle_out: Final = angle_out
        self.clockwise: Final = clockwise
        self.stretch: Final = stretch
        self.long: Final = long
        self.stretch_axis: Final = stretch_axis
        self.hook: Final = hook
        self.reversed_circle: Final = reversed_circle
        self.overlap_angle: Final = overlap_angle if overlap_angle is None else overlap_angle % 180
        self.secondary: Final = clockwise if secondary is None else secondary
        self.may_reposition_cursive_endpoints: Final = may_reposition_cursive_endpoints
        self.entry_position: Final = entry_position
        self.exit_position: Final = exit_position
        self.smooth_1: Final = smooth_1
        self.smooth_2: Final = smooth_2

    @override
    def clone(
        self,
        *,
        angle_in: CloneDefault | float = CLONE_DEFAULT,
        angle_out: CloneDefault | float = CLONE_DEFAULT,
        clockwise: CloneDefault | bool = CLONE_DEFAULT,
        stretch: CloneDefault | float = CLONE_DEFAULT,
        long: CloneDefault | bool = CLONE_DEFAULT,
        stretch_axis: CloneDefault | StretchAxis = CLONE_DEFAULT,
        hook: CloneDefault | bool = CLONE_DEFAULT,
        reversed_circle: CloneDefault | float = CLONE_DEFAULT,
        overlap_angle: CloneDefault | float | None = CLONE_DEFAULT,
        secondary: CloneDefault | bool | None = CLONE_DEFAULT,
        may_reposition_cursive_endpoints: CloneDefault | bool = CLONE_DEFAULT,
        entry_position: CloneDefault | float = CLONE_DEFAULT,
        exit_position: CloneDefault | float = CLONE_DEFAULT,
        smooth_1: CloneDefault | bool = CLONE_DEFAULT,
        smooth_2: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            clockwise=self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            stretch=self.stretch if stretch is CLONE_DEFAULT else stretch,
            long=self.long if long is CLONE_DEFAULT else long,
            stretch_axis=self.stretch_axis if stretch_axis is CLONE_DEFAULT else stretch_axis,
            hook=self.hook if hook is CLONE_DEFAULT else hook,
            reversed_circle=self.reversed_circle if reversed_circle is CLONE_DEFAULT else reversed_circle,
            overlap_angle=self.overlap_angle if overlap_angle is CLONE_DEFAULT else overlap_angle,
            secondary=self.secondary if secondary is CLONE_DEFAULT else secondary,
            may_reposition_cursive_endpoints=(
                self.may_reposition_cursive_endpoints if may_reposition_cursive_endpoints is CLONE_DEFAULT else may_reposition_cursive_endpoints
            ),
            entry_position=self.entry_position if entry_position is CLONE_DEFAULT else entry_position,
            exit_position=self.exit_position if exit_position is CLONE_DEFAULT else exit_position,
            smooth_1=self.smooth_1 if smooth_1 is CLONE_DEFAULT else smooth_1,
            smooth_2=self.smooth_2 if smooth_2 is CLONE_DEFAULT else smooth_2,
        )

    def smooth(
        self,
        *,
        smooth_1: CloneDefault | bool = CLONE_DEFAULT,
        smooth_2: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        """Returns a copy of this shape with the ends smoothed.

        Args:
            smooth_1: The `smooth_1` value to use when cloning this
                shape.
            smooth_2: The `smooth_2` value to use when cloning this
                shape.
        """
        return self.clone(smooth_1=smooth_1, smooth_2=smooth_2)

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if self.overlap_angle is not None:
            name = f'{int(self.overlap_angle)}'
        elif joining_type == Type.ORIENTING:
            name = f'''{
                    int(self.angle_in)
                }{
                    'n' if self.clockwise else 'p'
                }{
                    int(self.angle_out)
                }{
                    'r' if self.reversed_circle else ''
                }{
                    '.ee' if not self.entry_position == self.exit_position == 1 else ''
                }'''
        else:
            name = ''
        if self.smooth_1 or self.smooth_2:
            name += f'''{
                    '.' if name else ''
                }s{
                    '1' if self.smooth_1 else ''
                }{
                    '2' if self.smooth_2 else ''
                }'''
        return name

    @override
    def group(self) -> Hashable:
        if self.stretch:
            long = self.long
            stretch_axis = self.stretch_axis
            if stretch_axis == StretchAxis.ANGLE_OUT:
                match self.angle_out % 180:
                    case 0.0:
                        stretch_axis = StretchAxis.ABSOLUTE
                    case a if a == self.angle_in % 180:
                        stretch_axis = StretchAxis.ANGLE_IN
            elif stretch_axis == StretchAxis.ANGLE_IN and self.angle_in % 180 == 0:
                stretch_axis = StretchAxis.ABSOLUTE
        else:
            long = False
            stretch_axis = StretchAxis.ANGLE_IN
        return (
            self.angle_in,
            self.angle_out,
            self.clockwise,
            self.stretch,
            long,
            stretch_axis,
            self.reversed_circle,
            self.overlap_angle,
            self.entry_position,
            self.exit_position,
            self.smooth_1,
            self.smooth_2,
        )

    @override
    def can_take_secant(self) -> bool:
        return True

    @override
    def hub_priority(self, size: float) -> int:
        return 0 if size >= 6 else 1

    def _pre_stretch(self, *angles: float) -> tuple[Sequence[float], float, float, float]:
        """Returns various values related to drawing this curve before
        it is stretched.

        Stretching a glyph changes its angles. To make the final glyph
        use the specified `angle_in` and `angle_out`, it needs to start
        with different angles that will be stretched into the correct
        final angles. This method returns those pre-stretch angles. It
        also returns some other stretching-related values for the sake
        of convenience.

        If `stretch` is false, the pre-stretch angles are equal to the
        final angles.

        Args:
            angles: A sequence of angles.

        Returns:
            A tuple of pre-stretch values.

            1. The pre-stretch equivalents of `angles`.
            2. The non-negative number of degrees by which to rotate the
               curve clockwise before stretching it. After stretching,
               the curve is rotated back the same amount
               counterclockwise.
            3. How much to stretch this curve in the x axis.
            4. How much to stretch this curve in the y axis.
        """
        scale_x = 1.0
        scale_y = 1.0 + self.stretch
        if self.long:
            scale_x, scale_y = scale_y, scale_x
        match self.stretch_axis:
            case StretchAxis.ABSOLUTE:
                theta = 0.0
            case StretchAxis.ANGLE_IN:
                theta = self.angle_in
            case StretchAxis.ANGLE_OUT:
                theta = self.angle_out
        if self.stretch:
            pre_stretch_angles: Sequence[float] = [(_scale_angle(angle - theta, 1 / scale_x, 1 / scale_y) + theta) % 360 for angle in angles]
        else:
            pre_stretch_angles = angles
        return pre_stretch_angles, theta, scale_x, scale_y

    def get_normalized_angles(
        self,
        angle_in: float | None = None,
        angle_out: float | None = None,
    ) -> tuple[float, float]:
        if angle_in is None:
            angle_in = self.angle_in
        if angle_out is None:
            angle_out = self.angle_out
        if self.clockwise and angle_out > angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        return a1, a2

    def _get_normalized_angles_and_da(
        self,
        angle_in: float | None,
        angle_out: float | None,
        final_circle_diphthong: bool = False,
        initial_circle_diphthong: bool = False,
    ) -> tuple[float, float, float]:
        a1, a2 = self.get_normalized_angles(angle_in, angle_out)
        if final_circle_diphthong:
            a2 = a1
        elif initial_circle_diphthong:
            a1 = a2
        return a1, a2, a2 - a1 or 360

    def get_da(
        self,
        angle_in: float | None = None,
        angle_out: float | None = None,
    ) -> float:
        """Returns the difference between the entry and exit angles.

        Args:
            angle_in: An entry angle, or ``None`` to default to
                ``self.angle_in``.
            angle_out: An exit angle, or ``None`` to default to
                ``self.angle_out``.

        Returns:
            The difference between this curve’s entry angle and exit
            angle. If the difference is 0, the return value is 360.
        """
        return self._get_normalized_angles_and_da(angle_in, angle_out)[2]

    def _get_angle_to_overlap_point(
        self,
        a1: float,
        a2: float,
        *,
        is_entry: bool,
    ) -> float:
        assert self.overlap_angle is not None
        angle_to_overlap_point = self.overlap_angle
        angle_at_overlap_point = (angle_to_overlap_point - (90 if self.clockwise else -90))
        if (not self.in_degree_range(
                angle_at_overlap_point % 360,
                self.angle_in,
                self.angle_out,
                self.clockwise,
            )
            or is_entry and self.in_degree_range(
                (angle_at_overlap_point + 180) % 360,
                self.angle_in,
                self.angle_out,
                self.clockwise,
            ) and self.in_degree_range(
                (angle_at_overlap_point + 180) % 360,
                self.angle_in - 90,
                self.angle_in + 90,
                clockwise=False,
            )
        ):
            angle_to_overlap_point += 180
        angle_at_overlap_point = (angle_to_overlap_point - (90 if self.clockwise else -90)) % 180
        exclusivity_zone = 30
        if self.in_degree_range(
            angle_to_overlap_point,
            ((a1 if is_entry else a2) - exclusivity_zone) % 360,
            ((a1 if is_entry else a2) + exclusivity_zone) % 360,
            clockwise=False,
        ):
            delta = abs(angle_to_overlap_point - self.overlap_angle - (180 if is_entry else 0)) - exclusivity_zone
            if is_entry != self.clockwise:
                delta = -delta
            angle_to_overlap_point += delta
        return angle_to_overlap_point % 360

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        pen = glyph.glyphPen()
        final_abs_da = abs(self.get_da())
        smooth_delta = 45
        offset_1 = 90 if diphthong_1 else smooth_delta if self.smooth_1 else -final_abs_da / 2 if diphthong_2 and final_abs_da < 180 else 0
        offset_2 = 90 if diphthong_2 else smooth_delta if self.smooth_2 else -final_abs_da / 2 if diphthong_1 and final_abs_da < 180 else 0
        offset_angle_in = (self.angle_in - offset_2 * (1 if self.clockwise else -1)) % 360
        offset_angle_out = (self.angle_out + offset_1 * (1 if self.clockwise else -1)) % 360
        (
            (pre_stretch_angle_in, pre_stretch_angle_out, pre_stretch_offset_angle_in, pre_stretch_offset_angle_out),
            stretch_axis_angle,
            scale_x,
            scale_y,
        ) = self._pre_stretch(self.angle_in, self.angle_out, offset_angle_in, offset_angle_out)
        exit_delta_scalar = (abs(math.tan(math.radians(pre_stretch_angle_out - (1 if self.clockwise else -1) * pre_stretch_offset_angle_out)))
            if offset_1 != 90
            else math.sin(math.radians(final_abs_da / 2))
            if final_abs_da < 180
            else 1
        )
        entry_delta_scalar = (abs(math.tan(math.radians(pre_stretch_angle_in + (1 if self.clockwise else -1) * pre_stretch_offset_angle_in)))
            if offset_2 != 90
            else math.sin(math.radians(final_abs_da / 2))
            if final_abs_da < 180
            else 1
        )
        a1, a2, da = self._get_normalized_angles_and_da(
            pre_stretch_offset_angle_in,
            pre_stretch_offset_angle_out,
            final_circle_diphthong,
            initial_circle_diphthong,
        )
        r = int(RADIUS * size)
        beziers_needed = math.ceil(abs(da) / 90)
        bezier_arc = da / beziers_needed
        cp = r * (4 / 3) * math.tan(math.pi / (2 * beziers_needed * 360 / da))
        cp_distance = math.hypot(cp, r)
        cp_angle = math.asin(cp / cp_distance)
        p0 = _rect(r, math.radians(a1))
        if diphthong_2:
            entry_delta = _rect(entry_delta_scalar * r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (p0[0] + entry_delta[0], p0[1] + entry_delta[1])
            pen.moveTo(entry)
            pen.lineTo(p0)
        elif self.smooth_2:
            entry_delta = _rect(-entry_delta_scalar * r, math.radians(pre_stretch_offset_angle_in))
            entry = (p0[0] + entry_delta[0], p0[1] + entry_delta[1])
            pen.moveTo(entry)
            pen.lineTo(p0)
        else:
            entry = p0
            pen.moveTo(entry)
        for i in range(1, beziers_needed + 1):
            theta0 = math.radians(a1 + (i - 1) * bezier_arc)
            p1 = _rect(cp_distance, theta0 + cp_angle)
            theta3 = math.radians(a2 if i == beziers_needed else a1 + i * bezier_arc)
            p3 = _rect(r, theta3)
            p2 = _rect(cp_distance, theta3 - cp_angle)
            pen.curveTo(p1, p2, p3)
        if self.reversed_circle and not diphthong_1 and not diphthong_2:
            swash_angle = (360 - abs(da)) / 2
            swash_length = abs(self.reversed_circle * math.sin(math.radians(swash_angle)) * r / math.sin(math.radians(90 - swash_angle)))
            if self.reversed_circle < 1:
                swash_length = min(r, swash_length)
            minimum_safe_da = 240
            maximum_safe_swash_length = (2 ** 0.5 - 1) * RADIUS
            if abs(da) < minimum_safe_da and swash_length >= maximum_safe_swash_length and joining_type == Type.ORIENTING:
                new_da = min(abs(da) + 10, minimum_safe_da)
                rv = self.clone(angle_out=(self.angle_in + new_da * (-1 if self.clockwise else 1)) % 360).draw(
                    glyph,
                    stroke_width,
                    light_line,
                    stroke_gap,
                    size,
                    anchor,
                    joining_type,
                    initial_circle_diphthong,
                    final_circle_diphthong,
                    diphthong_1,
                    diphthong_2,
                )
                glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *p3)
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *p3)
                return rv
            swash_endpoint = _rect(swash_length, math.radians(pre_stretch_angle_out))
            swash_endpoint = (p3[0] + swash_endpoint[0], p3[1] + swash_endpoint[1])
            pen.lineTo(swash_endpoint)
            exit = _rect(min(r, swash_length), math.radians(pre_stretch_angle_out))
            exit = (p3[0] + exit[0], p3[1] + exit[1])
        else:
            if self.entry_position != 1:
                entry = _rect(r, math.radians(a2 - da * self.entry_position))
            if self.exit_position != 1:
                exit = _rect(r, math.radians(a1 + da * self.exit_position))
            else:
                exit = p3
        if diphthong_1:
            exit_delta = _rect(exit_delta_scalar * r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
        elif self.smooth_1:
            exit_delta = _rect(exit_delta_scalar * r, math.radians(pre_stretch_offset_angle_out))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
        pen.endPath()
        relative_mark_angle = (a1 + a2) / 2
        if not anchor and joining_type != Type.NON_JOINING:
            max_tree_width = self.max_tree_width(size)
            child_interval = da / (max_tree_width + 2)
            if self.overlap_angle is None:
                for child in [0, 1]:
                    for child_index in range(max_tree_width):
                        glyph.addAnchorPoint(
                            anchors.CHILD_EDGES[child][child_index],
                            'base',
                            *_rect(r, math.radians(a1 + child_interval * (child_index + 2))),
                        )
            else:
                overlap_exit_angle = self._get_angle_to_overlap_point(a1, a2, is_entry=False)
                for child in [0, 1]:
                    glyph.addAnchorPoint(
                        anchors.CHILD_EDGES[child][0],
                        'base',
                        *_rect(r, math.radians(overlap_exit_angle)),
                    )
            overlap_entry_angle = (a1 + child_interval
                if self.overlap_angle is None
                else self._get_angle_to_overlap_point(a1, a2, is_entry=True))
            glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', *_rect(r, math.radians(overlap_entry_angle)))
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', *_rect(r, math.radians(overlap_entry_angle)))
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', *_rect(r, math.radians(
                a1 + child_interval * (max_tree_width + 1)
                    if self.overlap_angle is None
                    else overlap_exit_angle)))
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
            glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', *_rect(r, math.radians(overlap_entry_angle)))
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *_rect(r, math.radians(a1)))
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
            glyph.addAnchorPoint(
                anchors.SECANT,
                'base',
                *_rect(0, 0)
                    if abs(da) > 180
                    else _rect(r, math.radians(a1 + child_interval * (max_tree_width + 1))),
            )
        glyph.addAnchorPoint(anchors.MIDDLE, 'base', *_rect(r, math.radians(relative_mark_angle)))
        if not anchor:
            if self.stretch:
                theta = math.radians(stretch_axis_angle)
                glyph.addAnchorPoint(anchors.RELATIVE_1, 'base', *_rect(0, 0))
                glyph.transform(
                    fontTools.misc.transform.Identity
                        .rotate(theta)
                        .scale(scale_x, scale_y)
                        .rotate(-theta),
                )
                glyph.addAnchorPoint(
                    anchors.RELATIVE_2,
                    'base',
                    *_rect(scale_x * r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(self.angle_in)),
                )
            else:
                glyph.addAnchorPoint(anchors.RELATIVE_1, 'base',
                    *(_rect(0, 0) if abs(da) > 180 else _rect(
                        min(stroke_width, r - (stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2)),
                        math.radians(relative_mark_angle))))
                glyph.addAnchorPoint(
                    anchors.RELATIVE_2,
                    'base',
                    *_rect(r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(relative_mark_angle)),
                )
        glyph.stroke('circular', stroke_width, 'round')
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        match anchor:
            case None:
                glyph.addAnchorPoint(anchors.ABOVE, 'base', x_center, y_max + stroke_gap)
                glyph.addAnchorPoint(anchors.BELOW, 'base', x_center, y_min - stroke_gap)
            case anchors.ABOVE:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            case anchors.BELOW:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            case _:
                glyph.addAnchorPoint(anchor, 'mark', *_rect(r, math.radians(relative_mark_angle)))
        return None

    @override
    def can_be_child(self, size: float) -> bool:
        a1, a2 = self.get_normalized_angles()
        return abs(a2 - a1) <= 180

    @override
    def max_tree_width(self, size: float) -> int:
        return 1

    @override
    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        if any(m.anchor == anchors.MIDDLE for m in marks):
            return 0
        a1, a2 = self.get_normalized_angles()
        return min(3, int(abs(a1 - a2) / 360 * size))

    @override
    def is_shadable(self) -> bool:
        return True

    @staticmethod
    def in_degree_range(key: float, start: float, stop: float, clockwise: bool) -> bool:
        """Returns whether an angle appears within a range of angles.

        Args:
            key: The angle to check.
            start: The start of the range.
            stop: The end of the range.
            clockwise: Whether to check whether `key` is within the
                range going clockwise, as opposed to counterclockwise,
                from `start`.
        """
        if clockwise:
            start, stop = stop, start
        if start <= stop:
            return start <= key <= stop
        return start <= key or key <= stop

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if self.hook and context_in != NO_CONTEXT != context_out:
            rv = self.as_reversed().clone(hook=False).contextualize(context_out.as_reversed(), context_in.as_reversed())
            assert isinstance(rv, type(self))
            rv = rv.clone(hook=True).as_reversed()
            if rv.context_in().angle == context_in.angle:
                if rv.entry_position == 1:
                    rv = Complex([
                        (0.5, Curve((rv.angle_in + 90 * (1 if rv.clockwise else -1)) % 360, rv.angle_in, clockwise=rv.clockwise)),
                        (1, rv),
                    ])
                else:
                    rv = rv.clone(entry_position=0)
            return rv
        angle_in = context_in.angle
        angle_out = context_out.angle
        da = self.angle_out - self.angle_in
        if angle_in is None:
            if angle_out is None:
                angle_in = self.angle_in
            else:
                angle_in = (angle_out - da) % 360
        if angle_out is None:
            angle_out = (angle_in + da) % 360
        flips = 0

        candidate_clockwise: bool
        candidate_angle_in: float
        candidate_angle_out: float

        def flip() -> None:
            nonlocal candidate_clockwise
            nonlocal candidate_angle_in
            nonlocal candidate_angle_out
            candidate_clockwise = not candidate_clockwise
            if context_in == NO_CONTEXT:
                candidate_angle_in = (2 * candidate_angle_out - candidate_angle_in) % 360
            else:
                candidate_angle_out = (2 * candidate_angle_in - candidate_angle_out) % 360

        candidate_angle_in = angle_in
        if self.hook:
            candidate_angle_in = (candidate_angle_in + 180) % 360
        candidate_angle_out = (candidate_angle_in + da) % 360
        candidate_clockwise = self.clockwise
        if candidate_clockwise != (context_in == NO_CONTEXT):
            flip()
        clockwise_from_adjacent_curve = (
            context_in.clockwise
                if context_in != NO_CONTEXT
                else context_out.clockwise
        )
        if self.secondary != (clockwise_from_adjacent_curve not in {None, candidate_clockwise}):
            flip()
        if context_in != NO_CONTEXT != context_out:
            if self.hook:
                candidate_angle_in, candidate_angle_out = candidate_angle_out, candidate_angle_in
                candidate_clockwise = not candidate_clockwise
            context_clockwises = (context_in.clockwise, context_out.clockwise)
            curve_offset = 0 if context_clockwises in {(None, None), (True, False), (False, True)} else CURVE_OFFSET
            if False in context_clockwises:
                curve_offset = -curve_offset
            a1, a2 = self.get_normalized_angles()
            slight_overlap_offset = abs(a1 - a2) / 3 * (1 if candidate_clockwise else -1)
            if not (
                (abs(slight_overlap_offset) + abs(curve_offset) >= abs(a1 - a2)
                    and math.copysign(1, slight_overlap_offset) != math.copysign(1, curve_offset))
                or self.in_degree_range(
                    (angle_out + 180) % 360,
                    (candidate_angle_out + slight_overlap_offset) % 360,
                    (candidate_angle_in + curve_offset) % 360,
                    candidate_clockwise,
                )
            ):
                flip()
                flips += 1
            if (context_out.clockwise == context_in.clockwise == candidate_clockwise
                and (self.in_degree_range(
                    angle_out,
                    (angle_in + 180) % 360,
                    (angle_in + 180 + curve_offset) % 360,
                    not candidate_clockwise,
                ) or self.in_degree_range(
                    (angle_out - curve_offset) % 360,
                    (angle_in + 180) % 360,
                    (angle_in + 180 + curve_offset) % 360,
                    not candidate_clockwise,
                ))
            ):
                flip()
                flips += 1
            if self.hook:
                candidate_angle_in, candidate_angle_out = candidate_angle_out, candidate_angle_in
                candidate_clockwise = not candidate_clockwise
        if context_in.diphthong_start or context_out.diphthong_end:
            candidate_angle_in = (candidate_angle_in - 180) % 360
            candidate_angle_out = (candidate_angle_out - 180) % 360
        would_flip = flips % 2 == 1 and context_in != NO_CONTEXT != context_out
        if would_flip:
            flip()
        return self.clone(
            angle_in=candidate_angle_in,
            angle_out=candidate_angle_out,
            clockwise=candidate_clockwise,
            # TODO: Track the precise output angle instead of assuming that the exit
            # should be halfway along the curve.
            exit_position=0.5 if would_flip and self.may_reposition_cursive_endpoints else CLONE_DEFAULT,
        )

    @override
    def context_in(self) -> Context:
        return Context(self.angle_in, self.clockwise)

    @override
    def context_out(self) -> Context:
        return Context(self.angle_out, self.clockwise)

    @override
    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        halfway_angle = (self.angle_in + self.angle_out) / 2 % 180
        return {
            anchors.RELATIVE_1: halfway_angle,
            anchors.RELATIVE_2: halfway_angle,
            anchors.MIDDLE: (halfway_angle + 90) % 180,
            anchors.SECANT: self.angle_out % 180,
        }

    def as_reversed(self) -> Self:
        """Returns a `Curve` that looks the same but is drawn in the
        opposite direction.
        """
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
            stretch_axis=StretchAxis.ANGLE_IN
                if self.stretch_axis == StretchAxis.ANGLE_OUT
                else StretchAxis.ANGLE_OUT
                if self.stretch_axis == StretchAxis.ANGLE_IN
                else self.stretch_axis,
            entry_position=self.exit_position,
            exit_position=self.entry_position,
        )


class CircleRole(enum.Enum):
    """The role of a `Circle` in an orienting sequence.
    """

    #: The one and only `Circle` in the sequence.
    INDEPENDENT = enum.auto()

    #: The `Circle` at one end of the sequence that participates on the
    #: main topographical phases.
    LEADER = enum.auto()

    #: A `Circle` that is ignored for the main topographical phases and
    #: is later contextualized based on one with the `LEADER` role.
    DEPENDENT = enum.auto()


class Circle(Shape):
    """An ellipse.

    Attributes:
        angle_in: The angle tangent to this circle at its entry point.
        angle_out: The angle tangent to this circle at its exit point.
        clockwise: Whether this circle turns clockwise.
        reversed_circle: Whether this represents a reversed circle
            character. The only reversed circle character in Unicode is
            U+1BC42 DUPLOYAN LETTER SLOAN OW.
        pinned: Whether to force this circle to stay a `Circle` when
            contextualized, even if a `Curve` would normally be
            considered more appropriate.
        stretch: How much to stretch this circle in one axis, as a
            proportion of the other axis. If ``stretch == 0``, this
            circle is a true circle instead of merely an ellipse. It
            must be greater than -1.
        long: Whether to stretch this ellipse along the axis
            perpendicular to the entry angle, as opposed to parallel.
            This has no effect if ``stretch == 0``.
        role: The role of this circle in its orienting sequence.
    """

    @override
    def __init__(
        self,
        angle_in: float,
        angle_out: float,
        *,
        clockwise: bool,
        reversed_circle: bool = False,
        pinned: bool = False,
        stretch: float = 0,
        long: bool = False,
        role: CircleRole = CircleRole.INDEPENDENT,
    ) -> None:
        """Initializes this `Circle`.

        Args:
            angle_in: The ``angle_in`` attribute.
            angle_out: The ``angle_out`` attribute.
            clockwise: The ``clockwise`` attribute.
            reversed_circle: The ``reversed_circle`` attribute.
            pinned: The ``pinned`` attribute.
            stretch: The ``stretch`` attribute.
            long: The ``long`` attribute.
            role: The ``role`` attribute.
        """
        assert stretch > -1
        self.angle_in: Final = angle_in
        self.angle_out: Final = angle_out
        self.clockwise: Final = clockwise
        self.reversed_circle: Final = reversed_circle
        self.pinned: Final = pinned
        self.stretch: Final = stretch
        self.long: Final = long
        self.role: Final = role

    @override
    def clone(
        self,
        *,
        angle_in: CloneDefault | float = CLONE_DEFAULT,
        angle_out: CloneDefault | float = CLONE_DEFAULT,
        clockwise: CloneDefault | bool = CLONE_DEFAULT,
        reversed_circle: CloneDefault | bool = CLONE_DEFAULT,
        pinned: CloneDefault | bool = CLONE_DEFAULT,
        stretch: CloneDefault | float = CLONE_DEFAULT,
        long: CloneDefault | bool = CLONE_DEFAULT,
        role: CloneDefault | CircleRole = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            clockwise=self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            reversed_circle=self.reversed_circle if reversed_circle is CLONE_DEFAULT else reversed_circle,
            pinned=self.pinned if pinned is CLONE_DEFAULT else pinned,
            stretch=self.stretch if stretch is CLONE_DEFAULT else stretch,
            long=self.long if long is CLONE_DEFAULT else long,
            role=self.role if role is CLONE_DEFAULT else role,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if joining_type != Type.ORIENTING:
            return ''
        angle_in = self.angle_in
        angle_out = self.angle_out
        clockwise = self.clockwise
        if angle_in == angle_out >= 180:
            angle_in = (angle_in + 180) % 360
            angle_out = angle_in
            clockwise = not clockwise
        return f'''{
                int(angle_in)
            }{
                'n' if clockwise else 'p'
            }{
                int(angle_out)
            }{
                'r' if self.reversed_circle and self.angle_in != self.angle_out else ''
            }{
                '.circle' if self.role != CircleRole.INDEPENDENT and self.angle_in != self.angle_out else ''
            }'''

    @override
    def group(self) -> Hashable:
        angle_in = self.angle_in
        angle_out = self.angle_out
        if self.clockwise:
            angle_in = (angle_in + 180) % 360
            angle_out = (angle_out + 180) % 360
        return (
            angle_in,
            angle_out,
            self.stretch,
            self.long,
        )

    @override
    def can_take_secant(self) -> bool:
        return True

    @override
    def hub_priority(self, size: float) -> int:
        return 0 if size >= 6 else 1

    @functools.cached_property
    def _pre_stretch_values(self) -> tuple[float, float, float, float, float]:
        """Returns various values related to drawing this curve before
        it is stretched.

        Stretching a glyph changes its angles. To make the final glyph
        use the specified `angle_in` and `angle_out`, it needs to start
        with different angles that will be stretched into the correct
        final angles. This method returns those pre-stretch angles. It
        also returns some other stretching-related values for the sake
        of convenience.

        If `stretch` is false, the pre-stretch angles are equal to the
        final angles.

        Returns:
            A tuple of five floats.

            1. The pre-stretch entry angle.
            2. The pre-stretch exit angle.
            3. The non-negative number of degrees by which to rotate the
               curve clockwise before stretching it. After stretching,
               the curve is rotated back the same amount
               counterclockwise.
            4. How much to stretch this curve in the x axis.
            5. How much to stretch this curve in the y axis.
        """
        scale_x = 1.0 + self.stretch
        scale_y = 1.0
        if self.long:
            scale_x, scale_y = scale_y, scale_x
        theta = self.angle_in
        if self.stretch:
            pre_stretch_angle_in = (_scale_angle(self.angle_in - theta, 1 / scale_x, 1 / scale_y) + theta) % 360
            pre_stretch_angle_out = (_scale_angle(self.angle_out - theta, 1 / scale_x, 1 / scale_y) + theta) % 360
        else:
            pre_stretch_angle_in = self.angle_in
            pre_stretch_angle_out = self.angle_out
        return pre_stretch_angle_in, pre_stretch_angle_out, theta, scale_x, scale_y

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if (diphthong_1 or diphthong_2) and self.angle_in == self.angle_out:
            return Curve(
                    self.angle_in,
                    self.angle_out,
                    clockwise=self.clockwise,
                    stretch=self.stretch,
                    long=True,
                    reversed_circle=self.reversed_circle,
                ).draw(
                    glyph,
                    stroke_width,
                    light_line,
                    stroke_gap,
                    size,
                    anchor,
                    joining_type,
                    initial_circle_diphthong,
                    final_circle_diphthong,
                    diphthong_1,
                    diphthong_2,
                )
        pre_stretch_angle_in, pre_stretch_angle_out, stretch_axis_angle, scale_x, scale_y = self._pre_stretch_values
        pen = glyph.glyphPen()
        if diphthong_1:
            pre_stretch_angle_out = (pre_stretch_angle_out + 90 * (1 if self.clockwise else -1)) % 360
        if diphthong_2:
            pre_stretch_angle_in = (pre_stretch_angle_in - 90 * (1 if self.clockwise else -1)) % 360
        if self.clockwise and pre_stretch_angle_out > pre_stretch_angle_in:
            pre_stretch_angle_out -= 360
        elif not self.clockwise and pre_stretch_angle_out < pre_stretch_angle_in:
            pre_stretch_angle_out += 360
        a1 = (90 if self.clockwise else -90) + pre_stretch_angle_in
        a2 = (90 if self.clockwise else -90) + pre_stretch_angle_out
        r = int(RADIUS * size)
        cp = r * (4 / 3) * math.tan(math.pi / 8)
        entry = _rect(r, math.radians(a1))
        if diphthong_2:
            pen.moveTo(entry)
            entry_delta = _rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (entry[0] + entry_delta[0], entry[1] + entry_delta[1])
            pen.lineTo(entry)
            pen.endPath()
        pen.moveTo((0, r))
        pen.curveTo((cp, r), (r, cp), (r, 0))
        pen.curveTo((r, -cp), (cp, -r), (0, -r))
        pen.curveTo((-cp, -r), (-r, -cp), (-r, 0))
        pen.curveTo((-r, cp), (-cp, r), (0, r))
        pen.endPath()
        exit = _rect(r, math.radians(a2))
        if diphthong_1:
            pen.moveTo(exit)
            exit_delta = _rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
            pen.endPath()
        if joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', 0, 0)
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
            glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
            glyph.addAnchorPoint(anchors.SECANT, 'base', 0, 0)
        glyph.addAnchorPoint(anchors.RELATIVE_1, 'base', *_rect(0, 0))
        if self.stretch:
            theta = math.radians(stretch_axis_angle)
            glyph.transform(
                fontTools.misc.transform.Identity
                    .rotate(theta)
                    .scale(scale_x, scale_y)
                    .rotate(-theta),
            )
            glyph.addAnchorPoint(
                anchors.RELATIVE_2,
                'base',
                *_rect(scale_x * r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(self.angle_in)),
            )
        else:
            glyph.addAnchorPoint(anchors.RELATIVE_2, 'base', *_rect(r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians((a1 + a2) / 2)))
        glyph.stroke('circular', stroke_width, 'round')
        if diphthong_1 or diphthong_2:
            glyph.removeOverlap()
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        match anchor:
            case None:
                glyph.addAnchorPoint(anchors.ABOVE, 'base', x_center, y_max + stroke_gap)
                glyph.addAnchorPoint(anchors.BELOW, 'base', x_center, y_min - stroke_gap)
            case anchors.ABOVE:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            case anchors.BELOW:
                glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            case _:
                glyph.addAnchorPoint(anchor, 'mark', 0, 0)
        return None

    @override
    def can_be_child(self, size: float) -> bool:
        return True

    @override
    def max_tree_width(self, size: float) -> int:
        return 0

    @override
    def is_shadable(self) -> bool:
        return True

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        angle_in = context_in.angle
        angle_out = context_out.angle
        if angle_in is None:
            if angle_out is None:
                angle_in = 0
            else:
                angle_in = angle_out
        if angle_out is None:
            angle_out = angle_in
        is_reversed = self.reversed_circle and self.role != CircleRole.LEADER
        clockwise_from_adjacent_curve = (
            context_in.clockwise
                if context_in.clockwise is not None
                else None
                if context_in.angle == context_out.angle
                else context_out.clockwise)

        clockwise: bool

        def flop() -> None:
            nonlocal clockwise
            nonlocal angle_in
            nonlocal angle_out
            assert angle_in is not None
            assert angle_out is not None
            if self.role == CircleRole.LEADER:
                clockwise = self.clockwise
            elif (context_in.ignorable_for_topography and (context_in.clockwise == clockwise) != context_in.diphthong_start
                or context_out.ignorable_for_topography and (context_out.clockwise == clockwise) != context_out.diphthong_end
            ):
                clockwise = not clockwise
            if context_in.ignorable_for_topography and context_out == NO_CONTEXT:
                angle_out = angle_in if context_in.diphthong_start else (angle_in + 180) % 360
            elif context_out.ignorable_for_topography and context_in == NO_CONTEXT:
                angle_in = angle_out if context_out.diphthong_end else (angle_out + 180) % 360
            if context_in.diphthong_start:
                angle_in = (angle_in - 180) % 360
                if context_out == NO_CONTEXT:
                    angle_out = (angle_out - 180) % 360
            elif context_out.diphthong_end:
                angle_in = (angle_in - 180) % 360
                angle_out = (angle_out - 180) % 360

        if angle_in == angle_out:
            clockwise = (clockwise_from_adjacent_curve != is_reversed
                if clockwise_from_adjacent_curve is not None
                else self.clockwise
            )
            flop()
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_out,
                clockwise=clockwise,
            )
        da = abs(angle_out - angle_in)
        clockwise_ignoring_curvature = (da >= 180) != (angle_out > angle_in)
        forms_loop_next_to_curve = context_in.has_clockwise_loop_to(context_out) == clockwise_from_adjacent_curve
        clockwise_ignoring_reversal = (
            clockwise_from_adjacent_curve
                if forms_loop_next_to_curve and clockwise_from_adjacent_curve is not None
                else clockwise_ignoring_curvature)
        clockwise = clockwise_ignoring_reversal != is_reversed
        flop()
        if angle_in == angle_out:
            clockwise = (clockwise_from_adjacent_curve != is_reversed
                if clockwise_from_adjacent_curve is not None
                else self.clockwise
            )
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_out,
                clockwise=clockwise,
            )
        if (self.role != CircleRole.INDEPENDENT and (self.pinned or not is_reversed)
            and (clockwise is not context_in.has_clockwise_loop_to(context_out)
                or self.role == CircleRole.LEADER or angle_in == angle_out or context_in.diphthong_start or context_out.diphthong_end
            )
        ):
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_in if self.role == CircleRole.LEADER else angle_out,
                clockwise=clockwise,
            )
        elif clockwise_ignoring_reversal == clockwise_ignoring_curvature:
            if is_reversed:
                if da != 180 and (self.role != CircleRole.DEPENDENT or abs(Curve(angle_in, (angle_out + 180) % 360, clockwise=clockwise).get_da()) == 270):
                    return Curve(
                        angle_in,
                        (angle_out + 180) % 360,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=1,
                    )
                else:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=(angle_out + 180) % 360,
                        clockwise=clockwise,
                    )
            else:
                return Curve(
                    angle_in,
                    angle_out,
                    clockwise=clockwise,
                    stretch=self.stretch,
                    long=True,
                )
        else:
            if is_reversed:
                if da != 180 and (self.role != CircleRole.DEPENDENT or abs(Curve(angle_in, angle_out, clockwise=clockwise).get_da()) == 270):
                    return Curve(
                        angle_in,
                        angle_out,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=1,
                    )
                else:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=(angle_out + 180) % 360,
                        clockwise=clockwise,
                    )
            else:
                if da != 180 and not forms_loop_next_to_curve:
                    return self.clone(
                        angle_in=angle_in,
                        angle_out=angle_out,
                        clockwise=clockwise,
                    )
                else:
                    return Curve(
                        angle_in,
                        angle_out,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                    )

    @override
    def context_in(self) -> Context:
        return Context(self.angle_in, self.clockwise)

    @override
    def context_out(self) -> Context:
        return Context(self.angle_out, self.clockwise)

    def as_reversed(self) -> Self:
        """Returns a `Circle` that looks the same but is drawn in the
        opposite direction.
        """
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
            reversed_circle=not self.reversed_circle,
        )


class Component(NamedTuple):
    """An instruction for drawing a shape in a `Complex`.
    """

    #: The number by which to scale the component shape, or its absolute
    #: size if `tick` is ``True``.
    size: float

    #: The component shape to include in a `Complex`.
    shape: Shape

    #: Whether to skip drawing the component shape. (Anchor points are
    #: never skipped.)
    skip_drawing: bool = False

    #: Whether this component acts like a tick:
    #:
    #: * Its `size` is the absolute size of the component instead of a
    #:   scalar.
    #: * It is always drawn with a light line regardless of the
    #:   `Complex`’s shading.
    #: * It (along with every following component) is ignored for the
    #:   `Complex`’s effective bounding box.
    #: * It (along with every following component) is ignored when
    #:   determining the main component of the `Complex`.
    tick: bool = False


type _AnchorType = Literal['base', 'basemark', 'entry', 'exit', 'ligature', 'mark']


type _StrictInstruction = Callable[[Context], Context] | Component


type _Instruction = _StrictInstruction | tuple[float, Shape] | tuple[float, Shape, bool] | tuple[float, Shape, bool, bool]


type Instructions = Sequence[_Instruction]


type _StrictInstructions = Sequence[_StrictInstruction]


type _Point = tuple[float, float]


class Complex(Shape):
    """A shape built out of other shapes.

    Attributes:
        instructions: A sequence of instructions for how to build this
            compound shape. Each instruction is either a `Component`,
            representing a shape to include in this one, a tuple to be
            converted to a `Component`, or a callable, which modifies
            the context.

            The components are drawn (or not) in order, and connected
            end to end by their `anchors.CURSIVE` anchor points. Every
            component must add entry and exit anchor points accordingly.

            When contextualizing this shape, each component is
            contextualized with the same exit context, but the entry
            context varies. For a component shape as the first
            instruction, the entry context is the overall entry context
            for the whole `Complex`. For subsequent components, the
            entry context is the exit context of the previous component.

            A callable instruction modifies the entry context for the
            following instruction. It takes one argument, a context
            which would be the entry context for the following
            component, and returns the actual entry context that the
            following component should use.
        rotation: The number of degrees to rotate the glyph
            counterclockwise as the final step of drawing. It is always
            0 in ``Complex`` but may be overridden in subclasses.
    """

    rotation: float = 0

    @override
    def __init__(
        self,
        instructions: Instructions,
    ) -> None:
        """Initializes this `Complex`.

        Args:
            instructions: The ``instructions`` attribute.
        """
        self.instructions: Final[_StrictInstructions] = [op if callable(op) else Component(*op) for op in instructions]

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if any(not callable(op) and op.tick for op in self.instructions):
            return 'tick'
        if joining_type != Type.ORIENTING:
            return ''
        non_callables = filter(lambda op: not callable(op), self.instructions)
        op = next(non_callables)
        assert not callable(op)
        if isinstance(op.shape, Circle) or isinstance(op.shape, Curve) and op.shape.reversed_circle:
            op = next(non_callables)
            assert not callable(op)
        return op.shape.get_name(size, joining_type)

    @override
    def group(self) -> Hashable:
        return (
            *(op if callable(op) else (op.size, op.shape.group(), op[2:]) for op in self.instructions),
            self.rotation,
        )

    @functools.cached_property
    def base_index(self) -> int | None:
        """Returns the index of this shape’s main component.

        A complex shape may have multiple component shapes, but if only
        one is the main one that determines how phases should treat it,
        that is the one whose index is returned. If not, ``None`` is
        returned.
        """
        base_index: int | None = None
        for i, op in enumerate(self.instructions):
            if not callable(op):
                if op.tick:
                    break
                if base_index is None:
                    base_index = i
                else:
                    return None
        return base_index

    @functools.cached_property
    def _base_shape(self) -> Shape | None:
        """Returns the shape of this shape’s main component.

        Returns:
            The shape of the component at the index indicated by
            `base_index`, or ``None`` if that returns ``None``.
        """
        base_index = self.base_index
        if base_index is None:
            return None
        base_op = self.instructions[base_index]
        assert not callable(base_op)
        return base_op.shape

    @override
    def can_take_secant(self) -> bool:
        return self._base_shape is not None and self._base_shape.can_take_secant()

    @override
    def hub_priority(self, size: float) -> int:
        first_scalar, first_component, *_ = next(op for op in self.instructions if not (callable(op) or op.shape.invisible()))
        return first_component.hub_priority(first_scalar * size)

    class Proxy:
        """A proxy for `fontforge.glyph` and `fontforge.glyphPen`.

        `Complex` uses ``Proxy`` to collect data from component shapes’
        ``draw`` methods without actually involving FontForge objects,
        which are only used for the top-level ``Complex``’s ``draw``
        method.

        Attributes:
            anchor_points: The component shapes’ collected anchor
                points. The keys are tuples of anchor name and anchor
                type (as defined for `fontforge.glyph.addAnchorPoint`).
                The values are sequences of anchor points.
        """

        def __init__(self) -> None:
            """Initializes this `Proxy`.
            """
            self.anchor_points: Final[collections.defaultdict[tuple[str, _AnchorType], MutableSequence[_Point]]] = collections.defaultdict(list)
            self._stroke_args: tuple[tuple[object, ...], tuple[tuple[str, object], ...]] | None = None
            layer = fontforge.layer()
            layer += fontforge.contour()
            self._layer = layer

        def addAnchorPoint(
            self,
            anchor_class_name: str,
            anchor_type: _AnchorType,
            x: float,
            y: float,
        ) -> None:
            """Simulates `fontforge.glyph.addAnchorPoint`.

            Args:
                anchor_class_name: The ``anchor_class_name`` argument.
                anchor_type: The ``anchor_type`` argument.
                x: The ``x`` argument.
                y: The ``y`` argument.
            """
            self.anchor_points[anchor_class_name, anchor_type].append((x, y))

        def glyphPen(self) -> Self:
            """Simulates `fontforge.glyph.glyphPen`.

            Returns:
                This proxy.
            """
            return self

        def stroke(
            self,
            *args: object,
            **kwargs: object,
        ) -> None:
            """Simulates `fontforge.glyph.stroke`.

            Args:
                args: Positional arguments.
                kwargs: Keyword arguments.
            """
            self._stroke_args = (args, tuple(kwargs.items()))

        def _stroke(self, *, copy: bool = False) -> fontforge.layer:
            """Strokes a layer using the saved `_stroke_args`.

            If `_stroke_args` is ``None``, the layer is not modified.

            Args:
                copy: Whether to stroke a copy of `_layer` instead of
                    modifying `_layer`.

            Returns:
                The stroked layer.
            """
            layer = self._layer
            if self._stroke_args is not None:
                if copy:
                    layer = layer.dup()
                layer.stroke(*self._stroke_args[0], **dict(self._stroke_args[1]))  # type: ignore[call-overload]
                if not copy:
                    self._stroke_args = None
            return layer

        def boundingBox(self) -> tuple[float, float, float, float]:
            """Simulates `fontforge.glyph.boundingBox`.

            Returns:
                The bounding box of the proxied glyph, as a tuple of
                minimum x, minimum y, maximum x, and maximum y.
            """
            layer = self._stroke(copy=True)
            bounding_box: tuple[float, float, float, float] = layer.boundingBox()
            return bounding_box

        def draw(
            self,
            pen: fontforge.glyphPen,
            deferred_proxies: MutableMapping[tuple[tuple[object, ...], tuple[tuple[str, object], ...]], Complex.Proxy] | None = None,
        ) -> None:
            """Draws the collected data to a FontForge glyph.

            If possible, it actually defers the drawing and records the
            deferral in `deferred_proxies`. Its keys are an encoding of
            the arguments to `stroke`. If this proxy’s `stroke` call was
            deferred, the cached arguments are used as the key into
            `deferred_proxies` to find a compatible proxy. If there is a
            compatible proxy, this proxy’s layer is appended to it; if
            not, this proxy is added to the mapping for later compatible
            proxies to be added to. It is up to the caller to make sure
            all the deferred proxies ultimately get drawn.

            If this proxy has no cached `stroke` arguments, it is drawn
            immediately. This mainly happens when the stroking actually
            happened, in which case deferring is impossible because
            stroking is not idempotent. It also happens when `stroke`
            was not called at all, e.g. for a space glyph, in which case
            there is nothing to defer.

            Args:
                pen: The pen to draw with.
                deferred_proxies: An optional mapping to proxies whose
                    `draw` calls have been deferred.
            """
            if deferred_proxies is None or self._stroke_args is None:
                self._stroke()
                assert all(len(contour) == 0 or contour.closed for contour in self._layer), (
                    f'''A proxy contains an open contour: {
                        [(point.x, point.y) for point in next(filter(lambda contour: len(contour) and not contour.closed, self._layer))]
                    }''')
                self._layer.draw(pen)
            elif (deferred_proxy := deferred_proxies.get(self._stroke_args)) is not None:
                if (
                    deferred_proxy._layer and self._layer
                    and (deferred_contour := deferred_proxy._layer[-1]) and (contour := self._layer[0])
                    and deferred_contour[-1] == contour[0]
                ):
                    deferred_contour += contour
                else:
                    deferred_proxy._layer += self._layer
            else:
                deferred_proxies[self._stroke_args] = self

        def transform(self, matrix: tuple[float, float, float, float, float, float], *args: Unused) -> None:
            """Simulates `fontforge.glyph.transform`.

            Args:
                matrix: The ``matrix`` argument.
                args: Anything. Further arguments are ignored.
            """
            for anchor, points in self.anchor_points.items():
                for i, x_y in enumerate(points):
                    new_point = fontforge.point(*x_y).transform(matrix)
                    self.anchor_points[anchor][i] = (new_point.x, new_point.y)
            self._layer.transform(matrix)

        def moveTo(self, x_y: _Point) -> None:
            """Simulates `fontforge.glyphPen.moveTo`.

            Args:
                x_y: The ``(x, y)`` argument.
            """
            for contour in self._layer:
                contour.moveTo(*x_y)

        def lineTo(self, x_y: _Point) -> None:
            """Simulates `fontforge.glyphPen.lineTo`.

            Args:
                x_y: The ``(x, y)`` argument.
            """
            for contour in self._layer:
                contour.lineTo(x_y)

        def curveTo(self, cp1: _Point, cp2: _Point, x_y: _Point) -> None:
            """Simulates `fontforge.glyphPen.curveTo`.

            Args:
                cp1: The ``(cp1.x, cp1.y)`` argument.
                cp2: The ``(cp2.x, cp2.y)`` argument.
                x_y: The ``(x, y)`` argument.
            """
            for contour in self._layer:
                contour.cubicTo(cp1, cp2, x_y)

        def endPath(self) -> None:
            """Ignores `fontforge.glyphPen.endPath`.
            """

        def removeOverlap(self) -> None:
            """Ignores `fontforge.glyph.removeOverlap`.
            """

        def get_crossing_point(self, component: Curve | Circle) -> _Point:
            """Returns the point at which two rays extending from a
            circle or curve’s entry and exit points would cross.

            Args:
                component: A circle or curve.
            """
            entry_list = self.anchor_points[anchors.CURSIVE, 'entry']
            assert len(entry_list) == 1
            if component.angle_in == component.angle_out:
                return entry_list[0]
            exit_list = self.anchor_points[anchors.CURSIVE, 'exit']
            assert len(exit_list) == 1
            if isinstance(component, Circle):
                rel1_list = self.anchor_points[anchors.RELATIVE_1, 'base']
                assert len(rel1_list) == 1
                rel2_list = self.anchor_points[anchors.RELATIVE_2, 'base']
                assert len(rel2_list) == 1
                r = math.hypot(entry_list[0][1] - rel1_list[0][1], entry_list[0][0] - rel1_list[0][0])
                theta = math.atan2(rel2_list[0][1] - rel1_list[0][1], rel2_list[0][0] - rel1_list[0][0])
                return _rect(r, theta)
            asx = entry_list[0][0]
            asy = entry_list[0][1]
            bsx = exit_list[0][0]
            bsy = exit_list[0][1]
            adx = math.cos(math.radians(component.angle_in))
            ady = math.sin(math.radians(component.angle_in))
            bdx = math.cos(math.radians(component.angle_out))
            bdy = math.sin(math.radians(component.angle_out))
            dx = bsx - asx
            dy = bsy - asy
            det = bdx * ady - bdy * adx
            if abs(det) < EPSILON:
                return 0, 0
            u = (dy * bdx - dx * bdy) / det
            px = asx + adx * u
            py = asy + ady * u
            return px, py

    def draw_to_proxy(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[tuple[float, float, float, float] | None, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        """Draws this shape to a `Proxy`.

        This method is split out from `draw` so that subclasses can
        override it.

        Args:
            glyph: The ``glyph`` argument from `draw`.
            stroke_width: The ``stroke_width`` argument from `draw`.
            light_line: The ``light_line`` argument from `draw`.
            stroke_gap: The ``stroke_gap`` argument from `draw`.
            size: The ``size`` argument from `draw`.

        Returns:
            A tuple of two elements.

            The first element is the effective bounding box.

            The second element is the mapping of all components’
            singular anchor points. An anchor point is singular if no
            other anchor points in the same component share the same
            anchor name and anchor type.
        """
        singular_anchor_points: collections.defaultdict[tuple[str, _AnchorType], list[_Point]] = collections.defaultdict(list)
        pen = glyph.glyphPen()
        effective_bounding_box = None
        deferred_proxies: MutableMapping[tuple[tuple[object, ...], tuple[tuple[str, object], ...]], Complex.Proxy] = {}
        for op in self.instructions:
            if callable(op):
                continue
            scalar, component, skip_drawing, tick = op
            if tick and effective_bounding_box is None:
                for deferred_proxy in deferred_proxies.values():
                    deferred_proxy.draw(pen)
                deferred_proxies.clear()
                effective_bounding_box = glyph.boundingBox()
            proxy = Complex.Proxy()
            component.draw(
                proxy,  # type: ignore[arg-type]
                light_line if tick else stroke_width,
                light_line,
                stroke_gap,
                scalar * (1 if tick else size),
                None,
                Type.JOINING,
                initial_circle_diphthong=False,
                final_circle_diphthong=False,
                diphthong_1=False,
                diphthong_2=False,
            )
            this_entry_list = proxy.anchor_points[anchors.CURSIVE, 'entry']
            assert len(this_entry_list) == 1
            this_x, this_y = this_entry_list[0]
            if exit_list := singular_anchor_points.get((anchors.CURSIVE, 'exit')):
                last_x, last_y = exit_list[-1]
                proxy.transform(fontTools.misc.transform.Offset(
                    last_x - this_x,
                    last_y - this_y,
                ))
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1 and not (effective_bounding_box and anchor_and_type[0] != anchors.CURSIVE):
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not skip_drawing:
                proxy.draw(pen, deferred_proxies)
        for deferred_proxy in deferred_proxies.values():
            deferred_proxy.draw(pen)
        return effective_bounding_box, singular_anchor_points

    @staticmethod
    def _remove_bad_contours(glyph: fontforge.glyph) -> None:
        """Removes contours that might crash FontForge.

        See `FontForge issue #4560
        <https://github.com/fontforge/fontforge/issues/4560>`__.

        Args:
            glyph: The FontForge glyph to remove contours from.
        """
        if not hasattr(glyph, 'foreground'):
            # This `Complex` is nested within another `Complex`. The outermost one
            # will remove all the bad contours.
            return
        bad_indices = []
        foreground = glyph.foreground
        for contour_index, contour in enumerate(foreground):
            if not contour.closed:
                bad_indices.append(contour_index)
        if bad_indices:
            for bad_index in reversed(bad_indices):
                del foreground[bad_index]
            glyph.foreground = foreground

    def enter_on_first_path(self) -> bool:
        """Returns whether this shape’s cursive entry point is based on
        its first singular cursive entry point.

        If not, it is based on the last.
        """
        return True

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        effective_bounding_box, singular_anchor_points = self.draw_to_proxy(glyph, stroke_width, light_line, stroke_gap, size)
        glyph.removeOverlap()
        self._remove_bad_contours(glyph)
        if not (anchor or joining_type == Type.NON_JOINING):
            entry = singular_anchor_points[anchors.CURSIVE, 'entry'][0 if self.enter_on_first_path() else -1]
            exit = singular_anchor_points[anchors.CURSIVE, 'exit'][-1]
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
        if anchor is None:
            for (singular_anchor, anchor_type), points in singular_anchor_points.items():
                if (
                    singular_anchor in anchors.ALL_MARK and singular_anchor not in {anchors.ABOVE, anchors.BELOW}
                        if singular_anchor not in {
                            anchors.MIDDLE,
                            anchors.PRE_HUB_CONTINUING_OVERLAP,
                            anchors.POST_HUB_CONTINUING_OVERLAP,
                            anchors.PRE_HUB_CURSIVE,
                            anchors.POST_HUB_CURSIVE,
                        }
                        else len(points) == 1
                ) or (
                    self.can_be_child(size)
                    and (
                        singular_anchor == anchors.PARENT_EDGE
                        or singular_anchor in {anchors.CONTINUING_OVERLAP, anchors.POST_HUB_CONTINUING_OVERLAP} and anchor_type == 'entry'
                    )
                ) or (
                    self.max_tree_width(size) and (
                        singular_anchor == anchors.CONTINUING_OVERLAP and anchor_type == 'exit'
                        or any(singular_anchor in layer for layer in anchors.CHILD_EDGES)
                    )
                ):
                    glyph.addAnchorPoint(singular_anchor, anchor_type, *points[-1])
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self.rotation)),
            ('round',),
        )
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        y_center = (y_max + y_min) / 2
        if anchor == anchors.MIDDLE:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_center)
        elif anchor == anchors.ABOVE:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_min + stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
        elif anchor == anchors.BELOW:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
        return effective_bounding_box

    @override
    def fixed_y(self) -> bool:
        for op in self.instructions:
            if callable(op):
                continue
            return op.shape.invisible()
        return False

    @override
    def can_be_child(self, size: float) -> bool:
        base_index = self.base_index
        if base_index is None:
            return False
        assert self._base_shape is not None
        base_op = self.instructions[base_index]
        assert not callable(base_op)
        return self._base_shape.can_be_child(base_op.size * size)

    @override
    def max_tree_width(self, size: float) -> int:
        for op in reversed(self.instructions):
            if not (callable(op) or op.tick):
                return op.shape.max_tree_width(op.size * size)
        return 0

    @override
    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        bases = [op for op in self.instructions if not (callable(op) or op.tick)]
        if len(bases) != 1:
            return 0
        return bases[0].shape.max_double_marks(bases[0].size * size, joining_type, marks)

    @override
    def is_shadable(self) -> bool:
        return all(callable(op) or op.shape.is_shadable() for op in self.instructions)

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        instructions: MutableSequence[_Instruction] = []
        initial = context_in == NO_CONTEXT
        forced_context = None
        for i, op in enumerate(self.instructions):
            if callable(op):
                forced_context = op(context_out if initial else context_in)
                if forced_context.ignorable_for_topography:
                    forced_context = forced_context.clone(ignorable_for_topography=False)
                instructions.append(op)
            else:
                scalar, component, skip_drawing, tick = op
                component = component.contextualize(context_in, context_out)
                assert isinstance(component, (Circle, Curve, Line))
                if i and initial:
                    component = component.as_reversed()
                if forced_context is not None:
                    if isinstance(component, Line):
                        if forced_context != NO_CONTEXT:
                            component = component.clone(angle=forced_context.angle)  # type: ignore[arg-type]
                    else:
                        if forced_context.clockwise is not None and forced_context.clockwise != component.clockwise:
                            component = component.as_reversed()
                        if forced_context != NO_CONTEXT and forced_context.angle != (component.angle_out if initial else component.angle_in):
                            assert forced_context.angle is not None
                            angle_out = component.angle_out
                            if component.clockwise and angle_out > component.angle_in:
                                angle_out -= 360
                            elif not component.clockwise and angle_out < component.angle_in:
                                angle_out += 360
                            da = angle_out - component.angle_in
                            if initial:
                                component = component.clone(
                                    angle_in=(forced_context.angle - da) % 360,
                                    angle_out=forced_context.angle,
                                )
                            else:
                                component = component.clone(
                                    angle_in=forced_context.angle,
                                    angle_out=(forced_context.angle + da) % 360,
                                )
                instructions.append((scalar, component, skip_drawing, tick))
                if initial:
                    context_out = component.context_in()
                else:
                    context_in = component.context_out()
                if forced_context is not None:
                    if __debug__:
                        actual_context = component.context_out() if initial else component.context_in()
                        if forced_context.clockwise is None:
                            actual_context = actual_context.clone(clockwise=None)
                        assert actual_context == forced_context, f'{actual_context} != {forced_context}'
                    forced_context = None
        if initial:
            instructions.reverse()
        return self.clone(instructions=instructions)

    @override
    def context_in(self) -> Context:
        return next(op for op in self.instructions if not callable(op))[1].context_in()

    @override
    def context_out(self) -> Context:
        return next(op for op in reversed(self.instructions) if not callable(op))[1].context_out()

    @override
    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        if self._base_shape is not None:
            return self._base_shape.calculate_diacritic_angles()
        return super().calculate_diacritic_angles()


class ComplexCurve(Complex):
    """A sequence of multiple cochiral curves.
    """

    @override
    def __init__(self, instructions: Instructions) -> None:
        super().__init__(instructions)
        assert len(instructions) >= 2, 'Not enough instructions: {len(instructions)}'
        assert all(
            not callable(op) and isinstance(op.shape, Curve) and not op.shape.reversed_circle
            and op.shape.clockwise is self.instructions[0].shape.clockwise  # type: ignore[union-attr]
            for op in self.instructions
        ), f'Invalid instructions for `ComplexCurve`: {instructions}'
        self._first_curve: Curve = self.instructions[0].shape  # type: ignore[assignment, union-attr]
        self._last_curve: Curve = self.instructions[-1].shape  # type: ignore[assignment, union-attr]

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        name = super().get_name(size, joining_type)
        if self.smooth_1 or self.smooth_2:
            name += f'''{
                    '.' if name else ''
                }s{
                    '1' if self.smooth_1 else ''
                }{
                    '2' if self.smooth_2 else ''
                }'''
        return name

    @property
    def angle_in(self) -> float:
        return self._first_curve.angle_in

    @property
    def angle_out(self) -> float:
        return self._last_curve.angle_out

    @property
    def clockwise(self) -> bool:
        return self._last_curve.clockwise

    @property
    def reversed_circle(self) -> float:
        return self._first_curve.reversed_circle

    @property
    def entry_position(self) -> float:
        return self._first_curve.entry_position

    @property
    def exit_position(self) -> float:
        return self._last_curve.exit_position

    @property
    def smooth_1(self) -> bool:
        return self._last_curve.smooth_1

    @property
    def smooth_2(self) -> bool:
        return self._first_curve.smooth_2

    def get_da(self) -> float:
        """Returns the difference between the entry and exit angles.

        Returns:
            The difference between this curve’s entry angle and exit
            angle. If the difference is 0, the return value is 360.
        """
        return self._last_curve.get_da(self.angle_in)

    def smooth(
        self,
        *,
        smooth_1: CloneDefault | bool = CLONE_DEFAULT,
        smooth_2: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        """Returns a copy of this shape with the ends smoothed.

        Args:
            smooth_1: The `smooth_1` value to use when cloning this
                shape’s last curve.
            smooth_2: The `smooth_2` value to use when cloning this
                shape’s first curve.
        """
        return self.clone(instructions=[
            self.instructions[0]._replace(shape=self._first_curve.clone(smooth_2=smooth_2)),  # type: ignore[union-attr]
            *self.instructions[1:-1],
            self.instructions[-1]._replace(shape=self._last_curve.clone(smooth_1=smooth_1)),  # type: ignore[union-attr]
        ])


class RotatedComplex(Complex):
    """A shape made by rotating another shape.
    """

    @override
    def __init__(
        self,
        instructions: Instructions,
        rotation: float = 0,
    ) -> None:
        """Initializes this `RotatedComplex`.

        Args:
            instructions: The ``instructions`` attribute.
            rotation: The ``rotation`` attribute.
        """
        super().__init__(instructions)
        self.rotation = rotation

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
        rotation: CloneDefault | float = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            rotation=self.rotation if rotation is CLONE_DEFAULT else rotation,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        return str(int(self.rotation))

    def rotate_diacritic(self, context: Context) -> Self:
        angle = context.angle
        assert angle is not None
        return self.clone(rotation=angle)


class EqualsSign(Complex):
    """U+003D EQUALS SIGN.
    """


class Grammalogue(Complex):
    """A symbol that might overlap but is not cursively joining.

    Grammalogues that don’t join, like U+1BC9C DUPLOYAN SIGN O WITH
    CROSS, should not use use this class. Grammalogues that are normal
    cursively joined letters, or sequences thereof, should also not use
    this class.
    """

    @override
    @functools.cached_property
    def base_index(self) -> int:
        return -1

    @override
    def can_take_secant(self) -> bool:
        return False

    @override
    def context_in(self) -> Context:
        return NO_CONTEXT

    @override
    def context_out(self) -> Context:
        return NO_CONTEXT


class InvalidDTLS(Complex):
    """An invalid instance of U+1BC9D DUPLOYAN THICK LETTER SELECTOR.
    """

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER


class InvalidOverlap(Complex):
    """An invalid instance of U+1BCA0 SHORTHAND FORMAT LETTER OVERLAP or
    U+1BCA1 SHORTHAND FORMAT CONTINUING OVERLAP.

    Attributes:
        continuing: Whether this is an instance of U+1BCA1.
    """

    @override
    def __init__(
        self,
        *,
        continuing: bool,
        instructions: Instructions,
    ) -> None:
        """Initializes this `InvalidOverlap`.

        Args:
            continuing: The ``continuing`` attribute.
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)
        self.continuing: Final = continuing

    @override
    def clone(
        self,
        *,
        continuing: CloneDefault | bool = CLONE_DEFAULT,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            continuing=self.continuing if continuing is CLONE_DEFAULT else continuing,
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    @override
    def guaranteed_glyph_class(self) -> GlyphClass | None:
        return GlyphClass.BLOCKER


class InvalidStep(Complex):
    """An invalid instance of U+1BCA2 SHORTHAND FORMAT DOWN STEP or
    U+1BCA3 SHORTHAND FORMAT UP STEP.

    Attributes:
        angle: The ``angle`` of the `Space` the step would be if it were
            valid.
    """

    @override
    def __init__(
        self,
        angle: float,
        instructions: Instructions,
    ) -> None:
        """Initializes this `InvalidStep`.

        Args:
            angle: The ``angle`` attribute.
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)
        self.angle: Final = angle

    @override
    def clone(
        self,
        *,
        angle: CloneDefault | float = CLONE_DEFAULT,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        return Space(self.angle, margins=True)


class RomanianU(Complex):
    """U+1BC56 DUPLOYAN LETTER ROMANIAN U.
    """

    @override
    def draw_to_proxy(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[tuple[float, float, float, float] | None, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        effective_bounding_box, singular_anchor_points = super().draw_to_proxy(glyph, stroke_width, light_line, stroke_gap, size)
        singular_anchor_points[anchors.RELATIVE_1, 'base'] = singular_anchor_points[anchors.CURSIVE, 'exit']
        return effective_bounding_box, singular_anchor_points

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if NO_CONTEXT in {context_in, context_out}:
            return super().contextualize(context_in, context_out)
        return Circle(0, 0, clockwise=False).contextualize(context_in, context_out)


class Ou(Complex):
    """U+1BC5B DUPLOYAN LETTER OU.

    Attributes:
        role: The role of this shape in its orienting sequence.
    """

    @override
    def __init__(
        self,
        instructions: Instructions,
        role: CircleRole = CircleRole.INDEPENDENT,
        _initial: bool = False,
        _angled_against_next: bool = False,
        _isolated: bool = True,
    ) -> None:
        """Initializes this `Ou`.

        Args:
            instructions: The ``instructions`` attribute.
            role: The ``role`` attribute.
        """
        super().__init__(instructions)
        self.role: Final = role
        self._initial: Final = _initial
        self._angled_against_next: Final = _angled_against_next
        self._isolated: Final = _isolated

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
        role: CloneDefault | CircleRole = CLONE_DEFAULT,
        _initial: CloneDefault | bool = CLONE_DEFAULT,
        _angled_against_next: CloneDefault | bool = CLONE_DEFAULT,
        _isolated: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            self.role if role is CLONE_DEFAULT else role,
            self._initial if _initial is CLONE_DEFAULT else _initial,
            self._angled_against_next if _angled_against_next is CLONE_DEFAULT else _angled_against_next,
            self._isolated if _isolated is CLONE_DEFAULT else _isolated,
        )

    @override
    def get_name(self, size: float, joining_type: Type) -> str:
        if self.role == CircleRole.INDEPENDENT and self._isolated:
            return ''
        circle_op = self.instructions[0]
        assert not callable(circle_op)
        circle_path = circle_op.shape
        if isinstance(circle_path, Circle):
            rv = f'''{
                    int(circle_path.angle_in)
                }{
                    'n' if circle_path.clockwise else 'p'
                }{
                    int(circle_path.angle_out)
                }'''
        else:
            rv = circle_path.get_name(size, joining_type)
        if self.role == CircleRole.LEADER and not self._isolated:
            rv += '.cusp'
        if self._initial:
            rv += '.init'
        if self._isolated:
            rv += '.isol'
        return rv

    @override
    def group(self) -> Hashable:
        circle_op = self.instructions[0]
        assert not callable(circle_op)
        circle_path = circle_op.shape
        assert isinstance(circle_path, (Circle, Curve))
        return (
            super().group(),
            circle_path.angle_in,
            self.role,
            self._initial,
            self._isolated,
            self._angled_against_next and circle_path.reversed_circle,
        )

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        if len(self.instructions) != 1:
            return super().draw(
                glyph,
                stroke_width,
                light_line,
                stroke_gap,
                size,
                anchor,
                joining_type,
                initial_circle_diphthong,
                final_circle_diphthong,
                diphthong_1,
                diphthong_2,
            )
        inner_curve_da = 125
        outer_rewind_da = -35
        angle_against_next = 90
        circle_op = self.instructions[0]
        assert not callable(circle_op)
        inner_curve_size = 5 / 9 * circle_op.size
        inner_curve_stretch = 0.3
        circle_path = circle_op.shape
        assert isinstance(circle_path, (Circle, Curve))
        angle_in = circle_path.angle_in
        angle_out = circle_path.angle_out
        clockwise = circle_path.clockwise
        clockwise_sign = -1 if clockwise else 1
        if self.role == CircleRole.LEADER:
            if self._isolated:
                intermediate_angle = (angle_out + clockwise_sign * inner_curve_da) % 360
                instructions: Instructions = [
                    (inner_curve_size, Curve(angle_out, intermediate_angle, clockwise=clockwise)),
                    circle_op._replace(shape=Circle(intermediate_angle, angle_out, clockwise=clockwise)),
                ]
            elif self._initial:
                intermediate_angle = (angle_out + clockwise_sign * inner_curve_da) % 360
                instructions = [
                    (inner_curve_size, Curve(angle_out, intermediate_angle, clockwise=clockwise)),
                    circle_op._replace(shape=Curve(intermediate_angle, angle_out, clockwise=clockwise)),
                ]
            else:
                intermediate_angle = (angle_in - clockwise_sign * inner_curve_da) % 360
                instructions = [
                    circle_op._replace(shape=Curve(angle_in, intermediate_angle, clockwise=clockwise)),
                    (inner_curve_size, Curve(intermediate_angle, angle_in, clockwise=clockwise)),
                ]
        elif self._initial:
            instructions = [
                (inner_curve_size, Curve(angle_out - clockwise_sign * inner_curve_da, angle_out, clockwise=clockwise, stretch=inner_curve_stretch, long=True)),
                circle_op._replace(shape=Circle(
                    angle_out,
                    angle_out,
                    clockwise=clockwise,
                )),
            ]
        elif self._angled_against_next and circle_path.reversed_circle:
            angle_out = (angle_out - clockwise_sign * angle_against_next) % 360
            intermediate_angle = (angle_out - clockwise_sign * inner_curve_da) % 360
            instructions = [
                circle_op._replace(shape=Circle(angle_in, intermediate_angle, clockwise=clockwise)),
                (inner_curve_size, Curve(intermediate_angle, angle_out, clockwise=clockwise, stretch=inner_curve_stretch, long=True, stretch_axis=StretchAxis.ANGLE_OUT)),
            ]
        elif angle_in != angle_out:
            instructions = [
                circle_op._replace(shape=(Curve if self.role == CircleRole.INDEPENDENT else Circle)(
                    angle_in,
                    angle_out,
                    clockwise=clockwise,
                )),
                (inner_curve_size, Curve(
                    angle_out,
                    angle_out + clockwise_sign * inner_curve_da,
                    clockwise=clockwise,
                    stretch=0 if self.role == CircleRole.INDEPENDENT else inner_curve_stretch,
                    long=True,
                    stretch_axis=StretchAxis.ANGLE_OUT,
                )),
            ]
        elif self._isolated:
            intermediate_angle = (270 - clockwise_sign * inner_curve_da - 180) % 360
            angle_in = (intermediate_angle - clockwise_sign * outer_rewind_da - 180) % 360
            clockwise = not clockwise
            instructions = [
                (inner_curve_size, Curve(intermediate_angle + clockwise_sign * inner_curve_da,
                    intermediate_angle,
                    clockwise=clockwise,
                    stretch=inner_curve_stretch,
                    long=True,
                )),
                circle_op._replace(shape=Circle(
                    intermediate_angle,
                    angle_in,
                    clockwise=clockwise,
                )),
            ]
        else:
            instructions = [
                circle_op._replace(shape=Circle(
                    angle_in,
                    angle_in,
                    clockwise=clockwise,
                )),
                (inner_curve_size, Curve(angle_in,
                    (angle_in + clockwise_sign * inner_curve_da) % 360,
                    clockwise=clockwise,
                    stretch=inner_curve_stretch,
                    long=True,
                    stretch_axis=StretchAxis.ANGLE_OUT,
                )),
            ]
        return self.clone(instructions=instructions).draw(
            glyph,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )

    @override
    def can_be_child(self, size: float) -> bool:
        return True

    @override
    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        return 0

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        contextualized = super().contextualize(context_in, context_out)
        assert isinstance(contextualized, Ou)
        circle_op = contextualized.instructions[0]
        assert not callable(circle_op)
        circle_path = circle_op.shape
        assert isinstance(circle_path, (Circle, Curve))
        if self.role == CircleRole.LEADER:
            original_circle_op = self.instructions[0]
            assert not callable(original_circle_op)
            original_circle_path = original_circle_op.shape
            assert isinstance(original_circle_path, Circle)
            if original_circle_path.clockwise is not circle_path.clockwise:
                contextualized = self.clone(
                        instructions=[
                            original_circle_op._replace(shape=original_circle_path.clone(reversed_circle=not original_circle_path.reversed_circle)),
                        ],
                        role=CircleRole.INDEPENDENT,
                    ).contextualize(context_in, context_out)
                assert isinstance(contextualized, Ou)
                return contextualized.clone(role=CircleRole.LEADER)
        return contextualized.clone(
            _initial=context_in == NO_CONTEXT,
            _angled_against_next=context_out.angle is not None is not context_in.angle != context_out.angle != circle_path.angle_out,
            _isolated=False,
        )

    @override
    def context_in(self) -> Context:
        if self._initial:
            rv = super().context_out()
            assert rv.angle is not None
            return rv.clone(angle=(rv.angle + 180) % 360, ou=True)
        return super().context_in()

    @override
    def context_out(self) -> Context:
        if self._isolated:
            return super().context_out()
        rv = self.context_in()
        assert rv.angle is not None
        return rv.clone(angle=(rv.angle + 180) % 360, ou=True)

    def as_reversed(self) -> Self:
        """Returns an `Ou` that is drawn in the opposite direction but
        whose outer circle looks the same.
        """
        return self.clone(
            instructions=[op if callable(op) else op._replace(shape=op.shape.as_reversed()) for op in self.instructions],  # type: ignore[attr-defined]
        )


class SeparateAffix(Complex):
    """A separate affix.

    Attributes:
        low: Whether this shape is low as opposed to high.
        tight: Whether this shape is “tight”. It is not quite clear what
            that is supposed to mean; the representative code chart
            glyphs do not match the primary sources. The current
            encoding model may not be appropriate.
    """

    @override
    def __init__(
        self,
        instructions: Instructions,
        *,
        low: bool = False,
        tight: bool = False,
    ) -> None:
        """Initializes this ``.

        Args:
            instructions: The ``instructions`` attribute.
            low: The ``low`` attribute.
            tight: The ``tight`` attribute.
        """
        super().__init__(instructions)
        self.low: Final = low
        self.tight: Final = tight

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
        low: CloneDefault | bool = CLONE_DEFAULT,
        tight: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            low=self.low if low is CLONE_DEFAULT else low,
            tight=self.tight if tight is CLONE_DEFAULT else tight,
        )

    @override
    def group(self) -> Hashable:
        return (
            super().group(),
            self.low,
            self.tight,
        )

    @override
    def can_take_secant(self) -> bool:
        return False

    @override
    def hub_priority(self, size: float) -> int:
        return -1

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        effective_bounding_box = super().draw(
            glyph,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        glyph.anchorPoints = []
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        cursive_y = (y_max + 200 if self.low else y_min - 200)
        entry_x, exit_x = x_min, x_max
        if self.tight:
            entry_x, exit_x = exit_x, entry_x
        glyph.transform(fontTools.misc.transform.Offset(y=-cursive_y))
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', entry_x, 0)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', exit_x, 0)
        return effective_bounding_box

    @override
    def fixed_y(self) -> bool:
        return True

    @override
    def can_be_child(self, size: float) -> bool:
        return False

    @override
    def max_tree_width(self, size: float) -> int:
        return 0

    @override
    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        return 0

    @override
    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    @override
    def is_shadable(self) -> bool:
        return False

    @override
    def context_in(self) -> Context:
        return NO_CONTEXT

    @override
    def context_out(self) -> Context:
        return NO_CONTEXT


class Wa(Complex):
    r"""A circled circle in the style of U+1BC5C DUPLOYAN LETTER WA.

    `instructions` must not contain any callables. The first and last
    components must be `Circle`\ s or `Curve`\ s, at least one of which
    must be a `Circle`.
    """

    @override
    def __init__(
        self,
        instructions: Instructions,
        _initial: bool = False,
    ) -> None:
        """Initializes this `Wa`.

        Args:
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)
        self._initial = _initial

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
        _initial: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            self._initial if _initial is CLONE_DEFAULT else _initial,
        )

    @override
    def draw_to_proxy(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[tuple[float, float, float, float] | None, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        if self._initial:
            return super().draw_to_proxy(glyph, stroke_width, light_line, stroke_gap, size)
        last_crossing_point: _Point | None = None
        singular_anchor_points = collections.defaultdict(list)
        pen = glyph.glyphPen()
        deferred_proxies: MutableMapping[tuple[tuple[object, ...], tuple[tuple[str, object], ...]], Complex.Proxy] = {}
        for op in self.instructions:
            assert not callable(op)
            scalar, component, skip_drawing, tick = op
            proxy = Complex.Proxy()
            component.draw(
                proxy,  # type: ignore[arg-type]
                light_line if tick else stroke_width,
                light_line,
                stroke_gap,
                scalar * (1 if tick else size),
                None,
                Type.JOINING,
                initial_circle_diphthong=False,
                final_circle_diphthong=False,
                diphthong_1=False,
                diphthong_2=False,
            )
            assert isinstance(component, (Circle, Curve))
            this_crossing_point = proxy.get_crossing_point(component)
            if last_crossing_point is not None:
                proxy.transform(fontTools.misc.transform.Offset(
                    last_crossing_point[0] - this_crossing_point[0],
                    last_crossing_point[1] - this_crossing_point[1],
                ))
            last_crossing_point = this_crossing_point
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1:
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not skip_drawing:
                proxy.draw(pen, deferred_proxies)
        for deferred_proxy in deferred_proxies.values():
            deferred_proxy.draw(pen)
        return None, singular_anchor_points

    @override
    def enter_on_first_path(self) -> bool:
        return False

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        context_in = context_in.clone(ignorable_for_topography=False)
        context_out = context_out.clone(ignorable_for_topography=False)
        original_instructions: Sequence[Component] = self.instructions  # type: ignore[assignment]
        if context_in == NO_CONTEXT and context_out != NO_CONTEXT:
            assert context_out.angle is not None
            outer_circle_op = original_instructions[0]
            assert not callable(outer_circle_op)
            inner_circle_op = original_instructions[-1]
            assert not callable(inner_circle_op)
            inner_circle = inner_circle_op.shape
            assert isinstance(inner_circle, Circle)
            inner_curve = inner_circle.contextualize(outer_circle_op.shape.context_out(), context_out)
            minimum_da = 180
            if isinstance(inner_curve, Curve) and inner_curve.clockwise == inner_circle.clockwise and inner_curve.get_da() % 360 >= minimum_da:
                instructions = [
                    *original_instructions[:-1],
                    inner_circle_op._replace(shape=inner_curve),
                ]
            else:
                instructions = [
                    *[
                        op._replace(shape=op.shape.clone(
                            angle_in=(context_out.angle - minimum_da) % 360,  # type: ignore[call-arg]
                            angle_out=(context_out.angle - minimum_da) % 360,
                        ))
                        for op in original_instructions[:-1]
                    ],
                    inner_circle_op._replace(shape=Curve((context_out.angle - minimum_da) % 360, context_out.angle, clockwise=inner_circle.clockwise)),
                ]
            return self.clone(instructions=instructions, _initial=True)
        if context_in != NO_CONTEXT != context_out:
            if context_in.angle != context_out.angle and any(isinstance(op.shape, Circle) and op.shape.reversed_circle for op in original_instructions):
                assert context_out.angle is not None
                outer_circle_op = original_instructions[0]
                outer_circle = outer_circle_op.shape
                assert isinstance(outer_circle, Circle)
                tracer = original_instructions[-1].shape.contextualize(context_in, context_out)
                assert isinstance(tracer, (Circle, Curve))
                clockwise_sign = -1 if tracer.clockwise else 1
                new_outer_angle_out = (outer_circle.angle_in + clockwise_sign * 270) % 360
                new_inner_circle = Curve(
                    angle_in=new_outer_angle_out,
                    angle_out=context_out.angle,
                    clockwise=tracer.clockwise,
                    stretch=outer_circle.stretch,
                )
                if ((new_inner_circle.angle_out - new_inner_circle.angle_in) * clockwise_sign % 360 < 180
                    and ((new_new_outer_angle_out := (context_out.angle - 180) % 360) - outer_circle.angle_in) * clockwise_sign % 360 >= 180
                ):
                    new_outer_angle_out = new_new_outer_angle_out
                    new_inner_circle = new_inner_circle.clone(angle_in=new_outer_angle_out)
                inner_circle_op = original_instructions[-1]
                inner_circle = inner_circle_op.shape
                assert isinstance(inner_circle, Circle)
                if outer_circle.stretch or inner_circle.stretch:
                    raise NotImplementedError
                return Complex(instructions=[
                    outer_circle_op._replace(shape=Curve(
                        angle_in=outer_circle.angle_in,
                        angle_out=new_outer_angle_out,
                        clockwise=tracer.clockwise,
                        stretch=outer_circle.stretch,
                        reversed_circle=(outer_circle_op.size - inner_circle_op.size) / outer_circle_op.size,
                    )),
                    *[
                        op._replace(shape=op.shape.clone(  # type: ignore[call-arg]
                            angle_in=new_outer_angle_out,
                            angle_out=new_outer_angle_out,
                            clockwise=tracer.clockwise,
                        ))
                        for op in original_instructions[1:-1]
                    ],
                    inner_circle_op._replace(shape=new_inner_circle),
                ])
            inner_circle = original_instructions[-1].shape.contextualize(context_in, context_out)
            assert isinstance(inner_circle, (Circle, Curve))
            return Complex(instructions=[
                *[
                    op._replace(shape=op.shape.clone(
                        angle_in=inner_circle.angle_in,  # type: ignore[call-arg]
                        angle_out=inner_circle.angle_in,
                        clockwise=inner_circle.clockwise,
                    ))
                    for op in original_instructions[:-1]
                ],
                original_instructions[-1]._replace(shape=inner_circle),
            ])
        return self.clone(instructions=[
            op._replace(shape=op.shape.contextualize(context_in, context_out))
            for op in original_instructions
        ])

    def as_reversed(self) -> Self:
        """Returns a `Wa` that looks the same but is drawn in the
        opposite direction.
        """
        return self.clone(
            instructions=[op if callable(op) else op._replace(shape=op.shape.as_reversed()) for op in self.instructions],  # type: ignore[attr-defined]
        )


class Wi(Complex):
    """A circled sequence of curves in the style of U+1BC5E DUPLOYAN
    LETTER WI.

    `instructions` must begin or end with a `Circle` component and must
    contain at least one `Curve` component.
    """

    _CURVE_BIAS: Final[float] = 50

    @functools.cached_property
    def _has_only_one_curve(self) -> bool:
        return len([op for op in self.instructions if not callable(op)]) == 2

    @functools.cached_property
    def _first_curve_index(self) -> int:
        return next(i for i, op in enumerate(self.instructions) if not callable(op) and not isinstance(op.shape, Circle))

    def _contextualize_with_curve_bias(
        self,
        context_out: Context,
    ) -> Complex | None:
        """Contextualizes this `Wi` with a non-default output angle for
        the curve.

        In some initial or medial contexts, a `Wi` with a single curve
        (as in U+1BC5E DUPLOYAN LETTER WI but not U+1BC5F DUPLOYAN
        LETTER WEI) way seem ambiguous with U+1BC5C DUPLOYAN LETTER WA,
        to avoid which the curve gets a output angle different from its
        usual contextualization.

        Args:
            context_out: The entry context of the following schema, or
                ``NO_CONTEXT`` if there is none.

        Returns:
            A new contextualized `Wi`, or ``None`` if it is not
            necessary to add a curve bias to this `Wi` in the given
            context.
        """
        bias = self._CURVE_BIAS
        if self._has_only_one_curve and context_out.angle is not None:
            curve_op = self.instructions[self._first_curve_index]
            assert isinstance(curve_op, Component)
            curve = curve_op.shape
            assert isinstance(curve, Curve)
            clockwise_sign = -1 if curve.clockwise else 1
            if Curve.in_degree_range(
                context_out.angle,
                (curve.angle_out - bias * clockwise_sign) % 360,
                (curve.angle_out + bias * clockwise_sign) % 360,
                curve.clockwise,
            ):
                if Curve.in_degree_range(
                    context_out.angle,
                    (curve.angle_out + bias / 2 * clockwise_sign) % 360,
                    (curve.angle_out + bias * clockwise_sign) % 360,
                    curve.clockwise,
                ):
                    bias *= -1
                curve = curve.clone(angle_out=(curve.angle_out + bias * clockwise_sign) % 360)
                return self.clone(instructions=[self.instructions[self._first_curve_index - 1], curve_op._replace(shape=curve)])
        return None

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if self._first_curve_index == 1:
            return super().contextualize(context_in, context_out)
        curve_path = self._contextualize_with_curve_bias(context_out)
        if context_in == NO_CONTEXT and context_out != NO_CONTEXT:
            return self if curve_path is None else self.clone(instructions=[self.instructions[0], *curve_path.instructions])
        if curve_path is None:
            curve_path_ = self.clone(instructions=self.instructions[self._first_curve_index - 1:]).contextualize(context_in, context_out)
            assert isinstance(curve_path_, Complex)
            curve_path = curve_path_
        assert not callable(self.instructions[0])
        circle = self.instructions[0].shape
        assert isinstance(circle, Circle)
        curve_op = curve_path.instructions[1]
        assert isinstance(curve_op, Component)
        curve = curve_op.shape
        assert isinstance(curve, Curve)
        circle_path = circle.clone(
            angle_in=curve.angle_in,
            angle_out=curve.angle_in,
            clockwise=curve.clockwise,
        )
        return self.clone(instructions=[(self.instructions[0].size, circle_path), *curve_path.instructions])

    def as_reversed(self) -> Self:
        """Returns a `Wi` that is drawn in the opposite direction but
        whose outer circle looks the same.
        """
        first_callable = True
        return self.clone(
            instructions=[
                ((lambda c, op=op: (c0 := op(c)).clone(clockwise=not c0.clockwise))  # type: ignore[misc]
                        if (first_callable and not (first_callable := False))
                        else op
                    )
                    if callable(op)
                    else (
                        op.size,
                        op.shape.clone(
                                angle_in=(op.shape.angle_in + 180) % 360,
                                angle_out=(op.shape.angle_out + 180) % 360,
                                clockwise=not op.shape.clockwise,
                            ) if isinstance(op.shape, (Circle, Curve))
                            else op.shape,
                        *op[2:],
                    ) for op in self.instructions
            ],
        )


class TangentHook(Complex):
    """U+1BC7C DUPLOYAN AFFIX ATTACHED TANGENT HOOK.
    """

    @override
    def __init__(
        self,
        instructions: Instructions,
        *,
        _initial: bool = False,
    ) -> None:
        """Initializes this `TangentHook`.

        Args:
            instructions: The ``instructions`` attribute.
        """
        while callable(instructions[0]):
            instructions = instructions[1:]
        super().__init__([self._override_initial_context if _initial else self._override_noninitial_context, *instructions])
        self._initial: Final = _initial

    @staticmethod
    def _override_noninitial_context(c: Context) -> Context:
        assert c.angle is not None
        return Context(
            (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360,
            not (90 < c.angle < 315),
        )

    @staticmethod
    def _override_initial_context(c: Context) -> Context:
        assert c.angle is not None
        return Context(
            (c.angle - 90) % 360 if 90 < c.angle < 315 else (c.angle + 90) % 360,
            90 < c.angle < 315,
        )

    @override
    def clone(
        self,
        *,
        instructions: CloneDefault | Instructions = CLONE_DEFAULT,
        _initial: CloneDefault | bool = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            _initial=self._initial if _initial is CLONE_DEFAULT else _initial,
        )

    @override
    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if context_in == NO_CONTEXT != context_out and not self._initial:
            assert not callable(self.instructions[1])
            assert isinstance(self.instructions[1][1], Curve)
            assert not callable(self.instructions[3])
            assert isinstance(self.instructions[3][1], Curve)
            shape = self.clone(instructions=[
                self.instructions[0],
                (self.instructions[1][0], self.instructions[1][1].clone(
                    angle_in=self.instructions[1][1].angle_in,
                    angle_out=(self.instructions[1][1].angle_out + 180) % 360,
                    clockwise=not self.instructions[1][1].clockwise,
                ), *self.instructions[1][2:]),
                self.instructions[2],
                (self.instructions[3][0], self.instructions[3][1].clone(
                    angle_in=self.instructions[3][1].angle_out,
                    angle_out=(self.instructions[3][1].angle_out + 180) % 360,
                    clockwise=not self.instructions[3][1].clockwise,
                ), *self.instructions[3][2:]),
            ], _initial=True)
        else:
            shape = super()
        return shape.contextualize(context_in, context_out)  # type: ignore[union-attr]


class XShape(Complex):
    """U+1BC01 DUPLOYAN LETTER X.
    """

    @override
    def hub_priority(self, size: float) -> int:
        return 1

    @override
    def draw(
        self,
        glyph: fontforge.glyph,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
        anchor: str | None,
        joining_type: Type,
        initial_circle_diphthong: bool,
        final_circle_diphthong: bool,
        diphthong_1: bool,
        diphthong_2: bool,
    ) -> tuple[float, float, float, float] | None:
        effective_bounding_box = super().draw(
            glyph,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != anchors.CURSIVE]
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_avg = (x_min + x_max) / 2
        y_avg = (y_min + y_max) / 2
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', x_avg, y_avg)
        return effective_bounding_box

    @override
    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    @override
    def context_in(self) -> Context:
        return NO_CONTEXT

    @override
    def context_out(self) -> Context:
        return NO_CONTEXT
