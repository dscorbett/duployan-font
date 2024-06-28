#!/usr/bin/env python3

# Copyright 2019, 2022-2024 David Corbett
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


import argparse
import functools
import importlib.metadata
import json
import re
import subprocess
import sys
from typing import TYPE_CHECKING
import urllib.request

import packaging.markers
import packaging.requirements
import packaging.specifiers
import packaging.utils
import packaging.version


if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Mapping
    from collections.abc import MutableMapping
    from collections.abc import Sequence

    from _typeshed import FileDescriptorOrPath
    from packaging.utils import NormalizedName


COMMENT_PATTERN = re.compile(r'(^|\s)#.*')


def get_lines(file: FileDescriptorOrPath) -> Sequence[str]:
    continuation = False
    lines: list[str] = []
    with open(file, encoding='utf-8') as input:
        for line in input:
            if continuation:
                lines[-1] += line
            else:
                lines.append(line)
            continuation = line.endswith('\\')
    return [stripped_line for line in lines if (stripped_line := COMMENT_PATTERN.sub('', line).strip())]


def parse_constraints(lines: Sequence[str]) -> Mapping[NormalizedName, packaging.specifiers.SpecifierSet]:
    constraints = {}
    for line in lines:
        if line.startswith(('-c ', '--constraint ')):
            for constraint_line in get_lines(line.split(' ', 1)[1]):
                try:
                    constraint = packaging.requirements.Requirement(constraint_line)
                except packaging.requirements.InvalidRequirement:
                    continue
                constraints[packaging.utils.canonicalize_name(constraint.name)] = constraint.specifier
    return constraints


@functools.cache
def get_metadata(
    requirement_name: NormalizedName,
    specifier: packaging.specifiers.SpecifierSet,
) -> tuple[importlib.metadata.PackageMetadata | None, packaging.specifiers.SpecifierSet]:
    new_specifier = packaging.specifiers.SpecifierSet()
    for release in get_matching_releases(requirement_name, specifier):
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', f'{requirement_name}=={release}'])
            return importlib.metadata.metadata(requirement_name), new_specifier
        except (importlib.metadata.PackageNotFoundError, subprocess.CalledProcessError):
            new_specifier &= packaging.specifiers.SpecifierSet(f'!={release}')
    return None, new_specifier


def get_metadata_and_update_specifier(
    requirement_name: NormalizedName,
    specifier: packaging.specifiers.SpecifierSet,
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet],
) -> importlib.metadata.PackageMetadata | None:
    metadata, new_specifier = get_metadata(requirement_name, specifier)
    requirements[requirement_name] &= new_specifier
    return metadata


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
    new = name not in requirements
    if new:
        requirements[name] = constraints.get(name, packaging.specifiers.SpecifierSet())
    if (specifier_union := requirements[name] & requirement.specifier) != requirements[name] or new:
        requirements[name] = specifier_union
        new = True
    if ((new or requirement.extras)
        and (metadata := get_metadata_and_update_specifier(name, requirements[name], requirements))
        and (required_dists := metadata.get_all('Requires-Dist'))
    ):
        add_required_dists(requirements, required_dists, constraints)
        if requirement.extras:
            for extra in metadata.get_all('Provides-Extra') or []:
                if extra in requirement.extras:
                    add_required_dists(requirements, required_dists, constraints, extra)


def parse_requirement(
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet],
    line: str,
    constraints: Mapping[NormalizedName, packaging.specifiers.SpecifierSet],
) -> None:
    try:
        requirement = packaging.requirements.Requirement(line)
    except packaging.requirements.InvalidRequirement:
        return
    add_requirement(requirements, requirement, constraints)


def parse_requirements(
    lines: Sequence[str],
    constraints: Mapping[NormalizedName, packaging.specifiers.SpecifierSet],
) -> Mapping[NormalizedName, packaging.specifiers.SpecifierSet]:
    requirements: MutableMapping[NormalizedName, packaging.specifiers.SpecifierSet] = {}
    for line in lines:
        if line.startswith(('-r ', '--requirement ')):
            for requirement_name, specifier in parse_requirements(get_lines(line.split(' ', 1)[1]), constraints).items():
                parse_requirement(requirements, f'{requirement_name}{specifier}', constraints)
        else:
            parse_requirement(requirements, line, constraints)
    return requirements


def get_valid_version(release: tuple[str, object]) -> packaging.version.Version | None:
    if not release[1]:
        return None
    try:
        return packaging.version.Version(release[0])
    except packaging.version.InvalidVersion:
        return None


@functools.cache
def fetch_releases(requirement_name: str) -> Iterator[tuple[str, object]]:
    return json.loads(urllib.request.urlopen(f'https://pypi.org/pypi/{requirement_name}/json').read())['releases'].items()  # type: ignore[no-any-return]


def get_matching_releases(requirement_name: str, specifier: packaging.specifiers.SpecifierSet) -> Iterator[packaging.version.Version]:
    for release in sorted(filter(None, map(
        get_valid_version,
        fetch_releases(requirement_name),
    ))):
        if release in specifier:
            yield release


def main() -> None:
    if sys.prefix == sys.base_prefix:
        sys.exit('Must be run in a virtual environment')

    parser = argparse.ArgumentParser(description='Pin the requirements in a requirements file to their oldest versions.')
    parser.add_argument('--input', metavar='FILE', required=True, help='input requirements file')
    parser.add_argument('--output', metavar='FILE', required=True, help='output requirements file')
    args = parser.parse_args()

    lines = get_lines(args.input)

    requirements = parse_requirements(lines, parse_constraints(lines))

    failures = {}
    with open(args.output, 'w', encoding='utf-8') as output:
        for requirement_name, specifier in requirements.items():
            for release in get_matching_releases(requirement_name, specifier):
                output.write(f'{requirement_name}=={release}\n')
                break
            else:
                failures[requirement_name] = specifier
    if failures:
        sys.exit('\n'.join(f'Cannot find any version of {requirement_name} that satisfies {specifier}' for requirement_name, specifier in failures.items()))


if __name__ == '__main__':
    main()
