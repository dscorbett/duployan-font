# Copyright 2018-2019 David Corbett
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

from __future__ import annotations


__all__ = [
    'Ignorability',
    'MAX_DOUBLE_MARKS',
    'MAX_HUB_PRIORITY',
    'NO_PHASE_INDEX',
    'Schema',
]


from collections.abc import Mapping
from collections.abc import MutableMapping
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
from utils import NO_CONTEXT
from utils import Type


NO_PHASE_INDEX: Final[int] = -1


CURRENT_PHASE_INDEX: int = NO_PHASE_INDEX


MAX_DOUBLE_MARKS: Final[int] = 3


MAX_HUB_PRIORITY: Final[int] = 2


class Ignorability(enum.Enum):
    DEFAULT_NO = enum.auto()
    DEFAULT_YES = enum.auto()
    OVERRIDDEN_NO = enum.auto()


class Schema:
    _MAX_GLYPH_NAME_LENGTH: ClassVar[int] = 63 - 2 - 4
    _COLLAPSIBLE_UNI_NAME: ClassVar[re.Pattern[str]] = re.compile(r'(?<=uni[0-9A-F]{4})_uni(?=[0-9A-F]{4})')
    _CHARACTER_NAME_SUBSTITUTIONS: ClassVar[Iterable[Tuple[re.Pattern[str], Any]]] = [(re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in [
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
    ]]
    _SEQUENCE_NAME_SUBSTITUTIONS: ClassVar[Sequence[Tuple[re.Pattern[str], Any]]] = [(re.compile(pattern_repl[0]), pattern_repl[1]) for pattern_repl in [
        (r'__zwj__', '___'),
        (r'((?:[a-z]+_)+)_dtls(?=__|$)', lambda m: m.group(1)[:-1].upper()),
    ]]
    _canonical_names: MutableMapping[str, list[Schema]] = {}

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
            shading_allowed: bool = True,
            context_in: Optional[Context] = None,
            context_out: Optional[Context] = None,
            diphthong_1: bool = False,
            diphthong_2: bool = False,
            base_angle: Optional[float] = None,
            cps: Optional[Sequence[int]] = None,
            original_shape: Optional[type[Shape]] = None,
    ) -> None:
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
        self._lookalike_group: Sequence[Schema] = [self]
        self.glyph: Optional[fontforge.glyph] = None

    def sort_key(self):
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
            [repr(m) for m in self.marks or []],
        ])))

    @functools.cached_property
    def diacritic_angles(self) -> Mapping[str, float]:
        return self.path.calculate_diacritic_angles()

    @functools.cached_property
    def without_marks(self):
        return self.marks and self.clone(cmap=None, marks=None)

    @functools.cached_property
    def glyph_class(self):
        return self.path.guaranteed_glyph_class() or (
            GlyphClass.MARK
                if self.anchor or self.child or self.ignored_for_topography
                else GlyphClass.BLOCKER
                if self.joining_type == Type.NON_JOINING
                else GlyphClass.JOINER
        )

    @functools.cached_property
    def might_need_width_markers(self) -> bool:
        return not (
                self.ignored_for_topography or self.widthless
            ) and (
                self.glyph_class == GlyphClass.JOINER
                or self.glyph_class == GlyphClass.MARK
            )

    @functools.cached_property
    def group(self) -> Any:
        if self.ignored_for_topography:
            return (
                self.ignorability == Ignorability.DEFAULT_YES,
                self.side_bearing,
                self.y_min,
                self.y_max,
            )
        if isinstance(self.path, Circle) and (self.diphthong_1 or self.diphthong_2):
            path_group = (
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
            tuple(m.group for m in self.marks or []),
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
    def lookalike_group(self) -> Sequence[Schema]:
        return self._lookalike_group

    @lookalike_group.setter
    def lookalike_group(self, lookalike_group: Sequence[Schema]) -> None:
        assert len(self._lookalike_group) == 1 and self._lookalike_group[0] is self
        self._lookalike_group = lookalike_group

    @lookalike_group.deleter
    def lookalike_group(self) -> None:
        del self._lookalike_group

    @staticmethod
    def _agl_name(cp: int) -> Optional[str]:
        return fontTools.agl.UV2AGL[cp] if cp <= 0x7F else None

    @staticmethod
    def _u_name(cp: int) -> str:
        return '{}{:04X}'.format('uni' if cp <= 0xFFFF else 'u', cp)

    @classmethod
    def _readable_name(cls, cp: int) -> str:
        try:
            name = unicodedata.name(chr(cp))
        except ValueError:
            name = cls._u_name(cp)
        for regex, repl in cls._CHARACTER_NAME_SUBSTITUTIONS:
            name = regex.sub(repl, name)
        return name

    def _calculate_name(self) -> str:
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
        if first_component_implies_type or self.path.name_in_sfd() or (
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
        if isinstance(self.path, Curve) and self.path.early_exit:
            name += '.ee'
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
            name += '.psts'
        if self.ignored_for_topography:
            name += '.dependent'
        if (isinstance(self.path, Circle)
            and self.path.role != CircleRole.INDEPENDENT
            and self.path.angle_in != self.path.angle_out
        ):
            name += '.circle'
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
        return name

    def __str__(self) -> str:
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

    def max_double_marks(self) -> int:
        return (0
            if self.glyph_class != GlyphClass.JOINER
            else max(0, min(MAX_DOUBLE_MARKS, self.path.max_double_marks(self.size, self.joining_type, self.marks))))

    @functools.cached_property
    def pseudo_cursive(self) -> bool:
        return self.glyph_class == GlyphClass.JOINER and self.path.is_pseudo_cursive(self.size)

    @functools.cached_property
    def is_primary(self):
        return not (self.path.reversed if isinstance(self.path, Circle) else self.path.secondary or self.path.reversed_circle)

    @functools.cached_property
    def can_become_part_of_diphthong(self):
        return not (self.diphthong_1
            or self.diphthong_2
            or (self.glyph_class != GlyphClass.JOINER and not self.ignored_for_topography)
            or self.joining_type != Type.ORIENTING
            or isinstance(self.path, Ou)
            or not self.can_be_ignored_for_topography()
            or isinstance(self.path, Curve) and not self.path.reversed_circle and (self.path.hook or (self.path.angle_out - self.path.angle_in) % 180 != 0)
            # TODO: Remove the following restriction.
            or self.path.stretch
        )

    def can_be_ignored_for_topography(self) -> bool:
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
        return self.clone(
            cmap=None,
            path=self.path.rotate_diacritic(context),  # type: ignore[attr-defined]
            base_angle=context.angle,
        )

    @functools.cached_property
    def hub_priority(self) -> int:
        if self.glyph_class != GlyphClass.JOINER:
            return -1
        priority = self.path.hub_priority(self.size)
        assert -1 <= priority <= MAX_HUB_PRIORITY, f'Invalid hub priority for {self._calculate_name()}: {priority}'
        return priority
