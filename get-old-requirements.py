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
import collections
from collections.abc import Container
from collections.abc import Mapping
from collections.abc import MutableMapping
from collections.abc import Sequence
from collections.abc import Set
import importlib.metadata
import json
import re
import urllib.request

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


def get_extra_requirements(
    package_name: str,
    relevant_extras: Container[str],
) -> Mapping[str, packaging.specifiers.SpecifierSet]:
    metadata = importlib.metadata.metadata(package_name)
    required_dists = metadata.get_all('Requires-Dist')
    extra_requirements: MutableMapping[str, packaging.specifiers.SpecifierSet] = collections.defaultdict(packaging.specifiers.SpecifierSet)
    for extra in metadata.get_all('Provides-Extra'):
        if extra not in relevant_extras:
            continue
        for required_dist in required_dists:
            if match := re.search(fr"(\S+) \(([^);]+)\).*;.*\bextra *== *'{re.escape(extra)}'", required_dist):
                extra_requirements[match.group(1)] &= packaging.specifiers.SpecifierSet(match.group(2))
    return extra_requirements


def add_requirement(
    requirements: MutableMapping[str, packaging.specifiers.SpecifierSet],
    requirement_name: str,
    requirement_specifier: packaging.specifiers.SpecifierSet,
    requirement_extras: Set[str],
    constraints: Mapping[str, packaging.specifiers.SpecifierSet],
) -> None:
    if requirement_name not in requirements:
        requirements[requirement_name] = constraints.get(requirement_name, packaging.specifiers.SpecifierSet())
    requirements[requirement_name] &= requirement_specifier
    if requirement_extras:
        for extra_requirement in get_extra_requirements(requirement_name, requirement_extras).items():
            add_requirement(requirements, *extra_requirement, set(), constraints)


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
        add_requirement(requirements, requirement.name, requirement.specifier, requirement.extras, constraints)
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
