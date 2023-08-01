<!--
Copyright 2022 Google LLC
Copyright 2023 David Corbett

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

## The font

Noto Sans Duployan is an unmodulated (“sans-serif”) font for many modes of
the Duployan shorthand script. These modes include
Duployé’s original mode (French),
stenographie Duployé codifiée (French),
Pernin (English),
Perrault-Duployan (English),
Sloan-Duployan (English),
a Romanian adaptation,
and Wawa Shorthand (primarily Chinook Jargon, English, and French,
but also Halkomelem, Latin, Okanagan, Sechelt, Shuswap, and Thompson).
The font is available in regular and bold.
It is not a variable font.

## The encoding

Noto Sans Duployan follows <i>The Unicode Standard</i>.
However, the standard says very little about Duployan.

Most of the details of the encoding are described in
[Unicode Technical Note #37](
https://www.unicode.org/notes/tn37/utn37-1-duployan.pdf).
Unicode technical notes are not official Unicode documents in any way,
so while this font does generally follow its recommendations,
many details are different.
The font’s encoding model is graphetic whereas the technical note tends towards
the phonetic side.

The easiest way to understand the encoding model is to try some typing some
stenograms.
With orienting vowels, it is not always obvious which one to use.
If U+1BC41 DUPLOYAN LETTER A looks wrong, try U+1BC42 DUPLOYAN LETTER SLOAN OW,
and vice versa.
If U+1BC46 DUPLOYAN LETTER I looks wrong, try U+1BC47 DUPLOYAN LETTER E, and
vice versa.
The syntax of overlap sequences is exactly as defined in the technical note.
Everything else should be clear to a user who knows Duployan.

## Limitations

Noto Sans Duployan requires HarfBuzz 8.1.0 or later.
It does not work in other shaping engines.

Duployan is unusual in that, although it is a left-to-right script,
certain specific stenograms can be effectively written from right to left.
OpenType does not handle this well, and the font’s workarounds are inefficient.
Rendering any significant amount of text in the font is noticeably slow.
A web page with around 1000 words in Duployan can take over 30 seconds to load.

For the same reason, long strings are liable to be rendered wrong.
The glyphs will not be cursively connected but will instead overlap each other
in a semilegible jumble.
This is because HarfBuzz has an internal limit of how many operations it will
take on a buffer before giving up.
Splitting long paragraphs into multiple paragraphs works around the problem.

Overlap trees are supported up to a width of 2, a depth of 2, and a breadth of
2.
(See [Unicode Technical Note #37](
https://www.unicode.org/notes/tn37/utn37-1-duployan.pdf), section “Shorthand
Control level of implementation” for what those terms mean.)
These are the maximums: not all letters have values that high.
The font does not support U+1BCA1 SHORTHAND FORMAT CONTINUING OVERLAP followed
by U+1BCA0 SHORTHAND FORMAT LETTER OVERLAP, which is syntactically valid but
unattested.

The Unicode encoding of Duployan is incomplete and underdefined.
It does not fully support any of the modes the code chart implies it supports.
It is almost adequate for Chinook Jargon, but not much else.
Noto Sans Duployan, as with any Duployan Unicode font, is therefore unsuitable
for most Duployan purposes.

