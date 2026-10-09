/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Shared functional execution of the SMAPH-F/OpenVG command subset.
 * Derived from the donor command decoder; Z6 drawing is separately regressed.
 * The console is a GUI-surface probe, not an emulation of the LCD scanout.
 * YUV422 layouts follow the original software pixel getter104e7ef8. */
#include "ui/console.h"
#include <math.h>

typedef struct NikonGPUEdge {
    double x0, y0, x1, y1;
    double ux0, uy0, ux1, uy1;
    unsigned contour;
} NikonGPUEdge;
typedef struct NikonGPUCross { double x; int winding; } NikonGPUCross;
typedef struct NikonGPUPath {
    uint32_t regs[512];
    GByteArray *segments, *coordinates;
    GArray *edges;
    bool valid;
    unsigned contour;
} NikonGPUPath;
typedef struct NikonGPU {
    uint32_t regs[2][512];
    GHashTable *paths;
    NikonGPUPath *active;
    QemuConsole *console;
    uint32_t present_address;
    unsigned rendered, unsupported;
    unsigned stroke_samples;
    unsigned icon_samples;
    bool lcd_scanout;
} NikonGPU;

static bool nikon_gpu_range(uint32_t addr, uint64_t bytes, bool write)
{
    uint64_t end = (uint64_t)addr + bytes;
    if (!bytes || end > UINT64_C(0x100000000)) { return false; }
    MemoryRegionSection section = memory_region_find(get_system_memory(), addr, bytes);
    bool valid = section.mr && memory_region_is_ram(section.mr) &&
                 (!write || !memory_region_is_rom(section.mr)) &&
                 int128_ge(section.size, int128_make64(bytes));
    if (section.mr) { memory_region_unref(section.mr); }
    return valid;
}

static double nikon_gpu_f32(uint32_t word)
{
    float value;
    memcpy(&value, &word, 4);
    return value;
}

static double nikon_gpu_f24(uint32_t word)
{
    if (!(word & 0x7fffff)) { return 0; }
    return (word & 0x800000 ? -1 : 1) *
           ldexp(1.0 + (word & 65535) / 65536.0, ((word >> 16) & 127) - 63);
}

static void nikon_gpu_path_free(gpointer opaque)
{
    NikonGPUPath *p = opaque;
    g_byte_array_unref(p->segments);
    g_byte_array_unref(p->coordinates);
    g_array_unref(p->edges);
    g_free(p);
}

static void nikon_gpu_edge(NikonGPUPath *p, double x0, double y0, double x1, double y1)
{
    double q[4], xs[] = {x0, x1}, ys[] = {y0, y1};
    for (int i = 0; i < 2; i++) {
        double w = nikon_gpu_f32(p->regs[0x43])*xs[i] + nikon_gpu_f32(p->regs[0x46])*ys[i] + nikon_gpu_f32(p->regs[0x49]);
        q[i*2] = (nikon_gpu_f32(p->regs[0x41])*xs[i] + nikon_gpu_f32(p->regs[0x44])*ys[i] + nikon_gpu_f32(p->regs[0x47]))/w;
        q[i*2+1] = (nikon_gpu_f32(p->regs[0x42])*xs[i] + nikon_gpu_f32(p->regs[0x45])*ys[i] + nikon_gpu_f32(p->regs[0x48]))/w;
        if (!isfinite(q[i*2]) || !isfinite(q[i*2+1]) || fabs(q[i*2]) > 1e6 || fabs(q[i*2+1]) > 1e6) {
            p->valid = false; return;
        }
    }
    NikonGPUEdge e = {q[0], q[1], q[2], q[3], x0, y0, x1, y1, p->contour};
    g_array_append_val(p->edges, e);
}

static void nikon_gpu_polygon(NikonGPUPath *p, const double (*v)[2], unsigned n)
{
    double area = 0;
    for (unsigned i=0;i<n;i++) { unsigned j=(i+1)%n; area+=v[i][0]*v[j][1]-v[j][0]*v[i][1]; }
    for (unsigned i=0;i<n;i++) {
        unsigned a=area>=0?i:n-1-i, b=area>=0?(i+1)%n:(n+n-2-i)%n;
        nikon_gpu_edge(p,v[a][0],v[a][1],v[b][0],v[b][1]);
    }
}

static void nikon_gpu_disc(NikonGPUPath *p, double x, double y, double radius)
{
    double v[32][2];
    for (unsigned i=0;i<32;i++) {
        double a=i*(6.283185307179586/32); v[i][0]=x+radius*cos(a); v[i][1]=y+radius*sin(a);
    }
    nikon_gpu_polygon(p,v,32);
}

