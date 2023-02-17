# Copyright 2018-2019, 2022-2023 David Corbett
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


__all__ = [
    'AnchorWidthDigit',
    'Bound',
    'Carry',
    'ChildEdge',
    'Circle',
    'CircleRole',
    'Complex',
    'ContextMarker',
    'ContinuingOverlap',
    'ContinuingOverlapS',
    'Curve',
    'Digit',
    'DigitStatus',
    'Dot',
    'Dummy',
    'End',
    'EntryWidthDigit',
    'GlyphClassSelector',
    'Hub',
    'InitialSecantMarker',
    'InvalidDTLS',
    'InvalidOverlap',
    'InvalidStep',
    'LINE_FACTOR',
    'LeftBoundDigit',
    'Line',
    'MarkAnchorSelector',
    'Notdef',
    'Ou',
    'ParentEdge',
    'RADIUS',
    'RightBoundDigit',
    'RomanianU',
    'RootOnlyParentEdge',
    'SeparateAffix',
    'Shape',
    'Space',
    'Start',
    'TangentHook',
    'ValidDTLS',
    'Wa',
    'Wi',
    'WidthNumber',
    'XShape',
]


import collections
from collections.abc import Hashable
from collections.abc import Mapping
from collections.abc import MutableSequence
from collections.abc import Sequence
import enum
import math
import typing
from typing import Callable
from typing import ClassVar
from typing import Final
from typing import Generic
from typing import Literal
from typing import LiteralString
from typing import Optional
from typing import Self
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import cast


import fontTools.misc.transform
import fontforge


import anchors
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import CURVE_OFFSET
from utils import CloneDefault
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
    from _typeshed import Unused

    from schema import Schema


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


