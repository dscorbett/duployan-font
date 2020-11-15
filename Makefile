# Copyright 2018-2019 David Corbett
# Copyright 2020 Google LLC
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

FONT = font/Duployan.otf

.PHONY: all
all: $(FONT)

%.otf: %.sfd font/*.py
	font/build.py --input $< --output $@

.PHONY: clean
clean:
	find font -name '*.otf' -type f -delete
	$(RM) -r tests/failed

.PHONY: check
check: $(FONT)
	tests/run-tests.py $< tests/*.test

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
		$(MAKE) -C util CPPFLAGS=-DHB_BUFFER_MAX_OPS_FACTOR=256 lib hb-shape; \
	fi

.PHONY: requirements.txt
requirements.txt:
	$(eval TMP := $(shell mktemp -d))
	virtualenv -p python3 $(TMP)
	. $(TMP)/bin/activate; \
	pip install -U pip; \
	pip install -r requirements-to-freeze.txt; \
	sed -n '1,/^$$/p' requirements-to-freeze.txt >requirements.txt; \
	pip freeze >>requirements.txt; \
	deactivate
	$(RM) -r $(TMP)
	git diff requirements.txt
