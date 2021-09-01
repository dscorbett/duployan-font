# Copyright 2018-2019 David Corbett
# Copyright 2020-2021 Google LLC
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

STYLES = Regular Bold
ifdef NOTO
    FONT_FAMILY_NAME = NotoSansDuployan
    override NOTO = --noto
else
    FONT_FAMILY_NAME = Duployan
endif
FONT_PREFIX = font/$(FONT_FAMILY_NAME)-
FONT_SUFFIX = .otf
FONTS = $(addprefix $(FONT_PREFIX),$(addsuffix $(FONT_SUFFIX),$(STYLES)))

.PHONY: all
all: $(FONTS)

$(FONT_PREFIX)Regular.otf: font/Duployan.fea font/*.py
	font/build.py --fea $< $(NOTO) --output $@

$(FONT_PREFIX)Bold.otf: font/Duployan.fea font/*.py
	font/build.py --bold --fea $< $(NOTO) --output $@

.PHONY: clean
clean:
	$(RM) -r $(FONTS) tests/failed

.PHONY: $(addprefix check-,$(STYLES))
$(addprefix check-,$(STYLES)): check-%: $(FONT_PREFIX)%$(FONT_SUFFIX)
	tests/run-tests.py $< tests/*.test

.PHONY: check
check: $(addprefix check-,$(STYLES))

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
	pip-compile --allow-unsafe --generate-hashes --no-emit-index-url --no-emit-trusted-host --quiet --upgrade $<
	printf '%s\n%s\n' "$$(sed -n '1,/^$$/p' $<)" "$$(cat $@)" >$@
	git diff $@
