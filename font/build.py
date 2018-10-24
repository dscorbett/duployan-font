#!/usr/bin/env python

# build.py - Duployan font build utility
#
# Written in 2010-2018 by Khaled Hosny <khaledhosny@eglug.org>
# Written in 2018 by David Corbett <corbett.dav@husky.neu.edu>
#
# To the extent possible under law, the authors have dedicated all
# copyright and related and neighboring rights to this software to the
# public domain worldwide. This software is distributed without any
# warranty.
#
# You should have received a copy of the CC0 Public Domain Dedication
# along with this software. If not, see
# <http://creativecommons.org/publicdomain/zero/1.0/>.

import argparse
import os

import fontforge
import fontTools.ttLib

import duployan

def build_font(options, font):
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        os.environ['SOURCE_DATE_EPOCH'] = '0'
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = ['dummy-dsig', 'no-hints', 'omit-instructions', 'opentype']
    font.generate(options.output, flags=flags)

def tweak_font(options):
    tt_font = fontTools.ttLib.TTFont(options.output)

    # Remove the FontForge timestamp table.
    if 'FFTM' in tt_font:
        del tt_font['FFTM']

    # This font has no vendor.
    tt_font['OS/2'].achVendID = '    '

    tt_font.save(options.output)

def make_font(options):
    font = fontforge.open(options.input)
    font.encoding = 'UnicodeFull'
    font = duployan.augment(font)
    build_font(options, font)
    tweak_font(options)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--input', metavar='FILE', required=True, help='input font')
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    args = parser.parse_args()
    make_font(args)

