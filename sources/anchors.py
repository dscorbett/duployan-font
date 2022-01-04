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

__all__ = [
    'ABOVE',
    'ALL',
    'ALL_CURSIVE',
    'ALL_MARK',
    'ALL_MKMK',
    'BELOW',
    'CHILD_EDGES',
    'CONTINUING_OVERLAP',
    'CURSIVE',
    'INTER_EDGES',
    'MIDDLE',
    'PARENT_EDGE',
    'POST_HUB_CONTINUING_OVERLAP',
    'POST_HUB_CURSIVE',
    'PRE_HUB_CONTINUING_OVERLAP',
    'PRE_HUB_CURSIVE',
    'RELATIVE_1',
    'RELATIVE_2',
    'SECANT',
]


from collections.abc import Sequence
from typing import Final
from typing import Iterable


from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH


PARENT_EDGE: Final[str] = 'pe'


CHILD_EDGES: Final[Sequence[Sequence[str]]] = [[f'ce{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(min(2, MAX_TREE_DEPTH))]


INTER_EDGES: Final[Sequence[Sequence[str]]] = [[f'edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]


RELATIVE_1: Final[str] = 'rel1'


RELATIVE_2: Final[str] = 'rel2'


MIDDLE: Final[str] = 'mid'


ABOVE: Final[str] = 'abv'


BELOW: Final[str] = 'blw'


SECANT: Final[str] = 'sec'


ALL_MKMK: Final[list[str]] = [
    RELATIVE_1,
    RELATIVE_2,
    MIDDLE,
    ABOVE,
    BELOW,
]


ALL_MARK: Final[list[str]] = ALL_MKMK + [
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


ALL: Final[Iterable[str]] = ALL_MARK + ALL_CURSIVE
