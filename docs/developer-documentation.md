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

To build Noto Sans Duployan, run:

```sh
python3 -m venv venv
. venv/bin/activate
pip install --no-deps -r requirements.txt
make NOTO=1
```

That will produce four fonts:

* fonts/NotoSansDuployan/unhinted/ttf/NotoSansDuployan-Regular.ttf
* fonts/NotoSansDuployan/unhinted/ttf/NotoSansDuployan-Bold.ttf
* fonts/NotoSansDuployan/unhinted/otf/NotoSansDuployan-Regular.otf
* fonts/NotoSansDuployan/unhinted/otf/NotoSansDuployan-Bold.otf

To only build one weight, append `STYLES=Regular` or `STYLES=Bold`.

To only build fonts with cubic Bézier curves, append `SUFFIXES=otf`.

## Testing

The prerequisites are:

* HarfBuzz 8.1.0 or later

To test the fonts, run:

```sh
python3 -m venv venv
. venv/bin/activate
pip install --no-deps -r dev-requirements.txt
make NOTO=1 check
```

`STYLES` and `SUFFIXES` are also respected here.

To measure coverage and check that it is above the target percentage,
add `COVERAGE=1` to both make commands for building and testing.

## Understanding the code

The [width system](width-system.md) has documentation.
Some of the code has docstrings.
