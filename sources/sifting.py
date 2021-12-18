# Copyright 2019 David Corbett
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
    'Grouper',
    'group_schemas',
    'sift_groups',
]


import collections


class Grouper:
    def __init__(self, groups):
        self._groups = []
        self._inverted = {}
        for group in groups:
            if len(group) > 1:
                self.add(group)

    def groups(self):
        return list(self._groups)

    def group_of(self, item):
        return self._inverted.get(item)

    def add(self, group):
        self._groups.append(group)
        for item in group:
            self._inverted[item] = group

    def remove(self, group):
        self._groups.remove(group)
        for item in group:
            del self._inverted[item]

    def remove_item(self, group, item):
        group.remove(item)
        del self._inverted[item]
        if len(group) == 1:
            self.remove(group)

    def remove_items(self, minuend, subtrahend):
        for item in subtrahend:
            try:
                self.remove_item(minuend, item)
            except ValueError:
                pass


def group_schemas(schemas):
    group_dict = collections.defaultdict(list)
    for schema in schemas:
        group_dict[schema.group].append(schema)
    return Grouper(group_dict.values())


def _sift_groups_in_rule_part(grouper, rule, target_part, classes, named_lookups_with_phases):
    for s in target_part:
        if isinstance(s, str):
            cls = classes[s]
            cls_intersection = set(cls).intersection
            for group in grouper.groups():
                intersection_set = cls_intersection(group)
                if overlap := len(intersection_set):
                    if overlap == len(group):
                        intersection = group
                    else:
                        grouper.remove_items(group, intersection_set)
                        if overlap != 1:
                            intersection = [*dict.fromkeys(x for x in cls if x in intersection_set)]
                            grouper.add(intersection)
                    if overlap != 1 and target_part is rule.inputs:
                        if rule.outputs is not None:
                            for output in rule.outputs:
                                if isinstance(output, str) and len(output := classes[output]) != 1:
                                    grouper.remove(intersection)
                                    new_groups = collections.defaultdict(list)
                                    for input_schema, output_schema in zip(cls, output):
                                        if input_schema in intersection_set:
                                            key = id(grouper.group_of(output_schema) or output_schema)
                                            new_groups[key].append(input_schema)
                                    new_intersection = None
                                    for schema in intersection:
                                        new_group = new_groups.get(id(schema))
                                        if new_group and schema in new_group:
                                            if new_intersection is None:
                                                new_intersection = new_group
                                            else:
                                                new_intersection += new_group
                                                new_group *= 0
                                    for new_group in new_groups.values():
                                        if len(new_group) > 1:
                                            grouper.add([*dict.fromkeys(new_group)])
                        elif rule.lookups is not None:
                            for lookup in rule.lookups:
                                if lookup is not None:
                                    sift_groups(grouper, named_lookups_with_phases[lookup][0], classes, named_lookups_with_phases)
        else:
            for group in grouper.groups():
                if s in group:
                    grouper.remove_item(group, s)
                    break


def sift_groups(grouper, lookup, classes, named_lookups_with_phases):
    for rule in lookup.rules:
        _sift_groups_in_rule_part(grouper, rule, rule.contexts_in, classes, named_lookups_with_phases)
        _sift_groups_in_rule_part(grouper, rule, rule.contexts_out, classes, named_lookups_with_phases)
        _sift_groups_in_rule_part(grouper, rule, rule.inputs, classes, named_lookups_with_phases)