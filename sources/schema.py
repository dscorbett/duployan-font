# Copyright 2018-2019, 2022 David Corbett
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

"""Schemas and related things.
"""


from __future__ import annotations


__all__ = [
    'Ignorability',
    'MAX_DOUBLE_MARKS',
    'MAX_HUB_PRIORITY',
    'NO_PHASE_INDEX',
    'Schema',
]


from collections.abc import Collection
from collections.abc import Hashable
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from collections.abc import Sequence
import enum
import functools
import math
import re
import typing
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import Final
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import Union
import unicodedata


import fontTools.agl
import fontforge


from shapes import ChildEdge
from shapes import Circle
from shapes import CircleRole
from shapes import Curve
from shapes import InvalidStep
from shapes import Line
from shapes import Notdef
from shapes import Ou
from shapes import Shape
from shapes import Space
from utils import CAP_HEIGHT
from utils import CLONE_DEFAULT
from utils import Context
from utils import DEFAULT_SIDE_BEARING
from utils import GlyphClass
from utils import MAX_TREE_WIDTH
from utils import NO_CONTEXT
from utils import Type


#: An integer representing the lack of a phase index. It is less than
#: any phase’s index.
NO_PHASE_INDEX: Final[int] = -1


# TODO: Don’t use a mutable global variable.
#: An integer representing the current phase’s index. It starts at
#: `NO_PHASE_INDEX` and increases with each new phase as the builder
#: iterates through all the phases.
CURRENT_PHASE_INDEX: int = NO_PHASE_INDEX


#: The maximum number of consecutive instances of U+1BC9E DUPLOYAN
#: DOUBLE MARK supported after any base.
MAX_DOUBLE_MARKS: Final[int] = 3


#: The maximum hub priority.
MAX_HUB_PRIORITY: Final[int] = 2


class Ignorability(enum.Enum):
    """How ignorable a character is.
    """

    #: The character is not a default ignorable code point.
    DEFAULT_NO = enum.auto()

    #: The character is a default ignorable code point.
    DEFAULT_YES = enum.auto()

    #: The character is a default ignorable code point, but should be
    #: treated as if it weren’t, for the purpose of Duployan.
    OVERRIDDEN_NO = enum.auto()


