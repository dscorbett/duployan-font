#!/usr/bin/env python3

# Copyright 2019, 2022-2023 David Corbett
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

import argparse
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import Sequence
import importlib.metadata
import json
import re
import urllib.request

import packaging.markers
import packaging.requirements
import packaging.specifiers
import packaging.utils
from packaging.utils import NormalizedName
import packaging.version


COMMENT_PATTERN = re.compile(r'(^|\s)#.*')


def parse_constraints(lines: Sequence[str]) -> Mapping[NormalizedName, packaging.specifiers.SpecifierSet]:
    constraints = {}
    for line in lines:
        if line.startswith(('-c ', '--constraint ')):
            with open(line.split(' ', 1)[1]) as constraint_file:
                for constraint_line in constraint_file:
                    try:
                        constraint = packaging.requirements.Requirement(constraint_line)
                    except packaging.requirements.InvalidRequirement:
                        continue
                    constraints[packaging.utils.canonicalize_name(constraint.name)] = constraint.specifier
    return constraints


def add_required_dists(
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet],
    required_dists: Sequence[str],
    constraints: Mapping[NormalizedName, packaging.specifiers.SpecifierSet],
    extra: str | None = None,
) -> None:
    for required_dist in required_dists:
        requirement = packaging.requirements.Requirement(required_dist)
        if ((marker := requirement.marker) is None
            or marker.evaluate(environment=None if extra is None else {'extra': extra})
        ):
            add_requirement(requirements, requirement, constraints)


def add_requirement(
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet],
    requirement: packaging.requirements.Requirement,
    constraints: Mapping[NormalizedName, packaging.specifiers.SpecifierSet],
) -> None:
    name = packaging.utils.canonicalize_name(requirement.name)
    if name not in requirements:
        requirements[name] = constraints.get(name, packaging.specifiers.SpecifierSet())
    requirements[name] &= requirement.specifier
    metadata = importlib.metadata.metadata(name)
    required_dists = metadata.get_all('Requires-Dist')
    if required_dists:
        add_required_dists(requirements, required_dists, constraints)
        if requirement.extras:
            for extra in metadata.get_all('Provides-Extra'):
                if extra not in requirement.extras:
                    continue
                add_required_dists(requirements, required_dists, constraints, extra)


def parse_requirements(
    lines: Sequence[str],
    constraints: Mapping[NormalizedName, packaging.specifiers.SpecifierSet],
) -> Mapping[NormalizedName, packaging.specifiers.SpecifierSet]:
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet] = {}
    for line in lines:
        try:
            requirement = packaging.requirements.Requirement(line)
        except packaging.requirements.InvalidRequirement:
            continue
        add_requirement(requirements, requirement, constraints)
    return requirements


def main() -> None:
    parser = argparse.ArgumentParser(description='Pin the requirements in a requirements file to their oldest versions.')
    parser.add_argument('--input', metavar='FILE', required=True, help='input requirements file')
    parser.add_argument('--output', metavar='FILE', required=True, help='output requirements file')
    args = parser.parse_args()

    continuation = False
    lines: list[str] = []
    with open(args.input) as input:
        for line in input:
            if continuation:
                lines[-1] += line
            else:
                lines.append(line)
            continuation = line.endswith('\\')
    lines = [stripped_line for line in lines if (stripped_line := COMMENT_PATTERN.sub('', line).strip())]

    requirements = parse_requirements(lines, parse_constraints(lines))

    with open(args.output, 'w') as output:
        for requirement_name, specifier in requirements.items():
            for release in sorted(map(
                packaging.version.Version,
                json.loads(urllib.request.urlopen(f'https://pypi.org/pypi/{requirement_name}/json').read())['releases']),
            ):
                if release in specifier:
                    output.write(f'{requirement_name} == {release}\n')
                    break


if __name__ == '__main__':
    main()
