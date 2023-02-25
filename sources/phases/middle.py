# Copyright 2021 Google LLC
# Copyright 2023 David Corbett
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
    'PHASE_LIST',
    'merge_lookalikes',
]


from collections.abc import MutableSequence
from typing import TYPE_CHECKING


from . import Lookup
from . import Rule
from schema import Schema
import sifting
from utils import OrderedSet
from utils import PrefixView


if TYPE_CHECKING:
    from . import AddRule
    from duployan import Builder


def merge_lookalikes(
    builder: Builder,
    original_schemas: OrderedSet[Schema],
    schemas: OrderedSet[Schema],
    new_schemas: OrderedSet[Schema],
    classes: PrefixView[MutableSequence[Schema]],
    named_lookups: PrefixView[Lookup],
    add_rule: AddRule,
) -> MutableSequence[Lookup]:
    lookup = Lookup(
        'rlig',
        'dflt',
    )
    grouper = sifting.group_schemas(new_schemas)
    for group in grouper.groups():
        group.sort(key=Schema.sort_key)
        group_iter = iter(group)
        lookalike_schema = next(group_iter)
        if not lookalike_schema.might_need_width_markers:
            continue
        lookalike_schema.lookalike_group = group
        for schema in group_iter:
            add_rule(lookup, Rule([schema], [lookalike_schema]))
            schema.lookalike_group = group
    return [lookup]


PHASE_LIST = [
    merge_lookalikes,
]