class Schema:
    """Everything needed to add a glyph to a font.

    A schema represents a glyph, broadly speaking. It covers the glyph’s
    contours, Unicode code point, advance, bearings, anchor points, and
    name. It also covers some information about how this glyph behaves
    in OpenType Layout, though the specifics are determined by the
    phases that the schema goes through.

    Every schema corresponds to a glyph in the final font. Many schemas
    can correspond to the same glyph. Such schemas are called mergeable.
    One schema in a group of mergeable schemas is considered the
    canonical one for that group.

    A schema is mostly immutable. It ultimately represents certain
    unchangeable bytes in the generated font and so it would not make
    sense to mutate it. Two exceptions are `canonical_schema` and
    `lookalike_group`. These are used for build-time optimizations
    related to the schema itself, as a Python object, rather than as the
    font data it represents.

    The third exception to immutability is `glyph`, the FontForge object
    corresponding to this schema. `glyph` is set once the glyph has been
    drawn, which, as an optimization, is not done till schemas have been
    merged. This is rather a case of caching and lazy initialization
    than full immutability.

    Attributes:
        cmap: The code point the 'cmap' table should map to this
            schema’s glyph, if any.
        path: The shape to use to contextualize and draw this schema’s
            glyph.
        size: The size of the shape. The exact meaning depends on
            `path`.
        joining_type: The joining type of this schema, relevant in GSUB
            for contextualization and GPOS for cursive attachment.
        side_bearing: The side bearing, in units of em, of this schema’s
            glyph. The left and right side bearings are identical.
        y_min: The minimum y coordinate of this schema’s glyph’s
            bounding box, or ``None`` if the minimum y coordinate is
            unconstrained.
        y_max: The maximum y coordinate of this schema’s glyph’s
            bounding box, or ``None`` if the maximum y coordinate is
            unconstrained.
        child: Whether this schema is a child in an overlap sequence.
        can_lead_orienting_sequence: Whether this schema can lead an
            orienting sequence.
        ignored_for_topography: Whether this schema is in an orienting
            sequence but not its head, and is thus ignored for the main
            topographical phases.
        anchor: The anchor this schema attaches to, if this schema
            represents a mark.
        widthless: Whether width calculations should be suppressed for
            this schema. This is an optimization for schemas for mark
            glyphs applied to non-joining bases; otherwise, there would
            be a large space to the right of the base. Technically, a
            wide diacritic on a narrow non-joining base could overlap
            adjacent glyphs, but it is unlikely to be a problem in
            practice.
        marks: The sequence of marks of this schema, if this schema
            represents a glyph that can be decomposed into a base and
            some marks. For most schemas, this is empty.
        ignorability: The ignorability of this schema’s character.
        encirclable: Whether this schema’s character is attested with a
            following U+20DD COMBINING ENCLOSING CIRCLE.
        maximum_tree_width: The maximum width of a shorthand overlap
            sequence following this schema. The true maximum width may
            be lower, depending on this schema’s shape and size.
        shading_allowed: Whether this schema may be followed by U+1BC9D
            DUPLOYAN THICK LETTER SELECTOR. Some characters for which
            shading is attested nevertheless have this attribute set to
            ``False`` as an optimization.
        context_in: The end context of the schema known to cursively
            join to this one’s start. If none is known, the value is
            `NO_CONTEXT`.
        context_out: The start context of the schema known to cursively
            join to this one’s end. If none is known, the value is
            `NO_CONTEXT`.
        diphthong_1: Whether this schema is a non-final element of a
            diphthong ligature.
        diphthong_2: Whether this schema is a non-initial element of a
            diphthong ligature.
        base_angle: The angle of the shape of the original schema from
            which this schema is derived by `rotate_diacritic`. If this
            schema has not been so derived, the value is ``None``.
        cps: The code point sequence corresponding to this schema. This
            doesn’t affect anything critical in the final font (just
            glyph names), unlike the `cmap` attribute.
        original_shape: The type of the `path` attribute of the original
            schema from which this schema is derived through some number
            of phases.
        phase_index: The phase index for the phase in which this schema
            was generated. See `CURRENT_PHASE_INDEX`.
        glyph: The cached FontForge glyph generated for this schema, or
            ``None`` if one has not been generated.
    """

    #: The maximum length of a glyph name without a disambiguatory
    #: suffix. The Adobe Glyph List Specification sets a maximum of 63.
    #: A disambiguatory suffix consists of the two characters ``"._"``
    #: followed by a hexadecimal number. There are at most ``0xFFFF``
    #: glyphs in a font, so the longest possible disambiguatory number
    #: is 4 characters long. Thus, the suffix can be up to 6 characters
    #: long, and the effective maximum glyph name length is 57
    #: characters.
    _MAX_GLYPH_NAME_LENGTH: ClassVar[int] = 63 - 2 - 4

    #: A pattern that must not appear in an undisambiguated glyph name.
    #: This ensures that a glyph name can never end with what appears to
    #: be a disambiguatory suffix but isn’t.
    _RESERVED_GLYPH_NAME_PATTERN: re.Pattern[str] = re.compile(r'\._[1-9A-F][0-9A-F]*$')

    #: A pattern matching a ``uni`` glyph name component that follows
    #: and can be collapsed into a preceding ``uni`` glyph name
    #: component. For example, ``uni1234_uniABCD`` can be collapsed into
    #: ``uni1234ABCD``.
    _COLLAPSIBLE_UNI_NAME: ClassVar[re.Pattern[str]] = re.compile(r'(?<=uni[0-9A-F]{4})_uni(?=[0-9A-F]{4})')

    #: An iterable of substitutions to apply to a character name to get
    #: its glyph name. A substitution is a tuple of a search string and
    #: a replacement. A search string is a regular expression to search
    #: for in a character name. A replacement is either a string or a
    #: callable to call on each match to get its replacement string;
    #: either way, all matches of the search string are replaced. A
    #: character name is a Unicode character name or, for nameless code
    #: points, the glyph name recommended by the Adobe Glyph List
    #: Specification.
    _CHARACTER_NAME_RAW_SUBSTITUTIONS: ClassVar[Iterable[Tuple[str, Union[str, Callable[[re.Match[str]], str]]]]] = [
        # Custom PUA names
        (r'^uniE000$', 'BOUND'),
        (r'^uniE001$', 'LATIN CROSS POMMEE'),
        (r'^uniE003$', 'HEART WITH CROSS'),
        (r'^uniEC02$', 'DUPLOYAN LETTER REVERSED P'),
        (r'^uniEC03$', 'DUPLOYAN LETTER REVERSED T'),
        (r'^uniEC04$', 'DUPLOYAN LETTER REVERSED F'),
        (r'^uniEC05$', 'DUPLOYAN LETTER REVERSED K'),
        (r'^uniEC06$', 'DUPLOYAN LETTER REVERSED L'),
        (r'^uniEC19$', 'DUPLOYAN LETTER REVERSED M'),
        (r'^uniEC1A$', 'DUPLOYAN LETTER REVERSED N'),
        (r'^uniEC1B$', 'DUPLOYAN LETTER REVERSED J'),
        (r'^uniEC1C$', 'DUPLOYAN LETTER REVERSED S'),
        # Unicode name aliases
        (r'^COMBINING GRAPHEME JOINER$', 'CGJ'),
        (r'^ZERO WIDTH SPACE$', 'ZWSP'),
        (r'^ZERO WIDTH NON-JOINER$', 'ZWNJ'),
        (r'^ZERO WIDTH JOINER$', 'ZWJ'),
        (r'^NARROW NO-BREAK SPACE$', 'NNBSP'),
        (r'^MEDIUM MATHEMATICAL SPACE$', 'MMSP'),
        (r'^WORD JOINER$', 'WJ'),
        (r'^ZERO WIDTH NO-BREAK SPACE$', 'ZWNBSP'),
        # Custom name aliases
        (r'^DUPLOYAN THICK LETTER SELECTOR$', 'DTLS'),
        # Familiar vocabulary choices from AGLFN
        (r'\bFULL STOP\b', 'PERIOD'),
        (r'\bQUOTATION MARK\b', 'QUOTE'),
        (r'\bSOLIDUS\b', 'SLASH'),
        (r'(?<=ER|SS)[- ]THAN\b', ''),
        # Unnecessary words
        (r'\bDOTS INSIDE AND ABOVE\b', 'DOTS'),
        (r' ACCENT\b', ''),
        (r' (AND|WITH) ', ' '),
        (r'\bCOMBINING ', ''),
        (r'\bDIGIT ', ''),
        (r'^DUPLOYAN ((AFFIX( ATTACHED)?|LETTER|PUNCTUATION|SIGN) )?', ''),
        (r' (MARK|SIGN)$', ''),
        (r'[- ]POINTING\b', ''),
        (r'^SHORTHAND FORMAT ', ''),
        # Final munging
        (r'.+', lambda m: m.group(0).lower()),
        (r'[ -]+', '_'),
    ]

    #: `_CHARACTER_NAME_RAW_SUBSTITUTIONS` with all the search strings
    #: compiled into pattern objects.
    _CHARACTER_NAME_SUBSTITUTIONS: ClassVar[Iterable[Tuple[re.Pattern[str], Union[str, Callable[[re.Match[str]], str]]]]] = [
        (re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in _CHARACTER_NAME_RAW_SUBSTITUTIONS
    ]

    #: An iterable of substitutions to apply to a glyph name to get a
    #: better glyph name. The details are the same as in
    #: `_CHARACTER_NAME_RAW_SUBSTITUTIONS` except that this is applied
    #: to a sequence of the outputs of `_CHARACTER_NAME_SUBSTITUTIONS`
    #: joined by ``"__"``.
    _SEQUENCE_NAME_RAW_SUBSTITUTIONS: ClassVar[Sequence[Tuple[str, Union[str, Callable[[re.Match[str]], str]]]]] = [
        (r'__zwj__', '___'),
        (r'((?:[a-z]+_)+)_dtls(?=__|$)', lambda m: m.group(1)[:-1].upper()),
    ]

    #: `_SEQUENCE_NAME_RAW_SUBSTITUTIONS` with all the search strings
    #: compiled into pattern objects.
    _SEQUENCE_NAME_SUBSTITUTIONS: ClassVar[Sequence[Tuple[re.Pattern[str], Union[str, Callable[[re.Match[str]], str]]]]] = [
        (re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in _SEQUENCE_NAME_RAW_SUBSTITUTIONS
    ]

    # TODO: This seems like a bad design.
    #: A mutable mapping of undisambiguated schema names to mutable
    #: sequences of all the schemas that share that name.
    _canonical_names: MutableMapping[str, MutableSequence[Schema]] = {}

    def __init__(
            self,
            cmap: Optional[int],
            path: Shape,
            size: float,
            joining_type: Type = Type.JOINING,
            *,
            side_bearing: float = DEFAULT_SIDE_BEARING,
            y_min: Optional[float] = 0,
            y_max: Optional[float] = None,
            child: bool = False,
            can_lead_orienting_sequence: Optional[bool] = None,
            ignored_for_topography: bool = False,
            anchor: Optional[str] = None,
            widthless: Optional[bool] = None,
            marks: Optional[Sequence[Schema]] = None,
            ignorability: Ignorability = Ignorability.DEFAULT_NO,
            encirclable: bool = False,
            maximum_tree_width: int = MAX_TREE_WIDTH,
            shading_allowed: bool = True,
            context_in: Optional[Context] = None,
            context_out: Optional[Context] = None,
            diphthong_1: bool = False,
            diphthong_2: bool = False,
            base_angle: Optional[float] = None,
            cps: Optional[Sequence[int]] = None,
            original_shape: Optional[type[Shape]] = None,
    ) -> None:
        """Initializes this `Schema`.

        Args:
            cmap: The ``cmap`` attribute.
            path: The ``path`` attribute.
            size: The ``size`` attribute.
            joining_type: The ``joining_type`` attribute.
            side_bearing: The ``side_bearing`` attribute.
            y_min: The ``y_min`` attribute.
            y_max: The ``y_max`` attribute.
            child: The ``child`` attribute.
            can_lead_orienting_sequence: The
                ``can_lead_orienting_sequence`` attribute, or ``None``
                to set the attribute to ``joining_type ==
                Type.ORIENTING``.
            ignored_for_topography: The ``ignored_for_topography`` attribute.
            anchor: The ``anchor`` attribute.
            widthless: The ``widthless`` attribute.
            marks: The ``marks`` attribute, or ``None`` to set the
                attribute to an empty sequence.
            ignorability: The ``ignorability`` attribute.
            encirclable: The ``encirclable`` attribute.
            maximum_tree_width: The ``maximum_tree_width`` attribute.
            shading_allowed: The ``shading_allowed`` attribute.
            context_in: The ``context_in`` attribute, or ``None`` to set
                the attribute to `NO_CONTEXT`.
            context_out: The ``context_out`` attribute, or ``None`` to
                set the attribute to `NO_CONTEXT`.
            diphthong_1: The ``diphthong_1`` attribute.
            diphthong_2: The ``diphthong_2`` attribute.
            base_angle: The ``base_angle`` attribute.
            cps: The ``cps`` attribute,  or ``None`` to set the
                attribute to the sequence containing `cmap` (if it is
                not ``None``) or else an empty sequence.
            original_shape: The ``original_shape`` attribute, or
                ``None`` to set the attribute to ``type(path)``.
        """
        assert not (marks and anchor), 'A schema has both marks {} and anchor {}'.format(marks, anchor)
        assert not widthless or anchor, f'A widthless schema has anchor {anchor}'
        self.cmap = cmap
        self.path = path
        self.size = size
        self.joining_type = joining_type
        self.side_bearing = side_bearing
        self.y_min = y_min
        self.y_max = y_max
        self.child = child
        self.can_lead_orienting_sequence = can_lead_orienting_sequence if can_lead_orienting_sequence is not None else joining_type == Type.ORIENTING
        self.ignored_for_topography = ignored_for_topography
        self.anchor = anchor
        self.widthless = widthless
        self.marks = marks or []
        self.ignorability = ignorability
        self.encirclable = encirclable
        self.maximum_tree_width = maximum_tree_width
        self.shading_allowed = shading_allowed
        self.context_in = context_in or NO_CONTEXT
        self.context_out = context_out or NO_CONTEXT
        self.diphthong_1 = diphthong_1
        self.diphthong_2 = diphthong_2
        self.base_angle = base_angle
        self.cps = cps or ([] if cmap is None else [cmap])
        self.original_shape = original_shape or type(path)
        self.phase_index = CURRENT_PHASE_INDEX
        self._glyph_name: Optional[str] = None
        self._canonical_schema: Schema = self
        self._lookalike_group: Collection[Schema] = [self]
        self.glyph: Optional[fontforge.glyph] = None

    def sort_key(self):
        """Returns a sortable key representing this schema.

        This is used to decide which schema among many mergeable schemas
        should be the canonical one. The sort key is therefore generally
        the one that produces the glyph name that is the shortest, the
        most informative, and the most likely match for the original
        code point sequence.
        """
        cmap_string = '' if self.cmap is None else chr(self.cmap)
        return (
            bool(self.cps) and any(unicodedata.category(chr(cp)) == 'Co' for cp in self.cps),
            self.phase_index,
            self.cmap is None,
            not unicodedata.is_normalized('NFD', cmap_string),
            not self.cps,
            len(self.cps),
            self.original_shape != type(self.path),
            self.cps,
            len(self._calculate_name()),
        )

    def clone(
        self,
        *,
        cmap=CLONE_DEFAULT,
        path=CLONE_DEFAULT,
        size=CLONE_DEFAULT,
        joining_type=CLONE_DEFAULT,
        side_bearing=CLONE_DEFAULT,
        y_min=CLONE_DEFAULT,
        y_max=CLONE_DEFAULT,
        child=CLONE_DEFAULT,
        can_lead_orienting_sequence=CLONE_DEFAULT,
        ignored_for_topography=CLONE_DEFAULT,
        anchor=CLONE_DEFAULT,
        widthless=CLONE_DEFAULT,
        marks=CLONE_DEFAULT,
        ignorability=CLONE_DEFAULT,
        encirclable=CLONE_DEFAULT,
        maximum_tree_width=CLONE_DEFAULT,
        shading_allowed=CLONE_DEFAULT,
        context_in=CLONE_DEFAULT,
        context_out=CLONE_DEFAULT,
        diphthong_1=CLONE_DEFAULT,
        diphthong_2=CLONE_DEFAULT,
        base_angle=CLONE_DEFAULT,
        cps=CLONE_DEFAULT,
        original_shape=CLONE_DEFAULT,
    ):
        return type(self)(
            self.cmap if cmap is CLONE_DEFAULT else cmap,
            self.path if path is CLONE_DEFAULT else path,
            self.size if size is CLONE_DEFAULT else size,
            self.joining_type if joining_type is CLONE_DEFAULT else joining_type,
            side_bearing=self.side_bearing if side_bearing is CLONE_DEFAULT else side_bearing,
            y_min=self.y_min if y_min is CLONE_DEFAULT else y_min,
            y_max=self.y_max if y_max is CLONE_DEFAULT else y_max,
            child=self.child if child is CLONE_DEFAULT else child,
            can_lead_orienting_sequence=self.can_lead_orienting_sequence if can_lead_orienting_sequence is CLONE_DEFAULT else can_lead_orienting_sequence,
            ignored_for_topography=self.ignored_for_topography if ignored_for_topography is CLONE_DEFAULT else ignored_for_topography,
            anchor=self.anchor if anchor is CLONE_DEFAULT else anchor,
            widthless=self.widthless if widthless is CLONE_DEFAULT else widthless,
            marks=self.marks if marks is CLONE_DEFAULT else marks,
            ignorability=self.ignorability if ignorability is CLONE_DEFAULT else ignorability,
            encirclable=self.encirclable if encirclable is CLONE_DEFAULT else encirclable,
            maximum_tree_width=self.maximum_tree_width if maximum_tree_width is CLONE_DEFAULT else maximum_tree_width,
            shading_allowed=self.shading_allowed if shading_allowed is CLONE_DEFAULT else shading_allowed,
            context_in=self.context_in if context_in is CLONE_DEFAULT else context_in,
            context_out=self.context_out if context_out is CLONE_DEFAULT else context_out,
            diphthong_1=self.diphthong_1 if diphthong_1 is CLONE_DEFAULT else diphthong_1,
            diphthong_2=self.diphthong_2 if diphthong_2 is CLONE_DEFAULT else diphthong_2,
            base_angle=self.base_angle if base_angle is CLONE_DEFAULT else base_angle,
            cps=self.cps if cps is CLONE_DEFAULT else cps,
            original_shape=self.original_shape if original_shape is CLONE_DEFAULT else original_shape,
        )

    def __repr__(self) -> str:
        return '<Schema {}>'.format(', '.join(map(str, [
            self._calculate_name(),
            self.cmap and f'{self.cmap:04X}',
            self.path,
            self.size,
            self.side_bearing,
            self.context_in,
            'NJ' if self.joining_type == Type.NON_JOINING else '',
            'mark' if self.anchor else 'base',
            [repr(m) for m in self.marks],
        ])))

    @functools.cached_property
    def diacritic_angles(self) -> Mapping[str, float]:
        """Returns the path’s diacritic angles.
        """
        return self.path.calculate_diacritic_angles()

    @functools.cached_property
    def without_marks(self) -> Schema:
        """Returns this schema without its marks.

        If this schema has no marks, the return value is ``self``.

        Otherwise, the return value is the same as this schema but with
        the ``cmap`` and ``marks`` attributes reset.
        """
        return self.clone(cmap=None, marks=None) if self.marks else self

    @functools.cached_property
    def glyph_class(self) -> str:
        """Returns the glyph class of the glyph this schema represents.
        """
        return self.path.guaranteed_glyph_class() or (
            GlyphClass.MARK
                if self.anchor or self.child or self.ignored_for_topography
                else GlyphClass.BLOCKER
                if self.joining_type == Type.NON_JOINING
                else GlyphClass.JOINER
        )

    @functools.cached_property
    def might_need_width_markers(self) -> bool:
        """Returns whether this schema might need width markers.

        Whether a schema really needs width markers also depends on
        details of the glyph which are not known till the glyph has
        been drawn.
        """
        return not (
                self.ignored_for_topography or self.widthless
            ) and (
                self.glyph_class == GlyphClass.JOINER
                or self.glyph_class == GlyphClass.MARK
            )

    @functools.cached_property
    def group(self) -> Hashable:
        """Returns the schema’s group.

        A group is like a hash, but instead of being an uninterpretable
        number, it may be any hashable value. Two schemas with equal
        groups represent glyphs that are interchangeable for all
        purposes except perhaps for GSUB.
        """
        if self.ignored_for_topography:
            return (
                self.ignorability == Ignorability.DEFAULT_YES,
                self.side_bearing,
                self.y_min,
                self.y_max,
            )
        if isinstance(self.path, Circle) and (self.diphthong_1 or self.diphthong_2):
            path_group: Hashable = (
                self.path.angle_in,
                self.path.angle_out,
                self.path.clockwise,
                self.path.stretch,
                self.path.long,
            )
        else:
            path_group = self.path.group()
        return (
            self.ignorability == Ignorability.DEFAULT_YES,
            type(self.path),
            path_group,
            self.path.invisible() or self.cmap is not None or self.cps[-1:] != [0x1BC9D],
            self.size,
            self.joining_type,
            self.side_bearing,
            self.y_min,
            self.y_max,
            self.child,
            self.anchor,
            self.widthless,
            tuple(m.group for m in self.marks),
            self.glyph_class,
            self.context_in == NO_CONTEXT and not self.diphthong_1,
            self.context_out == NO_CONTEXT and not self.diphthong_2,
            self.context_in == NO_CONTEXT and self.diphthong_1,
            self.context_out == NO_CONTEXT and self.diphthong_2,
            self.diphthong_1,
            self.diphthong_2,
        )

    @property
    def canonical_schema(self) -> Schema:
        """This schema’s canonical schema.

        Two schemas with the same canonical schema represent the same
        glyph.

        A canonical schema is its own canonical schema.

        A schema’s canonical schema starts as itself but may be reset a
        single time.
        """
        return self._canonical_schema

    @canonical_schema.setter
    def canonical_schema(self, canonical_schema: Schema) -> None:
        assert self._canonical_schema is self
        self._canonical_schema = canonical_schema
        self._glyph_name = None

    @canonical_schema.deleter
    def canonical_schema(self) -> None:
        del self._canonical_schema

    @property
    def lookalike_group(self) -> Collection[Schema]:
        r"""The group of schemas that all have equal `group`\ s.

        A schema’s lookalike group starts as a collection containing
        only itself but may be reset a single time.
        """
        return self._lookalike_group

    @lookalike_group.setter
    def lookalike_group(self, lookalike_group: Collection[Schema]) -> None:
        assert len(self._lookalike_group) == 1 and next(iter(self._lookalike_group)) is self
        self._lookalike_group = lookalike_group

    @lookalike_group.deleter
    def lookalike_group(self) -> None:
        del self._lookalike_group

    @staticmethod
    def _agl_name(cp: int) -> Optional[str]:
        """Returns the Adobe Glyph List name of an ASCII code point.

        Args:
            cp: A code point.

        Returns:
            The Adobe Glyph List name of an ASCII code point, or
            ``None`` if `cp` is not ASCII.

        Raises:
            KeyError: If `cp` is ASCII but has no AGL name.
        """
        return fontTools.agl.UV2AGL[cp] if cp <= 0x7F else None

    @staticmethod
    def _u_name(cp: int) -> str:
        """Returns the Adobe Glyph List name of a code point with the
        ``uni`` or ``u`` prefix.

        Args:
            cp: A code point.
        """
        return '{}{:04X}'.format('uni' if cp <= 0xFFFF else 'u', cp)

    @classmethod
    def _readable_name(cls, cp: int) -> str:
        """Returns a human-readable glyph name for a code point.

        The naming system is specific to this project. It follows no
        standard.

        Args:
            cp: A code point.
        """
        try:
            name = unicodedata.name(chr(cp))
        except ValueError:
            name = cls._u_name(cp)
        for regex, repl in cls._CHARACTER_NAME_SUBSTITUTIONS:
            name = regex.sub(repl, name)
        return name

    def _calculate_name(self) -> str:
        """Returns this schema’s undisambiguated glyph name.

        The naming system is compatible with the Adobe Glyph List
        Specification but is otherwise specific to this project. In
        general, it prioritizes making the ``hb-shape`` debugging
        experience smoother. The one guarantee (besides AGL) is that
        `_RESERVED_GLYPH_NAME_PATTERN` does not match anywhere in it.
        """
        cps = self.cps
        if cps:
            first_component_implies_type = False
            try:
                name = '_'.join(map(self._agl_name, cps))  # type: ignore[arg-type]
            except (KeyError, TypeError):
                name = '_'.join(map(self._u_name, cps))
                name = self._COLLAPSIBLE_UNI_NAME.sub('', name)
                readable_name = '__'.join(map(self._readable_name, cps))
                for regex, repl in self._SEQUENCE_NAME_SUBSTITUTIONS:
                    readable_name = regex.sub(repl, readable_name)
                if name != readable_name.replace('__', '_'):
                    name = f'{name}.{readable_name}'
        else:
            first_component_implies_type = self.path.name_implies_type()
            if first_component_implies_type:
                name = ''
            else:
                name = f'dupl.{type(self.path).__name__}'
        if first_component_implies_type or (
            self.cmap is None
            and (
                self.joining_type == Type.ORIENTING
                or isinstance(self.path, ChildEdge)
                or isinstance(self.path, Line) and self.path.dots
            )
        ):
            if name_from_path := str(self.path):
                if name:
                    name += '.'
                name += name_from_path
        if self.cmap is None and cps == [0x2044]:
            name += '.frac'
        if cps and self.cmap is None and cps[0] in range(0x0030, 0x0039 + 1):
            if self.y_min is None:
                assert self.y_max is not None
                if self.y_max > CAP_HEIGHT:
                    name += '.sups'
                else:
                    name += '.numr'
            else:
                if self.y_min < 0:
                    name += '.subs'
                else:
                    name += '.dnom'
        if not cps and isinstance(self.path, Space):
            name += f'''.{
                    int(self.size * math.cos(math.radians(self.path.angle)))
                }.{
                    int(self.size * math.sin(math.radians(self.path.angle)))
                }'''.replace('-', 'n')
        if not cps and self.anchor:
            name += f'.{self.anchor}'
        if self.diphthong_1 or self.diphthong_2:
            name += '.diph'
            if self.diphthong_1:
                name += '1'
            if self.diphthong_2:
                name += '2'
        if self.child:
            name += '.sub'
        if isinstance(self.path, Curve) and self.path.overlap_angle is not None:
            name += f'.{int(self.path.overlap_angle)}'
        if self.widthless:
            name += '.wl'
        if self.ignored_for_topography:
            name += '.skip'
        if first_component_implies_type or self.cmap is None and self.path.invisible():
            if name and first_component_implies_type:
                name = f'.{name}'
            if not isinstance(self.path, Notdef):
                if name.startswith('dupl.'):
                    name = name.removeprefix('dupl')
                name = f'_{name}'
        agl_string = fontTools.agl.toUnicode(name)
        agl_cps = [*map(ord, agl_string)]
        assert cps == agl_cps, f'''The glyph name "{
                name
            }" corresponds to <{
                ', '.join(f'U+{cp:04X}' for cp in agl_cps)
            }> but its glyph corresponds to <{
                ', '.join(f'U+{cp:04X}' for cp in cps)
            }>'''
        assert not self._RESERVED_GLYPH_NAME_PATTERN.search(name), f'The glyph name "{name}" misleadingly appears to have a disambiguatory suffix'
        return name

    def __str__(self) -> str:
        """Returns this schema’s disambiguated glyph name.

        Every non-canonical schema has same glyph name as its canonical
        schema (since they represent the same glyph). This method must
        therefore not be called till canonical schemas have been
        assigned.

        A glyph’s name may include a suffix to disambiguate it from
        other glyphs that happen to otherwise share the same name. In a
        group of homonymous glyphs, the first gets the plain name and
        the rest get numeric suffixes, starting at 1 and incrementing by
        1 for each subsequent glyph. The suffix is ``"._"`` followed by
        the number in uppercase hexadecimal.
        """
        # TODO: Forbidding `str` till schemas have been merged is a
        # major footgun.
        if self._glyph_name is None:
            if self is not (canonical := self._canonical_schema):
                self._glyph_name = str(canonical)
            else:
                name = self._calculate_name()
                while len(name) > self._MAX_GLYPH_NAME_LENGTH:
                    name = name.rsplit('.', 1)[0]
                if name in self._canonical_names:
                    if self not in self._canonical_names[name]:
                        self._canonical_names[name].append(self)
                        name += '._{:X}'.format(len(self._canonical_names[name]) - 1)
                else:
                    self._canonical_names[name] = [self]
                self._glyph_name = name
        return self._glyph_name

    def max_tree_width(self) -> int:
        """Returns the maximum width of a shorthand overlap sequence
        following this schema.
        """
        return min(self.maximum_tree_width, self.path.max_tree_width(self.size))

    def max_double_marks(self) -> int:
        """Returns the maximum number of consecutive instances of
        U+1BC9E DUPLOYAN DOUBLE MARK supported after this schema’s
        glyph.
        """
        return (0
            if self.glyph_class != GlyphClass.JOINER
            else max(0, min(MAX_DOUBLE_MARKS, self.path.max_double_marks(self.size, self.joining_type, self.marks))))

    @functools.cached_property
    def pseudo_cursive(self) -> bool:
        """Returns whether this schema joins pseudo-cursively.
        """
        return self.glyph_class == GlyphClass.JOINER and self.path.is_pseudo_cursive(self.size)

    @functools.cached_property
    def is_primary(self) -> bool:
        """Returns whether this schema’s path is primary.

        This method must only be called if `path` is known to support
        the notion of being primary, which not all shapes do.
        """
        return not (self.path.reversed if isinstance(self.path, Circle) else self.path.secondary or self.path.reversed_circle)  # type: ignore[attr-defined]

    @functools.cached_property
    def can_become_part_of_diphthong(self) -> bool:
        """Returns whether this schema can give rise to a schema that is
        part of a diphthong ligature.

        A schema that already is part of a diphthong ligature cannot
        *become* part of a diphthong ligature, so the return value for
        such a schema is ``False``.
        """
        return not (self.diphthong_1
            or self.diphthong_2
            or (self.glyph_class != GlyphClass.JOINER and not self.ignored_for_topography)
            or self.joining_type != Type.ORIENTING
            or isinstance(self.path, Ou)
            or not self.can_be_ignored_for_topography()
            or isinstance(self.path, Curve) and not self.path.reversed_circle and (self.path.hook or (self.path.angle_out - self.path.angle_in) % 180 != 0)
            # TODO: Remove the following restriction.
            or self.path.stretch  # type: ignore[attr-defined]
        )

    def can_be_ignored_for_topography(self) -> bool:
        """Return whether this schema can give rise to a schema that is
        ignored for topography.
        """
        return (isinstance(self.path, (Circle, Ou))
            or isinstance(self.path, Curve) and not self.path.hook
        )

    def contextualize(
        self,
        context_in: Context,
        context_out: Context,
        *,
        ignore_dependent_schemas: bool = True,
    ) -> Schema:
        """Returns a schema based on this schema between two contexts.

        Args:
            context_in: The exit context of the preceding schema, or
                ``NO_CONTEXT`` if there is none.
            context_out: The entry context of the following schema, or
                ``NO_CONTEXT`` if there is none.
            ignore_dependent_schemas: Whether the output schema might
                have ``ignored_for_topography`` set to ``True``.
        """
        assert self.joining_type == Type.ORIENTING or isinstance(self.path, InvalidStep)
        ignored_for_topography = (
            ignore_dependent_schemas
            and context_out == NO_CONTEXT
            and self.can_be_ignored_for_topography()
            and context_in.ignorable_for_topography
        )
        if ignored_for_topography:
            if isinstance(self.path, Circle):
                path = self.path.clone(role=CircleRole.DEPENDENT)
            else:
                path = self.path
        else:
            if not ignore_dependent_schemas and (self.diphthong_1 or self.diphthong_2):
                context_in = context_in.clone(diphthong_start=self.diphthong_2)
                context_out = context_out.clone(diphthong_end=self.diphthong_1)
            path = self.path.contextualize(context_in, context_out)
            if path is self.path:
                # TODO: Verify that this optimization is safe.
                return self
        return self.clone(
            cmap=None,
            path=path,
            ignored_for_topography=ignored_for_topography,
            anchor=None,
            marks=None,
            context_in=None if ignored_for_topography else context_in,
            context_out=None if ignored_for_topography else context_out,
        )

    def path_context_in(self) -> Context:
        """Returns this schema’s entry context.
        """
        context_in = self.path.context_in()
        ignorable_for_topography = (
                self.glyph_class == GlyphClass.JOINER
                and self.can_lead_orienting_sequence
                and (isinstance(self.path, Ou) or self.can_be_ignored_for_topography())
            ) or CLONE_DEFAULT
        return context_in.clone(
            ignorable_for_topography=ignorable_for_topography,
            diphthong_start=self.diphthong_1,
            diphthong_end=self.diphthong_2,
        )

    def path_context_out(self) -> Context:
        """Returns this schema’s exit context.
        """
        context_out = self.path.context_out()
        ignorable_for_topography = (
            self.glyph_class == GlyphClass.JOINER
                and self.can_lead_orienting_sequence
                and (isinstance(self.path, Ou) or self.can_be_ignored_for_topography())
            ) or CLONE_DEFAULT
        return context_out.clone(
            ignorable_for_topography=ignorable_for_topography,
            diphthong_start=self.diphthong_1,
            diphthong_end=self.diphthong_2,
        )

    def rotate_diacritic(self, context) -> Schema:
        """Returns a schema based on this schema but rotated as per the
        given context.

        This assumes that this schema represents a mark glyph.

        Args:
            context: The context of the base glyph relative to which
                this schema’s mark glyph should be rotated.
        """
        return self.clone(
            cmap=None,
            path=self.path.rotate_diacritic(context),  # type: ignore[attr-defined]
            base_angle=context.angle,
        )

    @functools.cached_property
    def hub_priority(self) -> int:
        """Returns this schema’s hub priority.

        See ``shapes.Hub``.
        """
        if self.glyph_class != GlyphClass.JOINER:
            return -1
        priority = self.path.hub_priority(self.size)
        assert -1 <= priority <= MAX_HUB_PRIORITY, f'Invalid hub priority for {self._calculate_name()}: {priority}'
        return priority
