<!--
Copyright 2022 Google LLC
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

# Developer documentation

## Building

The prerequisites are:

* GNU Make
* Python 3.11 or later
* FontForge 20190801 with Python 3 extensions
* unifdef

To build the basic default set of fonts, run:

```sh
python3 -m venv venv
. venv/bin/activate
pip install --no-deps -r requirements.txt
make
```

That will produce four fonts:

* fonts/Duployan/unhinted/otf/Duployan-Bold.otf
* fonts/Duployan/unhinted/otf/Duployan-Regular.otf
* fonts/Duployan/unhinted/ttf/Duployan-Bold.ttf
* fonts/Duployan/unhinted/ttf/Duployan-Regular.ttf

See .github/workflows/main.yml for how to get the prerequisites on Ubuntu. The
steps should be analogous on other platforms. Getting FontForge to build
correctly is a challenge.

## Testing

The additional prerequisite for testing is:

* HarfBuzz 8.1.0 or later

To test the fonts, run:

```sh
python3 -m venv venv
. venv/bin/activate
pip install --no-deps -r dev-requirements.txt
make check
```

Alternatively, push a commit and wait for GitHub Actions to run CI.

## Advanced build options

Makefile has many available targets. The main ones are:

* `all`: Build the fonts. This is the default target.
* A specific font path ending with `.otf` or `.ttf`: Build one font. (This might
  build other fonts too; see below for a discussion of vertical metrics.)
* `clean`: Remove the fonts and other build leftovers.
* `check`: Run various tests.
* `hb-shape` and `hb-view`: Build HarfBuzz’s command-line utilities.
* `requirements.txt` and `dev-requirements.txt`: Update `*requirements.txt`
  based on `*requirements.in`.
* `sync-noto`: Prepare to sync the downstream Noto repository with changes in
  this repository. (Some manual work is still required.)

These targets are affected by various variables:

* `CHARSET`: Which [character set variant](variants.md) to build: `standard` for
  Duployan, `noto` for Noto Sans Duployan, or `testing` for Duployan Test.
* `WEIGHTS`: A space-separated list of weights to build. The only valid weights
  are `Regular` and `Bold`. The default is both.
* `SUFFIXES`: A space-separated list of OpenType variants to build. The only
  valid variants are `otf` and `ttf`. The default is both.
* `NOTO`: If defined, build a Noto font.
* `UNJOINED`: If defined, build an Unjoined font.
* `FONT_FAMILY_NAME`: The name of the font.
* `VERSION`: The base version number. It is automatically augmented with various
  affixes.
* `RELEASE`: If defined, this is a release build. This only affects the version
  number.
* `TALL_TEXT`: A string that helps determine the common vertical metrics across
  all the fonts.
* `COVERAGE`: Whether to measure code coverage when building the fonts and
  whether to enforce a minimum coverage percentage when testing.
* `HB_VERSION`: The version of HarfBuzz to build when building its command-line
  utilities.

All the fonts for a given character set variant should share the same vertical
metrics. When building the fonts, preliminary versions of all of the fonts with
that character set variant are built, and the final fonts’ vertical metrics are
set to the most extreme values of all of them. If `TALL_TEXT` is defined, the
vertical metrics are also modified to make sure the bounding box of `TALL_TEXT`
falls within every font’s vertical metrics. By default, it is defined with a
string that is suitable for Chinook Jargon and reasonable for other modes.

## How it works

Most of the build is done by a Python script, which has some documentation in
docstrings and comments. At a high level, this is what is does:

1. Using the specified character set, decide what code points will go in 'cmap'.
  Each code point gets a schema. A schema is a build-time abstraction of a
  glyph.
1. Send the schemas through a sequence of phases. A phase is an abstraction of a
  sequence of OTL lookups (usually GSUB). A GSUB phase can add or remove schemas
  from the set of current schemas, corresponding to the set of glyphs that can
  exist at that point in OTL.
1. Using FontForge, draw the schemas by expanding their strokes, and convert
  them to glyphs. Schemas that behave and look the same up to this point are
  merged and get the same glyph.
1. Send the schemas through another sequence of phases. These phases have access
  to glyphs and can create lookups that depend on their exact bounding boxes and
  anchor points. (Bounding boxes in particular are necessary for [the width
  system](width-system.md).) Schemas created in these phases are not subject to
  later merging.
1. Add mark attachment GPOS rules.
1. Compile the font with fontTools.
