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

import duployan

def build_font(options, font):
    if os.environ.get('SOURCE_DATE_EPOCH') is None:
        os.environ['SOURCE_DATE_EPOCH'] = '0'
    font.selection.all()
    font.correctReferences()
    font.selection.none()
    flags = []
    if args.output.endswith('.ttf'):
        flags += ['opentype', 'dummy-dsig', 'omit-instructions']
    font.generate(options.output, flags=flags)

def make_font(options):
    font = fontforge.open(options.input)
    font.encoding = 'UnicodeFull'
    duployan.augment(font)
    build_font(options, font)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add Duployan glyphs to a font.')
    parser.add_argument('--input', metavar='FILE', required=True, help='input font')
    parser.add_argument('--output', metavar='FILE', required=True, help='output font')
    args = parser.parse_args()
    make_font(args)

