# Copyright 2025 David Corbett
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

from collections.abc import Sequence
from typing import NamedTuple

from _typeshed import StrOrBytesPath

class GlyphInfo:
    @property
    def codepoint(self) -> int: ...

class GlyphPosition:
    @property
    def y_offset(self) -> int: ...

class Buffer:
    def add_str(
        self,
        text: str,
        item_offset: int = ...,
        item_length: int = ...,
    ) -> None: ...

    @property
    def glyph_infos(self) -> list[GlyphInfo]: ...

    @property
    def glyph_positions(self) -> list[GlyphPosition] | None: ...

    @property
    def script(self) -> str | None: ...

    def add_codepoints(
        self,
        codepoints: list[int],
        item_offset: int = ...,
        item_length: int = ...,
    ) -> None: ...

    def guess_segment_properties(self) -> None: ...

class Blob:
    @classmethod
    def from_file_path(cls, filename: StrOrBytesPath) -> Blob: ...

class Face:
    def __init__(self, blob: Blob | bytes | None = ..., index: int = ...) -> None: ...

class GlyphExtents(NamedTuple):
    x_bearing: int
    y_bearing: int
    width: int
    height: int

class Font:
    def __init__(self, face_or_font: Face | Font | None = ...) -> None: ...

    def get_glyph_extents(self, gid: int) -> GlyphExtents | None: ...

def shape(
    font: Font,
    buffer: Buffer,
    features: dict[str, int | Sequence[tuple[int, int, int]]] | None = ...,
    shapers: list[str] | None = ...,
) -> None: ...
