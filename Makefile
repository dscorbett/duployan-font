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

WEIGHTS = $(VALID_WEIGHTS)
ifdef RELEASE
    override RELEASE = --release
endif
ifdef UNJOINED
    override UNJOINED = --unjoined
endif
ifdef NOTO
    FONT_FAMILY_NAME = Noto Sans Duployan$(if $(UNJOINED), Unjoined)
    CHARSET = noto
    VERSION = 3.003
    override NOTO = --noto
else
    FONT_FAMILY_NAME = $(if $(filter standard,$(CHARSET)),Rawnd Musmus,Ilo Snas) Duployan$(if $(UNJOINED), Uncow)
    CHARSET = standard
    VERSION = 1.1
endif
unexport CHARSET
SUFFIXES = $(VALID_SUFFIXES)
TALL_TEXT = 𛰋𛱚𛰚‌𛰆𛱁𛰚𛰊
HB_VERSION = 9.0.0
NEXT_VERSION = $$(python -c 'v = "$(VERSION)".split("."); print(f"{v[0]}.{int(v[1]) + 1}")')

CHECK_ARGS = $(if $(filter testing,$(CHARSET)),,--incomplete)
FONT_FILE_NAME = $(subst $(eval ) ,,$(FONT_FAMILY_NAME))
FONTS = $(foreach suffix,$(SUFFIXES),$(addprefix fonts/$(FONT_FILE_NAME)/unhinted/$(suffix)/$(FONT_FILE_NAME)-,$(addsuffix .$(suffix),$(WEIGHTS))))
INTERMEDIATE_PREFIX = tmp-
INTERMEDIATE_FONTS = $(addprefix $(INTERMEDIATE_PREFIX),$(FONTS))
SUBSET_PREFIX = subset-
HB_PROGRAMS = hb-shape hb-view

VALID_CHARSETS = $(shell PYTHONPATH="sources:$$PYTHONPATH" python3 -c 'import charsets; print(" ".join(charsets.Charset))')
ifneq ($(strip $(filter-out $(VALID_CHARSETS),$(CHARSET))),)
    $(error One or more invalid values: $(CHARSET); must be one of: $(VALID_CHARSETS))
endif

VALID_WEIGHTS = Regular Bold
ifneq ($(strip $(filter-out $(VALID_WEIGHTS),$(WEIGHTS))),)
    $(error One or more invalid values: $(WEIGHTS); must be subset of: $(VALID_WEIGHTS))
endif

VALID_SUFFIXES = otf ttf
ifneq ($(strip $(filter-out $(VALID_SUFFIXES),$(SUFFIXES))),)
    $(error One or more invalid values: $(SUFFIXES); must be subset of: $(VALID_SUFFIXES))
endif

ifdef COVERAGE
    override COVERAGE = coverage run
endif
BUILD = PYTHONPATH="sources:$(PYTHONPATH)" $(COVERAGE) sources/build.py \
    --charset $(CHARSET) --name '$(FONT_FAMILY_NAME)' $(NOTO) $(RELEASE) $(UNJOINED) --version $(VERSION)
RUN_TESTS = PYTHONPATH="sources:$(PYTHONPATH)" tests/run-tests.py
UNIFDEF = unifdef -$(if $(NOTO),D,U)NOTO -t

.PHONY: all
all: $(FONTS)

.PHONY: otf
otf: $(filter %.otf,$(FONTS))

.PHONY: ttf
ttf: $(filter %.ttf,$(FONTS))

$(SUBSET_PREFIX)fonts/%.subset-glyphs.txt: fonts/%
	mkdir -p "$$(dirname "$@")"
	ttx -o - -q -t GlyphOrder "$<" \
	| grep '<GlyphID ' \
	| cut -f4 -d'"' \
	| grep '^\(_[^.]*_\(\.\|$$\)\|[^_][^.]*_\.[^.]*\.\|\([^_][^.]*[^_]\(\.[^.]*\)\?\|\.[^.]*\)\(\._[0-9A-F][1-9A-F]*\)\?$$\)' \
	>"$@"

$(SUBSET_PREFIX)fonts/%: fonts/% $(SUBSET_PREFIX)fonts/%.subset-glyphs.txt
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
	$(COVERAGE) sources/copy_metrics.py --text $(TALL_TEXT) $@ $(INTERMEDIATE_PREFIX)$@ $(filter-out $(INTERMEDIATE_PREFIX)$@,$^)

%.otf: sources/metadata.fea $(shell find sources -name '*.py') | dummy-%
ifdef COVERAGE
	coverage erase
endif
	$(BUILD) $(BOLD_ARG) --fea <($(UNIFDEF) $<) --output $@

%-Bold.otf: BOLD_ARG=--bold

define MAKE_TTF
    mkdir -p "$$(dirname "$@")"
    sources/otf2ttf.py --output "$@" --overwrite "$<"
endef

%.ttf: %.otf
	$(MAKE_TTF)

$(addprefix $(INTERMEDIATE_PREFIX)fonts/$(FONT_FILE_NAME)/unhinted/ttf/$(FONT_FILE_NAME)-,$(addsuffix .ttf,$(WEIGHTS))): $(INTERMEDIATE_PREFIX)fonts/$(FONT_FILE_NAME)/unhinted/ttf/%.ttf: $(INTERMEDIATE_PREFIX)fonts/$(FONT_FILE_NAME)/unhinted/otf/%.otf
	$(MAKE_TTF)

.PHONY: clean
clean: clean-coverage
	$(RM) -r fonts $(INTERMEDIATE_PREFIX)fonts $(SUBSET_PREFIX)fonts tests/failed coverage.json coverage.lcov coverage.xml htmlcov $(shell find . -name '*,cover')
	$(RM) -r sync-1-venv sync-2-venv sync-1.txt sync-2.txt