/* Native10486a64..aae: reg65 bit8=fill; zero selects VG_STROKE_PATH.
 * 10486910 uploads stroke parameters: 5c=width/2, 5d=tangent miter extent;
 * 65[17:16]=cap, [21:20]=join. Construct the stroke in user coordinates,
 * then transform its outline, so nonuniform scales also scale the width. */
static void nikon_gpu_stroke(NikonGPUPath *p)
{
    double radius=nikon_gpu_f32(p->regs[0x5c]), extension=nikon_gpu_f32(p->regs[0x5d]);
    unsigned cap=(p->regs[0x65]>>16)&3, join=(p->regs[0x65]>>20)&3;
    if (!isfinite(radius) || radius<0 || radius>4096 || !isfinite(extension) ||
        extension<0 || cap>2 || join>2 || (p->regs[0x5a]&255)) {
        p->valid=false; return; /* Dashed strokes are not yet implemented. */
    }
    GArray *center=p->edges;
    p->edges=g_array_new(false,false,sizeof(NikonGPUEdge));
    if (!radius) { g_array_unref(center); return; }
    for (unsigned first=0;first<center->len;) {
        unsigned end=first+1;
        while (end<center->len && g_array_index(center,NikonGPUEdge,end).contour==
               g_array_index(center,NikonGPUEdge,first).contour) { end++; }
        NikonGPUEdge a=g_array_index(center,NikonGPUEdge,first), b=g_array_index(center,NikonGPUEdge,end-1);
        bool closed=hypot(a.ux0-b.ux1,a.uy0-b.uy1)<1e-9;
        for (unsigned i=first;i<end;i++) {
            NikonGPUEdge e=g_array_index(center,NikonGPUEdge,i);
            double dx=e.ux1-e.ux0, dy=e.uy1-e.uy0, length=hypot(dx,dy);
            if (length<1e-12) { continue; }
            dx/=length; dy/=length;
            double nx=-dy*radius, ny=dx*radius;
            double start=(!closed && i==first && cap==2)?radius:0;
            double finish=(!closed && i+1==end && cap==2)?radius:0;
            double x0=e.ux0-dx*start,y0=e.uy0-dy*start,x1=e.ux1+dx*finish,y1=e.uy1+dy*finish;
            double quad[4][2]={{x0+nx,y0+ny},{x0-nx,y0-ny},{x1-nx,y1-ny},{x1+nx,y1+ny}};
            nikon_gpu_polygon(p,quad,4);
            if (!closed && cap==1) {
                if (i==first) { nikon_gpu_disc(p,e.ux0,e.uy0,radius); }
                if (i+1==end) { nikon_gpu_disc(p,e.ux1,e.uy1,radius); }
            }
            if (i+1==end && !closed) { continue; }
            NikonGPUEdge next=g_array_index(center,NikonGPUEdge,i+1==end?first:i+1);
            double ex=next.ux1-next.ux0,ey=next.uy1-next.uy0,elen=hypot(ex,ey);
            if (elen<1e-12) { continue; }
            ex/=elen; ey/=elen;
            double turn=dx*ey-dy*ex;
            if (join==1) { nikon_gpu_disc(p,e.ux1,e.uy1,radius); continue; }
            if (fabs(turn)<1e-9) { continue; }
            double side=turn>0?-1:1;
            double qx=e.ux1+side*nx,qy=e.uy1+side*ny;
            double rx=e.ux1-side*ey*radius,ry=e.uy1+side*ex*radius;
            double t=((rx-qx)*ey-(ry-qy)*ex)/turn;
            if (join==0 && fabs(t)<=extension+1e-6) {
                double poly[4][2]={{e.ux1,e.uy1},{qx,qy},{qx+t*dx,qy+t*dy},{rx,ry}};
                nikon_gpu_polygon(p,poly,4);
            } else {
                double tri[3][2]={{e.ux1,e.uy1},{qx,qy},{rx,ry}};
                nikon_gpu_polygon(p,tri,3);
            }
        }
        first=end;
    }
    g_array_unref(center);
}

