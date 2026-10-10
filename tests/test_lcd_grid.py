# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile the actual scanout grid function with sanitizers; no camera access."""
from pathlib import Path
import subprocess,tempfile
source=(Path(__file__).resolve().parents[1]/'qemu/nikon-z6.c').read_text()
start=source.index('static void nikon_lcd_grid(')
end=source.index('static unsigned nikon_lcd_overlay(',start)
body=source[start:end]
pre=r'''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define MIN(a,b) ((a)<(b)?(a):(b))
static uint32_t ldl_p(void *p){uint32_t x;memcpy(&x,p,4);return x;}
static void stl_p(void *p,uint32_t x){memcpy(p,&x,4);}
'''
post=r'''
int main(void){
 uint32_t r[0x4000/4]={0};uint32_t pixels[20*12];
 memset(pixels,0,sizeof pixels);
 r[0x1600/4]=2|(3<<16);r[0x1604/4]=5|(1<<16);
 r[0x1608/4]=15|(10<<16);r[0x160c/4]=1|(1<<16);
 r[0x1610/4]=3|(4<<16);r[0x1614/4]=2|(2<<16);
 r[0x1618/4]=0x03ffffff;
 nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);
 for(int i=0;i<240;i++)assert(pixels[i]==0);
 r[0x1620/4]=1;nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);
 unsigned n=0;
 for(int y=0;y<12;y++)for(int x=0;x<20;x++){
  int hit=((y==3||y==6||y==9)&&x>=2&&x<17)||((x==5||x==9||x==13)&&y>=1&&y<11);
  assert(pixels[y*20+x]==(hit?0xffffff:0));n+=hit;
 }
 assert(n==66);
 memset(pixels,0,sizeof pixels);r[0x1618/4]=0x030000ff;
 nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);assert(pixels[3*20+2]==0xff0000);
 memset(pixels,0,sizeof pixels);r[0x1618/4]=0x010000ff;
 nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);assert(pixels[3*20+2]==0x550000);
 memset(pixels,0,sizeof pixels);r[0x1618/4]=0xffffff;
 nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);for(int i=0;i<240;i++)assert(pixels[i]==0);
 r[0x1600/4]=0x3fffffff;r[0x1604/4]=0x3fffffff;r[0x1618/4]=0x03ffffff;
 nikon_lcd_grid(r,(uint8_t*)pixels,80,20,12);for(int i=0;i<240;i++)assert(pixels[i]==0);
 puts("PASS actual native-grid scanout: enable,6 lines,intersections,RGB,opacity,clipping");
}
'''
with tempfile.TemporaryDirectory() as td:
 c=Path(td)/'grid.c';exe=Path(td)/'grid';c.write_text(pre+body+post)
 subprocess.run(['cc','-fsanitize=address,undefined','-g',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
