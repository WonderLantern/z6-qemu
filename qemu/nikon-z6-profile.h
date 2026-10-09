/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef NIKON_Z6_PROFILE_H
#define NIKON_Z6_PROFILE_H
#include "nikon-model-config.h"

typedef struct NikonZ6Profile {
    const char *cpu_type;
    uint32_t cbar, timer_hz, main_base, main_bytes;
    unsigned gic_version, serial_fifo_depth;
    NikonRawGeometry raw;
    NikonFunctionalTiming timing;
} NikonZ6Profile;

/* Z6 C3.80 software interfaces. CPU type/CBAR/GIC revision and functional
 * completion timing are execution choices, not identified silicon values.
 * 48MHz, RAW geometry and software RAM windows have separate ROM/log evidence. */
static const NikonZ6Profile nikon_z6_profile = {
    .cpu_type = "cortex-a15-arm-cpu", .cbar = 0x2c000000,
    .timer_hz = 48000000, .main_base = 0x10020000, .main_bytes = 33502842,
    .gic_version = 1, .serial_fifo_depth = 16,
    .raw = {2034, 1434, 4080, 64, 4095},
    .timing = {100000, 100000, 1000000, 1000000, 33333333, 16666667},
};
typedef struct NikonRAMWindow { uint32_t base, size; } NikonRAMWindow;

/* Z6 ROM scatter and classified software windows; see port audit. */
static const NikonRAMWindow nikon_z6_ram_windows[] = {
            {0x80000000, 0x10000}, {0x80400000, 0x340000},
            /* Classification window101e5a4a..101e5a56; blob at80100000. */
            {0x80100000, 0x200000},
            /* Native blob copy11db80b4 ->80300000, length27800;
             * classification window101e5a56..101e5a64 ends80400000. */
            {0x80300000, 0x100000},
            {0x80a00000, 0x2313880}, {0x82e00000, 0x82bc400},
            {0x8b100000, 0x2817400}, {0x8da00000, 0x315d4c00},
            {0xbfc00000, 0x3fde00},
            /* Z6 processing/auxiliary windows101e5ad8/e6/f4. */
            {0xc0000000, 0x1000000}, {0xc1000000, 0x800000},
            {0xc1800000, 0x7a00000},
            {0xc9200000, 0x449000}, {0xc9700000, 0x2d00000},
            {0xcc400000, 0x700000},
            {0xccb00000, 0xda0000}, {0xcd900000, 0x10e0000},
            {0xcea00000, 0x63cb400}, {0xd4e00000, 0xd320000},
            {0xe2200000, 0x1dcef800},
};
#endif
