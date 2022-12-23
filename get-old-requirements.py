#!/usr/bin/env python3

# Copyright 2019, 2022 David Corbett
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
from typing import Optional
import urllib.request

import packaging.markers
import packaging.requirements
import packaging.specifiers
import packaging.version


def parse_constraints(lines: Sequence[str]) -> Mapping[str, packaging.specifiers.SpecifierSet]:
    constraints = {}
    for line in lines:
        line = line.strip()
        if line.startswith('-c ') or line.startswith('--constraint '):
            with open(line.split(' ', 1)[1], 'r') as constraint_file:
                for constraint_line in constraint_file:
                    try:
                        constraint = packaging.requirements.Requirement(constraint_line)
                    except packaging.requirements.InvalidRequirement:
                        continue
                    constraints[constraint.name] = constraint.specifier
    return constraints


def add_required_dists(
    requirements: MutableMapping[str, packaging.specifiers.SpecifierSet],
    required_dists: Sequence[str],
    constraints: Mapping[str, packaging.specifiers.SpecifierSet],
    extra: Optional[str] = None,
) -> None:
    for required_dist in required_dists:
        requirement = packaging.requirements.Requirement(required_dist)
        if ((marker := requirement.marker) is None
            or marker.evaluate(environment=None if extra is None else {'extra': extra})
        ):
            add_requirement(requirements, requirement, constraints)


def add_requirement(
    requirements: MutableMapping[str, packaging.specifiers.SpecifierSet],
    requirement: packaging.requirements.Requirement,
    constraints: Mapping[str, packaging.specifiers.SpecifierSet],
) -> None:
    if requirement.name not in requirements:
        requirements[requirement.name] = constraints.get(requirement.name, packaging.specifiers.SpecifierSet())
    requirements[requirement.name] &= requirement.specifier
    metadata = importlib.metadata.metadata(requirement.name)
    required_dists = metadata.get_all('Requires-Dist')
    if required_dists:
        add_required_dists(requirements, required_dists, constraints)
        if requirement.extras:
            for extra in metadata.get_all('Provides-Extra'):
                if extra not in requirement.extras:
                    continue
                add_required_dists(requirements, required_dists, constraints, extra)


def parse_requirements(
    lines: list[str],
    constraints: Mapping[str, packaging.specifiers.SpecifierSet],
) -> Mapping[str, packaging.specifiers.SpecifierSet]:
    requirements: MutableMapping[str, packaging.specifiers.SpecifierSet] = {}
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

    with open(args.input) as input:
        lines = input.readlines()

    requirements = parse_requirements(lines, parse_constraints(lines))

    with open(args.output, 'w') as output:
        for requirement_name, specifier in requirements.items():
            for release in sorted(map(
                packaging.version.Version,
                json.loads(urllib.request.urlopen('https://pypi.org/pypi/{}/json'.format(requirement_name)).read())['releases']),
            ):
                if release in specifier:
                    output.write(f'{requirement_name} == {release}\n')
                    break


if __name__ == '__main__':
    main()
