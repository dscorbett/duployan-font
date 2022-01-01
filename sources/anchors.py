# Copyright 2018-2019 David Corbett
# Copyright 2020-2021 Google LLC
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
    'CHILD_EDGE_CLASSES',
    'CONTINUING_OVERLAP',
    'CONTINUING_OVERLAP_CLASS',
    'CONTINUING_OVERLAP_OR_HUB_CLASS',
    'CURSIVE',
    'HUB_CLASS',
    'INTER_EDGES',
    'INTER_EDGE_CLASSES',
    'MIDDLE',
    'PARENT_EDGE',
    'PARENT_EDGE_CLASS',
    'POST_HUB_CONTINUING_OVERLAP',
    'POST_HUB_CURSIVE',
    'PRE_HUB_CONTINUING_OVERLAP',
    'PRE_HUB_CURSIVE',
    'RELATIVE_1',
    'RELATIVE_2',
    'SECANT',
]


from utils import MAX_TREE_DEPTH
from utils import MAX_TREE_WIDTH


PARENT_EDGE = 'pe'


CHILD_EDGES = [[f'ce{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(min(2, MAX_TREE_DEPTH))]


INTER_EDGES = [[f'edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]


RELATIVE_1 = 'rel1'


RELATIVE_2 = 'rel2'


MIDDLE = 'mid'


ABOVE = 'abv'


BELOW = 'blw'


SECANT = 'sec'


ALL_MKMK = [
    RELATIVE_1,
    RELATIVE_2,
    MIDDLE,
    ABOVE,
    BELOW,
]


ALL_MARK = ALL_MKMK + [
    SECANT,
]


PRE_HUB_CONTINUING_OVERLAP = 'hub1cont'


POST_HUB_CONTINUING_OVERLAP = 'hub2cont'


CONTINUING_OVERLAP = 'cont'


PRE_HUB_CURSIVE = 'hub1cursive'


POST_HUB_CURSIVE = 'hub2cursive'


CURSIVE = 'cursive'


ALL_CURSIVE = [
    # The hub cursive anchors are intentionally skipped here: they are
    # duplicates of the standard cursive anchors used only to finagle the
    # baseline glyph into the root of the cursive attachment tree.
    CONTINUING_OVERLAP,
    CURSIVE,
]


ALL = ALL_MARK + ALL_CURSIVE


PARENT_EDGE_CLASS = 'global..pe'


CHILD_EDGE_CLASSES = [f'global..ce{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)]


INTER_EDGE_CLASSES = [[f'global..edge{layer_index}_{child_index + 1}' for child_index in range(MAX_TREE_WIDTH)] for layer_index in range(MAX_TREE_DEPTH)]


HUB_CLASS = 'global..hub'


CONTINUING_OVERLAP_CLASS = 'global..cont'


CONTINUING_OVERLAP_OR_HUB_CLASS = 'global..cont_or_hub'
