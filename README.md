<!--
Copyright 2024 David Corbett

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

# Rawnd Musmus Duployan

An OpenType Unicode font for Duployan shorthand.

Duployan is a shorthand used for French, English, Romanian, Chinook Jargon, and
many other languages. Rawnd Musmus Duployan is a technical proof of concept for
all of Duployan’s features that is also suitable for practical use.

## Installation

The font has not been released yet. Until then, you can download a development
build from the latest [workflow run](
https://github.com/dscorbett/duployan-font/actions) or [the alpha version](
https://github.com/dscorbett/duployan-test/tree/gh-pages/assets/fonts) used by
the font demo.

[The font demo](https://dscorbett.github.io/duployan-test/) is an online
keyboard app that lets you type in Duployan. It is useful for testing the font
without installing it locally and for use as a Duployan IME.

The third-party article [“How to get the Chinuk Pipa font”](
https://kaltashwawa.ca/2021/12/26/how-to-get-the-chinuk-pipa-font/) has further
advice about installing the font that might be helpful.

## Features

Rawnd Musmus Duployan has full support for Unicode Duployan:

* All characters in the Duployan and Shorthand Format Controls blocks
* Contextual forms and cursive joining
* Shaded characters
* Overlapping characters
* Non-Duployan characters used with Duployan, such as digits and punctuation

There are [multiple variants](docs/variants.md) of the font, including:

* Rawnd Musmus Duployan: the main font
* Rawnd Musmus Duployan Uncow: the font with cursive joining removed
* Noto Sans Duployan: the font with modifications for the Noto font project

See [the user guide](docs/user-documentation.md) for more information.

## Building

See [the developer documentation](docs/developer-documentation.md) for how to
build the fonts from source.
