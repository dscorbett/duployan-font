# Copyright 2021 Google LLC
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
    'PHASE_LIST',
    'merge_lookalikes',
]


from . import Lookup
from . import Rule
from schema import Schema
import sifting


def merge_lookalikes(builder, original_schemas, schemas, new_schemas, classes, named_lookups, add_rule):
    lookup = Lookup(
        'rclt',
        {'DFLT', 'dupl'},
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
