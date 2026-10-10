#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
TEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$TEST_ROOT"
mkdir -p .build/tests
python3 -B tests/test_inputs.py
python3 -B tests/test_lcd_grid.py
python3 -B tests/test_lcd_overlay.py
cc -std=c11 -O1 -g -fsanitize=address,undefined tests/test_isp.c $(pkg-config --cflags --libs glib-2.0) -lm -o .build/tests/isp
ASAN_OPTIONS=detect_leaks=1 .build/tests/isp
