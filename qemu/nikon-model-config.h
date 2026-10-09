/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef NIKON_MODEL_CONFIG_H
#define NIKON_MODEL_CONFIG_H
#include <stdint.h>

/* Functional Bayer conversion input, independent of camera model. */
typedef struct NikonRawGeometry {
    unsigned width, height, stride, black_level, white_level;
} NikonRawGeometry;

typedef struct NikonFunctionalTiming {
    uint64_t exmcu_sync_ns, sdes_mode_ns, sdes_sequence_ns, isp_job_ns;
    uint64_t tg_frame_ns, tg_half_frame_ns;
} NikonFunctionalTiming;
#endif