static void nikon_gpu_flatten(NikonGPUPath *p)
{
    unsigned ns = p->regs[3] & 65535, nc = p->regs[5] & 65535, at = 0;
    /* 104868b6 packs VG_PATH_DATATYPE into register5 bits30..31.
     * Register65 selects path rendering state, not coordinate datatype. */
    unsigned datatype = p->regs[5] >> 30;
    bool indirect = p->regs[3] & 0x10000000;
    unsigned coordinate_bytes = indirect && datatype < 2 ? 1U << datatype : 4;
    bool floating = datatype == 3;
    bool stroke = !(p->regs[0x65] & 0x100);
    double x = 0, y = 0, sx = 0, sy = 0;
    bool open = false;
    if (p->segments->len < ns || p->coordinates->len < nc*coordinate_bytes) { p->valid = false; return; }
    for (unsigned i = 0; i < ns; i++) {
        unsigned op = p->segments->data[i] & ~1, rel = p->segments->data[i] & 1;
        unsigned n;
        switch (op) {
        case 0: n = 0; break;
        case 2: case 4: n = 2; break;
        case 6: case 8: n = 1; break;
        case 10: n = 4; break;
        case 12: n = 6; break;
        default:
            fprintf(stderr, "Z6_GPU_PATH_OPCODE unsupported=%u index=%u\n", op, i);
            p->valid = false; return;
        }
        if (at + n > nc) {
            fprintf(stderr, "Z6_GPU_PATH_COORDINATES at=%u need=%u count=%u\n", at, n, nc);
            p->valid = false; return;
        }
        double v[6];
        for (unsigned j = 0; j < n; j++) {
            const uint8_t *q = p->coordinates->data + coordinate_bytes*at++;
            double raw = coordinate_bytes == 1 ? (int8_t)*q : coordinate_bytes == 2 ?
                (int16_t)lduw_le_p(q) : floating ? nikon_gpu_f32(ldl_le_p(q)) : (int32_t)ldl_le_p(q);
            v[j] = raw * nikon_gpu_f32(p->regs[0x5e]) + nikon_gpu_f32(p->regs[0x5f]);
            if (!isfinite(v[j]) || fabs(v[j]) > 1e6) { p->valid = false; return; }
        }
        if (op == 0) {
            if (open) { nikon_gpu_edge(p, x, y, sx, sy); }
            x = sx; y = sy; open = false;
        } else if (op == 2) {
            if (open && !stroke) { nikon_gpu_edge(p, x, y, sx, sy); }
            p->contour++;
            x = v[0] + (rel ? x : 0); y = v[1] + (rel ? y : 0);
            sx = x; sy = y; open = true;
        } else if (op == 4 || op == 6 || op == 8) {
            double nx = x, ny = y;
            if (op == 4) { nx = v[0] + (rel ? x : 0); ny = v[1] + (rel ? y : 0); }
            if (op == 6) { nx = v[0] + (rel ? x : 0); }
            if (op == 8) { ny = v[0] + (rel ? y : 0); }
            nikon_gpu_edge(p, x, y, nx, ny); x = nx; y = ny;
        } else {
            for (unsigned j = 0; j < n; j += 2) { v[j] += rel ? x : 0; v[j+1] += rel ? y : 0; }
            double length = hypot(v[0]-x, v[1]-y);
            for (unsigned j = 2; j < n; j += 2) { length += hypot(v[j]-v[j-2], v[j+1]-v[j-1]); }
            int steps = MAX(8, MIN(128, (int)ceil(length/2)));
            double px = x, py = y;
            for (int j = 1; j <= steps; j++) {
                double t = (double)j/steps, u = 1-t, nx, ny;
                if (op == 10) {
                    nx = u*u*x + 2*u*t*v[0] + t*t*v[2]; ny = u*u*y + 2*u*t*v[1] + t*t*v[3];
                } else {
                    nx = u*u*u*x + 3*u*u*t*v[0] + 3*u*t*t*v[2] + t*t*t*v[4];
                    ny = u*u*u*y + 3*u*u*t*v[1] + 3*u*t*t*v[3] + t*t*t*v[5];
                }
                nikon_gpu_edge(p, px, py, nx, ny); px = nx; py = ny;
            }
            x = v[n-2]; y = v[n-1];
        }
    }
    if (open && !stroke) { nikon_gpu_edge(p, x, y, sx, sy); }
    if (at != nc) { p->valid = false; }
    if (p->valid && stroke) { nikon_gpu_stroke(p); }
}

static int nikon_gpu_compare(const void *a, const void *b)
{
    double x = ((const NikonGPUCross *)a)->x, y = ((const NikonGPUCross *)b)->x;
    return (x > y) - (x < y);
}

