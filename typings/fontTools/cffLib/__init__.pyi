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

from typing import Literal
from typing import SupportsIndex

class CFFFontSet:
    fontNames: list[str]

    def __getitem__(self, nameOrIndex: str | SupportsIndex) -> TopDict: ...

class Index: ...

class FDArrayIndex(Index): ...

class VarStoreData: ...

class FDSelect: ...

class CharStrings: ...

class BaseDict:
    rawDict: dict[str, object]

class TopDict(BaseDict):
    maxstack: float | None
    ROS: tuple[str | bytes, str | bytes, int] | None
    SyntheticBase: float | None
    version: str | bytes | None
    Notice: str | bytes | None
    Copyright: str | bytes | None
    FullName: str | bytes | None
    FontName: str | bytes | None
    FamilyName: str | bytes | None
    Weight: str | bytes | None
    isFixedPitch: float | None
    ItalicAngle: float | None
    UnderlinePosition: float | None
    UnderlineThickness: float | None
    PaintType: float | None
    CharstringType: float | None
    FontMatrix: list[float] | None
    UniqueID: float | None
    FontBBox: list[float] | None
    StrokeWidth: float | None
    XUID: list[float] | None
    PostScript: str | bytes | None
    BaseFontName: str | bytes | None
    BaseFontBlend: list[float] | None
    CIDFontVersion: float | None
    CIDFontRevision: float | None
    CIDFontType: float | None
    CIDCount: float | None
    charset: list[str] | None
    UIDBase: float | None
    Encoding: int | Literal['StandardEncoding', 'ExpertEncoding'] | None
    Private: PrivateDict | None
    FDSelect: FDSelect | None
    FDArray: FDArrayIndex | None
    CharStrings: CharStrings | None
    VarStore: VarStoreData | None

    def decompileAllCharStrings(self) -> None: ...

class PrivateDict(BaseDict): ...
