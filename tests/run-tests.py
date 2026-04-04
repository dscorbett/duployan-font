#!/usr/bin/env python3

# Copyright 2018-2019, 2023-2026 David Corbett
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

"""A CLI to run shaping tests.
"""

from __future__ import annotations

import argparse
import difflib
import enum
from io import IOBase
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING
from typing import TypedDict
from typing import assert_never
import unicodedata


if TYPE_CHECKING:
    from collections.abc import Generator
    from collections.abc import Set as AbstractSet


CI = os.getenv('CI') == 'true'


DEFAULT_IGNORABLE_CODE_POINTS_IN_HARFBUZZ: AbstractSet[int] = {
    0x00AD, 0x034F, 0x061C, 0x17B4, 0x17B5, *range(0x180B, 0x180F + 1), *range(0x200B, 0x200F + 1), *range(0x202A, 0x202E + 1), *range(0x2060, 0x206F + 1),
    *range(0xFE00, 0xFE0F + 1), 0xFEFF, *range(0xFFF0, 0xFFF8 + 1), *range(0x1D173, 0x1D17A + 1), *range(0xE0000, 0xE0FFF + 1),
}


DISAMBIGUATION_SUFFIX_PATTERN = re.compile(r'\._[0-9A-F]+$')


GLYPH_POSITION_PATTERN = re.compile(r'@-?[0-9]+,-?[0-9]+')


NOTDEF_PATTERN = re.compile(r'[\[|]\.notdef@')


NAME_PREFIX = r'(?:(?:dupl|u(?:ni(?:[0-9A-F]{4})+|[0-9A-F]{4,6})(?:_[^.]*)?)\.)'


UNSTABLE_NAME_COMPONENT_PATTERN = re.compile(fr'(?<=[\[|])(?:{NAME_PREFIX}[0-9A-Za-z_]+|(?!{NAME_PREFIX})[0-9A-Za-z_]+)(\.su[bp]s)?')


class Color(enum.StrEnum):
    """Whether to print diffs in color.
    """

    #: Choose automatically.
    AUTO = enum.auto()

    #: Do not use color.
    NO = enum.auto()

    #: Use color.
    YES = enum.auto()


def parse_color(color: Color) -> bool:
    """Resolves a `Color` to a `bool`.

    Returns:
        Whether to print diffs in color.
    """
    match color:
        case Color.AUTO:
            assert isinstance(sys.stdout, IOBase)
            return CI or sys.stdout.isatty()
        case Color.NO:
            return False
        case Color.YES:
            return True
        case _:
            assert_never(color)


class Glyph(TypedDict):
    """A glyph JSON object from hb-shape.

    Attributes:
        g: The glyph name.
        cl: The cluster value.
        dx: The x offset.
        dy: The y offset.
        ax: The x advance.
        ay: The y advance.
    """

    g: str
    cl: int
    dx: int
    dy: int
    ax: int
    ay: int


def parse_json(s: str) -> Generator[str]:
    """Converts HarfBuzz’s JSON output to the test storage format.

    Yields:
        One test string per visible glyph in the JSON, representing its
        name and absolute position, plus one final test string
        representing the total advance width.
    """
    x = 0
    y = 0
    glyph: Glyph
    for glyph in json.loads(s):  # type: ignore[misc]
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
    """Modifies a test string before comparing the expected output to
    the actual output.

    Args:
        output: A test output string, which is either the expected
            output or the actual output.
        regular: Whether the font being tested is a regular-weight font.
            If not, glyph positions are ignored.
        incomplete: Whether the font uses a subset of the available
            glyphs such that glyph names cannot be tested and must be
            ignored.

    Returns:
        The modified test string.
    """
    if incomplete:
        output = UNSTABLE_NAME_COMPONENT_PATTERN.sub('dupl', output)
    if not regular:
        output = GLYPH_POSITION_PATTERN.sub('', output)
    return output


def may_fail(code_points: str, actual_output: str) -> bool:
    """Returns whether a test failure should be ignored.

    A failure should be ignored if the test does not apply to the font.
    If the actual test output includes a ``.notdef`` glyph, the test is
    ignored: the font is more likely to be using a restricted character
    set than it is to be accidentally missing a character in its 'cmap'.
    A failure is also ignored if the test includes any default-ignorable
    code points: it doesn’t necessarily matter if a font is missing an
    ignorable code point.

    Args:
        code_points: The space-separated code points of the test’s
            input.
        actual_output: The actual test output.
    """
    return bool(NOTDEF_PATTERN.search(actual_output)
        or any((cp := int(cp_str, 16)) in DEFAULT_IGNORABLE_CODE_POINTS_IN_HARFBUZZ
                or cp != 0x0020 and unicodedata.category(chr(cp)) == 'Zs'
            for cp_str in code_points.split())
        ,
    )


def print_diff(
    code_points: str,
    options: str,
    actual_output: str,
    expected_output: str,
    color: bool,
) -> None:
    """Prints a diff between the actual and expected outputs.

    Args:
        code_points: The space-separated code points of the test’s
            input.
        options: The HarfBuzz options of the test’s input.
        actual_output: The actual test output.
        expected_output: The expected test output.
        color: Whether to print the diff in color.
    """
    if color:
        highlighted_actual_output = []
        highlighted_expected_output = []
        matcher = difflib.SequenceMatcher(None, actual_output, expected_output, autojunk=False)
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
                assert_never(tag)
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
    """Runs one test from a test file.

    Args:
        font: The path of the font to test.
        line: A test line from a test file.
        png_path_prefix: The path of the generated PNG file, to which
            are appended a hyphen-separated code point sequence and
            ``'.png'``. By default, only failed tests get PNGs.
        color: Whether to print the diff in color if the test fails.
        incomplete: Whether the font uses a subset of the available
            glyphs such that glyph names cannot be tested and must be
            ignored, and whether some test failures are acceptable.
        view_all: Whether to generate a PNG regardless of the test
            result.

    Returns:
        A tuple of two elements.

        1. Whether the test passed.
        2. A test line corresponding to the actual output. If the test
           passed, this is equivalent to the expected output. Otherwise,
           it is suitable as a replacement for the expected output in
           the test file if the actual output is correct.
    """
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
    assert isinstance(args.color, Color)  # type: ignore[misc]
    color = parse_color(args.color)
    passed_all = True
    assert isinstance(args.font, str)  # type: ignore[misc]
    failed_dir = Path(sys.argv[0]).parent / 'failed' / Path(args.font).name
    failed_dir.mkdir(parents=True, exist_ok=True)
    assert isinstance(args.tests, list)  # type: ignore[misc]
    for fn in args.tests:
        assert isinstance(fn, Path)
        result_lines = []
        passed_file = True
        with fn.open(encoding='utf-8') as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip()
                if line and line[0] != '#':
                    assert isinstance(args.incomplete, bool)  # type: ignore[misc]
                    assert isinstance(args.view, bool)  # type: ignore[misc]
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
