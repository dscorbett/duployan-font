# Copyright 2018-2019, 2023-2024, 2026 David Corbett
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

from typing import Final
from typing import TYPE_CHECKING

from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH


if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Sequence


PARENT_EDGE: Final[str] = 'pe'


CHILD_EDGES: Final[Sequence[Sequence[str]]] = [
    [f'ce{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]
    for layer_index in range(min(2, MAX_TREE_DEPTH))
]


INTER_EDGES: Final[Sequence[Sequence[str]]] = [[f'edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]


#: The anchor for marks that are inherently part of their bases’
#: characters (like the dot in U+1BC5A DUPLOYAN LETTER OW) where the
#: mark’s left and right x coordinates fall between the stenogram’s left
#: and right x coordinates (inclusive) in all contexts. If the base
#: orients, the mark is positioned relative to it.
RELATIVE_NARROW: Final[str] = 'rel1'


#: The anchor for marks that are inherently part of their bases’
#: characters (like the line in U+1BC4E DUPLOYAN LETTER SLOAN EE) where
#: the mark’s left and right x coordinates might not fall between the
#: stenogram’s left and right x coordinates. It is okay if they do fall
#: between them, but in that case `RELATIVE_NARROW` is more efficient if
#: possible. If the base orients, the mark is positioned relative to it.
RELATIVE_WIDE: Final[str] = 'rel2'


MIDDLE: Final[str] = 'mid'


ABOVE: Final[str] = 'abv'


BELOW: Final[str] = 'blw'


SECANT: Final[str] = 'sec'


ALL_MKMK: Final[list[str]] = [
    RELATIVE_NARROW,
    RELATIVE_WIDE,
    MIDDLE,
    ABOVE,
    BELOW,
]


ALL_MARK: Final[list[str]] = [
    *ALL_MKMK,
    SECANT,
]


PRE_HUB_CONTINUING_OVERLAP: Final[str] = 'hub1cont'


POST_HUB_CONTINUING_OVERLAP: Final[str] = 'hub2cont'


CONTINUING_OVERLAP: Final[str] = 'cont'


PRE_HUB_CURSIVE: Final[str] = 'hub1cursive'


POST_HUB_CURSIVE: Final[str] = 'hub2cursive'


CURSIVE: Final[str] = 'cursive'


ALL_CURSIVE: Final[list[str]] = [
    # The hub cursive anchors are intentionally skipped here: they are
    # duplicates of the standard cursive anchors used only to finagle the
    # baseline glyph into the root of the cursive attachment tree.
    CONTINUING_OVERLAP,
    CURSIVE,
]


ALL: Final[Collection[str]] = ALL_MARK + ALL_CURSIVE
