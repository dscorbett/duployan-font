# Copyright 2023-2026 David Corbett
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

"""Filtering schemas by character set.
"""

import string
from typing import TYPE_CHECKING
from typing import assert_never

import gfsubsets
import unicodedata2 as unicodedata

from . import Charset
from utils import Type


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet
    from typing import Final

    from schema import Schema


#: The set of code points which should be omitted from the Noto build
#: for no reason that is otherwise derivable.
_NOTO_EXCLUSIONS: Final[AbstractSet[int]] = {
    # Some punctuation marks are marked as encirclable for consistency with
    # related characters without having direct attestations.
    0x00A1, 0x00BF, 0x0589, 0x2018, 0x2019, 0x2E2E,
    # Manseau’s English adaptation is not fully supported in Unicode. It is
    # not useful to include code points specific to unsupported modes.
    0x030B, 0x030F, 0x1AE8, 0x1AEE, 0x1AEF,
    # It is not clear whether this is the right code point for the Chinese
    # aspiration mark.
    0x0312,
    # Duployé-Flageul for Esperanto is not fully supported in Unicode.
    0x031C, 0x0339, 0x0351, 0x0357,
    # Lockett’s Shorthand is not fully supported in Unicode.
    0x0325, 0x032E, 0x033D,
    # Brandt’s Danish adaptation is not fully supported in Unicode.
    0x0326, 0x1AB7,
    # U+034F COMBINING GRAPHEME JOINER creates reversed circle letters not
    # supported by Unicode. It is effectively a private use character.
    0x034F,
}


#: The set of code points which should be included in the Noto build for
#: no reason that is otherwise derivable.
_NOTO_INCLUSIONS: Final[AbstractSet[int]] = {
    # The whole set of Romanian grammalogues should be included for
    # consistency, even those that don’t have Duployan-specific behavior.
    0x002B, 0x2197, 0x2641, 0x271D,
    # U+00B0 DEGREE SIGN is mentioned in Unicode Technical Note #37.
    0x00B0,
    # Finally, the following characters were included in previous releases
    # of Noto Sans Duployan. Removing them would be a breaking change.
    0x0024, 0x002A, 0x002E, 0x002F, 0x005B, 0x005D, 0x00AB, 0x00BA, 0x00BB, 0x2013, 0x2039, 0x203A, 0x2308, 0x2309, 0x230A, 0x230B, 0x2620, 0x2E40,
}


assert _NOTO_EXCLUSIONS.isdisjoint(_NOTO_INCLUSIONS), (
    f'Cannot simultaneously include and exclude characters in the Noto build: {", ".join(f"U+{cp:04X}" for cp in sorted(_NOTO_EXCLUSIONS & _NOTO_INCLUSIONS))}')


def _include_in_noto(schema: Schema) -> bool:
    """Returns whether a schema should be included in the Noto build.

    Args:
        schema: A schema.
    """
    if schema.cmap is None:
        return True
    if schema.cmap in _NOTO_EXCLUSIONS:
        return False
    if schema.cmap in _NOTO_INCLUSIONS:
        return True
    char = chr(schema.cmap)
    gc = unicodedata.category(char)
    if gc == 'Co':
        return False
    if gc == 'Zs':
        # Among the spaces, Noto fonts usually only include U+0020 SPACE and
        # U+00A0 NO-BREAK SPACE. U+202F NARROW NO-BREAK SPACE should also be
        # included for Duployan because it has special joining behavior, but
        # it resets the baseline in Chrome, so it is excluded to make sure
        # the font behaves consistently between applications with different
        # itemizers.
        return schema.joining_type == Type.NON_JOINING
    if char in f'{string.digits}\u2044':
        # Digits can take combining marks. This is not technically
        # Duployan-specific behavior but most other fonts don’t support this.
        return True
    if unicodedata.decomposition(char).startswith('<fraction>'):
        # Fractions have a distinct appearance in Romanian and can take
        # combining marks.
        return True
    if (schema.cmap not in gfsubsets.CodepointsInSubset('duployan', unique_glyphs=True)  # ruff: ignore[needless-bool]
        and gc[0] != 'M'
        and schema.joining_type == Type.NON_JOINING
        and not schema.encirclable
        and not schema.shading_allowed
    ):
        # Non-Duployan characters only belong in Noto Sans Duployan if they
        # interact with Duployan characters or have other Duployan-specific
        # behavior.
        return False
    return True


def _include_in_standard_charset(schema: Schema) -> bool:
    """Returns whether a schema should be included in the standard
    non-test build for general use.

    Args:
        schema: A schema.
    """
    if schema.cmap is None:
        return True
    return not (
        # U+E000 is only for testing side bearings.
        schema.cmap == 0xE000
        # The range U+EC00..U+ECAF is reserved for characters corresponding to
        # U+1BC00..U+1BCAF. If a private use character corresponds to an
        # assigned character, it represents a variant of the latter that is
        # unattested but useful for testing. If it corresponds to a reserved
        # code point, it represents an attested Duployan character not supported
        # by Unicode; this should be included in the standard character set once
        # the mapping is more stable.
        or schema.cmap in range(0xEC00, 0xECAF + 1)
    )


def contains(charset: Charset, schema: Schema) -> bool:
    """Returns whether a schema is in a character set.

    Args:
        charset: A character set.
        schema: A schema.
    """
    match charset:
        case Charset.NOTO:
            return _include_in_noto(schema)
        case Charset.STANDARD:
            return _include_in_standard_charset(schema)
        case Charset.TESTING:
            return True
        case _:
            assert_never(charset)


def filter_charset(charset: Charset, schemas: Iterable[Schema]) -> Iterable[Schema]:
    """Returns the schemas in a character set.

    Args:
        charset: A character set.
        schemas: An iterable of schemas.

    Returns:
        The largest subset of `schemas` appropriate for `charset`.
    """
    return [s for s in schemas if contains(charset, s)]
