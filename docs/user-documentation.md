<!--
Copyright 2022 Google LLC
Copyright 2023-2025 David Corbett

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# User documentation

Rawnd Musmus Duployan is an unmodulated (“sans-serif”) font for many Duployan
modes, available in regular and bold weights.

## Installation

See the top-level [README.md](../README.md) for installation instructions.

The latest release and all past releases are listed on [the GitHub repository’s
release page](https://github.com/dscorbett/duployan-font/releases). Each release
has ZIP files attached for Rawnd Musmus Duployan and Rawnd Musmus Duployan
Uncow.

## Character set

* All characters in the Duployan and Shorthand Format Controls blocks
* Non-Duployan characters used with Duployan, such as digits and punctuation
* Some custom (non-Unicode) extensions

### Custom extensions

Rawnd Musmus Duployan uses some code point sequences not sanctioned by Unicode
to support some orienting letters needed in Chinook Jargon (and, incidentally,
various other modes). Adding the sequence \<U+034F, U+034F, U+034F> after one of
the letters U+1BC44, U+1BC53, U+1BC5A, U+1BC5B, U+1BC5C, U+1BC5D, U+1BC5E,
U+1BC5F, or U+1BC60 changes it from primary orientation to secondary
orientation.

There are also some private use characters for non-joining characters:

* U+E001 LATIN CROSS POMMEE
* U+E003 HEART WITH CROSS
* U+E010 TWO LINES JOINED CONVERGING LEFT
* U+E011 LEFT PARENTHESIS WITH STROKE
* U+E012 RIGHT PARENTHESIS WITH STROKE
* U+E013 LEFT PARENTHESIS WITH DOUBLE STROKE
* U+E014 RIGHT PARENTHESIS WITH DOUBLE STROKE
* U+E015 STENOGRAPHIC SEMICOLON
* U+E016 STENOGRAPHIC QUESTION MARK
* U+E017 STENOGRAPHIC EXCLAMATION MARK
* U+E021 COMBINING DIGIT ONE ABOVE
* U+E02A COMBINING RING-AND-DOT ABOVE
* U+E031 COMBINING DIGIT ONE BELOW
* U+E033 COMBINING DIGIT THREE BELOW
* U+E035 COMBINING DIGIT FIVE BELOW
* U+E037 COMBINING DIGIT SEVEN BELOW

## Features

### Contextual orientation

Every character is either joining or non-joining. Some joining characters are
orienting. Most letters are joining. Most vowels are orienting and most
consonants are not. Orienting characters have either primary or secondary
orientation, which determines which way they curve (counterclockwise or
clockwise) in any given context. Circles and curves have different rules for
what primary orientation means. Secondary orientation is always the opposite of
primary orientation.

If a primary circle appears between two letters that form a non-straight angle,
it curves whichever direction puts it opposite the angle. Otherwise, it curves
counterclockwise.

If a primary curve appears in medial or final position, it curves
counterclockwise. In initial position, it curves clockwise.

Most curves are oriented relative to their preceding letters, if any, falling
back to their following letters in initial position. Hooks (U+1BC7A DUPLOYAN
AFFIX ATTACHED E HOOK and U+1BC7B DUPLOYAN AFFIX ATTACHED I HOOK) follow the
opposite rule.

### Cursive joining

Letters are cursively joined to adjacent letters with contextually appropriate
forms. This includes pseudo-cursive letters like U+1BC00 DUPLOYAN LETTER H and
U+1BC80 DUPLOYAN AFFIX HIGH ACUTE which do not visually touch adjacent letters
but which otherwise have cursive-like interactions with them.

Stenograms are separated by non-joining characters. This includes digits,
symbols, punctuation, and most spaces. To separate stenograms with no extra
space between them, use U+200C ZERO WIDTH NON-JOINER. To include a usually
non-joining character in a stenogram (e.g. U+2E3C STENOGRAPHIC FULL STOP),
join it to adjacent characters with a non-breaking space (U+202F NARROW NO-BREAK
SPACE) or step (U+1BCA2 SHORTHAND FORMAT DOWN STEP or U+1BCA3 SHORTHAND FORMAT
UP STEP).

### Overlapping characters

Overlap trees are supported up to a width of 2, a depth of 2, and a breadth of
2. (See [Unicode Technical Note #37](
https://www.unicode.org/notes/tn37/utn37-1-duployan.pdf), section “Shorthand
Control level of implementation” for what those terms mean.) These are the
maximums: not all letters have values that high. The font does not support
U+1BCA1 SHORTHAND FORMAT CONTINUING OVERLAP followed by U+1BCA0 SHORTHAND FORMAT
LETTER OVERLAP, which is syntactically valid but unattested.

Certain symbols have limited support for overlaps as used in Romanian:

* U+003C LESS-THAN SIGN
* U+003D EQUALS SIGN
* U+003E GREATER-THAN SIGN
* U+00D7 MULTIPLICATION SIGN

Secants are applied to their preceding letters, except for initial secants,
which are applied to their following letters.

### Other features

The vertical positioning of a stenogram is based on its first visually prominent
character, which is placed on the baseline. Different modes of Duployan have
different conventions for vertical positioning, but the precise positioning is
not significant.

Most letters support shading via U+1BC9D DUPLOYAN THICK LETTER SELECTOR. It is
unsupported for some letters for which shading is not attested. Although shading
is attested for orienting letters, that is not yet supported.

Some common punctuation marks may be circled in Romanian to disambiguate them
from similar-looking letters. Add U+20DD COMBINING ENCLOSING CIRCLE after the
punctuation for this circle.

Digits support fractions (with U+2044 FRACTION SLASH), superscripts (with the
OpenType feature 'sups'), and subscripts (with 'subs').

## Languages and modes

Rawnd Musmus Duployan supports all modes mentioned in the Duployan Unicode
proposals:

* Duployé’s original mode (French)
* Pernin (English)
* Perrault-Duployan (English)
* Romanian Duployan
* Sloan-Duployan (English)
* Stenographie Duployé codifiée (French)
* Wawa Shorthand (primarily Chinook Jargon, English, and French, but also Comox
  (Sliammon), Halkomelem, Latin, Lillooet, Okanagan, Sechelt, Shuswap, Squamish,
  and Thompson)

The character set available in Unicode is not actually sufficient for any of
these modes, but this font supports what it can, with a few non-Unicode
extensions for Chinook Jargon.

## Technical caveats

Rawnd Musmus Duployan does not work in all applications. For proper shaping, it
requires HarfBuzz 8.1.0 or later, which is used in all major browsers on all
operating systems, and for most applications on Linux. Even in some applications
that use HarfBuzz, though, it is broken to varying degrees. If the main font
does not work, use Rawnd Musmus Duployan Uncow as a fallback.

In particular, long strings are liable to be rendered wrong. The glyphs will not
be cursively connected but will instead overlap each other in a semilegible
jumble. This is because HarfBuzz has an internal limit of how many operations it
will take for a buffer before giving up. Splitting long paragraphs into multiple
paragraphs works around the problem. Inserting a character not supported by the
font in the middle of paragraph also works.

Rendering any significant amount of text in the main font is noticeably slow. A
web page with around 1000 words in Duployan can take over 30 seconds to load.