static void nikon_yuv_rgb(unsigned y, unsigned u, unsigned v, uint8_t *p)
{
    int c = MAX(0, (int)y - 16), d = (int)u - 128, e = (int)v - 128;
    p[0] = CLAMP((298*c + 409*e + 128) >> 8, 0, 255);
    p[1] = CLAMP((298*c - 100*d - 208*e + 128) >> 8, 0, 255);
    p[2] = CLAMP((298*c + 516*d + 128) >> 8, 0, 255);
}

static void nikon_rgb_yuv(const uint8_t *p, uint8_t *yuv)
{
    yuv[0] = CLAMP(((66*p[0] + 129*p[1] + 25*p[2] + 128) >> 8) + 16, 0, 255);
    yuv[1] = CLAMP(((-38*p[0] - 74*p[1] + 112*p[2] + 128) >> 8) + 128, 0, 255);
    yuv[2] = CLAMP(((112*p[0] - 94*p[1] - 18*p[2] + 128) >> 8) + 128, 0, 255);
}

/* 105: Y + full-height interleaved UV; 106/107: Y0,Y1,U,V.
 * 107 has a separately addressed alpha plane, optionally packed4-bit.
 * Conversion uses a functional BT.601 matrix, not Nikon's programmable LUT. */
static void nikon_gpu_pixel_read(const uint8_t *a, const uint8_t *b, unsigned fmt,
                              bool alpha4, size_t i, uint8_t *p)
{
    if (fmt == 0 || fmt == 0x100) { memcpy(p, a + i*4, 4); return; }
    if (fmt == 0x18) { p[0] = p[1] = p[2] = 255; p[3] = a[i]; return; }
    if (fmt == 0x105) {
        nikon_yuv_rgb(a[i], b[i & ~1ULL], b[(i & ~1ULL)+1], p);
    } else {
        const uint8_t *q = a + (i & ~1ULL)*2;
        nikon_yuv_rgb(q[i & 1], q[2], q[3], p);
    }
    p[3] = fmt != 0x107 ? 255 : alpha4 ?
        ((b[i/2] >> ((i & 1)*4)) & 15)*17 : b[i];
}

static void nikon_gpu_pair_write(uint8_t *a, uint8_t *b, unsigned fmt,
                              bool alpha4, size_t i, const uint8_t *p, unsigned changed)
{
    uint8_t yuv[3], other[3];
    nikon_rgb_yuv(p, yuv); nikon_rgb_yuv(p+4, other);
    unsigned u = (yuv[1] + other[1] + 1)/2, v = (yuv[2] + other[2] + 1)/2;
    if (fmt == 0x105) {
        if (changed & 1) { a[i] = yuv[0]; }
        if (changed & 2) { a[i+1] = other[0]; }
        b[i] = u; b[i+1] = v;
    } else {
        uint8_t *q = a + i*2;
        if (changed & 1) { q[0] = yuv[0]; }
        if (changed & 2) { q[1] = other[0]; }
        q[2] = u; q[3] = v;
        if (fmt == 0x107) {
            for (unsigned x = 0; x < 2; x++) {
                if (!(changed & (1 << x))) { continue; }
                if (alpha4) {
                    unsigned shift = x*4;
                    b[i/2] = (b[i/2] & ~(15 << shift)) | (((p[4*x+3]+8)/17) << shift);
                } else { b[i+x] = p[4*x+3]; }
            }
        }
    }
}

