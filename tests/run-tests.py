#!/usr/bin/env python3

# Copyright 2018-2019 David Corbett
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

import argparse
import json
import os
import re
import subprocess
import sys

DISAMBIGUATION_SUFFIX_PATTERN = re.compile(r'\._[0-9A-F]+$')

def parse_json(s):
    x = 0
    y = 0
    for glyph in json.loads(s):
        if not (name := glyph['g']).startswith('_'):
            yield f'''{
                DISAMBIGUATION_SUFFIX_PATTERN.sub('', name)
            }@{
                x + glyph["dx"]
            },{
                y + glyph["dy"]
            }'''
        x += int(glyph['ax'])
        y += int(glyph['ay'])
    yield f'_@{x},{y}'

def run_test(font, line, png_file, view_all):
    code_points, options, expected_output = line.split(':')
    p = subprocess.Popen(
        [
            'hb-shape',
            font,
            '-u',
            code_points,
            '-O',
            'json',
            '--remove-default-ignorables',
            *options.split(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_data, stderr_data = p.communicate()
    print(stderr_data.decode('utf-8'), end='', file=sys.stderr)
    actual_output = f'[{"|".join(parse_json(stdout_data.decode("utf-8")))}]'
    passed = actual_output == expected_output
    if not passed or view_all:
        if not passed:
            print()
            print('Actual:   ' + actual_output)
            print('Expected: ' + expected_output)
        if os.getenv('CI') != 'true':
            os.makedirs(os.path.dirname(png_file), exist_ok=True)
            png_file = '{}-{}.png'.format(png_file, code_points.replace(' ', '-'))
            p = subprocess.Popen(
                [
                    'hb-view',
                    '--font-file',
                    font,
                    '--font-size',
                    'upem',
                    '-u',
                    f'E000 {code_points} E000',
                    '--remove-default-ignorables',
                    '-o',
                    png_file,
                    '-O',
                    'png',
                    '--margin',
                    '800 0',
                    *options.split(),
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE)
            p.wait()
            print(p.stderr.read().decode('utf-8'), end='', file=sys.stderr)
    return (passed, ':'.join([code_points, options, actual_output]))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run shaping tests.')
    parser.add_argument('--view', action='store_true', help='Render all test cases, not just the failures.')
    parser.add_argument('font', help='The path to a font.')
    parser.add_argument('tests', nargs='*', help='The paths to test files.')
    args = parser.parse_args()
    passed_all = True
    failed_dir = os.path.join(os.path.dirname(sys.argv[0]), 'failed')
    os.makedirs(failed_dir, exist_ok=True)
    for fn in args.tests:
        result_lines = []
        passed_file = True
        with open(fn) as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip()
                if line and line[0] != '#':
                    passed_line, result_line = run_test(
                        args.font,
                        line,
                        os.path.join(failed_dir, 'png', os.path.basename(fn), '{:03}'.format(line_number)),
                        args.view,
                    )
                    passed_file = passed_file and passed_line
                    result_lines.append(result_line + '\n')
                else:
                    result_lines.append(line + '\n')
        if not passed_file:
            with open(os.path.join(failed_dir, os.path.basename(fn)), 'w') as f:
                f.writelines(result_lines)
        passed_all = passed_all and passed_file
    if not passed_all:
        sys.exit(1)

