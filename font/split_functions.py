# MIT License
#
# Copyright (c) 2017 Just van Rossum
# Copyright (c) 2019 David Corbett
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

def split_multiple_subst(old_subtable, new_subtable, overflow_record):
    ok = 1
    old_mapping = sorted(old_subtable.mapping.items())
    old_length = len(old_mapping)
    if overflow_record.itemName in ['Coverage', 'RangeRecord']:
        new_length = old_length // 2
    elif overflow_record.itemName == 'Sequence':
        new_length = overflow_record.itemIndex - 1
    new_subtable.mapping = {}
    for i in range(new_length, old_length):
        item = old_mapping[i]
        key = item[0]
        new_subtable.mapping[key] = item[1]
        del old_subtable.mapping[key]
    new_subtable.Format = old_subtable.Format
    return ok