static bool nikon_gpu_draw(NikonGPU *g, const uint32_t *r, NikonGPUPath *p)
{
    unsigned w = r[0x1a3] & 65535, h = r[0x1a3] >> 16, mode = r[0x184] & 255;
    unsigned logical_h = h;
    unsigned tw = r[0x152] >> 16, th = r[0x152] & 65535, fmt = r[0x156] & 65535;
    unsigned dfmt = r[0x1a2] & 0xffffff, bpp = !dfmt ? 4 : dfmt == 0x105 ? 1 : 2;
    /* 10486808: (enum << 28) >> 12 packs OpenVG2000+n into1a0[19:16].
     * 10486236 explicitly selects SRC for clear, including alpha=0. */
    unsigned blend_mode = (r[0x1a0] >> 16) & 15;
    bool alpha4 = r[0x1a2] & 0x1000000;
    bool second = dfmt == 0x105 || dfmt == 0x107;
    if (second && w && r[0x1b5] > r[0x1a4]) {
        /* GPU dimensions include alignment rows. Do not cross the explicitly
         * submitted next plane (native682 rows, GPU extent688). */
        h = MIN(h, (r[0x1b5] - r[0x1a4])/(w*bpp));
    }
    /* Native clear/copy paths span y=6..688 for a682-row plane. Keep the
     * aligned coordinate domain for geometry and texture sampling, and map
     * the submitted visible rows into the exact physical plane. Clipping
     * geometry at682 instead left six zero Y/UV rows (decoded as green). */
    unsigned y_bias = logical_h-h;
    uint64_t bytes = (uint64_t)w*h*bpp, second_bytes = (uint64_t)w*h/((dfmt == 0x107 && alpha4) ? 2 : 1);
    uint64_t texbytes = (uint64_t)tw*th*(fmt == 0x18 || fmt == 0x105 ? 1 : fmt == 0x106 || fmt == 0x107 ? 2 : 4);
    g_autofree uint8_t *dst = NULL, *dst2 = NULL, *tex = NULL, *tex2 = NULL;
    g_autofree uint8_t *pair_rgba = NULL, *pair_dirty = NULL;
    if (!p || !p->valid || (dfmt && dfmt != 0x105 && dfmt != 0x106 && dfmt != 0x107) ||
        !w || !h || w > 4096 || h > 4096 || (dfmt && (w & 1)) ||
        !nikon_gpu_range(r[0x1a4], bytes, true) ||
        (second && !nikon_gpu_range(r[0x1b5], second_bytes, true))) { return false; }
    if ((mode != 8 && mode != 2 && mode != 14) || blend_mode > 1) { return false; }
    double matrix[9];
    if (mode != 8) {
        if (!tw || !th || tw > 4096 || th > 4096 ||
            (fmt != 0 && fmt != 0x100 && fmt != 0x18 && fmt != 0x105 && fmt != 0x106 && fmt != 0x107) ||
            !nikon_gpu_range(r[0x155], texbytes, false)) { return false; }
        if (fmt == 0x105 || fmt == 0x107) {
            if ((tw & 1) || !nikon_gpu_range(r[0x15a], (uint64_t)tw*th, false)) { return false; }
            tex2 = g_malloc((size_t)tw*th); cpu_physical_memory_read(r[0x15a], tex2, (size_t)tw*th);
        }
        tex = g_malloc(texbytes); cpu_physical_memory_read(r[0x155], tex, texbytes);
        /* Opt-in, bounded read-only capture of original small icon textures. */
        const char *icon_dir = getenv("Z6_GPU_ICON_DUMP_DIR");
        if (icon_dir && tw <= 256 && th <= 256 && g->icon_samples < 512) {
            unsigned sample = g->icon_samples++;
            g_autofree char *prefix = g_strdup_printf("%s/%04u", icon_dir, sample);
            g_autofree char *rp = g_strdup_printf("%s-regs.bin", prefix);
            g_autofree char *tp = g_strdup_printf("%s-texture.bin", prefix);
            g_autofree char *pp = g_strdup_printf("%s-path-regs.bin", prefix);
            g_file_set_contents(rp, (const char *)r, 512*4, NULL);
            g_file_set_contents(pp, (const char *)p->regs, 512*4, NULL);
            g_file_set_contents(tp, (const char *)tex, texbytes, NULL);
            if (tex2) {
                g_autofree char *sp = g_strdup_printf("%s-second.bin", prefix);
                g_file_set_contents(sp, (const char *)tex2, (size_t)tw*th, NULL);
            }
        }
        for (int i = 0; i < 9; i++) { matrix[i] = nikon_gpu_f24(r[0x10c+i]); }
    }
    dst = g_malloc(bytes); cpu_physical_memory_read(r[0x1a4], dst, bytes);
    if (second) { dst2 = g_malloc(second_bytes); cpu_physical_memory_read(r[0x1b5], dst2, second_bytes); }
    if (dfmt) { pair_rgba = g_malloc((size_t)w*h*4); pair_dirty = g_malloc0((size_t)w*h/2); }
    g_autofree NikonGPUCross *cross = g_new(NikonGPUCross, p->edges->len);
    g_autofree uint8_t *mask = g_new0(uint8_t, w);
    int x0 = MAX(0, r[0xc0] & 65535), x1 = MIN(w, (r[0xc0] >> 16)+1);
    int y0 = MAX(y_bias, r[0xc1] & 65535), y1 = MIN(logical_h, (r[0xc1] >> 16)+1);
    double miny = logical_h, maxy = 0;
    for (unsigned i = 0; i < p->edges->len; i++) {
        NikonGPUEdge e = g_array_index(p->edges, NikonGPUEdge, i);
        miny = MIN(miny, MIN(e.y0, e.y1)); maxy = MAX(maxy, MAX(e.y0, e.y1));
    }
    y0 = MAX(y0, (int)floor(miny)); y1 = MIN(y1, (int)ceil(maxy));
    /* Native 10485d6a submits paint+0x0c unchanged: packed little-endian
     * RGBA, as with RGBA image storage. Captured no-card paint ff4848f0
     * is R=240,G=72,B=72. ARGB here swaps every colored solid/A8 icon. */
    double color[4] = {r[0x185]&255, (r[0x185]>>8)&255, (r[0x185]>>16)&255, r[0x185]>>24};
    for (int iy = y0; iy < y1; iy++) {
        memset(mask, 0, w);
        for (int sample = 0; sample < 4; sample++) {
            double y = iy + (sample+.5)/4;
            unsigned n = 0;
            for (unsigned i = 0; i < p->edges->len; i++) {
                NikonGPUEdge e = g_array_index(p->edges, NikonGPUEdge, i);
                if ((e.y0 <= y && e.y1 > y) || (e.y1 <= y && e.y0 > y)) {
                    cross[n++] = (NikonGPUCross){e.x0 + (y-e.y0)*(e.x1-e.x0)/(e.y1-e.y0), e.y1 > e.y0 ? 1 : -1};
                }
            }
            qsort(cross, n, sizeof(*cross), nikon_gpu_compare);
            int winding = 0;
            for (unsigned i = 0; i < n; i++) {
                if (winding && i) {
                    int a = MAX(x0*4, (int)ceil(cross[i-1].x*4-.5));
                    int b = MIN(x1*4, (int)ceil(cross[i].x*4-.5));
                    for (int j = a; j < b; j++) { mask[j/4]++; }
                }
                winding += cross[i].winding;
            }
        }
        for (int ix = x0; ix < x1; ix++) {
            if (!mask[ix]) { continue; }
            double src[4]; memcpy(src, color, sizeof(src));
            if (mode != 8) {
                double x = ix+.5, y = iy+.5, z = matrix[6]*x + matrix[7]*y + matrix[8];
                double u = (matrix[0]*x + matrix[1]*y + matrix[2])/z;
                double v = (matrix[3]*x + matrix[4]*y + matrix[5])/z;
                if (!isfinite(u) || !isfinite(v)) { return false; }
                int tx = floor(CLAMP(u*tw, 0, tw-1)), ty = floor(CLAMP(v*th, 0, th-1));
                unsigned index = ty*tw+tx;
                uint8_t sample[4];
                nikon_gpu_pixel_read(tex, tex2, fmt, false, index, sample);
                for (int c = 0; c < 4; c++) {
                    src[c] = sample[c];
                    if (mode == 14) { src[c] *= color[c]/255; }
                }
            }
            uint8_t pixel[4];
            size_t index = (size_t)(iy-y_bias)*w+ix;
            if (dfmt) {
                size_t pair = index & ~1ULL;
                if (!pair_dirty[index/2]) {
                    nikon_gpu_pixel_read(dst, dst2, dfmt, alpha4, pair, pair_rgba+pair*4);
                    nikon_gpu_pixel_read(dst, dst2, dfmt, alpha4, pair+1, pair_rgba+(pair+1)*4);
                }
                memcpy(pixel, pair_rgba+index*4, 4);
            } else { nikon_gpu_pixel_read(dst, dst2, dfmt, alpha4, index, pixel); }
            double coverage = mask[ix]/16.0;
            double sa = src[3]/255*coverage, da = pixel[3]/255.0;
            double keep = 1 - (blend_mode == 0 ? coverage : sa);
            double alpha = sa+da*keep;
            for (int c = 0; c < 3; c++) {
                pixel[c] = alpha ? CLAMP(lrint((src[c]*sa+pixel[c]*da*keep)/alpha), 0, 255) : 0;
            }
            pixel[3] = CLAMP(lrint(alpha*255), 0, 255);
            if (dfmt) {
                memcpy(pair_rgba+index*4, pixel, 4);
                pair_dirty[index/2] |= 1 << (index & 1);
            } else { memcpy(dst+index*4, pixel, 4); }
        }
    }
    if (dfmt) {
        for (size_t i = 0; i < (size_t)w*h; i += 2) {
            if (pair_dirty[i/2]) {
                nikon_gpu_pair_write(dst, dst2, dfmt, alpha4, i, pair_rgba+i*4, pair_dirty[i/2]);
            }
        }
    }
    cpu_physical_memory_write(r[0x1a4], dst, bytes);
    if (second) { cpu_physical_memory_write(r[0x1b5], dst2, second_bytes); }
    if (!dfmt && w == 720 && h == 480) { g->present_address = r[0x1a4]; }
    return true;
}

