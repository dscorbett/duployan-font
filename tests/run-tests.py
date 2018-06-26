#!/usr/bin/env python

# Copyright 2018 David Corbett
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function
from __future__ import unicode_literals

import subprocess
import sys

def run_test(line):
    code_points, options, expected_output = line.split(':')
    p = subprocess.Popen(
        ['hb-shape', font, '-u', code_points] + options.split(),
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE)
    p.wait()
    print(p.stderr.read().decode('utf-8'), end='', file=sys.stderr)
    actual_output = p.stdout.read().decode('utf-8').rstrip()
    if actual_output != expected_output:
        print()
        print('Actual:   ' + actual_output)
        print('Expected: ' + expected_output)
        return False
    return True

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: {} font tests...'.format(sys.argv[0]))
        sys.exit(1)
    passed = True
    font = sys.argv[1]
    for fn in sys.argv[2:]:
        with open(fn) as f:
            for line in f:
                line = line.decode('utf-8').rstrip()
                if line and line[0] != '#':
                    passed = run_test(line) and passed
    if not passed:
        sys.exit(1)

