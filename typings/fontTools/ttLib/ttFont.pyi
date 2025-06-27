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

from io import IOBase
from types import NotImplementedType
from types import TracebackType
from typing import Literal
from typing import Self

from _typeshed import FileDescriptorOrPath
from fontTools.misc.configTools import AbstractConfig
from fontTools.misc.configTools import Option
from fontTools.ttLib.tables.DefaultTable import DefaultTable

class TTFont:
    def __init__(
        self,
        file: FileDescriptorOrPath | IOBase | None = ...,
        res_name_or_index: int | str | None = ...,
        sfntVersion: Literal['\0\1\0\0', 'OTTO'] = ...,
        flavor: Literal['woff', 'woff2'] | None = ...,
        checkChecksums: Literal[0, 1, 2] = ...,
        verbose: None = ...,
        recalcBBoxes: bool = ...,
        allowVID: NotImplementedType = ...,
        ignoreDecompileErrors: bool = ...,
        recalcTimestamp: bool = ...,
        fontNumber: int = ...,
        lazy: bool | None = ...,
        quiet: None = ...,
        *,
        cfg: AbstractConfig | dict[str | Option, object] = ...,
    ) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def save(
        self,
        file: str | IOBase,
        reorderTables: bool | None = ...,
    ) -> None: ...

    def __contains__(self, tag: str) -> bool: ...

    def __getitem__(self, tag: str) -> DefaultTable: ...

    def __setitem__(self, tag: str, table: DefaultTable) -> None: ...

    def __delitem__(self, tag: str) -> None: ...

def newTable(tag: str) -> DefaultTable: ...
