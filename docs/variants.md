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

# Font variants

The Rawnd Musmus Duployan font family has multiple variants:

* Rawnd Musmus Duployan
* Rawnd Musmus Duployan Uncow
* Noto Sans Duployan
* Noto Sans Duployan Unjoined
* Ilo Snas Duployan
* Ilo Snas Duployan Uncow

By default, the font supports cursive joining and contextual forms. The
Uncow/Unjoined fonts remove those features for compatibility with software in
which the main fonts do not work.

The Noto variants exclude certain characters which are inappropriate or
unnecessary for inclusion in the Noto project’s Duployan font. The canonical
Noto Sans Duployan is available from [the Noto Duployan repository](
https://github.com/notofonts/duployan/releases) or from [Google Fonts](
https://fonts.google.com/noto/specimen/Noto+Sans+Duployan). Noto Sans Duployan
Unjoined is not an official Noto font.

Ilo Snas Duployan adds some private use characters to make testing more
convenient. They are only appropriate for testing the fonts during development.
Their PUA character assignments are unstable and may change at any time.

Each variant comes in both regular and bold, and both OTF and TTF.

## Future variants

More variants could exist in the future.

* Ilo Komtaks Duployan: The font with arbitrary user customizations, supported
  by a CLI with more fine-grained control than [the `CHARSET` variable](
  developer-documentation.md#advanced-build-options)
* Ilo Shabon Duployan: If you want to pay me for a custom feature that would
  normally be out of scope
* Gol Musmus Duployan: A font with no bugs that works on all platforms; a
  perfect simulacrum of handwriting; the ultimate goal
