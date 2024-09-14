# Copyright 2024 David Corbett
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

"""Character set enum.

Among all the available characters, the font can be built with different
subsets. `Charset` is an enum representing the available character sets.
"""


import enum


@enum.unique
class Charset(enum.StrEnum):
    """A set of characters to include in the font.

    A “character” here really means a ``Schema``. It is called a
    “character set” because it is supposed to filter schemas based on
    the characters they are mapped to. It can filter by other features
    too, but the mapped character is the main one.
    """

    #: A character set appropriate for Noto.
    NOTO = enum.auto()

    #: A character set appropriate for general-purpose use. It is like
    #: `NOTO` but includes more non-Duployan characters for convenience. It
    #: also includes some private use characters for certain Duployan
    #: characters not encoded in Unicode.
    STANDARD = enum.auto()

    #: A character set only appropriate for testing the font. It is like
    #: `STANDARD` but includes a few private use characters that appear in
    #: the test files but are not otherwise useful. It includes all
    #: available characters.
    TESTING = enum.auto()
