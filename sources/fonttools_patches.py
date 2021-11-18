# MIT License
#
# Copyright (c) 2017 Just van Rossum
# Copyright (c) 2020-2021 Google LLC
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

import fontTools.ttLib.tables.otBase
import fontTools.ttLib.tables.otTables

def buildCoverage(glyphs, glyphMap, *args, **kwargs):
    if not glyphs:
        return None
    self = fontTools.ttLib.tables.otTables.Coverage()
    self.glyphs = sorted(set(glyphs), key=glyphMap.__getitem__)
    return self

def compile(self, font, *args, **kwargs):
    writer = fontTools.ttLib.tables.otBase.OTTableWriter(tableTag=self.tableTag)
    if self.tableTag == 'GSUB':
        ext_type = 7
    elif self.tableTag == 'GPOS':
        ext_type = 9
    else:
        ext_type = None
    if ext_type is not None:
        ext_subtable_thunk = fontTools.ttLib.tables.otTables.lookupTypes[self.tableTag][ext_type]
        for lookup in font[self.tableTag].table.LookupList.Lookup:
            if lookup.SubTable[0].__class__.LookupType != ext_type:
                lookup.LookupType = ext_type
                for si, subtable in enumerate(lookup.SubTable):
                    ext_subtable = ext_subtable_thunk()
                    ext_subtable.Format = 1
                    ext_subtable.ExtSubTable = subtable
                    lookup.SubTable[si] = ext_subtable
    self.table.compile(writer, font)
    return writer.getAllData()

