# Copyright (C) 2007-2012 by George Williams
# Copyright (C) 2025 David Corbett
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# The name of the author may not be used to endorse or promote products
# derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
# EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from collections.abc import Iterable
from collections.abc import Iterator
from typing import Literal
from typing import Self
from typing import overload

class point:
    x: float
    y: float

    @overload
    def __init__(
        self,
        x_y_on_curve: tuple[float, float, bool],
        type: Literal[0, 1, 2, 3] = ...,
        selected: bool = ...,
        /,
    ) -> None: ...

    @overload
    def __init__(
        self,
        x_y: tuple[float, float],
        on_curve: bool = ...,
        type: Literal[0, 1, 2, 3] = ...,
        selected: bool = ...,
        /,
    ) -> None: ...

    @overload
    def __init__(
        self,
        x: float,
        y: float,
        on_curve: bool = ...,
        type: Literal[0, 1, 2, 3] = ...,
        selected: bool = ...,
        interpolated: bool = ...,
        /,
    ) -> None: ...

    def transform(
        self,
        matrix: tuple[float, float, float, float, float, float],
        /,
    ) -> point: ...

class contour:
    closed: bool

    def __iter__(self, /) -> Iterator[point]: ...

    def __len__(self, /) -> int: ...

    @overload
    def __getitem__(self, i: int, /) -> point: ...

    @overload
    def __getitem__(self, i_j: slice[int | None, int | None, Literal[1, -1] | None], /) -> contour: ...

    def __iadd__(self, d: point | contour, /) -> Self: ...

    def moveTo(self, x: float, y: float, /) -> contour: ...

    @overload
    def lineTo(self, x: float, y: float, pos: int = ..., /) -> contour: ...

    @overload
    def lineTo(self, x_y: tuple[float, float], pos: int = ..., /) -> contour: ...

    @overload
    def cubicTo(self, cp1: tuple[float, float], cp2: tuple[float, float], x_y: tuple[float, float], pos: int = ..., /) -> contour: ...

    @overload
    def cubicTo(self, cp1x: float, cp1y: float, cp2x: float, cp2y: float, x: float, y: float, pos: int = ..., /) -> contour: ...

