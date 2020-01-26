# MIT License
#
# Copyright (c) 2017 Just van Rossum
# Copyright (c) 2020 Google LLC
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import fontTools.feaLib.builder
import fontTools.feaLib.error
import fontTools.ttLib.tables.otTables

def add_multiple_subst(self, location, prefix, glyph, suffix, replacements, forceChain=False):
    if prefix or suffix or forceChain:
        chain = self.get_lookup_(location, fontTools.feaLib.builder.ChainContextSubstBuilder)
        sub = self.get_chained_lookup_(location, fontTools.feaLib.builder.MultipleSubstBuilder)
        sub.mapping[glyph] = replacements
        chain.substitutions.append((prefix, [{glyph}], suffix, [sub]))
        return
    lookup = self.get_lookup_(location, fontTools.feaLib.builder.MultipleSubstBuilder)
    if glyph in lookup.mapping:
        if replacements == lookup.mapping[glyph]:
            fontTools.feaLib.builder.log.info(
                'Removing duplicate multiple substitution from glyph "%s" to %s%s',
                glyph,
                replacements,
                ' at {}:{}:{}'.format(*location) if location else '',
            )
        else:
            raise fontTools.feaLib.error.FeatureLibError(
                'Already defined substitution for glyph "%s"' % glyph,
                location)
    lookup.mapping[glyph] = replacements

def fixLookupOverFlows(ttf, overflowRecord):
    ok = 0
    lookup_index = overflowRecord.LookupListIndex
    if overflowRecord.SubTableIndex is None:
        lookup_index = lookup_index - 1
    if lookup_index < 0:
        return ok
    if overflowRecord.tableType == 'GSUB':
        ext_type = 7
    elif overflowRecord.tableType == 'GPOS':
        ext_type = 9
    lookups = ttf[overflowRecord.tableType].table.LookupList.Lookup
    for lookup_index in range(lookup_index, -1, -1):
        lookup = lookups[lookup_index]
        if lookup.SubTable[0].__class__.LookupType != ext_type:
            lookup.LookupType = ext_type
            for si in range(len(lookup.SubTable)):
                subtable = lookup.SubTable[si]
                ext_subtable_class = fontTools.ttLib.tables.otTables.lookupTypes[overflowRecord.tableType][ext_type]
                ext_subtable = ext_subtable_class()
                ext_subtable.Format = 1
                ext_subtable.ExtSubTable = subtable
                lookup.SubTable[si] = ext_subtable
            ok = 1
    return ok

