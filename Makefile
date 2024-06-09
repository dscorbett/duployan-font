# Copyright 2018-2019, 2022-2024 David Corbett
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

.DELETE_ON_ERROR:

SHELL=/bin/bash

VALID_STYLES = Regular Bold
STYLES = $(VALID_STYLES)
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
VALID_SUFFIXES = otf ttf
SUFFIXES = $(VALID_SUFFIXES)
TALL_TEXT = 𛰋𛱚𛰚‌𛰆𛱁𛰚𛰊
FONTS = $(foreach suffix,$(SUFFIXES),$(addprefix fonts/$(FONT_FAMILY_NAME)/unhinted/$(suffix)/$(FONT_FAMILY_NAME)-,$(addsuffix .$(suffix),$(STYLES))))
INTERMEDIATE_PREFIX = tmp-
INTERMEDIATE_FONTS = $(addprefix $(INTERMEDIATE_PREFIX),$(FONTS))

BUILD = PYTHONPATH="sources:$(PYTHONPATH)" sources/build.py $(NOTO) $(RELEASE) --version $(VERSION)
RUN_TESTS = PYTHONPATH="sources:$(PYTHONPATH)" tests/run-tests.py
UNIFDEF = unifdef -$(if $(NOTO),D,U)NOTO -t

.PHONY: all
all: $(FONTS)

.PHONY: otf
otf: $(filter %.otf,$(FONTS))

.PHONY: ttf
ttf: $(filter %.ttf,$(FONTS))

subset-fonts/%.subset-glyphs.txt: fonts/%
	mkdir -p "$$(dirname "$@")"
	ttx -o - -q -t GlyphOrder "$<" \
	| grep '<GlyphID ' \
	| cut -f4 -d'"' \
	| grep '^\(_[^.]*_\(\.\|$$\)\|[^_][^.]*_\.[^.]*\.\|\([^_][^.]*[^_]\(\.[^.]*\)\?\|\.[^.]*\)\(\._[0-9A-F][1-9A-F]*\)\?$$\)' \
	>"$@"

subset-fonts/%: fonts/% subset-fonts/%.subset-glyphs.txt
	pyftsubset \
		--glyph-names \
		--glyphs-file="$(word 2,$^)" \
		--layout-features="$$(PYTHONPATH="sources:$$PYTHONPATH" python3 -c 'from utils import SUBSET_FEATURES; print(",".join(SUBSET_FEATURES))')" \
		--no-layout-closure \
		--notdef-outline \
		--output-file="$@" \
		--passthrough-tables \
		"$<"

dummy-%: ;

$(FONTS): $(INTERMEDIATE_FONTS)
	mkdir -p "$$(dirname "$@")"
	sources/copy_metrics.py --text $(TALL_TEXT) $@ $(INTERMEDIATE_PREFIX)$@ $(filter-out $(INTERMEDIATE_PREFIX)$@,$^)

%.otf: sources/Duployan.fea $(shell find sources -name '*.py') | dummy-%
	$(BUILD) $(BOLD_ARG) --fea <($(UNIFDEF) $<) --output $@

%-Bold.otf: BOLD_ARG=--bold

define MAKE_TTF
    mkdir -p "$$(dirname "$@")"
    sources/otf2ttf.py --output "$@" --overwrite "$<"
endef

%.ttf: %.otf
	$(MAKE_TTF)

$(addprefix $(INTERMEDIATE_PREFIX)fonts/$(FONT_FAMILY_NAME)/unhinted/ttf/$(FONT_FAMILY_NAME)-,$(addsuffix .ttf,$(STYLES))): $(INTERMEDIATE_PREFIX)fonts/$(FONT_FAMILY_NAME)/unhinted/ttf/%.ttf: $(INTERMEDIATE_PREFIX)fonts/$(FONT_FAMILY_NAME)/unhinted/otf/%.otf
	$(MAKE_TTF)

.PHONY: clean
clean:
	$(RM) -r $(FONTS) $(INTERMEDIATE_FONTS) $(addprefix subset-,$(FONTS)) tests/failed

.PHONY: $(addprefix check-,$(FONTS))
$(addprefix check-,$(FONTS)): check-%: %
	$(RUN_TESTS) $(CHECK_ARGS) $< tests/*.test

.PHONY: check-shaping
check-shaping: $(addprefix check-,$(FONTS))

.PHONY: $(addprefix check-subset-,$(FONTS))
$(addprefix check-subset-,$(FONTS)): check-subset-%: subset-%
	$(RUN_TESTS) $(CHECK_ARGS) $< tests/*.subset-test

.PHONY: check-subset
check-subset: $(addprefix check-subset-,$(FONTS))

.PHONY: $(addprefix fontbakery-,$(SUFFIXES))
$(addprefix fontbakery-,$(SUFFIXES)): fontbakery-%: %
	fontbakery check-notofonts --auto-jobs --configuration <($(UNIFDEF) tests/fontbakery-config.toml) --full-lists --skip-network $(filter %.$*,$(FONTS))

.PHONY: fontbakery
fontbakery: $(addprefix fontbakery-,$(SUFFIXES))

.PHONY: mypy
mypy:
	mypy get-old-requirements.py sources tests

.PHONY: check
check: check-shaping check-subset fontbakery mypy

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
	pip-compile $<
	printf '%s\n%s\n' "$$(sed -n '1,/^$$/p' $<)" "$$(cat $@)" >$@
	-git --no-pager diff $@
