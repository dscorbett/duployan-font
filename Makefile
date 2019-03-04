# Copyright 2018-2019 David Corbett
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
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
			curl -L https://github.com/harfbuzz/harfbuzz/releases/download/$$HB_VERSION/harfbuzz-$$HB_VERSION.tar.bz2 \
			| tar -xj; \
		fi && \
		cd harfbuzz-$$HB_VERSION && \
		./configure && \
		$(MAKE) -C util lib hb-shape; \
	fi

.PHONY: freeze
freeze:
	$(eval TMP := $(shell mktemp -d))
	virtualenv -p python $(TMP)
	. $(TMP)/bin/activate; \
	pip install -U pip; \
	pip install -r requirements-to-freeze.txt; \
	pip freeze >requirements.txt; \
	deactivate
	$(RM) -r $(TMP)
	git diff requirements.txt
