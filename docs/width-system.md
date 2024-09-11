<!--
Copyright 2022-2024 David Corbett

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

# The width system

This font encodes Duployan letters’ advance widths not with glyph advances
but with lots of invisible marker glyphs.
These markers encode each letter’s advance width.
They are added together to find the advance width of each stenogram.

## Background and motivation

In most fonts, each spacing character has a certain advance width which
determines where the following glyph is drawn.
In fonts that use cursive attachment, the position of the following glyph
instead depends on the positions of the cursive anchor points of the two glyphs.
The overall width of a cursively connected sequence is the sum of:

* The width from the starting side of the initial cursive glyph to its cursive
  exit point
* The widths, for all medial cursive glyphs, from their cursive entry points to
  their cursive exit points
* The width from the final glyph’s cursive entry point to its ending side

The starting side bearing of the whole sequence depends only on the first glyph.
Its ending side bearing depends only on the last glyph.
The medial glyphs’ advance widths and side bearings are irrelevant.
This is a problem if a sequence is not written purely in one direction.
This is rare, but it can occur, for example, in Arabic script in ⟨ہے⟩,
whose starting (right) side bearing depends on the final (leftmost) glyph,
because the final glyph has a long rightwards swash.
However, that is pretty much the only Arabic glyph with multidirectional
behavior, and it only occurs at the end of a cursive sequence,
and the swash is not strictly necessary for legible text anyway,
so it is not such a big deal.

It is a big deal in Duployan.
Duployan is a left-to-right script,
but many letters are written from right to left.
A stenogram (cursively connected sequence) like “𛰅𛱇𛰊” (<i>keg</i>)
is entirely written from right to left.
OpenType’s built-in width system would place the following non-cursive glyph
to the left of the final (leftmost) glyph, overlapping the middle of the
stenogram.

This font therefore eschews OpenType’s width system for cursive glyphs
and uses its own.

## Introduction

A width is a horizontal distance.
Vertical distances do not matter.

The point of the width system is to find a stenogram’s side bearings.
It does not find them directly; instead, it finds the stenogram’s left and right
bound widths.
These are calculated relative to the initial glyph’s starting point.
The right bound width is the sum of the right side bearing and the stenogram’s bounding box width.
That means that, for a normal left-to-right stenogram, the left bound width will
be a small negative number and the right bound width will be a large positive
number, getting larger the more letters there are.

At runtime, the font adds some invisible marker glyphs to the glyph stream
encoding all relevant width information.
The widths of all the glyphs in a stenogram are added,
and the left and right sums become the left and right bound widths.
A 'dist' lookup adds space as indicated by these marker glyphs.

## Types of width

Four kinds of width are relevant to this font.
Each has a code, which is used in glyph names.

A glyph’s right bound width (`rdx`) is measured from its cursive entry point to
the right side of its bounding box.
For example, U+1BC08 DUPLOYAN LETTER D is a long horizontal line.
In the regular font, it is a stroke 1000 units long plus two semicircular caps
with 35-unit radii.
Its right bound width is therefore 1035 units: the width of the stroke plus the
right cap.

A glyph’s left bound width (`ldx`) is measured from its cursive entry point to
the left side of its bounding box.
It is usually negative,
since the cursive entry point generally appears within the bounding box.
U+1BC08 DUPLOYAN LETTER D’s left bound width is −35.

A glyph’s entry width (`idx`) is measured from its overlap entry point to its
cursive entry point.
It is negative for a left-to-right glyph and positive for a right-to-left glyph.
U+1BC08 DUPLOYAN LETTER D’s entry width is −250 because its overlap entry point
is one quarter along the stroke.
Overlaps are a non-default form of cursive connection controlled by U+1BCA0
SHORTHAND FORMAT LETTER OVERLAP and U+1BCA1 SHORTHAND FORMAT CONTINUING OVERLAP.
They have no analogue in other scripts.

A glyph’s anchor widths (`adx`) are measured from its cursive entry point to
each mark anchor point.
Each glyph has 7 anchor widths.
The font has 8 relevant anchors (mark positioning and cursive), but each base
glyph uses the same x coordinate for its above- and below-base anchor points, so
the above- and below-base anchors are represented by the same anchor width
glyph.

## Number encoding

Widths are reified as invisible marker glyphs.
They are encoded as 7-digit numbers in base 4.
For example, 1035 is 100023<sub>4</sub>.

Negative numbers use the method of complements.
For example, −1 is 3333333<sub>4</sub> and −35 is 3333131<sub>4</sub>.

The invisible marker glyphs are named based on the width type and numeric value.
The format is <code>\_.<var>type</var>.<var>value</var>e<var>place</var></code>.
The least significant digit comes first.
For example, a right bound width marker (`rdx`) for 1035 (100023<sub>4</sub>)
would be encoded as the glyph sequence `_.rdx.3e0 _.rdx.2e1 _.rdx.0e2 _.rdx.0e3
_.rdx.0e4 _.rdx.1e5 _.rdx.0e6`.

Certain common widths get markers for the entire number.
Their glyph name format is
<code>\_.<var>type</var>.<var>number\_in\_base\_10</var></code>.
These are subsequently expanded into the canonical format of one digit per
glyph.
This is just an optimization: if enough glyphs share the same width, it saves
space for each glyph’s substitution rule to output a single glyph rather than
seven, at the cost of one additional rule in another lookup.

## The algorithm (simplified)

Every cursive glyph is replaced by itself preceded by a `_.START` glyph and
followed by its entry, left bound, right bound, and multiple anchor widths, and
an `_.END` glyph.
The order of the anchor widths is arbitrary but consistent between glyphs.
The values of the widths are calculated at build time:
there is no way to get this information at runtime.

