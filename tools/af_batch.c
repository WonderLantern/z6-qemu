// SPDX-License-Identifier: GPL-2.0-or-later
/* QEMU-only diagnostic batch, not an installable module or callback. */
#include <stdint.h>
__attribute__((noinline)) void pattern_begin(void) { __asm__ volatile("nop" ::: "memory"); }
__attribute__((noinline)) void pattern_capture(void) { __asm__ volatile("nop" ::: "memory"); }
__attribute__((naked)) static uint32_t claim(void *mutex) {
    __asm__ volatile(
        "ldr r2,[r0]\ncbz r2,2f\ndmb sy\nadd r1,r0,#4\n"
        "ldrex r2,[r1]\ncmn r2,#1\nbne 1f\nmovs r2,#0\n"
        "strex r3,r2,[r1]\ncmp r3,#0\nbne 2f\ndmb sy\n"
        "movs r0,#1\nbx lr\n1: clrex\n2: movs r0,#0\nbx lr\n");
}
/* Caller preflights all immutable rectangles and verifies native target state.
 * 0 completed batch (not GPU success), 1 busy; progress counts returned calls.
 */
uint32_t af_batch(const uint32_t *rects, uint32_t count, uint32_t unused,
                       volatile uint32_t *progress) {
    if (!claim((void *)0xc1d75f74)) return 1;
    typedef void (*Draw)(const uint32_t *);
    typedef void (*Release)(void *);
    volatile uint32_t *p=*(volatile uint32_t **)0xc1800c1c;
    const volatile uint32_t *clip=(const volatile uint32_t *)(uintptr_t)p[0x204/4];
    if (p[0]!=2 || p[0x104/4]!=0x1400 || p[0x7c/4] ||
        p[0x2d4/4]!=0xc201 || p[0x2ec/4]!=0xc201 || p[0x308/4]!=0xc201 ||
        p[0x208/4]!=1 || clip[0] || clip[1] || clip[2]!=720 || clip[3]!=480 ||
        *(volatile uint32_t *)0xc1f19248!=0x01e002d0 ||
        *(volatile uint32_t *)0xc1f19264!=0xd045f200 ||
        *(volatile uint32_t *)0xc1f19274) {
        ((Release)0x10164645)((void *)0xc1d75f74);
        return 2;
    }
    (void)unused;
    *progress = 0;
    pattern_begin();
    for (uint32_t i=0; i<count; ++i) {
        const uint32_t *r=rects+i*5;
        uint32_t request[7]={r[0],480u-r[3],r[2]-r[0],r[3]-r[1],r[4],0,0};
        ((Draw)0x10431c0f)(request);
        *progress = i+1;
    }
    /* Native vgFinish flushes the partially filled command buffer and waits.
     * An empty backend queue alone does not include unsubmitted VG commands. */
    ((void (*)(void))0x104315cb)(); /* same original worker as queued draws */
    for (uint32_t n=0; n<20 && *(volatile uint32_t *)0xc1d36534; ++n)
        ((void (*)(uint32_t))0x10170ccb)(10);
    ((void (*)(uint32_t))0x10170ccb)(10);
    progress[1]=*(volatile uint32_t *)0xc1d36534;
    pattern_capture();
    ((Release)0x10164645)((void *)0xc1d75f74);
    return 0;
}
