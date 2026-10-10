# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise actual native LCD region/bank compositor, with bounded mock RAM."""
from pathlib import Path
import subprocess, tempfile
source=(Path(__file__).resolve().parents[1]/'qemu/nikon-z6.c').read_text()
body=source[source.index('static unsigned nikon_lcd_overlay('):source.index('static void nikon_lcd_present(')]
pre=r'''
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define MIN(a,b) ((a)<(b)?(a):(b))
static uint8_t ram[65536];
static uint32_t ldl_p(void *p){uint32_t x;memcpy(&x,p,4);return x;}
static void stl_p(void *p,uint32_t x){memcpy(p,&x,4);}
static bool nikon_gpu_range(uint64_t a,uint64_t n,bool unused){return a&&n&&a<=sizeof ram&&n<=sizeof ram-a;}
static void cpu_physical_memory_read(uint64_t a,void *p,size_t n){assert(nikon_gpu_range(a,n,false));memcpy(p,ram+a,n);}
static void cleanup_free(void *p){free(*(void**)p);}
#define g_autofree __attribute__((cleanup(cleanup_free)))
#define g_malloc malloc
/* Pixel conversion has its own native GPU tests; isolate addressing/alpha. */
static void nikon_gpu_pixel_read(uint8_t *c,uint8_t *a,int fmt,bool a4,size_t i,uint8_t *out){
 assert(fmt==0x107&&!a4);out[0]=out[1]=out[2]=c[(i&~1)*2+(i&1)];out[3]=a[i];
}
'''
post=r'''
static void region(uint32_t *r,unsigned p,unsigned n,unsigned ca,unsigned aa,unsigned x,unsigned y){
 unsigned b=0x2000+p*0x1000;r[(b+0x110)/4]=1;r[(b+0x200)/4]=0x30006;
 r[(b+0x400)/4+n]=4|(2<<16);r[(b+0x4c0)/4+n]=aa;
 r[(b+0x500)/4+n]=12;r[(b+0x540)/4+n]=6;
 r[(b+0x580)/4+n]=x|(y<<16);r[(b+0x5c0)/4]|=1<<n;
 if(n)r[(b+0x47c)/4+n]=ca;else r[(b+0x440)/4]=ca;
}
int main(void){
 uint32_t r[0x4000/4]={0},out[8*6]={0};
 memset(ram+0x1000,255,48);memset(ram+0x2000,255,48);
 region(r,0,0,0x1000,0x2000,1,1);
 assert(nikon_lcd_overlay(r,0,(uint8_t*)out,32,8,6)==1);
 for(unsigned y=0;y<6;y++)for(unsigned x=0;x<8;x++)assert(out[y*8+x]==((x>=1&&x<5&&y>=1&&y<3)?0xffffff:0));
 /* Request bank2 and observe active readback, then nested region address. */
 memset(out,0,sizeof out);r[0x2448/4]=0x3000;r[0x2214/4]=2<<8;
 memset(ram+0x3000,80,48);nikon_lcd_overlay(r,0,(uint8_t*)out,32,8,6);
 assert(out[9]==0x505050&&((r[0x2214/4]>>16)&3)==2);
 r[0x2214/4]=0;region(r,0,1,0x1040,0x2040,6,5);
 memset(ram+0x1040,120,48);memset(ram+0x2040,255,48);
 memset(out,0,sizeof out);assert(nikon_lcd_overlay(r,0,(uint8_t*)out,32,8,6)==2);
 assert(out[5*8+6]==0x787878&&out[5*8+7]==0x787878);
 /* Overlay2 composes partial alpha over overlay1 with independent strides. */
 region(r,1,0,0x4000,0x5000,1,1);memset(ram+0x4000,0,48);memset(ram+0x5000,128,48);
 nikon_lcd_overlay(r,1,(uint8_t*)out,32,8,6);assert(out[9]==0x7f7f7f);
 r[0x3110/4]=0;assert(nikon_lcd_overlay(r,1,(uint8_t*)out,32,8,6)==0);
 r[0x3110/4]=1;r[0x3440/4]=65530;assert(nikon_lcd_overlay(r,1,(uint8_t*)out,32,8,6)==0);
 r[0x3440/4]=0x4000;r[0x3500/4]=1;assert(nikon_lcd_overlay(r,1,(uint8_t*)out,32,8,6)==0);
 r[0x3500/4]=12;r[0x3200/4]=7;assert(nikon_lcd_overlay(r,1,(uint8_t*)out,32,8,6)==0);
 puts("PASS actual LCD compositor: planes,regions,banks,readback,strides,alpha,clipping,bounds");
}
'''
with tempfile.TemporaryDirectory() as td:
    c=Path(td)/'overlay.c';exe=Path(td)/'overlay';c.write_text(pre+body+post)
    subprocess.run(['cc','-fsanitize=address,undefined','-g',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