class Shape:
    """The part of a schema directly related to what the glyph looks
    like.

    Some of ``Shape``’s methods raise `NotImplementedError`. These
    should be overridden in subclasses except when the method is not
    relevant to the subclass and would never be called.
    """

    def clone(self) -> Self:
        raise NotImplementedError

    def __str__(self) -> str:
        """Returns the piece of a glyph name derived from this shape.
        """
        raise NotImplementedError

    @staticmethod
    def name_implies_type() -> bool:
        """Returns whether the string returned by `__str__` identifies
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
        return str(self)

    def invisible(self) -> bool:
        """Returns whether this shape is invisible.

        An invisible shape has no contour points.
        """
        return False

    @staticmethod
    def can_take_secant() -> bool:
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
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        """Draws this shape to a FontForge glyph.

        Args:
            glyph: The FontForge glyph to add contour points and anchor
                points to.
            pen: ``glyph.glyphPen()``, or ``False`` if the glyph is
                invisible and guaranteed not to have any contour points.
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
            child: Whether this shape’s schema is a child in an overlap
                sequence.
            initial_circle_diphthong: Whether this shape is a circle at
                the beginning of a diphthong ligature.
            final_circle_diphthong: Whether this shape is a circle at
                the end of a diphthong ligature.
            diphthong_1: Whether this shape is a non-final element of a
                diphthong ligature.
            diphthong_2: Whether this shape is a non-initial element of
                a diphthong ligature.

        Returns:
            Whether the glyph should *not* be rescaled to align to the
            schema’s ``y_min`` and ``y_max``.
        """
        if not self.invisible():
            raise NotImplementedError
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

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        """Returns the glyph class that any schema with this shape is
        guaranteed to have, or ``None`` if there is no guarantee.
        """
        return None


class ContextMarker(Shape):
    """The reification of a `Context` as a glyph.

    Attributes:
        is_context_in: Whether this marker represents an entry context.
        context: The context this marker represents.
    """

    def __init__(
        self,
        is_context_in: bool,
        context: Context,
    ) -> None:
        """Initializes this `ContextMarker`.

        Args:
            is_context_in: The ``is_context_in`` attribute.
            context: The ``context`` attribute.
        """
        self.is_context_in = is_context_in
        self.context = context

    def clone(
        self,
        *,
        is_context_in: bool | CloneDefault = CLONE_DEFAULT,
        context: Context | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.is_context_in if is_context_in is CLONE_DEFAULT else is_context_in,
            self.context if context is CLONE_DEFAULT else context,
        )

    def __str__(self) -> str:
        return f'''{
                'in' if self.is_context_in else 'out'
            }.{
                self.context
            }'''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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

    def __str__(self) -> str:
        return ''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class Start(Shape):
    """The start of a cursively joined sequence.
    """

    def __str__(self) -> str:
        return 'START'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', 0, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class Hub(Shape):
    """A candidate for which letter to place on the baseline.

    A hub precedes each candidate for which letter to place on the
    baseline. Each hub has a priority level. The first hub at the most
    visually prominent priority level in a stenogram defines the
    baseline. The levels (by decreasing prominence) are:

    1. Dotted guidelines and most non-orienting letters
    2. Orienting letters and U+1BC01 DUPLOYAN LETTER X
    3. U+1BC03 DUPLOYAN LETTER T and its cognates

    Anything else (like secants and U+1BC00 DUPLOYAN LETTER H) or
    anything following an overlap control is ignored for determining the
    baseline.

    Attributes:
        priority: The priority level. Lower numbers have higher
            priority and represent greater visual prominence.
        initial_secant: Whether this hub marks a letter after an initial
            secant. This determines which set of cursive anchors to use.
    """

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
        self.priority = priority
        self.initial_secant = initial_secant

    def clone(
        self,
        *,
        priority: int | CloneDefault = CLONE_DEFAULT,
        initial_secant: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            priority=self.priority if priority is CLONE_DEFAULT else priority,
            initial_secant=self.initial_secant if initial_secant is CLONE_DEFAULT else initial_secant,
        )

    def __str__(self) -> str:
        return f'HUB.{self.priority}{"s" if self.initial_secant else ""}'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        if self.initial_secant:
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'exit', 0, 0)
        else:
            glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'entry', 0, 0)
            glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'exit', 0, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class End(Shape):
    """The end of a cursively joined sequence.
    """

    def __str__(self) -> str:
        return 'END'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.BLOCKER


class Carry(Shape):
    """A marker for the carry digit 1 when adding width digits.
    """

    def __str__(self) -> str:
        return 'c'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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

    def __init__(self, place: int, digit: int) -> None:
        """Initializes this `EntryWidthDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
        """
        self.place = place
        self.digit = digit

    def __str__(self) -> str:
        return f'idx.{self.digit}e{self.place}'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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

    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `LeftBoundDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place = place
        self.digit = digit
        self.status = status

    def __str__(self) -> str:
        return f'''{
                "LDX" if self.status == DigitStatus.DONE else "ldx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


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

    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `RightBoundDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place = place
        self.digit = digit
        self.status = status

    def __str__(self) -> str:
        return f'''{
                "RDX" if self.status == DigitStatus.DONE else "rdx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


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

    def __init__(self, place: int, digit: int, status: DigitStatus = DigitStatus.NORMAL) -> None:
        """Initializes this `AnchorWidthDigit`.

        Args:
            place: The ``place`` attribute.
            digit: The ``digit`` attribute.
            status: The ``status`` attribute.
        """
        self.place = place
        self.digit = digit
        self.status = status

    def __str__(self) -> str:
        return f'''{
                "ADX" if self.status == DigitStatus.DONE else "adx"
            }.{self.digit}{
                "e" if self.status == DigitStatus.NORMAL else "E"
            }{self.place}'''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


Digit = AnchorWidthDigit | EntryWidthDigit | LeftBoundDigit | RightBoundDigit


_D = TypeVar('_D', bound=Digit)


class WidthNumber(Shape, Generic[_D]):
    """An encoded x distance between two of a glyph’s anchor points.

    Attributes:
        digit_path: The class to instantiate to get each digit of the
            number.
        width: The x distance.
    """

    def __init__(
        self,
        digit_path: type[_D],
        width: int,
    ) -> None:
        """Initializes this `WidthNumber`.

        Args:
            digit_path: The ``digit_path`` attribute.
            width: The ``width`` attribute.
        """
        self.digit_path = digit_path
        self.width = width

    def __str__(self) -> str:
        return f'''{
                'ilra'[[EntryWidthDigit, LeftBoundDigit, RightBoundDigit, AnchorWidthDigit].index(self.digit_path)]
            }dx.{self.width}'''.replace('-', 'n')

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK

    def to_digits(
        self,
        register_width_marker: Callable[[type[_D], int, int], Schema],
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
    attaches to.

    Attributes:
        index: The index of the anchor in `anchors.ALL_MARK`.
    """

    def __init__(self, index: int) -> None:
        """Initializes this `MarkAnchorSelector`.

        Args:
            index: The ``index`` attribute.
        """
        self.index = index

    def __str__(self) -> str:
        return f'anchor.{anchors.ALL_MARK[self.index]}'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class GlyphClassSelector(Shape):
    """The reification of a `GlyphClass` as a glyph.

    Attributes:
        glyph_class: The glyph class.
    """

    def __init__(self, glyph_class: GlyphClass) -> None:
        """Initializes this `GlyphClassSelector`.

        Args:
            glyph_class: The ``glyph_class`` attribute.
        """
        self.glyph_class = glyph_class

    def __str__(self) -> str:
        return f'gc.{self.glyph_class.name}'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class InitialSecantMarker(Shape):
    """A marker inserted after an initial secant.
    """

    def __str__(self) -> str:
        return 'SECANT'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class Notdef(Shape):
    """The shape of the .notdef glyph.
    """

    def clone(self) -> Self:
        return self

    def __str__(self) -> str:
        return 'notdef'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def group(self) -> Hashable:
        return ()

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        assert pen
        stroke_width = 51
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, 663 + stroke_width / 2))
        pen.lineTo((360 + stroke_width / 2, stroke_width / 2))
        pen.lineTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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
        self.angle = angle
        self.margins = margins

    def clone(
        self,
        *,
        angle: float | CloneDefault = CLONE_DEFAULT,
        margins: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            margins=self.margins if margins is CLONE_DEFAULT else margins,
        )

    def __str__(self) -> str:
        return str(int(self.angle))

    def group(self) -> Hashable:
        return (
            self.angle,
            self.margins,
        )

    def invisible(self) -> bool:
        return True

    def hub_priority(self, size: float) -> int:
        return 0 if self.angle % 180 == 90 else -1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
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
        return False

    def can_be_child(self, size: float) -> bool:
        return size == 0 and self.angle == 0 and not self.margins

    def is_pseudo_cursive(self, size: float) -> bool:
        return bool(size) and self.hub_priority(size) == -1

    def context_in(self) -> Context:
        return NO_CONTEXT

    def context_out(self) -> Context:
        return NO_CONTEXT


class Bound(Shape):
    """The shape of a special glyph used in tests to indicate the
    precise left and right bounds of a test string’s rendered form.

    The glyph is two squares, one on the baseline and on at cap height.
    """

    def clone(self) -> Self:
        return self

    def __str__(self) -> str:
        return ''

    def group(self) -> Hashable:
        return ()

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        assert pen
        stroke_width = 75
        pen.moveTo((stroke_width / 2, stroke_width / 2))
        pen.endPath()
        pen.moveTo((stroke_width / 2, CAP_HEIGHT - stroke_width / 2))
        pen.endPath()
        glyph.stroke('caligraphic', stroke_width, stroke_width, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.BLOCKER


class ValidDTLS(Shape):
    """A marker for a valid instance of U+1BC9D DUPLOYAN THICK LETTER
    SELECTOR.

    An instance of U+1BC9D is valid if it is syntactically valid (it
    follows a character) and the preceding character supports shading.
    """
    def __str__(self) -> str:
        return 'dtls'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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

    def __init__(self, lineage: Sequence[tuple[int, int]]) -> None:
        """Initializes this `ChildEdge`.

        Args:
            lineage: The ``lineage`` attribute.
        """
        assert lineage, 'A lineage may not be empty'
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage: Sequence[tuple[int, int]] | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self) -> str:
        return f'''{
                '_'.join(str(x[0]) for x in self.lineage)
            }.{
                '_' if len(self.lineage) == 1 else '_'.join(str(x[1]) for x in self.lineage[:-1])
            }'''

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        layer_index = len(self.lineage) - 1
        child_index = self.lineage[-1][0] - 1
        glyph.addAnchorPoint(anchors.CHILD_EDGES[min(1, layer_index)][child_index], 'mark', 0, 0)
        glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'basemark', 0, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class ContinuingOverlapS(Shape):
    """A marker for a continuing edge pointing from a glyph to its child
    in an overlap tree.

    This corresponds to an instance of U+1BCA1 SHORTHAND FORMAT
    CONTINUING OVERLAP, to an instance of U+1BCA0 SHORTHAND FORMAT
    LETTER OVERLAP promoted to U+1BCA1, or to a glyph inserted after an
    initial secant character.
    """

    def clone(self) -> Self:
        return type(self)()

    def __str__(self) -> str:
        return ''

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
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

    def __init__(self, lineage: Sequence[tuple[int, int]]) -> None:
        """Initializes this `ParentEdge`.

        Args:
            lineage: The ``lineage`` attribute.
        """
        self.lineage = lineage

    def clone(
        self,
        *,
        lineage: Sequence[tuple[int, int]] | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.lineage if lineage is CLONE_DEFAULT else lineage,
        )

    def __str__(self) -> str:
        return f'''pe.{
                '_'.join(str(x[0]) for x in self.lineage) if self.lineage else '0'
            }.{
                '_'.join(str(x[1]) for x in self.lineage) if self.lineage else '0'
            }'''

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        if self.lineage:
            layer_index = len(self.lineage) - 1
            child_index = self.lineage[-1][0] - 1
            glyph.addAnchorPoint(anchors.PARENT_EDGE, 'basemark', 0, 0)
            glyph.addAnchorPoint(anchors.INTER_EDGES[layer_index][child_index], 'mark', 0, 0)
        return False

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class RootOnlyParentEdge(Shape):
    """A marker for a character that can only be the root of an overlap
    tree, not a child.
    """

    def __str__(self) -> str:
        return 'pe'

    @staticmethod
    def name_implies_type() -> bool:
        return True

    def invisible(self) -> bool:
        return True

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.MARK


class Dot(Shape):
    """A dot.

    Attributes:
        size_exponent: The exponent to use when determining the actual
            stroke width. The actual stroke width is the nominal stroke
            width multiplied by `SCALAR` raised to the power of
            `size_exponent`. A standalone dot should normally be scaled
            up lest it be hard to see at small font sizes.
        centered: Whether the cursive anchor points are placed in the
            center of the dot, as opposed to at the bottom.
    """

    #: The factor to use when determining the actual stroke width. See
    #: the ``size_exponent`` attribute.
    SCALAR: ClassVar[float] = 2 ** 0.5

    def __init__(
        self,
        size_exponent: float = 1,
        *,
        centered: bool = False,
    ) -> None:
        """Initializes this `Dot`.

        Args:
            size_exponent: The ``size_exponent`` attribute.
            centered: The ``centered`` attribute.
        """
        self.size_exponent = size_exponent
        self.centered = centered

    def clone(
        self,
        *,
        size_exponent: bool | CloneDefault = CLONE_DEFAULT,
        centered: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            size_exponent=self.size_exponent if size_exponent is CLONE_DEFAULT else size_exponent,
            centered=self.centered if centered is CLONE_DEFAULT else centered,
        )

    def __str__(self) -> str:
        return '' if self.size_exponent == 1 else str(int(self.size_exponent))

    def group(self) -> Hashable:
        return (
            self.centered,
            self.size_exponent,
        )

    def hub_priority(self, size: float) -> int:
        return -1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        assert pen
        assert not child
        stroke_width *= self.SCALAR ** self.size_exponent
        pen.moveTo((0, 0))
        pen.lineTo((0, 0))
        glyph.stroke('circular', stroke_width, 'round')
        if anchor:
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *_rect(0, 0))
            glyph.addAnchorPoint(anchor, 'mark', *_rect(0, 0))
        elif joining_type != Type.NON_JOINING:
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', 0, 0 if self.centered else -(stroke_width / 2))
            glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', 0, 0 if self.centered else -(stroke_width / 2))
        return False

    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    def is_shadable(self) -> bool:
        return True

    def context_in(self) -> Context:
        return NO_CONTEXT

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
        final_tick: Whether to add a small tick at the end of the stroke
            as a visual separator from cognates.
        original_angle: The original `angle` of the shape from which
            this shape is derived through some number of phases.
    """

    def __init__(
        self,
        angle: float,
        *,
        minor: bool = False,
        stretchy: bool = False,
        secant: Optional[float] = None,
        secant_curvature_offset: float = 45,
        dots: Optional[int] = None,
        final_tick: bool = False,
        original_angle: Optional[float] = None,
    ) -> None:
        """Initializes this `Line`.

        Args:
            angle: The ``angle`` attribute.
            minor: The ``minor`` attribute.
            stretchy: The ``stretchy`` attribute.
            secant: The ``secant`` attribute.
            secant_curvature_offset: The ``secant_curvature_offset`` attribute.
            dots: The ``dots`` attribute.
            final_tick: The ``final_tick`` attribute.
            original_angle: The ``original_angle`` attribute.
        """
        self.angle = angle
        self.minor = minor
        self.stretchy = stretchy
        self.secant = secant
        self.secant_curvature_offset = secant_curvature_offset
        self.dots = dots
        self.final_tick = final_tick
        self.original_angle = original_angle

    def clone(
        self,
        *,
        angle: float | CloneDefault = CLONE_DEFAULT,
        minor: bool | CloneDefault = CLONE_DEFAULT,
        stretchy: bool | CloneDefault = CLONE_DEFAULT,
        secant: Optional[float] | CloneDefault = CLONE_DEFAULT,
        secant_curvature_offset: float | CloneDefault = CLONE_DEFAULT,
        dots: Optional[int] | CloneDefault = CLONE_DEFAULT,
        final_tick: bool | CloneDefault = CLONE_DEFAULT,
        original_angle: Optional[float] | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            minor=self.minor if minor is CLONE_DEFAULT else minor,
            stretchy=self.stretchy if stretchy is CLONE_DEFAULT else stretchy,
            secant=self.secant if secant is CLONE_DEFAULT else secant,
            secant_curvature_offset=self.secant_curvature_offset if secant_curvature_offset is CLONE_DEFAULT else secant_curvature_offset,
            dots=self.dots if dots is CLONE_DEFAULT else dots,
            final_tick=self.final_tick if final_tick is CLONE_DEFAULT else final_tick,
            original_angle=self.original_angle if original_angle is CLONE_DEFAULT else original_angle,
        )

    def __str__(self) -> str:
        if self.final_tick:
            s = 'tick'
        elif self.dots or not self.stretchy:
            s = str(int(self.angle))
            if self.dots:
                s += '.dotted'
        else:
            s = ''
        return s

    def group(self) -> Hashable:
        return (
            self.angle,
            self.stretchy,
            self.secant,
            self.secant_curvature_offset,
            self.dots,
            self.final_tick,
            self.original_angle if self.original_angle != self.angle else None,
        )

    @staticmethod
    def can_take_secant() -> bool:
        return True

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

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        assert pen
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
            if self.final_tick:
                end_y = 100 if 90 < self.angle <= 270 else -100
                pen.lineTo((length, end_y))
        if anchor:
            if (joining_type == Type.ORIENTING
                or self.angle % 180 == 0
                or anchor not in [anchors.ABOVE, anchors.BELOW]
            ):
                length *= self.secant or 0.5
            elif (anchor == anchors.ABOVE) == (self.angle < 180):
                length = 0
            glyph.addAnchorPoint(anchor, 'mark', length, end_y)
            glyph.addAnchorPoint(mkmk(anchor), 'mark', length, end_y)
        elif self.secant:
            glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
            glyph.addAnchorPoint(anchors.PRE_HUB_CONTINUING_OVERLAP, 'exit', length * self.secant, end_y)
        else:
            anchor_name = mkmk if child else lambda a: a
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = length / (max_tree_width + 2)
                for child_index in range(max_tree_width):
                    glyph.addAnchorPoint(
                        anchors.CHILD_EDGES[int(child)][child_index],
                        base,
                        child_interval * (child_index + 2),
                        0,
                    )
                if child:
                    glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', child_interval, 0)
                else:
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', child_interval, 0)
                    glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'exit', child_interval * (max_tree_width + 1), 0)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'entry', 0, 0)
                    glyph.addAnchorPoint(anchors.CURSIVE, 'exit', length, end_y)
                    glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', child_interval, 0)
                    if self.hub_priority(size) != -1:
                        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', 0, 0)
                    if self.hub_priority(size) != 0:
                        glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', length, end_y)
                    glyph.addAnchorPoint(anchor_name(anchors.SECANT), base, child_interval * (max_tree_width + 1), 0)
            if size == 2 and 0 < self.angle <= 45:
                # Special case for U+1BC18 DUPLOYAN LETTER RH
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, length / 2 - (light_line + stroke_gap), -(stroke_width + Dot.SCALAR * light_line) / 2)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, length / 2 + light_line + stroke_gap, -(stroke_width + Dot.SCALAR * light_line) / 2)
            else:
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, length / 2, (stroke_width + Dot.SCALAR * light_line) / 2)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, length / 2, -(stroke_width + Dot.SCALAR * light_line) / 2)
            glyph.addAnchorPoint(anchor_name(anchors.MIDDLE), base, length / 2, 0)
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self.angle)),
            ('round',)
        )
        glyph.stroke('circular', stroke_width, 'round')
        floating = False
        if not anchor:
            if self.secant is None:
                x_min, y_min, x_max, y_max = glyph.boundingBox()
                x_center = (x_max + x_min) / 2
                glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_width / 2 + 2 * stroke_gap + light_line / 2)
                glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - (stroke_width / 2 + 2 * stroke_gap + light_line / 2))
            elif self.angle % 90 == 0:
                floating = True
                y_offset = 2 * LINE_FACTOR * (2 * self.secant - 1)
                if self.get_guideline_angle() % 180 == 90:
                    glyph.transform(fontTools.misc.transform.Offset(y=y_offset + stroke_width / 2))
                else:
                    glyph.transform(fontTools.misc.transform.Offset(y=-y_offset - LINE_FACTOR + stroke_width / 2))
        return floating

    def can_be_child(self, size: float) -> bool:
        return not (self.secant or self.dots)

    def max_tree_width(self, size: float) -> int:
        return 2 if size == 2 and not self.secant else 1

    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        return (0
            if self.secant or self.dots or any(
                m.anchor in [anchors.RELATIVE_1, anchors.RELATIVE_2, anchors.MIDDLE]
                    for m in marks
            ) else int(self._get_length(size) // (250 * 0.45)) - 1)

    def is_shadable(self) -> bool:
        return not self.dots

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if self.secant:
            if context_out != NO_CONTEXT:
                return self.rotate_diacritic(context_out)
        else:
            if self.stretchy:
                if context_out == Context(self.angle):
                    return self.clone(final_tick=True)
            elif context_in != NO_CONTEXT:
                return self.clone(angle=context_in.angle)  # type: ignore[arg-type]
        return self

    def context_in(self) -> Context:
        # FIXME: This should use the current angle, not the original angle.
        return Context(self.angle if self.original_angle is None else self.original_angle, minor=self.minor)

    def context_out(self) -> Context:
        # FIXME: This should use the current angle, not the original angle.
        return Context(self.angle if self.original_angle is None else self.original_angle, minor=self.minor)

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

    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        angle = float(self.angle % 180)
        return {
            anchors.RELATIVE_1: angle,
            anchors.RELATIVE_2: angle,
            anchors.MIDDLE: (angle + 90) % 180,
            anchors.SECANT: angle,
        }

    def reversed(self) -> Line:
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
    """The axis alone which a `Curve` is stretched.
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
            curve is an arc of a circle.
        long: Whether to stretch this curve along the axis perpendicular
            to the one indicated by `stretch_axis`. This has no effect
            if ``stretch == 0``.
        stretch_axis: The axis along which this curve is stretched.
        hook: Whether this curve represents a hook character.
        reversed_circle: Whether this curve represents a reversed circle
            character.
        overlap_angle: The angle from the ellipse’s center to the point
            at which this curve overlaps a parent glyph. This may only
            be ``True`` for semiellipses; there is no geometrical reason
            for this, but this attribute is a hack that only happens to
            be needed for semiellipses. If this attribute is ``None``,
            it uses the default angle.
        secondary: Whether this curve represents a secondary curve
            character.
        would_flip: Whether this curve is in a context where it looks
            confusingly like a loop, i.e. a circle letter, such that it
            would be less confusing if it flipped its chirality. A curve
            is not allowed to flip its chirality, but this attribute
            tracks whether it would help so the problem can be resolved
            another way.
        early_exit: Whether this curve’s normal cursive exit point is
            placed earlier than its apparent exit point. This may only
            be ``True`` if `would_flip` is also ``True``.
    """

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
        reversed_circle: bool = False,
        overlap_angle: Optional[float] = None,
        secondary: Optional[bool] = None,
        would_flip: bool = False,
        early_exit: bool = False,
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
            would_flip: The ``would_flip`` attribute.
            early_exit: The ``early_exit`` attribute.
        """
        assert overlap_angle is None or abs(angle_out - angle_in) == 180, 'Only a semicircle may have an overlap angle'
        assert would_flip or not early_exit, 'An early exit is not needed if the curve would not flip'
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.stretch = stretch
        self.long = long
        self.stretch_axis = stretch_axis
        self.hook = hook
        self.reversed_circle = reversed_circle
        self.overlap_angle = overlap_angle if overlap_angle is None else overlap_angle % 180
        self.secondary = clockwise if secondary is None else secondary
        self.would_flip = would_flip
        self.early_exit = early_exit

    def clone(
        self,
        *,
        angle_in: float | CloneDefault = CLONE_DEFAULT,
        angle_out: float | CloneDefault = CLONE_DEFAULT,
        clockwise: bool | CloneDefault = CLONE_DEFAULT,
        stretch: float | CloneDefault = CLONE_DEFAULT,
        long: bool | CloneDefault = CLONE_DEFAULT,
        stretch_axis: StretchAxis | CloneDefault = CLONE_DEFAULT,
        hook: bool | CloneDefault = CLONE_DEFAULT,
        reversed_circle: bool | CloneDefault = CLONE_DEFAULT,
        overlap_angle: Optional[float] | CloneDefault = CLONE_DEFAULT,
        secondary: Optional[bool] | CloneDefault = CLONE_DEFAULT,
        would_flip: bool | CloneDefault = CLONE_DEFAULT,
        early_exit: bool | CloneDefault = CLONE_DEFAULT,
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
            would_flip=self.would_flip if would_flip is CLONE_DEFAULT else would_flip,
            early_exit=self.early_exit if early_exit is CLONE_DEFAULT else early_exit,
        )

    def __str__(self) -> str:
        return f'''{
                int(self.angle_in)
            }{
                'n' if self.clockwise else 'p'
            }{
                int(self.angle_out)
            }{
                'r' if self.reversed_circle else ''
            }{
                '.ee' if self.early_exit else ''
            }'''

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
            self.early_exit,
        )

    @staticmethod
    def can_take_secant() -> bool:
        return True

    def hub_priority(self, size: float) -> int:
        return 0 if size >= 6 else 1

    def _get_normalized_angles(
        self,
        diphthong_1: bool = False,
        diphthong_2: bool = False,
    ) -> tuple[float, float]:
        angle_in = self.angle_in
        angle_out = self.angle_out
        if diphthong_1:
            angle_out = (angle_out + 90 * (1 if self.clockwise else -1)) % 360
        if diphthong_2:
            angle_in = (angle_in - 90 * (1 if self.clockwise else -1)) % 360
        if self.clockwise and angle_out > angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
        return a1, a2

    def _get_normalized_angles_and_da(
        self,
        diphthong_1: bool,
        diphthong_2: bool,
        final_circle_diphthong: bool,
        initial_circle_diphthong: bool,
    ) -> tuple[float, float, float]:
        a1, a2 = self._get_normalized_angles(diphthong_1, diphthong_2)
        if final_circle_diphthong:
            a2 = a1
        elif initial_circle_diphthong:
            a1 = a2
        return a1, a2, a2 - a1 or 360

    def get_da(self) -> float:
        """Returns the difference between the entry and exit angles.

        Returns:
            The difference between this curve’s entry angle and exit
            angle in the range (0, 360].
        """
        return self._get_normalized_angles_and_da(False, False, False, False)[2]

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
                False,
            )
        ):
            angle_to_overlap_point += 180
        angle_at_overlap_point = (angle_to_overlap_point - (90 if self.clockwise else -90)) % 180
        exclusivity_zone = 30
        if self.in_degree_range(
            angle_to_overlap_point,
            ((a1 if is_entry else a2) - exclusivity_zone) % 360,
            ((a1 if is_entry else a2) + exclusivity_zone) % 360,
            False,
        ):
            delta = abs(angle_to_overlap_point - self.overlap_angle - (180 if is_entry else 0)) - exclusivity_zone
            if is_entry != self.clockwise:
                delta = -delta
            angle_to_overlap_point += delta
        return angle_to_overlap_point % 360

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        assert pen
        a1, a2, da = self._get_normalized_angles_and_da(diphthong_1, diphthong_2, final_circle_diphthong, initial_circle_diphthong)
        r = int(RADIUS * size)
        beziers_needed = int(math.ceil(abs(da) / 90))
        bezier_arc = da / beziers_needed
        cp = r * (4 / 3) * math.tan(math.pi / (2 * beziers_needed * 360 / da))
        cp_distance = math.hypot(cp, r)
        cp_angle = math.asin(cp / cp_distance)
        p0 = _rect(r, math.radians(a1))
        if diphthong_2:
            entry = _rect(r, math.radians((a1 + 90 * (1 if self.clockwise else -1)) % 360))
            entry = (p0[0] + entry[0], p0[1] + entry[1])
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
            swash_length = math.sin(math.radians(swash_angle)) * r / math.sin(math.radians(90 - swash_angle))
            swash_endpoint = _rect(abs(swash_length), math.radians(self.angle_out))
            swash_endpoint = (p3[0] + swash_endpoint[0], p3[1] + swash_endpoint[1])
            pen.lineTo(swash_endpoint)
            exit = _rect(min(r, abs(swash_length)), math.radians(self.angle_out))
            exit = (p3[0] + exit[0], p3[1] + exit[1])
        elif self.early_exit:
            # TODO: Track the precise output angle instead of assuming that the exit
            # should be halfway along the curve.
            exit = _rect(r, math.radians(a1 + da / 2))
        else:
            exit = p3
        if diphthong_1:
            exit_delta = _rect(r, math.radians((a2 - 90 * (1 if self.clockwise else -1)) % 360))
            exit = (exit[0] + exit_delta[0], exit[1] + exit_delta[1])
            pen.lineTo(exit)
        pen.endPath()
        relative_mark_angle = (a1 + a2) / 2
        anchor_name = mkmk if child else lambda a: a
        if anchor:
            glyph.addAnchorPoint(anchor, 'mark', *_rect(r, math.radians(relative_mark_angle)))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', *_rect(r, math.radians(relative_mark_angle)))
        else:
            base = 'basemark' if child else 'base'
            if joining_type != Type.NON_JOINING:
                max_tree_width = self.max_tree_width(size)
                child_interval = da / (max_tree_width + 2)
                if self.overlap_angle is None:
                    for child_index in range(max_tree_width):
                        glyph.addAnchorPoint(
                            anchors.CHILD_EDGES[int(child)][child_index],
                            base,
                            *_rect(r, math.radians(a1 + child_interval * (child_index + 2))),
                        )
                else:
                    overlap_exit_angle = self._get_angle_to_overlap_point(a1, a2, is_entry=False)
                    glyph.addAnchorPoint(
                        anchors.CHILD_EDGES[int(child)][0],
                        base,
                        *_rect(r, math.radians(overlap_exit_angle)),
                    )
                overlap_entry_angle = (a1 + child_interval
                    if self.overlap_angle is None
                    else self._get_angle_to_overlap_point(a1, a2, is_entry=True))
                if child:
                    glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', *_rect(r, math.radians(overlap_entry_angle)))
                else:
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
                        anchor_name(anchors.SECANT),
                        base,
                        *_rect(0, 0)
                            if abs(da) > 180
                            else _rect(r, math.radians(a1 + child_interval * (max_tree_width + 1))),
                    )
            glyph.addAnchorPoint(anchor_name(anchors.MIDDLE), base, *_rect(r, math.radians(relative_mark_angle)))
        if not anchor:
            if self.stretch:
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
                theta = math.radians(theta % 180)
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, *_rect(0, 0))
                glyph.transform(
                    fontTools.misc.transform.Identity
                        .rotate(theta)
                        .scale(scale_x, scale_y)
                        .rotate(-theta),
                )
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(scale_x * r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(self.angle_in)))
            else:
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base,
                    *(_rect(0, 0) if abs(da) > 180 else _rect(
                        min(stroke_width, r - (stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2)),
                        math.radians(relative_mark_angle))))
                glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(relative_mark_angle)))
        glyph.stroke('circular', stroke_width, 'round')
        if not anchor:
            x_min, y_min, x_max, y_max = glyph.boundingBox()
            x_center = (x_max + x_min) / 2
            glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_gap)
            glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - stroke_gap)
        return False

    def can_be_child(self, size: float) -> bool:
        a1, a2 = self._get_normalized_angles()
        return abs(a2 - a1) <= 180

    def max_tree_width(self, size: float) -> int:
        return 1

    def max_double_marks(self, size: float, joining_type: Type, marks: Sequence[Schema]) -> int:
        if any(m.anchor == anchors.MIDDLE for m in marks):
            return 0
        a1, a2 = self._get_normalized_angles()
        return min(3, int(abs(a1 - a2) / 360 * size))

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

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
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

        if self.hook:
            candidate_angle_in = self.angle_in
            candidate_angle_out = self.angle_out
            candidate_clockwise = self.clockwise
            if context_in == NO_CONTEXT:
                if candidate_angle_out == context_out.angle:
                    candidate_clockwise = not candidate_clockwise
                    candidate_angle_out = (candidate_angle_out + 180) % 360
                    candidate_angle_in = (candidate_angle_out - da) % 360
            else:
                if candidate_angle_in == context_in.angle:
                    candidate_clockwise = not candidate_clockwise
                    candidate_angle_in = (candidate_angle_in + 180) % 360
                    candidate_angle_out = (candidate_angle_in + da) % 360
        else:
            candidate_angle_in = angle_in
            candidate_angle_out = (candidate_angle_in + da) % 360
            candidate_clockwise = self.clockwise
            if candidate_clockwise != (context_in == NO_CONTEXT):
                flip()
            clockwise_from_adjacent_curve = (
                context_in.clockwise
                    if context_in != NO_CONTEXT
                    else context_out.clockwise
            )
            if self.secondary != (clockwise_from_adjacent_curve not in [None, candidate_clockwise]):
                flip()
        if self.hook or (context_in != NO_CONTEXT != context_out):
            final_hook = self.hook and context_in != NO_CONTEXT
            if final_hook:
                flip()
                context_out = context_in.reversed()
                context_in = NO_CONTEXT
                angle_in, angle_out = (angle_out + 180) % 360, (angle_in + 180) % 360
            context_clockwises = (context_in.clockwise, context_out.clockwise)
            curve_offset = 0 if context_clockwises in [(None, None), (True, False), (False, True)] else CURVE_OFFSET
            if False in context_clockwises:
                curve_offset = -curve_offset
            a1, a2 = self._get_normalized_angles()
            slight_overlap_offset = abs(a1 - a2) / 3 * (1 if candidate_clockwise else -1)
            if final_hook == (
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
                flips += not final_hook
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
            would_flip=would_flip,
        )

    def context_in(self) -> Context:
        return Context(self.angle_in, self.clockwise)

    def context_out(self) -> Context:
        return Context(self.angle_out, self.clockwise)

    def calculate_diacritic_angles(self) -> Mapping[str, float]:
        halfway_angle = (self.angle_in + self.angle_out) / 2 % 180
        return {
            anchors.RELATIVE_1: halfway_angle,
            anchors.RELATIVE_2: halfway_angle,
            anchors.MIDDLE: (halfway_angle + 90) % 180,
            anchors.SECANT: self.angle_out % 180,
        }

    def reversed(self) -> Curve:
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
        reversed: Whether this represents a reversed circle character.
            The only reversed circle character in Unicode is U+1BC42
            DUPLOYAN LETTER SLOAN OW.
        pinned: Whether to force this circle to stay a `Circle` when
            contextualized, even if a `Curve` would normally be
            considered more appropriate.
        stretch: How much to stretch this circle in one axis, as a
            proportion of the other axis. If ``stretch == 0``, this
            circle is a true circle instead of merely an ellipse.
        long: Whether to stretch this ellipse along the axis
            perpendicular to the entry angle, as opposed to parallel.
            This has no effect if ``stretch == 0``.
        role: The role of this circle in its orienting sequence.
    """

    def __init__(
        self,
        angle_in: float,
        angle_out: float,
        *,
        clockwise: bool,
        reversed: bool = False,
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
            reversed: The ``reversed`` attribute.
            pinned: The ``pinned`` attribute.
            stretch: The ``stretch`` attribute.
            long: The ``long`` attribute.
            role: The ``role`` attribute.
        """
        self.angle_in = angle_in
        self.angle_out = angle_out
        self.clockwise = clockwise
        self.reversed = reversed
        self.pinned = pinned
        self.stretch = stretch
        self.long = long
        self.role = role

    def clone(
        self,
        *,
        angle_in: float | CloneDefault = CLONE_DEFAULT,
        angle_out: float | CloneDefault = CLONE_DEFAULT,
        clockwise: bool | CloneDefault = CLONE_DEFAULT,
        reversed: bool | CloneDefault = CLONE_DEFAULT,
        pinned: bool | CloneDefault = CLONE_DEFAULT,
        stretch: float | CloneDefault = CLONE_DEFAULT,
        long: bool | CloneDefault = CLONE_DEFAULT,
        role: CircleRole | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle_in if angle_in is CLONE_DEFAULT else angle_in,
            self.angle_out if angle_out is CLONE_DEFAULT else angle_out,
            clockwise=self.clockwise if clockwise is CLONE_DEFAULT else clockwise,
            reversed=self.reversed if reversed is CLONE_DEFAULT else reversed,
            pinned=self.pinned if pinned is CLONE_DEFAULT else pinned,
            stretch=self.stretch if stretch is CLONE_DEFAULT else stretch,
            long=self.long if long is CLONE_DEFAULT else long,
            role=self.role if role is CLONE_DEFAULT else role,
        )

    def __str__(self) -> str:
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
                'r' if self.reversed and self.angle_in != self.angle_out else ''
            }{
                '.circle' if self.role != CircleRole.INDEPENDENT and self.angle_in != self.angle_out else ''
            }'''

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

    @staticmethod
    def can_take_secant() -> bool:
        return True

    def hub_priority(self, size: float) -> int:
        return 0 if size >= 6 else 1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        angle_in = self.angle_in
        angle_out = self.angle_out
        if (diphthong_1 or diphthong_2) and angle_in == angle_out:
            Curve(
                    angle_in,
                    angle_out,
                    clockwise=self.clockwise,
                    stretch=self.stretch,
                    long=True,
                    reversed_circle=self.reversed,
                ).draw(
                    glyph,
                    pen,
                    stroke_width,
                    light_line,
                    stroke_gap,
                    size,
                    anchor,
                    joining_type,
                    child,
                    initial_circle_diphthong,
                    final_circle_diphthong,
                    diphthong_1,
                    diphthong_2,
                )
            return False
        assert pen
        if diphthong_1:
            angle_out = (angle_out + 90 * (1 if self.clockwise else -1)) % 360
        if diphthong_2:
            angle_in = (angle_in - 90 * (1 if self.clockwise else -1)) % 360
        if self.clockwise and angle_out > angle_in:
            angle_out -= 360
        elif not self.clockwise and angle_out < angle_in:
            angle_out += 360
        a1 = (90 if self.clockwise else -90) + angle_in
        a2 = (90 if self.clockwise else -90) + angle_out
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
        anchor_name = mkmk if child else lambda a: a
        base = 'basemark' if child else 'base'
        if joining_type != Type.NON_JOINING:
            if child:
                glyph.addAnchorPoint(anchors.PARENT_EDGE, 'mark', 0, 0)
            else:
                glyph.addAnchorPoint(anchors.CONTINUING_OVERLAP, 'entry', 0, 0)
                glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
                glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
                glyph.addAnchorPoint(anchors.POST_HUB_CONTINUING_OVERLAP, 'entry', 0, 0)
                if self.hub_priority(size) != -1:
                    glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
                if self.hub_priority(size) != 0:
                    glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
                glyph.addAnchorPoint(anchor_name(anchors.SECANT), base, 0, 0)
        glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_1), base, *_rect(0, 0))
        if anchor:
            glyph.addAnchorPoint(anchors.MIDDLE, 'mark', 0, 0)
        if self.stretch:
            scale_x = 1.0 + self.stretch
            scale_y = 1.0
            if self.long:
                scale_x, scale_y = scale_y, scale_x
            theta = math.radians(angle_in % 180)
            glyph.transform(
                fontTools.misc.transform.Identity
                    .rotate(theta)
                    .scale(scale_x, scale_y)
                    .rotate(-theta),
            )
            glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(scale_x * r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians(angle_in)))
        else:
            glyph.addAnchorPoint(anchor_name(anchors.RELATIVE_2), base, *_rect(r + stroke_width / 2 + stroke_gap + Dot.SCALAR * light_line / 2, math.radians((a1 + a2) / 2)))
        glyph.stroke('circular', stroke_width, 'round')
        if diphthong_1 or diphthong_2:
            glyph.removeOverlap()
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_center = (x_max + x_min) / 2
        glyph.addAnchorPoint(anchor_name(anchors.ABOVE), base, x_center, y_max + stroke_gap)
        glyph.addAnchorPoint(anchor_name(anchors.BELOW), base, x_center, y_min - stroke_gap)
        return False

    def can_be_child(self, size: float) -> bool:
        return True

    def max_tree_width(self, size: float) -> int:
        return 0

    def is_shadable(self) -> bool:
        return True

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
        is_reversed = self.reversed and self.role != CircleRole.LEADER
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
        if self.role != CircleRole.INDEPENDENT and (self.pinned or not is_reversed):
            return self.clone(
                angle_in=angle_in,
                angle_out=angle_in if self.role == CircleRole.LEADER else angle_out,
                clockwise=clockwise,
            )
        elif clockwise_ignoring_reversal == clockwise_ignoring_curvature:
            if is_reversed:
                if da != 180:
                    return Curve(
                        angle_in,
                        (angle_out + 180) % 360,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=True,
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
                if da != 180:
                    return Curve(
                        angle_in,
                        angle_out,
                        clockwise=clockwise,
                        stretch=self.stretch,
                        long=True,
                        reversed_circle=True,
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

    def context_in(self) -> Context:
        return Context(self.angle_in, self.clockwise)

    def context_out(self) -> Context:
        return Context(self.angle_out, self.clockwise)

    def as_reversed(self) -> Circle:
        """Returns a `Circle` that looks the same but is drawn in the
        opposite direction.
        """
        return self.clone(
            angle_in=(self.angle_out + 180) % 360,
            angle_out=(self.angle_in + 180) % 360,
            clockwise=not self.clockwise,
            reversed=not self.reversed,
        )


_AnchorType = Literal['base', 'basemark', 'entry', 'exit', 'ligature', 'mark']


_Instruction = Callable[[Context], Context] | tuple[float, Shape] | tuple[float, Shape, bool]


_Instructions = Sequence[_Instruction]


_MutableInstructions = MutableSequence[_Instruction]


_Point = tuple[float, float]


class Complex(Shape):
    """A shape built out of other shapes.

    Attributes:
        instructions: A sequence of instructions for how to build this
            compound shape. Each instruction is either a tuple,
            representing a shape to include in this one, or a callable,
            which modifies the context.

            A tuple instruction has two or three elements. The second
            element is a component shape to include in this shape. The
            first element is the size by which to scale the component
            shape. The third element, which is treated as ``False`` if
            absent, indicates whether to skip drawing the component
            shape. (Anchor points are never skipped.)

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
        hook: Whether this shape represents a hook character. If so, in
            initial position, everything about entry and exit contexts
            is swapped when contextualizing, and the order of the
            components is reversed.
        maximum_tree_width: The maximum width of a shorthand overlap
            sequence following a character with this shape.
    """

    def __init__(
        self,
        instructions: _Instructions,
        *,
        hook: bool = False,
        maximum_tree_width: int = 0,
        _final_rotation: float = 0,
    ) -> None:
        """Initializes this `Complex`.

        Args:
            instructions: The ``instructions`` attribute.
            hook: The ``hook`` attribute.
            maximum_tree_width: The ``maximum_tree_width`` attribute.
        """
        self.instructions = instructions
        self.hook = hook
        self.maximum_tree_width = maximum_tree_width
        self._final_rotation = _final_rotation

    def clone(
        self,
        *,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
        hook: bool | CloneDefault = CLONE_DEFAULT,
        maximum_tree_width: int | CloneDefault = CLONE_DEFAULT,
        _final_rotation: float | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            hook=self.hook if hook is CLONE_DEFAULT else hook,
            maximum_tree_width=self.maximum_tree_width if maximum_tree_width is CLONE_DEFAULT else maximum_tree_width,
            _final_rotation=self._final_rotation if _final_rotation is CLONE_DEFAULT else _final_rotation,
        )

    def __str__(self) -> str:
        if self._final_rotation:
            return str(int(self._final_rotation))
        non_callables = filter(lambda op: not callable(op), self.instructions)
        op = next(non_callables)
        assert not callable(op)
        if isinstance(op[1], Circle):
            op = next(non_callables)
            assert not callable(op)
        return str(op[1])

    def group(self) -> Hashable:
        return (
            *(op if callable(op) else (op[0], op[1].group(), op[2:]) for op in self.instructions),
            self._final_rotation,
        )

    def hub_priority(self, size: float) -> int:
        first_scalar, first_component, *_ = next(op for op in self.instructions if not (callable(op) or op[1].invisible()))
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
            self.anchor_points: collections.defaultdict[tuple[str, _AnchorType], MutableSequence[_Point]] = collections.defaultdict(list)
            self._layer = fontforge.layer()
            self._layer += fontforge.contour()

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
            self.anchor_points[(anchor_class_name, anchor_type)].append((x, y))

        def stroke(
            self,
            nib_type: LiteralString,
            width_or_contour: float,
            *args: float | str | tuple[str, ...],
            **kwargs: bool | float | str,
        ) -> None:
            """Simulates `fontforge.glyph.stroke`.

            Args:
                nib_type: The first argument.
                width_or_contour: The ``width`` or ``contour`` argument,
                    depending on `stroke_type`.
                args: Further arguments.
                kwargs: Further keyword arguments.
            """
            self._layer.stroke(nib_type, width_or_contour, *args, **kwargs)

        def boundingBox(self) -> tuple[float, float, float, float]:
            """Simulates `fontforge.glyph.boundingBox`.
            """
            return cast(tuple[float, float, float, float], self._layer.boundingBox())

        def draw(self, pen: fontforge.glyphPen) -> None:
            """Draws the collected data to a FontForge glyph.

            Args:
                pen: The pen to draw with.
            """
            assert all(len(contour) == 0 or contour.closed for contour in self._layer), (
                f'''A proxy contains an open contour: {
                    list((point.x, point.y) for point in next(filter(lambda contour: len(contour) and not contour.closed, self._layer)))
                }''')
            self._layer.draw(pen)

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
                contour.lineTo(*x_y)

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
            entry_list = self.anchor_points[(anchors.CURSIVE, 'entry')]
            assert len(entry_list) == 1
            if component.angle_in == component.angle_out:
                return entry_list[0]
            exit_list = self.anchor_points[(anchors.CURSIVE, 'exit')]
            assert len(exit_list) == 1
            if isinstance(component, Circle):
                rel1_list = self.anchor_points[(anchors.RELATIVE_1, 'base')]
                assert len(rel1_list) == 1
                rel2_list = self.anchor_points[(anchors.RELATIVE_2, 'base')]
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
            v = (dy * adx - dx * ady) / det
            px = asx + adx * u
            py = asy + ady * u
            return px, py

    def draw_to_proxy(
        self,
        pen: fontforge.glyphPen,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[bool, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        """Draws this shape to a `Proxy`.

        This method is split out from `draw` so that subclasses can
        override it.

        Args:
            pen: The ``pen`` argument from `draw`.
            stroke_width: The ``stroke_width`` argument from `draw`.
            light_line: The ``light_line`` argument from `draw`.
            stroke_gap: The ``stroke_gap`` argument from `draw`.
            size: The ``size`` argument from `draw`.

        Returns:
            A tuple of two elements.

            The first element is whether the first component is
            invisible.

            The second element is the mapping of all components’
            singular anchor points. An anchor point is singular if no
            other anchor points in the same component share the same
            anchor name and anchor type.
        """
        first_is_invisible = None
        singular_anchor_points: collections.defaultdict[tuple[str, _AnchorType], list[_Point]] = collections.defaultdict(list)
        for op in self.instructions:
            if callable(op):
                continue
            scalar, component, *skip_drawing = op
            proxy = Complex.Proxy()
            component.draw(
                proxy,
                proxy,
                stroke_width,
                light_line,
                stroke_gap,
                scalar * size,
                None,
                Type.JOINING,
                False,
                False,
                False,
                False,
                False,
            )
            if first_is_invisible is None:
                first_is_invisible = component.invisible()
            this_entry_list = proxy.anchor_points[(anchors.CURSIVE, 'entry')]
            assert len(this_entry_list) == 1
            this_x, this_y = this_entry_list[0]
            if exit_list := singular_anchor_points.get((anchors.CURSIVE, 'exit')):
                last_x, last_y = exit_list[-1]
                proxy.transform(fontTools.misc.transform.Offset(
                    last_x - this_x,
                    last_y - this_y,
                ))
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1:
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not (skip_drawing and skip_drawing[0]):
                proxy.draw(pen)
        assert first_is_invisible is not None
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    @staticmethod
    def _remove_bad_contours(glyph: fontforge.glyph) -> None:
        """Removes contours that might crash FontForge.

        See `FontForge issue #4560
        <https://github.com/fontforge/fontforge/issues/4560>`__.
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

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        (
            first_is_invisible,
            singular_anchor_points,
        ) = self.draw_to_proxy(pen, stroke_width, light_line, stroke_gap, size)
        glyph.removeOverlap()
        self._remove_bad_contours(glyph)
        if not (anchor or child or joining_type == Type.NON_JOINING):
            entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][0 if self.enter_on_first_path() else -1]
            exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][-1]
            glyph.addAnchorPoint(anchors.CURSIVE, 'entry', *entry)
            glyph.addAnchorPoint(anchors.CURSIVE, 'exit', *exit)
            if self.hub_priority(size) != -1:
                glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', *entry)
            if self.hub_priority(size) != 0:
                glyph.addAnchorPoint(anchors.PRE_HUB_CURSIVE, 'exit', *exit)
        anchor_name = mkmk if anchor or child else lambda a: a
        base = 'basemark' if anchor or child else 'base'
        if anchor is None:
            for (singular_anchor, type), points in singular_anchor_points.items():
                if singular_anchor in anchors.ALL_MARK or (
                    self.maximum_tree_width and (
                        singular_anchor == anchors.CONTINUING_OVERLAP
                        or any(map(lambda l: singular_anchor in l, anchors.CHILD_EDGES))
                    )
                ):
                    glyph.addAnchorPoint(singular_anchor, type, *points[-1])
        glyph.transform(
            fontTools.misc.transform.Identity.rotate(math.radians(self._final_rotation)),
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
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_min + stroke_width / 2)
        elif anchor == anchors.BELOW:
            glyph.addAnchorPoint(anchor, 'mark', x_center, y_max - stroke_width / 2)
            glyph.addAnchorPoint(mkmk(anchor), 'basemark', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
            glyph.addAnchorPoint(mkmk(anchor), 'mark', x_center, y_max - stroke_width / 2)
        elif anchor is None:
            glyph.addAnchorPoint(anchors.MIDDLE, 'base', x_center, y_center)
            glyph.addAnchorPoint(anchors.ABOVE, 'base', x_center, y_max + stroke_width / 2 + stroke_gap + light_line / 2)
            glyph.addAnchorPoint(anchors.BELOW, 'base', x_center, y_min - (stroke_width / 2 + stroke_gap + light_line / 2))
        return first_is_invisible

    def can_be_child(self, size: float) -> bool:
        # TODO: return not callable(self.instructions[0]) and self.instructions[0][1].can_be_child(size)
        return False

    def max_tree_width(self, size: float) -> int:
        return self.maximum_tree_width

    def is_shadable(self) -> bool:
        return all(callable(op) or op[1].is_shadable() for op in self.instructions)

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        instructions: _MutableInstructions = []
        initial_hook = context_in == NO_CONTEXT and self.hook
        forced_context = None
        for i, op in enumerate(self.instructions):
            if callable(op):
                forced_context = op(context_out if initial_hook else context_in)
                if forced_context.ignorable_for_topography:
                    forced_context = forced_context.clone(ignorable_for_topography=False)
                instructions.append(op)
            else:
                scalar, component = op  # type: ignore[misc]
                component = component.contextualize(context_in, context_out)
                if i and initial_hook:
                    component = component.reversed()  # type: ignore[union-attr]
                if forced_context is not None:
                    if isinstance(component, Line):
                        if forced_context != NO_CONTEXT:
                            component = component.clone(angle=forced_context.angle)  # type: ignore[arg-type]
                    else:
                        if forced_context.clockwise is not None and forced_context.clockwise != component.clockwise:
                            component = component.reversed()
                        if forced_context != NO_CONTEXT and forced_context.angle != (component.angle_out if initial_hook else component.angle_in):
                            angle_out = component.angle_out
                            if component.clockwise and angle_out > component.angle_in:
                                angle_out -= 360
                            elif not component.clockwise and angle_out < component.angle_in:
                                angle_out += 360
                            da = angle_out - component.angle_in
                            if initial_hook:
                                component = component.clone(
                                    angle_in=(forced_context.angle - da) % 360,
                                    angle_out=forced_context.angle,
                                )
                            else:
                                component = component.clone(
                                    angle_in=forced_context.angle,
                                    angle_out=(forced_context.angle + da) % 360,
                                )
                instructions.append((scalar, component))
                if initial_hook:
                    context_out = component.context_in()
                else:
                    context_in = component.context_out()
                if forced_context is not None:
                    actual_context = component.context_out() if initial_hook else component.context_in()
                    if forced_context.clockwise is None:
                        actual_context = actual_context.clone(clockwise=None)
                    assert actual_context == forced_context, f'{actual_context} != {forced_context}'
                    forced_context = None
        if initial_hook:
            instructions.reverse()
        return self.clone(instructions=instructions)

    def context_in(self) -> Context:
        return next(op for op in self.instructions if not callable(op))[1].context_in()

    def context_out(self) -> Context:
        return next(op for op in reversed(self.instructions) if not callable(op))[1].context_out()

    def rotate_diacritic(self, context: Context) -> Self:
        angle = context.angle
        assert angle is not None
        return self.clone(_final_rotation=angle)


class InvalidDTLS(Complex):
    """An invalid instance of U+1BC9D DUPLOYAN THICK LETTER SELECTOR.
    """

    def context_in(self) -> Context:
        return NO_CONTEXT

    def context_out(self) -> Context:
        return NO_CONTEXT

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.BLOCKER


class InvalidOverlap(Complex):
    """An invalid instance of U+1BCA0 SHORTHAND FORMAT LETTER OVERLAP or
    U+1BCA1 SHORTHAND FORMAT CONTINUING OVERLAP.

    Attributes:
        continuing: Whether this is an instance of U+1BCA1.
    """

    def __init__(
        self,
        *,
        continuing: bool,
        instructions: _Instructions,
    ) -> None:
        """Initializes this `InvalidOverlap`.

        Args:
            continuing: The ``continuing`` attribute.
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)
        self.continuing = continuing

    def clone(  # type: ignore[override]
        self,
        *,
        continuing: bool | CloneDefault = CLONE_DEFAULT,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            continuing=self.continuing if continuing is CLONE_DEFAULT else continuing,
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    @staticmethod
    def guaranteed_glyph_class() -> Optional[GlyphClass]:
        return GlyphClass.BLOCKER


class InvalidStep(Complex):
    """An invalid instance of U+1BCA2 SHORTHAND FORMAT DOWN STEP or
    U+1BCA3 SHORTHAND FORMAT UP STEP.

    Attributes:
        angle: The ``angle`` of the `Space` the step would be if it were
            valid.
    """

    def __init__(
        self,
        angle: float,
        instructions: _Instructions,
    ) -> None:
        """Initializes this `InvalidStep`.

        Args:
            angle: The ``angle`` attribute.
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)
        self.angle = angle

    def clone(  # type: ignore[override]
        self,
        *,
        angle: float | CloneDefault = CLONE_DEFAULT,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.angle if angle is CLONE_DEFAULT else angle,
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        return Space(self.angle, margins=True)

    def context_in(self) -> Context:
        return NO_CONTEXT

    def context_out(self) -> Context:
        return NO_CONTEXT


class RomanianU(Complex):
    """U+1BC56 DUPLOYAN LETTER ROMANIAN U.
    """

    def draw_to_proxy(
        self,
        pen: fontforge.glyphPen,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[bool, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        (
            first_is_invisible,
            singular_anchor_points,
        ) = super().draw_to_proxy(pen, stroke_width, light_line, stroke_gap, size)
        singular_anchor_points[(anchors.RELATIVE_1, 'base')] = singular_anchor_points[(anchors.CURSIVE, 'exit')]
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if context_in == NO_CONTEXT or context_out == NO_CONTEXT:
            return super().contextualize(context_in, context_out)
        return Circle(0, 0, clockwise=False).contextualize(context_in, context_out)


class Ou(Complex):
    """U+1BC5B DUPLOYAN LETTER OU.

    Attributes:
        role: The role of this shape in its orienting sequence.
    """

    def __init__(
        self,
        instructions: _Instructions,
        role: CircleRole = CircleRole.INDEPENDENT,
        _initial: bool = False,
        _isolated: bool = True,
    ) -> None:
        """Initializes this `Ou`.

        Args:
            instructions: The ``instructions`` attribute.
            role: The ``role`` attribute.
        """
        super().__init__(instructions, hook=True)
        self.role = role
        self._initial = _initial
        self._isolated = _isolated

    def clone(  # type: ignore[override]
        self,
        *,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
        role: CircleRole | CloneDefault = CLONE_DEFAULT,
        _initial: bool | CloneDefault = CLONE_DEFAULT,
        _isolated: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
            self.role if role is CLONE_DEFAULT else role,
            self._initial if _initial is CLONE_DEFAULT else _initial,
            self._isolated if _isolated is CLONE_DEFAULT else _isolated,
        )

    def __str__(self) -> str:
        circle_op = self.instructions[2 if self._initial and self.role == CircleRole.LEADER else 0]
        assert not callable(circle_op)
        rv = str(circle_op[1])
        if self.role == CircleRole.LEADER and not self._isolated:
            rv += '.open'
        return rv

    def group(self) -> Hashable:
        leader = self.role == CircleRole.LEADER and not self._isolated
        return (
            super().group(),
            leader,
            leader and self._initial,
        )

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        if self.role != CircleRole.LEADER or self._isolated:
            drawer = cast(Complex, super())
        else:
            circle_op = self.instructions[2 if self._initial else 0]
            circle_path = circle_op[1]  # type: ignore[index]
            assert isinstance(circle_path, Circle | Curve)
            clockwise = circle_path.clockwise
            curve_op = self.instructions[0 if self._initial else 2]
            curve_path = curve_op[1]  # type: ignore[index]
            assert isinstance(curve_path, Curve)
            curve_da = curve_path.angle_out - curve_path.angle_in
            if self._initial:
                angle_out = circle_path.angle_out
                intermediate_angle = (angle_out + curve_da) % 360
                instructions = [
                    (curve_op[0], curve_path.clone(  # type: ignore[index]
                        angle_in=angle_out,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (circle_op[0], Curve(  # type: ignore[index]
                        angle_in=intermediate_angle,
                        angle_out=angle_out,
                        clockwise=clockwise,
                    )),
                ]
            else:
                angle_in = circle_path.angle_in
                intermediate_angle = (angle_in - curve_da) % 360
                instructions = [
                    (circle_op[0], Curve(  # type: ignore[index]
                        angle_in=angle_in,
                        angle_out=intermediate_angle,
                        clockwise=clockwise,
                    )),
                    (curve_op[0], curve_path.clone(  # type: ignore[index]
                        angle_in=intermediate_angle,
                        angle_out=angle_in,
                        clockwise=clockwise,
                    )),
                ]
            drawer = Complex(instructions=instructions)
        drawer.draw(
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        return False

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        return super().contextualize(context_in, context_out).clone(  # type: ignore[call-arg]
            _initial=self._initial or context_in == NO_CONTEXT,
            _isolated=False,
        )

    def context_in(self) -> Context:
        if self._initial:
            rv = super().context_out()
            assert rv.angle is not None
            return rv.clone(angle=(rv.angle + 180) % 360)
        else:
            return super().context_in()

    def context_out(self) -> Context:
        if self._isolated:
            return super().context_out()
        else:
            rv = self.context_in()
            assert rv.angle is not None
            return rv.clone(angle=(rv.angle + 180) % 360)

    def as_reversed(self) -> Ou:
        """Returns an `Ou` that looks the same but is drawn in the
        opposite direction.
        """
        circle_path = self.instructions[0][1]  # type: ignore[index]
        curve_path = self.instructions[2][1]  # type: ignore[index]
        assert isinstance(circle_path, Circle)
        assert isinstance(curve_path, Curve)
        intermediate_angle = (circle_path.angle_in - circle_path.angle_out) % 360
        return self.clone(instructions=[
            (self.instructions[0][0], circle_path.clone(  # type: ignore[index]
                angle_in=(circle_path.angle_in + 180) % 360,
                angle_out=intermediate_angle,
                clockwise=not circle_path.clockwise,
            )),
            self.instructions[1],
            (self.instructions[2][0], curve_path.clone(  # type: ignore[index]
                angle_in=intermediate_angle,
                clockwise=not curve_path.clockwise,
            )),
        ])


class SeparateAffix(Complex):
    """A separate affix.

    Attributes:
        low: Whether this shape is low as opposed to high.
        tight: Whether this shape is “tight”. It is not quite clear what
            that is supposed to mean; the representative code chart
            glyphs do not match the primary sources. The current
            encoding model may not be appropriate.
    """

    def __init__(
        self,
        instructions: _Instructions,
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
        self.low = low
        self.tight = tight

    def clone(  # type: ignore[override]
        self,
        *,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
        low: bool | CloneDefault = CLONE_DEFAULT,
        tight: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            low=self.low if low is CLONE_DEFAULT else low,
            tight=self.tight if tight is CLONE_DEFAULT else tight,
        )

    def group(self) -> Hashable:
        return (
            super().group(),
            self.low,
            self.tight,
        )

    def hub_priority(self, size: float) -> int:
        return -1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        super().draw(
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        for anchor_class_name, type, x, y in glyph.anchorPoints:
            if anchor_class_name == anchors.CURSIVE:
                if type == 'entry':
                    entry = x, y
                elif type == 'exit':
                    exit = x, y
        glyph.anchorPoints = []
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        cursive_y = (y_max + 200 if self.low else y_min - 200)
        entry_x, exit_x = x_min, x_max
        if self.tight:
            entry_x, exit_x = exit_x, entry_x
        glyph.transform(fontTools.misc.transform.Offset(y=-cursive_y))
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', entry_x, 0)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', exit_x, 0)
        return True

    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    def is_shadable(self) -> bool:
        return False

    def context_in(self) -> Context:
        return NO_CONTEXT

    def context_out(self) -> Context:
        return NO_CONTEXT


class Wa(Complex):
    r"""A circled circle in the style of U+1BC5C DUPLOYAN LETTER WA.

    `instructions` must not contain any callables. The first and last
    components must be `Circle`\ s.
    """

    def __init__(
        self,
        instructions: _Instructions,
    ) -> None:
        """Initializes this `Wa`.

        Args:
            instructions: The ``instructions`` attribute.
        """
        super().__init__(instructions)

    def clone(  # type: ignore[override]
        self,
        *,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            self.instructions if instructions is CLONE_DEFAULT else instructions,
        )

    def draw_to_proxy(
        self,
        pen: fontforge.glyphPen,
        stroke_width: float,
        light_line: float,
        stroke_gap: float,
        size: float,
    ) -> tuple[bool, collections.defaultdict[tuple[str, _AnchorType], list[_Point]]]:
        first_is_invisible = None
        last_crossing_point: Optional[_Point] = None
        singular_anchor_points = collections.defaultdict(list)
        for op in self.instructions:
            assert not callable(op)
            scalar, component, *skip_drawing = op
            proxy = Complex.Proxy()
            component.draw(
                proxy,
                proxy,
                stroke_width,
                light_line,
                stroke_gap,
                scalar * size,
                None,
                Type.JOINING,
                False,
                False,
                False,
                False,
                False,
            )
            if first_is_invisible is None:
                first_is_invisible = component.invisible()
            this_crossing_point = proxy.get_crossing_point(component)  # type: ignore[arg-type]
            if last_crossing_point is not None:
                proxy.transform(fontTools.misc.transform.Offset(
                    last_crossing_point[0] - this_crossing_point[0],
                    last_crossing_point[1] - this_crossing_point[1],
                ))
            last_crossing_point = this_crossing_point
            for anchor_and_type, points in proxy.anchor_points.items():
                if len(points) == 1:
                    singular_anchor_points[anchor_and_type].append(points[0])
            if not (skip_drawing and skip_drawing[0]):
                proxy.draw(pen)
        first_entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][0]
        last_entry = singular_anchor_points[(anchors.CURSIVE, 'entry')][-1]
        if math.hypot(first_entry[0] - last_entry[0], first_entry[1] - last_entry[1]) >= 10:
            proxy = Complex.Proxy()
            # FIXME: Using the anchor points unmodified, FontForge gets stuck in
            # `font.generate`. If some but not all the points are offset by 0.01,
            # the stroking code produces buggy results for some glyphs.
            proxy.moveTo((first_entry[0], first_entry[1] + 0.01))
            proxy.lineTo((last_entry[0], last_entry[1] + 0.01))
            proxy.stroke('circular', stroke_width, 'round')
            proxy.draw(pen)
        first_exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][0]
        last_exit = singular_anchor_points[(anchors.CURSIVE, 'exit')][-1]
        if math.hypot(first_exit[0] - last_exit[0], first_exit[1] - last_exit[1]) >= 10:
            proxy = Complex.Proxy()
            proxy.moveTo((first_exit[0], first_exit[1] + 0.01))
            proxy.lineTo((last_exit[0], last_exit[1] + 0.01))
            proxy.stroke('circular', stroke_width, 'round')
            proxy.draw(pen)
        assert first_is_invisible is not None
        return (
            first_is_invisible,
            singular_anchor_points,
        )

    def enter_on_first_path(self) -> bool:
        return False

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        instructions = []
        for scalar, component in self.instructions:  # type: ignore[misc]
            component = component.contextualize(context_in, context_out)
            instructions.append((scalar, component))
        outer_circle_path = instructions[0][1]
        if isinstance(outer_circle_path, Curve):
            assert context_in != NO_CONTEXT and context_out != NO_CONTEXT
            a1, a2 = outer_circle_path._get_normalized_angles()
            if abs(a2 - a1) < 180:
                assert not callable(self.instructions[0])
                assert not callable(self.instructions[-1])
                assert isinstance(self.instructions[0][1], Circle)
                assert isinstance(instructions[-1][1], Curve)
                return Complex(instructions=[
                    (
                        instructions[0][0],
                        self.instructions[0][1].clone(
                            angle_in=instructions[-1][1].angle_in,
                            angle_out=instructions[-1][1].angle_in,
                            clockwise=instructions[-1][1].clockwise,
                        ),
                        *instructions[0][2:]
                    ),
                    *instructions[1:],
                ])
        return self.clone(instructions=instructions)

    def as_reversed(self) -> Wa:
        """Returns a `Wa` that looks the same but is drawn in the
        opposite direction.
        """
        return self.clone(
            instructions=[op if callable(op) else (op[0], op[1].as_reversed(), *op[2:]) for op in self.instructions],  # type: ignore[attr-defined, misc]
        )


class Wi(Complex):
    """A circled sequence of curves in the style of U+1BC5E DUPLOYAN
    LETTER WI.

    `instructions` must begin or end with a `Circle` component and must
    contain at least one `Curve` component.
    """

    def contextualize(self, context_in: Context, context_out: Context) -> Shape:
        if context_in != NO_CONTEXT or context_out == NO_CONTEXT:
            curve_index = next(i for i, op in enumerate(self.instructions) if not callable(op) and not isinstance(op[1], Circle))
            if curve_index == 1:
                return super().contextualize(context_in, context_out)
            curve_path = self.clone(instructions=self.instructions[curve_index - 1:]).contextualize(context_in, context_out)
            assert isinstance(curve_path, Wi)
            assert not callable(self.instructions[0])
            circle = self.instructions[0][1]
            assert isinstance(circle, Circle)
            curve_op = curve_path.instructions[1]
            assert isinstance(curve_op, tuple)
            curve = curve_op[1]
            assert isinstance(curve, Curve)
            circle_path = circle.clone(
                angle_in=curve.angle_in,
                angle_out=curve.angle_in,
                clockwise=curve.clockwise,
            )
            return self.clone(instructions=[(self.instructions[0][0], circle_path), *curve_path.instructions])
        assert context_out.angle is not None
        assert not callable(self.instructions[-1])
        assert isinstance(self.instructions[-1][1], Curve)
        if Curve.in_degree_range(
            context_out.angle,
            self.instructions[-1][1].angle_out,
            (self.instructions[-1][1].angle_out + 180 - EPSILON * (-1 if self.instructions[-1][1].clockwise else 1)) % 360,
            self.instructions[-1][1].clockwise,
        ):
            return self.as_reversed()
        return self

    def as_reversed(self) -> Wi:
        """Returns a `Wi` that looks the same but is drawn in the
        opposite direction.
        """
        first_callable = True
        return self.clone(
            instructions=[
                ((lambda op: (lambda c: (lambda c0: c0.clone(clockwise=not c0.clockwise))(op(c))))(op)  # type: ignore[misc]
                        if (first_callable | (first_callable := False))
                        else op
                    )
                    if callable(op)
                    else (
                        op[0],
                        op[1].clone(
                                angle_in=(op[1].angle_in + 180) % 360,
                                angle_out=(op[1].angle_out + 180) % 360,
                                clockwise=not op[1].clockwise,
                            ) if isinstance(op[1], Circle | Curve)
                            else op[1],
                        *op[2:],
                    ) for op in self.instructions
            ],
        )


class TangentHook(Complex):
    """U+1BC7C DUPLOYAN AFFIX ATTACHED TANGENT HOOK.
    """

    def __init__(
        self,
        instructions: _Instructions,
        *,
        _initial: bool = False,
    ) -> None:
        """Initializes this `TangentHook`.

        Args:
            instructions: The ``instructions`` attribute.
        """
        while callable(instructions[0]):
            instructions = instructions[1:]
        super().__init__([self._override_initial_context if _initial else self._override_noninitial_context, *instructions], hook=True)
        self._initial = _initial

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

    def clone(  # type: ignore[override]
        self,
        *,
        instructions: _Instructions | CloneDefault = CLONE_DEFAULT,
        _initial: bool | CloneDefault = CLONE_DEFAULT,
    ) -> Self:
        return type(self)(
            instructions=self.instructions if instructions is CLONE_DEFAULT else instructions,
            _initial=self._initial if _initial is CLONE_DEFAULT else _initial,
        )

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
                )),
                self.instructions[2],
                (self.instructions[3][0], self.instructions[3][1].clone(
                    angle_in=self.instructions[3][1].angle_out,
                    angle_out=(self.instructions[3][1].angle_out + 180) % 360,
                    clockwise=not self.instructions[3][1].clockwise,
                )),
            ], _initial=True)
        else:
            shape = cast(Self, super())
        return shape.contextualize(context_in, context_out)


class XShape(Complex):
    """U+1BC01 DUPLOYAN LETTER X.
    """

    def hub_priority(self, size: float) -> int:
        return 1

    def draw(
            self,
            glyph: fontforge.glyph,
            pen: fontforge.glyphPen | Literal[False],
            stroke_width: float,
            light_line: float,
            stroke_gap: float,
            size: float,
            anchor: Optional[str],
            joining_type: Type,
            child: bool,
            initial_circle_diphthong: bool,
            final_circle_diphthong: bool,
            diphthong_1: bool,
            diphthong_2: bool,
    ) -> bool:
        super().draw(
            glyph,
            pen,
            stroke_width,
            light_line,
            stroke_gap,
            size,
            anchor,
            joining_type,
            child,
            initial_circle_diphthong,
            final_circle_diphthong,
            diphthong_1,
            diphthong_2,
        )
        for anchor_class_name, type, x, y in glyph.anchorPoints:
            if anchor_class_name == anchors.CURSIVE:
                if type == 'entry':
                    entry = x, y
                elif type == 'exit':
                    exit = x, y
        glyph.anchorPoints = [a for a in glyph.anchorPoints if a[0] != anchors.CURSIVE]
        x_min, y_min, x_max, y_max = glyph.boundingBox()
        x_avg = (x_min + x_max) / 2
        y_avg = (y_min + y_max) / 2
        glyph.addAnchorPoint(anchors.CURSIVE, 'entry', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.CURSIVE, 'exit', x_avg, y_avg)
        glyph.addAnchorPoint(anchors.POST_HUB_CURSIVE, 'entry', x_avg, y_avg)
        return False

    def is_pseudo_cursive(self, size: float) -> bool:
        return True

    def context_in(self) -> Context:
        return NO_CONTEXT

    def context_out(self) -> Context:
        return NO_CONTEXT
