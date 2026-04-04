# Copyright 2019, 2022-2026 David Corbett
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

import collections
from typing import Final
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Mapping
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence
    from collections.abc import Sequence

    from phases import Lookup
    from phases import Phase
    from phases import Rule
    from schema import Schema


type _Group[T] = list[T]


class Grouper[T]:
    """A mutable bidirectional mapping between disjoint groups and their
    items.

    A group is a list of items. Every item is mapped to the group it is
    in. The minimum length of a group is 2. Every item is logically part
    of a group, but singleton groups are not represented explicitly.

    Type parameters:
        T: The type of the groups’ items.
    """
    def __init__(self, groups: Collection[_Group[T]]) -> None:
        """Initializes this `Grouper`.

        Args:
            groups: The initial groups. Empty and singleton groups are
                ignored.
        """
        self._groups: Final[MutableSequence[_Group[T]]] = []
        self._inverted: Final[MutableMapping[T, _Group[T]]] = {}
        for group in groups:
            if len(group) > 1:
                self.add(group)

    def groups(self) -> Sequence[_Group[T]]:
        """Returns a copy of the current groups.
        """
        return list(self._groups)

    def group_of(self, item: T) -> _Group[T] | None:
        """Returns an item’s group.

        Args:
            item: An item.

        Returns:
            The item’s group, or ``None`` if it is not explicitly in a
            group, which represents being in a singleton group.
        """
        return self._inverted.get(item)

    def add(self, group: _Group[T]) -> None:
        """Adds a group.

        Args:
            group: A new group. Its items must not be in any existing
                groups, but the grouper does not validate that.
        """
        self._groups.append(group)
        for item in group:
            self._inverted[item] = group

    def remove(self, group: _Group[T]) -> None:
        """Removes a group.

        Args:
            group: The group to remove.
        """
        self._groups.remove(group)
        for item in group:
            del self._inverted[item]

    def remove_item(self, group: _Group[T], item: T) -> None:
        """Removes an item from a group.

        Args:
            group: The group to remove from.
            item: The item to remove.

        Raises:
            ValueError: If `item` is not in `group`.
        """
        group.remove(item)
        del self._inverted[item]
        if len(group) == 1:
            self.remove(group)

    def remove_items(self, minuend: _Group[T], subtrahend: Collection[T]) -> None:
        """Removes items from a group.

        Args:
            minuend: The group to remove from.
            subtrahend: A collection of items to remove.

        Raises:
            ValueError: If any item in `subtrahend` is not in `minuend`.
        """
        for item in subtrahend:
            self.remove_item(minuend, item)


def group_schemas(schemas: Collection[Schema]) -> Grouper[Schema]:
    """Groups schemas by `Schema.group`.

    Args:
        schemas: A collection of schemas.

    Returns:
        A `Grouper` that initially groups schemas by their default
        groups.
    """
    group_dict = collections.defaultdict(list)
    for schema in schemas:
        group_dict[schema.group].append(schema)
    return Grouper(group_dict.values())


def _sift_groups_in_rule_part(
    grouper: Grouper[Schema],
    rule: Rule,
    target_part: Sequence[Schema | str],
    classes: Mapping[str, Collection[Schema]],
    named_lookups_with_phases: Mapping[str, tuple[Lookup, Phase]],
) -> None:
    for s in target_part:
        if isinstance(s, str):
            cls = classes[s]
            cls_set: dict[Schema, None] = dict.fromkeys(cls)
            intersection_sort_key = {schema: i for i, schema in enumerate(cls_set)}.__getitem__
            if target_part is rule.inputs and rule.outputs is not None:
                substitutions: dict[str, dict[Schema, Schema]] = {}
                for output in rule.outputs:
                    if isinstance(output, str) and len(output_class := classes[output]) != 1:
                        substitutions[output] = dict(zip(cls, output_class, strict=True))
            intersection_cache: dict[int, tuple[_Group[Schema], set[Schema]]] = {}
            for schema in cls_set:
                if (group := grouper.group_of(schema)) is not None:
                    key = id(group)
                    cache_entry = intersection_cache.get(key)
                    if cache_entry is None:
                        intersection_cache[key] = (group, {schema})
                    else:
                        cache_entry[1].add(schema)
            for group, intersection_set in intersection_cache.values():
                overlap = len(intersection_set)
                if overlap == len(group):
                    intersection = group
                else:
                    grouper.remove_items(group, intersection_set)
                    if overlap != 1:
                        intersection = sorted(intersection_set, key=intersection_sort_key)
                        grouper.add(intersection)
                if overlap != 1 and target_part is rule.inputs:
                    if rule.outputs is not None:
                        for substitution in substitutions.values():
                            grouper.remove(intersection)
                            new_groups = collections.defaultdict(list)
                            for input_schema in intersection:
                                output_schema = substitution[input_schema]
                                key = id(grouper.group_of(output_schema) or output_schema)
                                new_groups[key].append(input_schema)
                            new_intersection: MutableSequence[Schema] | None = None
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
                                    grouper.add([*dict.fromkeys(new_group)])  # type: ignore[misc]
                    elif rule.lookups is not None:
                        for lookup in rule.lookups:
                            if lookup is not None:
                                sift_groups(grouper, named_lookups_with_phases[lookup][0], classes, named_lookups_with_phases)
        elif (group := grouper.group_of(s)) is not None:
            grouper.remove_item(group, s)


def sift_groups(
    grouper: Grouper[Schema],
    lookup: Lookup,
    classes: Mapping[str, Collection[Schema]],
    named_lookups_with_phases: Mapping[str, tuple[Lookup, Phase]],
) -> None:
    """Regroups schemas into groups of interchangeable schemas.

    Args:
        grouper: A `Grouper` that initially maps schemas to their
            default groups. Sifting may mutate it.
        lookup: A lookup whose rules may affect which schemas are
            considered interchangeable.
        classes: A mapping of glyph class names to their schemas
            corresponding to the glyphs in each class, used by `lookup`.
        named_lookups_with_phases: A mapping of lookup names to lookups
            and phases, used by `lookup`.
    """
    for rule in lookup.rules:
        _sift_groups_in_rule_part(grouper, rule, rule.contexts_in, classes, named_lookups_with_phases)
        assert rule.contexts_out is not None
        _sift_groups_in_rule_part(grouper, rule, rule.contexts_out, classes, named_lookups_with_phases)
        _sift_groups_in_rule_part(grouper, rule, rule.inputs, classes, named_lookups_with_phases)
