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

from __future__ import annotations

import argparse
import difflib
import enum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING
from typing import assert_never
import unicodedata


if TYPE_CHECKING:
    from collections.abc import Generator


CI = os.getenv('CI') == 'true'


DEFAULT_IGNORABLE_CODE_POINTS_IN_HARFBUZZ = {
    0x00AD, 0x034F, 0x061C, 0x17B4, 0x17B5, *range(0x180B, 0x180F + 1), *range(0x200B, 0x200F + 1), *range(0x202A, 0x202E + 1), *range(0x2060, 0x206F + 1),
    *range(0xFE00, 0xFE0F + 1), 0xFEFF, *range(0xFFF0, 0xFFF8 + 1), *range(0x1D173, 0x1D17A + 1), *range(0xE0000, 0xE0FFF + 1),
}


DISAMBIGUATION_SUFFIX_PATTERN = re.compile(r'\._[0-9A-F]+$')


GLYPH_POSITION_PATTERN = re.compile(r'@-?[0-9]+,-?[0-9]+')


NOTDEF_PATTERN = re.compile(r'[\[|]\.notdef@')


NAME_PREFIX = r'(?:(?:dupl|u(?:ni(?:[0-9A-F]{4})+|[0-9A-F]{4,6})(?:_[^.]*)?)\.)'


UNSTABLE_NAME_COMPONENT_PATTERN = re.compile(fr'(?<=[\[|])(?:{NAME_PREFIX}[0-9A-Za-z_]+|(?!{NAME_PREFIX})[0-9A-Za-z_]+)(\.su[bp]s)?')


class Color(enum.StrEnum):
    AUTO = enum.auto()
    NO = enum.auto()
    YES = enum.auto()


def parse_color(color: Color) -> bool:
    match color:
        case Color.AUTO:
            return CI or sys.stdout.isatty()
        case Color.NO:
            return False
        case Color.YES:
            return True
        case _:
            assert_never(color)


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


def may_fail(code_points: str, actual_output: str) -> bool:
    return bool(NOTDEF_PATTERN.search(actual_output)
        or any((cp := int(cp_str, 16)) in DEFAULT_IGNORABLE_CODE_POINTS_IN_HARFBUZZ
                or cp != 0x0020 and unicodedata.category(chr(cp)) == 'Zs'
            for cp_str in code_points.split())
    )


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
                raise ValueError(f'Unknown tag: {tag}')
        actual_output = ''.join(highlighted_actual_output)
        expected_output = ''.join(highlighted_expected_output)
    print()
    print(f'Input:    {code_points}:{options}')
    print('Actual:   ' + actual_output)
    print('Expected: ' + expected_output)


def run_test(
    font: str,
    line: str,
    png_path_prefix: Path,
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
        or incomplete and may_fail(code_points, actual_output)
    )
    if not passed or view_all:
        if not passed:
            print_diff(code_points, options, actual_output, expected_output, color)
        if not CI:
            png_path_prefix.parent.mkdir(parents=True, exist_ok=True)
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
                    f'{png_path_prefix}-{code_points.replace(" ", "-")}.png',
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
    parser.add_argument(
        '--color',
        default=Color.AUTO,
        type=Color,
        help=f'Whether to print diffs in color; one of {{{", ".join(c.value for c in Color)}}} (default: %(default)s).',
    )
    parser.add_argument(
        '--incomplete',
        action='store_true',
        help=(
            'Whether the font is less than the complete font. Do not fail a test if the actual result contains `.notdef`.'
            ' Ignore the parts of glyph names that indicate code points.'
        ),
    )
    parser.add_argument('--view', action='store_true', help='Render all test cases, not just the failures.')
    parser.add_argument('font', help='The path to a font.')
    parser.add_argument('tests', nargs='*', type=Path, help='The paths to test files.')
    args = parser.parse_args()
    color = parse_color(args.color.lower())
    passed_all = True
    failed_dir = Path(sys.argv[0]).parent / 'failed' / Path(args.font).name
    failed_dir.mkdir(parents=True, exist_ok=True)
    for fn in args.tests:
        assert isinstance(fn, Path)
        result_lines = []
        passed_file = True
        with fn.open(encoding='utf-8') as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip()
                if line and line[0] != '#':
                    passed_line, result_line = run_test(
                        args.font,
                        line,
                        failed_dir / 'png' / fn.name / f'{line_number:03}',
                        color,
                        args.incomplete,
                        args.view,
                    )
                    passed_file = passed_file and passed_line
                    result_lines.append(result_line + '\n')
                else:
                    result_lines.append(line + '\n')
        if not passed_file:
            with (failed_dir / fn.name).open('w', encoding='utf-8') as f:
                f.writelines(result_lines)
        passed_all = passed_all and passed_file
    if not passed_all:
        sys.exit(1)
