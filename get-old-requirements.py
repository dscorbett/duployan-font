#!/usr/bin/env python3

# Copyright 2019 David Corbett
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
import json
import urllib.request

import packaging.requirements
import packaging.version

parser = argparse.ArgumentParser(description='Pin the requirements in a requirements file to their oldest versions.')
parser.add_argument('--input', metavar='FILE', required=True, help='input requirements file')
parser.add_argument('--output', metavar='FILE', required=True, help='output requirements file')
args = parser.parse_args()

with open(args.input) as input:
    with open(args.output, 'w') as output:
        for line in input:
            try:
                requirement = packaging.requirements.Requirement(line)
            except packaging.requirements.InvalidRequirement:
                # A blank line or comment
                continue
            for release in sorted(map(
                    packaging.version.Version,
                    json.loads(urllib.request.urlopen('https://pypi.org/pypi/{}/json'.format(requirement.name)).read())['releases'])):
                if release in requirement.specifier:
                    output.write('{} == {}\n'.format(requirement.name, release))
                    break