static void nikon_gpu_present(NikonGPU *g)
{
    if (!g->present_address || g->lcd_scanout) { return; }
    enum { W = 720, H = 480 };
    g_autofree uint8_t *rgba = g_malloc(W*H*4);
    cpu_physical_memory_read(g->present_address, rgba, W*H*4);
    DisplaySurface *surface = qemu_console_surface(g->console);
    uint8_t *out = surface_data(surface);
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            uint8_t *p = rgba + ((H-1-y)*W+x)*4;
            stl_p(out + y*surface_stride(surface) + x*4, (p[0]<<16)|(p[1]<<8)|p[2]);
        }
    }
    dpy_gfx_update(g->console, 0, 0, W, H);
    const char *dir = getenv("Z6_GRAPHICS_DUMP_DIR");
    if (dir) {
        g_autofree char *path = g_strdup_printf("%s/gui-latest.ppm", dir);
        GString *ppm = g_string_new("P6\n720 480\n255\n");
        for (int y = H-1; y >= 0; y--) {
            for (int x = 0; x < W; x++) { g_string_append_len(ppm, (char *)rgba + (y*W+x)*4, 3); }
        }
        g_file_set_contents(path, ppm->str, ppm->len, NULL); g_string_free(ppm, true);
    }
    fprintf(stderr, "Z6_GRAPHICS_FRAME source=0x%08x size=720x480 format=RGBA8888 view=GUI-probe rendered=%u unsupported=%u\n", g->present_address, g->rendered, g->unsupported);
}