If there are any width number glyphs, they are expanded into width digit glyphs.

Any `_.END` glyphs that precede other `_.END` glyphs within the same stenogram
are obviously not at the end, so they are removed.

The numbers are added using a full adder.
A full adder adds three digits (two width digits and a carry digit), outputting
a new width digit and a carry digit.
The new width digit overwrites the second addend.
The carry digit is a special glyph, `_.c`.
It is optional on both sides of the adder.
The absence of `_.c` represents a carry of 0.
`_.c` is inserted after the new width digit.

Any `_.START` glyphs that follow other `_.START` glyphs within the same
stenogram are obviously not at the start, so they are removed.

`_.START` is replaced with itself preceded by a left bound width marker sequence
encoding the number 0 with fully capitalized glyph names: `_.LDX.0E0` and so on.
This is just a placeholder.

By this point, the original widths have been overwritten.
The first glyph’s are unchanged,
but the second’s are the sums of the first two glyphs’ original widths,
the third’s are the sums of the first three glyphs’ original widths,
and so on.
The last glyph’s overwritten widths represent the widths for the whole
stenogram,
and they are therefore substituted with new markers that use capital letters
to indicate their relevance to subsequent steps of the algorithm.
For example, `_.rdx.2e3` after the final letter becomes `_.RDX.2E3`
and `_.adx.2e3` becomes `_.ADX.2E3`.

The left bound width markers are slightly different:
`_.ldx.2e3` after the final letter becomes the partially capitalized
`_.ldx.2E3`.
These are then copied, with fully capitalized glyph names,
over the placeholder left bound width markers that precede `_.START`.

Entry width markers do not get capitalized glyphs.
They are only used to calculate anchor widths
and by this point have fulfilled their purpose.

The width glyphs with fully capitalized names represent actual widths to add in
a single positioning lookup.
For example, `_.RDX.2E3` represents a width of 2 × 4<sup>3</sup>, i.e. 128,
so a 'dist' lookup adds 128 units to it.
Left bound widths are treated as their complements:
'dist' would add 64 units for `_.LDX.2E3`, i.e. (3 − 2) × 4<sup>3</sup>.
Anchor widths are treated as their opposites:
'dist' would add −128 units for `_.ADX.2E3`.

High values for the most significant digits indicate negative numbers.
They are interpreted as the above values plus (or, for right bound widths,
minus) <var>base</var><sup><var>places</var></sup>.
High values are those in the top half of possible digit values;
for base 4, that means 2 and 3.
For example, `_.RDX.2E6` gets −8192 units.
`_.LDX.1E6` also gets −8192 units, because 1 is the complement of 2.

The least significant digits of the left and right bound widths have 85 units
added to them to account for the side bearings;
thus `_.LDX.1E0` gets 88 units and `_.RDX.1E0` gets 86 units.

## Design rationales

The base is arbitrary, except it must be even.
The base must be even so that the width system can detect the sign of a number
based only on its most significant digit.
With an odd base, it would have to check more digits,
which would be more complex.

The number of digit places is also arbitrary.
The higher the base, the fewer places are necessary, which means fewer
substitution rules and a smaller GSUB table.
The lower the base, the fewer pairs of digits need to have their sums
precalculated, which means fewer substitution rules and a smaller GSUB
table.
Both are efficient and inefficient in different ways.
Base 4 with 7 places is a good trade-off.

The least significant digit comes first because that is the first digit a full
adder considers.
The full adder cannot use reverse chaining contextual single substitutions;
if it did, though, the least significant digit would have to come last.

In order to add two widths of the same type
(and, for anchor widths, the same anchor),
whose glyphs are separated by many other width glyphs,
the substitution rule needs to know how many glyphs separate them.
That is why numbers have a constant number of places.

A carry value of 0 is represented by the absence of a carry glyph.
This makes generating the rules more complex because they do not all involve the
same number of glyphs.
Even so, representing it implicitly generates fewer glyphs at runtime,
which is important because HarfBuzz’s `HB_BUFFER_MAX_LEN_FACTOR` and
`HB_BUFFER_MAX_LEN_MIN` constants limit how much the buffer can grow.

The side bearings are handled in the least significant digits
because it simplifies the mental math required for debugging.
They could just as well have been handled in any other place,
or even a combination of places,
as long as the extra width always totaled 85.

As described [above](#background-and-motivation), side bearings depend on the
initial and final cursive glyphs in the usual OpenType width system.
Cursive glyphs have positive advance widths, which means the final
cursive glyph’s advance width would be added to the total calculated right bound
width.
To avoid that problem, an invisible zero-width cursive glyph named `_.RDX.*E0`
is added at the end of the stenogram.
That is half the purpose of `_.RDX.*E0`;
the other is to add space after the final letter.
Similarly, `_.START` is an invisible zero-width cursive glyph added at the start
of the stenogram that suppresses the left side bearing of the initial letter.
The point of giving these glyphs advance widths that are never actually used is
to make debugging substitution rules more convenient in FontForge’s UI.
Since the `_.START` and `_.RDX.*E0` glyphs have to exist anyway,
it does not make the font too much more complex.

## Caveats

Fixed width numbers are subject to overflow.
The range is \[−2000000<sub>4</sub>, 1333333<sub>4</sub>\]
(in decimal, \[−8192, 8191\]).
Any stenogram wider than that will get the wrong width.

The width system is ponderous and slow.
It causes [user-visible problems](user-documentation.md#technical-caveats) with
rendering times and glyph positions.

The width system’s lookups take up a lot of space.
They add about half a megabyte to the font’s file size
and they make it hard to find space for lookups for other systems.