class layer:
    def __iter__(self, /) -> Iterator[contour]: ...

    def dup(self, /) -> layer: ...

    @overload
    def stroke(
        self,
        nib: Literal['circular'],
        width: float,
        cap: Literal['butt', 'round', 'square'] = ...,
        join: Literal['mitre', 'round', 'bevel'] = ...,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> layer: ...

    @overload
    def stroke(
        self,
        nib: Literal['eliptical'],
        width: float,
        minor_width: float,
        angle: float,
        cap: Literal['butt', 'round', 'square'] = ...,
        join: Literal['mitre', 'round', 'bevel'] = ...,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> layer: ...

    @overload
    def stroke(
        self,
        nib: Literal['caligraphic', 'square'],
        width: float,
        height: float,
        angle: float,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> layer: ...

    @overload
    def stroke(
        self,
        nib: Literal['polygonal', 'poly'],
        contour: contour | layer,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> layer: ...

    def transform(
        self,
        matrix: tuple[float, float, float, float, float, float],
        /,
    ) -> layer: ...

    def boundingBox(self, /) -> tuple[float, float, float, float]: ...

    def xBoundsAtY(self, ybottom: float, ytop: float = ..., /) -> tuple[float, float] | None: ...

    def draw(self, pen: glyphPen, /) -> layer: ...

    def __len__(self, /) -> int: ...

    def __getitem__(self, i: int, /) -> contour: ...

    def __delitem__(self, i: int, /) -> None: ...

    def __iadd__(self, m: contour | layer, /) -> Self: ...

class glyphPen:
    @overload
    def moveTo(self, x_y: tuple[float, float], /) -> glyphPen: ...

    @overload
    def moveTo(self, x: float, y: float, /) -> glyphPen: ...

    @overload
    def lineTo(self, x_y: tuple[float, float], /) -> glyphPen: ...

    @overload
    def lineTo(self, x: float, y: float, /) -> glyphPen: ...

    @overload
    def curveTo(self, cp1: tuple[float, float], cp2: tuple[float, float], /) -> glyphPen: ...

    @overload
    def curveTo(self, cp1_x: float, cp1_y: float, cp2_x: float, cp2_y: float, /) -> glyphPen: ...

    @overload
    def curveTo(self, cp1: tuple[float, float], cp2: tuple[float, float], x_y: tuple[float, float], /) -> glyphPen: ...

    @overload
    def curveTo(self, cp1_x: float, cp1_y: float, cp2_x: float, cp2_y: float, x: float, y: float, /) -> glyphPen: ...

    def endPath(self, /) -> glyphPen: ...

class glyph:
    @property
    def altuni(self, /) -> tuple[tuple[int, int, int], ...] | None: ...

    @altuni.setter
    def altuni(self, altuni: tuple[int | tuple[int] | tuple[int, int] | tuple[int, int, int], ...] | None) -> None: ...

    anchorPoints: list[
        tuple[str, Literal['mark', 'base', 'basemark', 'entry', 'exit'], float, float]
        | tuple[str, Literal['ligature', 'baselig'], float, float, int]
        ,
    ]
    foreground: layer
    glyphclass: Literal['automatic', 'noclass', 'baseglyph', 'baseligature', 'mark', 'component']
    glyphname: str
    left_side_bearing: float
    right_side_bearing: float
    temporary: object
    unicode: int
    width: int

    def addAnchorPoint(
        self,
        anchor_class_name: str,
        anchor_type: Literal['mark', 'base', 'ligature', 'basemark', 'entry', 'exit', 'baselig'],
        x: float,
        y: float,
        selected: int = ...,
        ligature_index: int = ...,
        /,
    ) -> glyph: ...

    def boundingBox(self, /) -> tuple[float, float, float, float]: ...

    def clear(self, /) -> glyph: ...

    def removeOverlap(self, /) -> glyph: ...

    @overload
    def stroke(
        self,
        nib: Literal['circular'],
        width: float,
        cap: Literal['butt', 'round', 'square'] = ...,
        join: Literal['mitre', 'round', 'bevel'] = ...,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> glyph: ...

    @overload
    def stroke(
        self,
        nib: Literal['eliptical'],
        width: float,
        minor_width: float,
        angle: float,
        cap: Literal['butt', 'round', 'square'] = ...,
        join: Literal['mitre', 'round', 'bevel'] = ...,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> glyph: ...

    @overload
    def stroke(
        self,
        nib: Literal['caligraphic', 'square'],
        width: float,
        height: float,
        angle: float,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> glyph: ...

    @overload
    def stroke(
        self,
        nib: Literal['polygonal', 'poly'],
        contour: contour | layer,
        flags: Iterable[Literal['removeinternal', 'removeexternal', 'cleanup']] = ...,
        /,
    ) -> glyph: ...

    def transform(
        self,
        matrix: tuple[float, float, float, float, float, float],
        flags: Iterable[Literal['partialRefs', 'round']] = ...,
        /,
    ) -> glyph: ...

    def draw(self, pen: glyphPen, /) -> layer: ...

    def glyphPen(self, /, replace: bool = ...) -> glyphPen: ...

class selection:
    def all(self, /) -> selection: ...

    def none(self, /) -> selection: ...

class font:
    encoding: str
    selection: selection

    def __contains__(self, index: int | str, /) -> bool: ...

    def __getitem__(self, index: int | str, /) -> glyph: ...

    def createChar(self, uni: int, name: str = ..., /) -> glyph: ...

    def glyphs(self, type: Literal['GID', 'encoding'] = ..., /) -> Iterator[glyph]: ...

    def generate(
        self,
        /,
        filename: str,
        bitmap_type: str = ...,
        flags: Iterable[Literal[
            'afm',
            'pfm',
            'short-post',
            'omit-instructions',
            'apple',
            'opentype',
            'PfEd-comments',
            'PfEd-colors',
            'PfEd-lookups',
            'PfEd-guides',
            'PfEd-background',
            'winkern',
            'glyph-map-file',
            'TeX-table',
            'ofm',
            'old-kern',
            'symbol',
            'dummy-dsig',
            'dummy-DSIG',
            'tfm',
            'no-flex',
            'no-hints',
            'round',
            'composites-in-afm',
            'no-mac-names',
        ]] = ...,
        bitmap_resolution: int = ...,
        subfont_directory: str = ...,
        namelist: str = ...,
        layer: int | str = ...,
    ) -> font: ...

    def canonicalContours(self, /) -> font: ...

    def canonicalStart(self, /) -> font: ...

    def correctReferences(self, /) -> font: ...

    def round(self, factor: float = ..., /) -> font: ...

    def simplify(
        self,
        error_bound: float = ...,
        flags: Iterable[Literal[
            'cleanup',
            'ignoreslopes',
            'ignoreextrema',
            'smoothcurves',
            'choosehv',
            'forcelines',
            'nearlyhvlines',
            'mergelines',
            'setstarttoextremum',
            'setstarttoextrema',
            'removesingletonpoints',
        ]] = ...,
        tan_bounds: float = ...,
        linefixup: float = ...,
        linelenmax: float = ...,
        /,
    ) -> font: ...
