/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Pure functional pixel conversion/cache; no guest memory, IRQ or GUI access.
 * Identity is a full byte comparison, including RAW row padding. Every input
 * change invalidates all three output geometries. Bounded to one RAW frame
 * and three NV12 images; destinations are intentionally not part of this cache.
 */
#include <math.h>
#include "nikon-model-config.h"

typedef struct NikonISPOutput {
    unsigned width, height, stride;
    uint8_t *data;
} NikonISPOutput;
typedef struct NikonISPImages {
    NikonRawGeometry geometry;
    uint8_t *raw;
    uint8_t tone[4096];
    char *sha;
    NikonISPOutput output[3];
    uint64_t hits, misses;
    bool disable_cache;
} NikonISPImages;

static NikonISPImages *nikon_isp_images_new(const NikonRawGeometry *geometry, bool disable_cache)
{
    if (!geometry || !geometry->width || !geometry->height ||
        (geometry->width & 1) || (geometry->height & 1) ||
        geometry->stride < geometry->width * 2 ||
        geometry->white_level > 4095 || geometry->black_level >= geometry->white_level) {
        return NULL;
    }
    NikonISPImages *p = g_new0(NikonISPImages, 1);
    p->geometry = *geometry;
    p->disable_cache = disable_cache;
    for (unsigned i = 0; i < 4096; i++) {
        double v = CLAMP(((double)i - geometry->black_level) /
                         (geometry->white_level - geometry->black_level), 0, 1);
        v = v <= 0.0031308 ? 12.92 * v : 1.055 * pow(v, 1.0 / 2.4) - 0.055;
        p->tone[i] = CLAMP(lrint(v * 255), 0, 255);
    }
    return p;
}

static void nikon_isp_images_input(NikonISPImages *p, const uint8_t *raw)
{
    const size_t bytes = (size_t)p->geometry.stride * p->geometry.height;
    if (p->raw && !memcmp(p->raw, raw, bytes)) { return; }
    if (!p->raw) { p->raw = g_malloc(bytes); }
    memcpy(p->raw, raw, bytes);
    g_free(p->sha);
    p->sha = g_compute_checksum_for_data(G_CHECKSUM_SHA256, raw, bytes);
    for (unsigned i = 0; i < 3; i++) {
        g_clear_pointer(&p->output[i].data, g_free);
    }
}

static const uint8_t *nikon_isp_images_output(NikonISPImages *p, unsigned channel,
                                         unsigned w, unsigned h, unsigned stride)
{
    if (!p->raw || channel >= 3 || !w || !h || (w & 1) || (h & 1) ||
        w > 1920 || h > 1280 || stride < w || stride > 2048) { return NULL; }
    NikonISPOutput *out = &p->output[channel];
    if (!p->disable_cache && out->data && out->width == w && out->height == h && out->stride == stride) {
        p->hits++; return out->data;
    }
    p->misses++;
    g_free(out->data);
    size_t ybytes = (size_t)stride * h;
    out->data = g_malloc(ybytes + ybytes / 2);
    out->width = w; out->height = h; out->stride = stride;
    uint8_t *yp = out->data, *uvp = out->data + ybytes;
    memset(yp, 16, ybytes); memset(uvp, 128, ybytes / 2);
    /* Hoist integer resampling divisions out of the per-pixel loop. Exact
     * same RGGB-cell selection and rounding as the original implementation. */
    unsigned xmap[1920], ymap[1280];
    const unsigned cell_width = p->geometry.width / 2, cell_height = p->geometry.height / 2;
    const unsigned raw_stride = p->geometry.stride;
    for (unsigned x = 0; x < w; x++) { xmap[x] = MIN(cell_width-1, (uint64_t)x * cell_width / w) * 4; }
    for (unsigned y = 0; y < h; y++) { ymap[y] = MIN(cell_height-1, (uint64_t)y * cell_height / h) * 2 * raw_stride; }
    for (unsigned y = 0; y < h; y += 2) {
        for (unsigned x = 0; x < w; x += 2) {
            unsigned sum_r = 0, sum_g = 0, sum_b = 0;
            for (unsigned dy = 0; dy < 2; dy++) {
                for (unsigned dx = 0; dx < 2; dx++) {
                    const uint8_t *q = p->raw + ymap[y+dy] + xmap[x+dx];
                    unsigned red = p->tone[lduw_le_p(q) & 4095];
                    unsigned green = p->tone[((lduw_le_p(q+2) & 4095) + (lduw_le_p(q+raw_stride) & 4095) + 1) / 2];
                    unsigned blue = p->tone[lduw_le_p(q+raw_stride+2) & 4095];
                    yp[(y+dy)*stride+x+dx] = CLAMP(((66*red+129*green+25*blue+128)>>8)+16,16,235);
                    sum_r += red; sum_g += green; sum_b += blue;
                }
            }
            int red = (sum_r+2)/4, green = (sum_g+2)/4, blue = (sum_b+2)/4;
            uvp[(y/2)*stride+x] = CLAMP(((-38*red-74*green+112*blue+128)>>8)+128,16,240);
            uvp[(y/2)*stride+x+1] = CLAMP(((112*red-94*green-18*blue+128)>>8)+128,16,240);
        }
    }
    return out->data;
}

static void G_GNUC_UNUSED nikon_isp_images_free(NikonISPImages *p)
{
    if (!p) { return; }
    for (unsigned i = 0; i < 3; i++) { g_free(p->output[i].data); }
    g_free(p->raw); g_free(p->sha); g_free(p);
}
