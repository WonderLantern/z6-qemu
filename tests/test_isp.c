/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic RAW only: no private frames or proprietary output oracle. */
#include <glib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
static uint16_t lduw_le_p(const void *p) { const uint8_t *q=p; return q[0]|q[1]<<8; }
#include "../qemu/nikon-isp-pixels.h"
static unsigned checks;
#define CHECK(c) do { checks++; if (!(c)) { fprintf(stderr,"FAIL line%d: %s\n",__LINE__,#c); return 1; } } while (0)
int main(void)
{
    size_t n=4080*1434;
    uint8_t *raw=g_malloc0(n);
    const NikonRawGeometry geometry = {2034,1434,4080,64,4095};
    NikonISPImages *p=nikon_isp_images_new(&geometry,false);
    CHECK(!nikon_isp_images_output(p,0,8,8,16));
    nikon_isp_images_input(p,raw);
    const uint8_t *image=nikon_isp_images_output(p,0,8,8,16);
    CHECK(image && p->misses==1);
    for (unsigned i=0;i<192;i++) CHECK(image[i]==(i<128?16:128));
    CHECK(nikon_isp_images_output(p,0,8,8,16)==image && p->hits==1);
    CHECK(!nikon_isp_images_output(p,3,8,8,16));
    CHECK(!nikon_isp_images_output(p,0,7,8,16));
    CHECK(!nikon_isp_images_output(p,0,8,7,16));
    CHECK(!nikon_isp_images_output(p,0,8,8,7));
    CHECK(!nikon_isp_images_output(p,0,1922,8,2048));
    CHECK(!nikon_isp_images_output(p,0,8,1282,16));
    CHECK(!nikon_isp_images_output(p,0,8,8,2050));
    CHECK(nikon_isp_images_output(p,1,8,6,16));
    CHECK(nikon_isp_images_output(p,2,8,8,8));
    raw[4079]=1; nikon_isp_images_input(p,raw);
    CHECK(!p->output[0].data && !p->output[1].data && !p->output[2].data);
    /* An independent constant white scene verifies Y/UV levels and padding. */
    for (unsigned y=0;y<1434;y++) for (unsigned x=0;x<2034;x++) {
        raw[y*4080+x*2]=255; raw[y*4080+x*2+1]=15;
    }
    nikon_isp_images_input(p,raw);
    image=nikon_isp_images_output(p,0,8,8,16);
    for (unsigned y=0;y<8;y++) for (unsigned x=0;x<16;x++) CHECK(image[y*16+x]==(x<8?235:16));
    for (unsigned i=128;i<192;i++) CHECK(image[i]==128);
    uint8_t saved[192]; memcpy(saved,image,192);
    uint64_t misses=p->misses; p->disable_cache=true;
    image=nikon_isp_images_output(p,0,8,8,16);
    CHECK(p->misses==misses+1 && !memcmp(saved,image,192));
    nikon_isp_images_free(p); g_free(raw);
    /* A different, padded geometry proves the shared converter has no
     * camera-specific RAW dimensions. Independent white-level expectation. */
    const NikonRawGeometry small = {6,4,16,32,1023};
    uint8_t tiny[64] = {0};
    for (unsigned y=0;y<4;y++) for (unsigned x=0;x<6;x++) {
        tiny[y*16+x*2]=255; tiny[y*16+x*2+1]=3;
    }
    p=nikon_isp_images_new(&small,false); CHECK(p);
    nikon_isp_images_input(p,tiny);
    image=nikon_isp_images_output(p,0,8,8,16); CHECK(image);
    for (unsigned y=0;y<8;y++) for (unsigned x=0;x<16;x++) CHECK(image[y*16+x]==(x<8?235:16));
    for (unsigned i=128;i<192;i++) CHECK(image[i]==128);
    nikon_isp_images_free(p);
    const NikonRawGeometry invalid = {5,4,16,32,1023};
    CHECK(!nikon_isp_images_new(&invalid,false));
    printf("PASS %u synthetic ISP checks\n",checks); return 0;
}