.PHONY: clean-coverage
clean-coverage:
	$(if $(COVERAGE),,-)coverage erase

.coverage: $(if $(COVERAGE),$(FONTS))
	coverage combine$(if $(COVERAGE),,; test $$? -le 1)

.PHONY: check-coverage
check-coverage: .coverage
	coverage report$(if $(COVERAGE),,; test $$? -le 1)

.PHONY: $(addprefix check-,$(FONTS))
$(addprefix check-,$(FONTS)): check-%: %
	$(RUN_TESTS) $(CHECK_ARGS) $< tests/*.test

ifdef UNJOINED

.PHONY: $(addprefix check-unjoined-,$(FONTS))
$(addprefix check-unjoined-,$(FONTS)): check-unjoined-%: %
	$(RUN_TESTS) $(CHECK_ARGS) $< tests/*.subset-test

.PHONY: check-unjoined
check-unjoined: $(addprefix check-unjoined-,$(FONTS))

else

.PHONY: check-shaping
check-shaping: $(addprefix check-,$(FONTS))

.PHONY: $(addprefix check-subset-,$(FONTS))
$(addprefix check-subset-,$(FONTS)): check-subset-%: subset-%
	$(RUN_TESTS) $(CHECK_ARGS) $< tests/*.subset-test

.PHONY: check-subset
check-subset: $(addprefix check-subset-,$(FONTS))

endif

.PHONY: $(addprefix fontbakery-,$(SUFFIXES))
$(addprefix fontbakery-,$(SUFFIXES)): fontbakery-%: %
	fontbakery check-notofonts --configuration <($(UNIFDEF) tests/fontbakery-config.toml) --full-lists --skip-network $(filter %.$*,$(FONTS))

.PHONY: fontbakery
fontbakery: $(addprefix fontbakery-,$(SUFFIXES))

.PHONY: mypy
mypy:
	mypy sources tests

.PHONY: ruff
ruff:
	ruff check pyproject.toml sources tests

.PHONY: check-fonts
check-fonts: $(if $(UNJOINED),check-unjoined,check-shaping check-subset) fontbakery

.PHONY: check-sources
check-sources: mypy ruff

.PHONY: check
check: check-sources check-fonts $(if $(COVERAGE),check-coverage)

.hb:
	mkdir -p .hb

.hb/harfbuzz-%/build: .hb
	cd $< && \
	if [ ! -d harfbuzz-$* ]; then \
		curl -L https://github.com/harfbuzz/harfbuzz/releases/download/$*/harfbuzz-$*.tar.xz \
		| tar -xJ; \
	fi && \
	cd harfbuzz-$* && \
	meson setup build -Dchafa=disabled -Dgobject=disabled -Dtests=disabled && \
	ninja -C build

$(addprefix .hb/harfbuzz-$(HB_VERSION)/build/util/,$(HB_PROGRAMS)):
	$(MAKE) -B .hb/harfbuzz-$(HB_VERSION)/build

.PHONY: $(HB_PROGRAMS)
$(HB_PROGRAMS): %: .hb/harfbuzz-$(HB_VERSION)/build/util/%

.PHONY: $(patsubst %.in,%.txt,$(wildcard *requirements.in))
$(patsubst %.in,%.txt,$(wildcard *requirements.in)): %requirements.txt: %requirements.in
	uv pip compile $< >$@
	printf '%s\n#\n%s\n' "$$(sed -n '1,/^$$/p' $<)" "$$(cat $@)" >$@
	-git --no-pager diff $@

.PHONY: release
release: RELEASE=1
release:
	test -z "$$(git status --porcelain --untracked-files=no)"
	grep "^[[:space:]]*VERSION[[:space:]]*=[[:space:]]*$(VERSION)[[:space:]]*$$" $(lastword $(MAKEFILE_LIST))
	git tag --annotate --message='$(FONT_FAMILY_NAME) $(VERSION).0' $(FONT_FILE_NAME)-v$(VERSION).0
	sed -i.bak "/^[[:space:]]*VERSION[[:space:]]*=[[:space:]]*$(VERSION)[[:space:]]*$$/s/=.*/= $(NEXT_VERSION)/" $(lastword $(MAKEFILE_LIST))
	$(RM) $(lastword $(MAKEFILE_LIST)).bak
	git add $(lastword $(MAKEFILE_LIST))
	git commit --message "Prepare for $(FONT_FAMILY_NAME) $(NEXT_VERSION).0"

.PHONY: sync-noto
sync-noto:
	if [ ! -d notofonts/duployan ]; then git clone git@github.com:notofonts/duployan.git notofonts/duployan; fi
	for f in $$(git ls-files | grep '^sources/.*\.\(fea\|py\)$$'); \
	do \
		unifdef -DNOTO -t -o notofonts/duployan/$$f $$f; \
		git -C notofonts/duployan add $$f; \
	done
	sed -i.bak '/==/d' notofonts/duployan/requirements.txt
	$(RM) -r sync-1-venv && python3 -m venv sync-1-venv && . sync-1-venv/bin/activate && pip install -r requirements.txt && pip freeze >sync-1.txt
	$(RM) -r sync-2-venv && python3 -m venv sync-2-venv && . sync-2-venv/bin/activate && pip install -r notofonts/duployan/requirements.txt && pip freeze >sync-2.txt
	comm -23 sync-1.txt sync-2.txt | tee -a notofonts/duployan/requirements.txt
	git -C notofonts/duployan add requirements.txt
	git -C notofonts/duployan status
	@echo 'Makefile and .github/workflows/ may need manual updates.'
