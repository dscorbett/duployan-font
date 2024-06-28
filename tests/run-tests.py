#!/usr/bin/env python3

# Copyright 2018-2019, 2023-2024 David Corbett
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

import argparse
from collections.abc import Generator
import difflib
import json
import os
import re
import subprocess
import sys
from typing import Literal

from utils import FULL_FONT_CODE_POINTS


CI = os.getenv('CI') == 'true'


DISAMBIGUATION_SUFFIX_PATTERN = re.compile(r'\._[0-9A-F]+$')


GLYPH_POSITION_PATTERN = re.compile(r'@-?[0-9]+,-?[0-9]+')


NOTDEF_PATTERN = re.compile(r'[\[|]\.notdef@')


SPACE_NAME_COMPONENT_PATTERN = re.compile(r'(?<=[\[|])(?:uni00A0|uni200[0-9A]|uni202F|uni205F|uni3000)(?![0-9A-Za-z_])')


NAME_PREFIX = r'(?:(?:dupl|u(?:ni(?:[0-9A-F]{4})+|[0-9A-F]{4,6})(?:_[^.]*)?)\.)'


UNSTABLE_NAME_COMPONENT_PATTERN = re.compile(fr'(?<=[\[|])(?:{NAME_PREFIX}[0-9A-Za-z_]+|(?!{NAME_PREFIX})[0-9A-Za-z_]+)')


_Color = Literal['auto', 'no', 'yes']


def parse_color(color: _Color) -> bool:
    match color:
        case 'auto':
            return CI or sys.stdout.isatty()
        case 'no':
            return False
        case 'yes':
            return True
    raise ValueError(f'Invalid --color value: {color}')


def parse_json(s: str) -> Generator[str, None, None]:
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


def munge(output: str, regular: bool, incomplete: bool) -> str:
    if incomplete:
        output = UNSTABLE_NAME_COMPONENT_PATTERN.sub('dupl', output)
    if not regular:
        output = GLYPH_POSITION_PATTERN.sub('', output)
    return output


def print_diff(
    code_points: str,
    options: str,
    actual_output: str,
    expected_output: str,
    color: bool,
) -> None:
    if color:
        highlighted_actual_output = []
        highlighted_expected_output = []
        matcher = difflib.SequenceMatcher(None, actual_output, expected_output, False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                highlighted_actual_output.append(actual_output[i1:i2])
                highlighted_expected_output.append(expected_output[j1:j2])
            elif tag == 'delete':
                highlighted_actual_output.append(f'\x1B[1;96m{actual_output[i1:i2]}\x1B[0m')
            elif tag == 'insert':
                highlighted_expected_output.append(f'\x1B[1;93m{expected_output[j1:j2]}\x1B[0m')
            elif tag == 'replace':
                highlighted_actual_output.append(f'\x1B[1;96m{actual_output[i1:i2]}\x1B[0m')
                highlighted_expected_output.append(f'\x1B[1;93m{expected_output[j1:j2]}\x1B[0m')
            else:
                assert False, f'Unknown tag: {tag}'
        actual_output = ''.join(highlighted_actual_output)
        expected_output = ''.join(highlighted_expected_output)
    print()
    print(f'Input:    {code_points}:{options}')
    print('Actual:   ' + actual_output)
    print('Expected: ' + expected_output)


def run_test(
    font: str,
    line: str,
    png_file: str,
    color: bool,
    incomplete: bool,
    view_all: bool,
) -> tuple[bool, str]:
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
        env={**os.environ, 'HB_SHAPER_LIST': ''},
    )
    stdout_data, stderr_data = p.communicate()
    print(stderr_data.decode('utf-8'), end='', file=sys.stderr)
    actual_output = f'[{"|".join(parse_json(stdout_data.decode("utf-8")))}]'
    regular = font.endswith('-Regular.otf')
    passed = (munge(actual_output, regular, incomplete) == munge(expected_output, regular, incomplete)
        or incomplete and bool(
            NOTDEF_PATTERN.search(actual_output)
            or SPACE_NAME_COMPONENT_PATTERN.search(expected_output)
            or any(int(cp, 16) in FULL_FONT_CODE_POINTS for cp in code_points.split())
        )
    )
    if not passed or view_all:
        if not passed:
            print_diff(code_points, options, actual_output, expected_output, color)
        if not CI:
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
                stdout=subprocess.PIPE,
                env={**os.environ, 'HB_SHAPER_LIST': ''},
            )
            p.wait()
            assert p.stderr is not None
            print(p.stderr.read().decode('utf-8'), end='', file=sys.stderr)
    return (passed, f'{code_points}:{options}:{actual_output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run shaping tests.')
    parser.add_argument('--color', default='auto', help='Whether to print diffs in color: "yes", "no", or "auto".')
    parser.add_argument('--incomplete', action='store_true', help='Whether the font is less than the complete font. Do not fail a test if the actual result contains `.notdef`. Ignore the parts of glyph names that indicate code points.')
    parser.add_argument('--view', action='store_true', help='Render all test cases, not just the failures.')
    parser.add_argument('font', help='The path to a font.')
    parser.add_argument('tests', nargs='*', help='The paths to test files.')
    args = parser.parse_args()
    color = parse_color(args.color.lower())
    passed_all = True
    failed_dir = os.path.join(os.path.dirname(sys.argv[0]), 'failed', os.path.basename(args.font))
    os.makedirs(failed_dir, exist_ok=True)
    for fn in args.tests:
        result_lines = []
        passed_file = True
        with open(fn, encoding='utf-8') as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip()
                if line and line[0] != '#':
                    passed_line, result_line = run_test(
                        args.font,
                        line,
                        os.path.join(failed_dir, 'png', os.path.basename(fn), f'{line_number:03}'),
                        color,
                        args.incomplete,
                        args.view,
                    )
                    passed_file = passed_file and passed_line
                    result_lines.append(result_line + '\n')
                else:
                    result_lines.append(line + '\n')
        if not passed_file:
            with open(os.path.join(failed_dir, os.path.basename(fn)), 'w', encoding='utf-8') as f:
                f.writelines(result_lines)
        passed_all = passed_all and passed_file
    if not passed_all:
        sys.exit(1)
