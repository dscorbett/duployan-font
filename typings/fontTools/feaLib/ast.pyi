# MIT License
#
# Copyright (c) 2017 Just van Rossum
# Copyright (c) 2025 David Corbett
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from collections.abc import MutableSequence
from collections.abc import Sequence

class Element:
    def asFea(self, indent: str = ...) -> str: ...

class Statement(Element): ...

class Expression(Element): ...

class GlyphName(Expression):
    def __init__(
        self,
        glyph: str | GlyphName,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class GlyphClass(Expression):
    glyphs: Sequence[str]

    def __init__(
        self,
        glyphs: Sequence[str] | None = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

    def append(self, glyph: str) -> None: ...

class GlyphClassName(Expression):
    def __init__(
        self,
        glyphclass: GlyphClassDefinition,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class Block(Statement):
    statements: MutableSequence[Statement]

class FeatureFile(Block): ...

class FeatureBlock(Block):
    def __init__(
        self,
        name: str,
        use_extension: bool = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class LookupBlock(Block):
    def __init__(
        self,
        name: object,
        use_extension: bool = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class TableBlock(Block):
    def __init__(
        self,
        name: str,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class GlyphClassDefinition(Statement):
    glyphs: GlyphClass

    def __init__(
        self,
        name: str,
        glyphs: GlyphClass,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class GlyphClassDefStatement(Statement):
    def __init__(
        self,
        baseGlyphs: GlyphClass | GlyphClassName | None,
        markGlyphs: GlyphClass | GlyphClassName | None,
        ligatureGlyphs: GlyphClass | GlyphClassName | None,
        componentGlyphs: GlyphClass | GlyphClassName | None,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class MarkClass:
    def __init__(self, name: str) -> None: ...

    def addDefinition(self, definition: MarkClassDefinition) -> None: ...

class MarkClassDefinition(Statement):
    def __init__(
        self,
        markClass: MarkClass,
        anchor: Anchor,
        glyphs: GlyphName | GlyphClass | GlyphClassName,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class Anchor(Expression):
    def __init__(
        self,
        x: float,
        y: float,
        name: str | None = ...,
        contourpoint: int | None = ...,
        xDeviceTable: tuple[int, int, int, int] | None = ...,
        yDeviceTable: tuple[int, int, int, int] | None = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class ChainContextSubstStatement(Statement):
    def __init__(
        self,
        prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        glyphs: Sequence[GlyphName | GlyphClass | GlyphClassName],
        suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        lookups: Sequence[LookupBlock | Sequence[LookupBlock] | None],
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class CursivePosStatement(Statement):
    def __init__(
        self,
        glyphclass: GlyphName | GlyphClass | GlyphClassName,
        entryAnchor: Anchor | None,
        exitAnchor: Anchor | None,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class LanguageStatement(Statement):
    def __init__(
        self,
        language: str,
        include_default: bool = ...,
        required: bool = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class LigatureSubstStatement(Statement):
    def __init__(
        self,
        prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        glyphs: Sequence[GlyphName | GlyphClass | GlyphClassName],
        suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        replacement: str,
        forceChain: bool,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class LookupFlagStatement(Statement):
    def __init__(
        self,
        value: int = ...,
        markAttachment: GlyphName | GlyphClass | GlyphClassName | None = ...,
        markFilteringSet: GlyphName | GlyphClass | GlyphClassName | None = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class LookupReferenceStatement(Statement):
    def __init__(
        self,
        lookup: LookupBlock,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class MarkBasePosStatement(Statement):
    def __init__(
        self,
        base: GlyphName | GlyphClass | GlyphClassName,
        marks: Sequence[tuple[Anchor, MarkClass]],
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class MarkMarkPosStatement(Statement):
    def __init__(
        self,
        baseMarks: GlyphName | GlyphClass | GlyphClassName,
        marks: Sequence[tuple[Anchor, MarkClass]],
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class MultipleSubstStatement(Statement):
    def __init__(
        self,
        prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        glyph: GlyphName | GlyphClass | GlyphClassName,
        suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        replacement: Sequence[GlyphName | GlyphClass | GlyphClassName],
        forceChain: bool = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class ReverseChainSingleSubstStatement(Statement):
    def __init__(
        self,
        old_prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        old_suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        glyphs: Sequence[GlyphName | GlyphClass | GlyphClassName],
        replacements: Sequence[GlyphName | GlyphClass | GlyphClassName],
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class SingleSubstStatement(Statement):
    def __init__(
        self,
        glyphs: Sequence[GlyphName | GlyphClass | GlyphClassName],
        replace: Sequence[GlyphName | GlyphClass | GlyphClassName],
        prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        forceChain: bool,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class ScriptStatement(Statement):
    def __init__(
        self,
        script: str,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class SinglePosStatement(Statement):
    def __init__(
        self,
        pos: Sequence[tuple[GlyphName | GlyphClass | GlyphClassName, ValueRecord]],
        prefix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        suffix: Sequence[GlyphName | GlyphClass | GlyphClassName],
        forceChain: bool,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...

class ValueRecord(Expression):
    def __init__(
        self,
        xPlacement: float | None = ...,
        yPlacement: float | None = ...,
        xAdvance: float | None = ...,
        yAdvance: float | None = ...,
        xPlaDevice: float | None = ...,
        yPlaDevice: float | None = ...,
        xAdvDevice: float | None = ...,
        yAdvDevice: float | None = ...,
        vertical: bool = ...,
        location: tuple[str, int, int] | None = ...,
    ) -> None: ...