static void nikon_gpu_execute(NikonGPU *g, unsigned ch, const uint8_t *data, unsigned length)
{
    uint32_t *r = g->regs[ch];
    unsigned at = 0;
    while (at+4 <= length) {
        uint32_t header = ldl_le_p(data+at); at += 4;
        if (!header) { continue; }
        unsigned op = header&7, n = ((header>>3)&255)+1;
        if (at+n*4 > length || (op != 2 && op != 4 && op != 6)) { goto bad; }
        if (op == 2) {
            if (ch || !g->active) { goto bad; }
            GByteArray *array = header & 0x10000 ? g->active->coordinates : g->active->segments;
            if (array->len+n*4 > 262144) { goto bad; }
            g_byte_array_append(array, data+at, n*4);
        } else {
            uint32_t mask = 0;
            for (unsigned i = 0; i < 4; i++) { if (header & (1U<<(12+i))) { mask |= 255U<<(8*i); } }
            for (unsigned i = 0; i < n; i++) {
                unsigned reg = (header>>16) + (op == 6 ? i : 0);
                if (reg >= 512) { goto bad; }
                r[reg] = (r[reg]&~mask) | (ldl_le_p(data+at+i*4)&mask);
                if (!ch && reg == 6 && r[reg] == 1) {
                    if (g->active) { goto bad; }
                    NikonGPUPath *p = g_new0(NikonGPUPath, 1); g->active = p;
                    memcpy(p->regs, r, sizeof(p->regs)); p->valid = true;
                    p->segments = g_byte_array_new(); p->coordinates = g_byte_array_new();
                    p->edges = g_array_new(false, false, sizeof(NikonGPUEdge));
                    if (r[3] & 0x10000000) {
                        unsigned datatype = r[5] >> 30;
                        unsigned ns = r[3]&65535, nc = (r[5]&65535)*(datatype < 2 ? 1U << datatype : 4);
                        if (!nikon_gpu_range(r[2], ns, false) || !nikon_gpu_range(r[4], nc, false)) { p->valid = false; }
                        else {
                            g_byte_array_set_size(p->segments, ns); g_byte_array_set_size(p->coordinates, nc);
                            cpu_physical_memory_read(r[2], p->segments->data, ns);
                            cpu_physical_memory_read(r[4], p->coordinates->data, nc);
                        }
                    }
                } else if (!ch && reg == 0x85) {
                    if (!g->active || g_hash_table_size(g->paths) > 4096) { goto bad; }
                    if (g->active->valid) { nikon_gpu_flatten(g->active); }
                    if (!g->active->valid) {
                        fprintf(stderr, "Z6_GPU_PATH_INVALID key=%08x segments=%08x/%08x coordinates=%08x/%08x type=%08x\n",
                                r[reg], g->active->regs[2], g->active->regs[3],
                                g->active->regs[4], g->active->regs[5], g->active->regs[0x65]);
                    }
                    g_hash_table_replace(g->paths, GUINT_TO_POINTER(r[reg]), g->active); g->active = NULL;
                } else if (ch && reg == 0x1a6 && (r[reg]&255) == 1) {
                    NikonGPUPath *p = g_hash_table_lookup(g->paths, GUINT_TO_POINTER(r[0xa6]));
                    if (r[0x1a2]) {
                        double lo=1e9, hi=-1e9;
                        if (p) for (unsigned j=0;j<p->edges->len;j++) {
                            NikonGPUEdge e=g_array_index(p->edges,NikonGPUEdge,j);
                            lo=MIN(lo,MIN(e.y0,e.y1)); hi=MAX(hi,MAX(e.y0,e.y1));
                        }
                        fprintf(stderr, "Z6_GPU_YUV_DRAW target=%08x format=%08x color=%08x blend=%08x clip=%08x/%08x flags=%08x key=%08x\n",
                                r[0x1a4], r[0x1a2], r[0x185], r[0x186], r[0xc0], r[0xc1], r[0x1a0], r[0xa6]);
                        fprintf(stderr,"Z6_GPU_GEOMETRY target=%08x size=%08x state=%08x path_y=%g..%g source=%08x source_size=%08x source_flags=%08x target_flags=%08x\n",
                                r[0x1a4],r[0x1a3],p?p->regs[0x65]:0,lo,hi,r[0x155],r[0x152],r[0x153],r[0x1a7]);
                    }
                    if (p && !(p->regs[0x65]&0x100) && g->stroke_samples++ < 24) {
                        fprintf(stderr,"Z6_GPU_STROKE state=%08x params=%08x/%08x/%08x/%08x scale=%g/%g color=%08x paint=%08x target=%08x\n",
                            p->regs[0x65],p->regs[0x5a],p->regs[0x5b],p->regs[0x5c],p->regs[0x5d],
                            nikon_gpu_f32(p->regs[0x41]),nikon_gpu_f32(p->regs[0x45]),r[0x185],r[0x184],r[0x1a4]);
                    }
                    if (nikon_gpu_draw(g, r, p)) { g->rendered++; }
                    else {
                        g->unsupported++;
                        fprintf(stderr, "Z6_GRAPHICS_UNSUPPORTED target=0x%08x format=0x%x mode=0x%x path=%s key=%08x\n", r[0x1a4], r[0x1a2], r[0x184]&255, p ? p->valid ? "valid" : "invalid" : "missing", r[0xa6]);
                        fprintf(stderr, "Z6_GRAPHICS_FORMAT target_size=%08x target_1a5=%08x source=%08x source_format=%08x source_size=%08x source_158=%08x\n",
                                r[0x1a3], r[0x1a5], r[0x155], r[0x156], r[0x152], r[0x158]);
                        /* 10453858..74 emits 1b5 for target formats105/107;
                         * 104539a0..b2 emits15a from image+a0 for textures. */
                        fprintf(stderr, "Z6_GRAPHICS_PLANES target_second=%08x source_second=%08x target_flags=%08x source_flags=%08x target_ch0_second=%08x\n",
                                r[0x1b5], r[0x15a], r[0x1a7], r[0x153], g->regs[0][0x1b5]);
                    }
                    g_hash_table_remove(g->paths, GUINT_TO_POINTER(r[0xa6]));
                }
            }
        }
        at += n*4;
    }
    if (ch) { nikon_gpu_present(g); }
    return;
bad:
    g->unsupported++;
    fprintf(stderr, "Z6_GRAPHICS_UNSUPPORTED malformed-command ch=%u offset=%u\n", ch, at);
}

static const GraphicHwOps nikon_gpu_ops = { 0 };
static NikonGPU *nikon_gpu_new(void)
{
    NikonGPU *g = g_new0(NikonGPU, 1);
    g->paths = g_hash_table_new_full(g_direct_hash, g_direct_equal, NULL, nikon_gpu_path_free);
    g->console = graphic_console_init(NULL, 0, &nikon_gpu_ops, g);
    qemu_console_resize(g->console, 720, 480);
    return g;
}
