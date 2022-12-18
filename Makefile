# Copyright 2018-2019, 2022 David Corbett
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

SHELL=/bin/bash

STYLES = Regular Bold
ifdef NOTO
    FONT_FAMILY_NAME = NotoSansDuployan
    VERSION = 3.001
    RELEASE =
    CHECK_ARGS = --incomplete
    override NOTO = --noto
else
    FONT_FAMILY_NAME = Duployan
    VERSION = 1.0
    RELEASE =
endif
SUFFIXES = otf ttf
FONTS = $(foreach suffix,$(SUFFIXES),$(addprefix fonts/$(suffix)/unhinted/instance_$(suffix)/$(FONT_FAMILY_NAME)-,$(addsuffix .$(suffix),$(STYLES))))

BUILD = sources/build.py $(NOTO) $(RELEASE) --version $(VERSION)
UNIFDEF = unifdef -$(if $(NOTO),D,U)NOTO -t

.PHONY: all
all: $(FONTS)

.PHONY: otf
otf: $(filter %.otf,$(FONTS))

.PHONY: ttf
ttf: $(filter %.ttf,$(FONTS))

fonts/otf/unhinted/instance_otf/$(FONT_FAMILY_NAME)-Regular.otf: sources/Duployan.fea sources/*.py
	$(BUILD) --fea <($(UNIFDEF) $<) --output $@

fonts/otf/unhinted/instance_otf/$(FONT_FAMILY_NAME)-Bold.otf: sources/Duployan.fea sources/*.py
	$(BUILD) --bold --fea <($(UNIFDEF) $<) --output $@

$(addprefix fonts/ttf/unhinted/instance_ttf/$(FONT_FAMILY_NAME)-,$(addsuffix .ttf,$(STYLES))): fonts/ttf/unhinted/instance_ttf/%.ttf: fonts/otf/unhinted/instance_otf/%.otf
	mkdir -p "$$(dirname "$@")"
	sources/otf2ttf.py --output "$@" --overwrite "$<"

.PHONY: clean
clean:
	$(RM) -r $(FONTS) tests/failed

.PHONY: $(addprefix check-,$(FONTS))
$(addprefix check-,$(FONTS)): check-%: %
	tests/run-tests.py $(CHECK_ARGS) $< tests/*.test

.PHONY: $(addprefix fontbakery-,$(SUFFIXES))
$(addprefix fontbakery-,$(SUFFIXES)): fontbakery-%: %
	fontbakery check-notofonts --auto-jobs --configuration <($(UNIFDEF) tests/fontbakery-config.toml) --full-lists $(filter %.$*,$(FONTS))

.PHONY: mypy
mypy:
	mypy get-old-requirements.py sources tests

.PHONY: check
check: $(addprefix check-,$(FONTS)) $(addprefix fontbakery-,$(SUFFIXES)) mypy

.PHONY: hb-shape
hb-shape:
ifndef HB_VERSION
	$(error HB_VERSION must be set)
endif
	mkdir -p .hb
	cd .hb && \
	if [ ! -f harfbuzz-$$HB_VERSION/util/hb-shape ]; \
	then \
		if [ ! -d harfbuzz-$$HB_VERSION ]; \
		then \
			curl -L https://github.com/harfbuzz/harfbuzz/releases/download/$$HB_VERSION/harfbuzz-$$HB_VERSION.tar.xz \
			| tar -xJ; \
		fi && \
		cd harfbuzz-$$HB_VERSION && \
		./configure && \
		$(MAKE) -C util lib hb-shape; \
	fi

.PHONY: $(patsubst %.in,%.txt,$(wildcard *requirements.in))
$(patsubst %.in,%.txt,$(wildcard *requirements.in)): %requirements.txt: %requirements.in
	pip-compile --allow-unsafe --no-emit-index-url --no-emit-trusted-host --quiet --resolver backtracking --upgrade $<
	printf '%s\n%s\n' "$$(sed -n '1,/^$$/p' $<)" "$$(cat $@)" >$@
	-git --no-pager diff $@
