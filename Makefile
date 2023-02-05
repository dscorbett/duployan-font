# Copyright 2018-2019, 2022-2023 David Corbett
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
FONTS = $(foreach suffix,$(SUFFIXES),$(addprefix fonts/$(FONT_FAMILY_NAME)/unhinted/$(suffix)/$(FONT_FAMILY_NAME)-,$(addsuffix .$(suffix),$(STYLES))))

BUILD = sources/build.py $(NOTO) $(RELEASE) --version $(VERSION)
UNIFDEF = unifdef -$(if $(NOTO),D,U)NOTO -t

.PHONY: all
all: $(FONTS)

.PHONY: otf
otf: $(filter %.otf,$(FONTS))

.PHONY: ttf
ttf: $(filter %.ttf,$(FONTS))

fonts/$(FONT_FAMILY_NAME)/unhinted/otf/$(FONT_FAMILY_NAME)-Regular.otf: sources/Duployan.fea sources/*.py
	$(BUILD) --fea <($(UNIFDEF) $<) --output $@

fonts/$(FONT_FAMILY_NAME)/unhinted/otf/$(FONT_FAMILY_NAME)-Bold.otf: sources/Duployan.fea sources/*.py
	$(BUILD) --bold --fea <($(UNIFDEF) $<) --output $@

$(addprefix fonts/$(FONT_FAMILY_NAME)/unhinted/ttf/$(FONT_FAMILY_NAME)-,$(addsuffix .ttf,$(STYLES))): fonts/$(FONT_FAMILY_NAME)/unhinted/ttf/%.ttf: fonts/$(FONT_FAMILY_NAME)/unhinted/otf/%.otf
	mkdir -p "$$(dirname "$@")"
	sources/otf2ttf.py --output "$@" --overwrite "$<"

subset-fonts/%.subset-glyphs.txt: fonts/%
	mkdir -p "$$(dirname "$@")"
	ttx -o - -q -t GlyphOrder "$<" \
	| grep '<GlyphID ' \
	| cut -f4 -d'"' \
	| grep '^[^_]\|^_u1BC9D\.dtls$$' \
	| grep -v '^u1BC7[0-7]\..*\.' \
	>"$@"

subset-fonts/%: fonts/% subset-fonts/%.subset-glyphs.txt
	pyftsubset \
		--glyph-names \
		--glyphs-file="$(word 2,$^)" \
		--layout-features+=subs,sups \
		--layout-features-=curs,rclt \
		--no-layout-closure \
		--output-file="$@" \
		--passthrough-tables \
		"$<"

.PHONY: clean
clean:
	$(RM) -r $(FONTS) $(addprefix subset-,$(FONTS)) tests/failed

.PHONY: $(addprefix check-,$(FONTS))
$(addprefix check-,$(FONTS)): check-%: %
	tests/run-tests.py $(CHECK_ARGS) $< tests/*.test

.PHONY: $(addprefix check-subset-,$(FONTS))
$(addprefix check-subset-,$(FONTS)): check-subset-%: subset-%
	tests/run-tests.py $(CHECK_ARGS) $< tests/*.subset-test

.PHONY: check-subset
check-subset: $(addprefix check-subset-,$(FONTS))

.PHONY: $(addprefix fontbakery-,$(SUFFIXES))
$(addprefix fontbakery-,$(SUFFIXES)): fontbakery-%: %
	fontbakery check-notofonts --auto-jobs --configuration <($(UNIFDEF) tests/fontbakery-config.toml) --full-lists $(filter %.$*,$(FONTS))

.PHONY: fontbakery
fontbakery: $(addprefix fontbakery-,$(SUFFIXES))

.PHONY: mypy
mypy:
	mypy get-old-requirements.py sources tests

.PHONY: check
check: $(addprefix check-,$(FONTS)) check-subset fontbakery mypy

.hb:
ifndef HB_VERSION
	$(error HB_VERSION must be set)
endif
	mkdir -p .hb

.hb/harfbuzz-$(HB_VERSION): .hb
	cd $< && \
	curl -L https://github.com/harfbuzz/harfbuzz/releases/download/$(HB_VERSION)/harfbuzz-$(HB_VERSION).tar.xz \
	| tar -xJ

.hb/harfbuzz-$(HB_VERSION)/util/Makefile: .hb/harfbuzz-$(HB_VERSION)
	cd $< && \
	./configure
	touch -c $@

.hb/harfbuzz-$(HB_VERSION)/util/hb-%: .hb/harfbuzz-$(HB_VERSION)/util/Makefile
	$(MAKE) -C $$(dirname $<) lib $$(basename $@)

.PHONY: hb-shape hb-view
hb-shape hb-view: hb-%: .hb/harfbuzz-$(HB_VERSION)/util/hb-%

.PHONY: $(patsubst %.in,%.txt,$(wildcard *requirements.in))
$(patsubst %.in,%.txt,$(wildcard *requirements.in)): %requirements.txt: %requirements.in
	pip-compile --allow-unsafe --no-emit-index-url --no-emit-trusted-host --quiet --resolver backtracking --upgrade $<
	printf '%s\n%s\n' "$$(sed -n '1,/^$$/p' $<)" "$$(cat $@)" >$@
	-git --no-pager diff $@
