/*
 * TurboView 4 - the Amiga companion to TurboCAT 4.
 *
 * Reads the catalogue TurboCAT writes into a shared folder (mounted as TurboCAT: by the
 * emulator) and lets you search it: in a Workbench window on Kickstart 2.04 and later, or from
 * the Shell on 1.3 (or with the SHELL option). Inside Amiberry or WinUAE-family emulators it can
 * also put a disk straight into DF0:-DF3: and restart into it.
 *
 * Build (vbcc, NDK 3.2):
 *     vc +kick13 -O2 -I<NDK>/Include_H -o TurboView turboview.c
 * The kick13 target keeps it runnable on 1.3; the window is only used when gadtools.library
 * (Kickstart 2.04+) is there.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <exec/types.h>
#include <exec/memory.h>
#include <intuition/intuition.h>
#include <intuition/gadgetclass.h>
#include <libraries/gadtools.h>
#include <graphics/text.h>
#include <graphics/displayinfo.h>
#include <graphics/modeid.h>
#include <dos/dosextens.h>
#include <workbench/startup.h>
#include <workbench/workbench.h>
#include <proto/icon.h>
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/intuition.h>
#include <proto/graphics.h>
#include <proto/gadtools.h>

/* Keir Fraser's inflate in 68000 assembly (public domain; amiga/inflate.asm, through
   amiga/inflate_glue.asm): unpacks TurboCAT.fz about 8 times faster than C could */
extern void fast_inflate(unsigned char *out, const unsigned char *in, void *work_end);
#define FZ_WORK 2928             /* inflate's tables, off the stack (see inflate_glue.asm) */

static const char version[] = "\0$VER: TurboView 4.0 alpha 7 (13.11.2026)";

long __stack = 40000;            /* the boot Shell's default 4 KB is too little for GadTools */

struct IntuitionBase *IntuitionBase;
struct GfxBase *GfxBase;
struct Library *GadToolsBase;
struct Library *IconBase;
static int from_wb;                  /* started from its Workbench icon: no Shell to print in */

#define LINE 1024
#define MAXROOTS 16
#define MAXROWS 300
#define MAXLINES 260
#define ROWLEN 120

static char line[LINE];
static char catdir[200] = "TurboCAT:";
static char roots_pc[MAXROOTS][160], roots_vol[MAXROOTS][32];
static int nroots;
static long nitems;
static char made[64];

/* ---------------------------------------------------------------- small helpers */

static int lower(int c)
{
    c &= 255;
    if ((c >= 'A' && c <= 'Z') || (c >= 0xC0 && c <= 0xDE && c != 0xD7)) return c + 32;
    return c;
}

/* Case-insensitive search. set_needle() lowercases the search text once; contains() then
   compares through a lookup table, which matters on a 7 MHz Amiga. */
static unsigned char lc[256];
static unsigned char needle_lc[130];
static int needle_n;

static void init_lc(void)
{
    int c;
    for (c = 0; c < 256; c++) lc[c] = (unsigned char)lower(c);
}

static void set_needle(const char *s)
{
    int i;
    for (i = 0; s[i] && i < 128; i++) needle_lc[i] = lc[(unsigned char)s[i]];
    needle_lc[i] = 0;
    needle_n = i;
}

static int contains(const char *hay, const char *unused)
{
    const unsigned char *h = (const unsigned char *)hay;
    unsigned char first = needle_lc[0];
    if (!needle_n) return 1;
    for (; *h; h++) {
        if (lc[*h] == first) {
            int i = 1;
            while (i < needle_n && h[i] && lc[h[i]] == needle_lc[i]) i++;
            if (i == needle_n) return 1;
        }
    }
    return 0;
}

static void chomp(char *s)
{
    int n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r')) s[--n] = 0;
}

static int fields(char *s, char **out, int max)
{
    int n = 0;
    out[n++] = s;
    while (*s && n < max) {
        if (*s == '\t') { *s = 0; out[n++] = s + 1; }
        s++;
    }
    return n;
}

static FILE *open_cat(const char *name)
{
    char path[260];
    strcpy(path, catdir);
    strcat(path, name);
    return fopen(path, "r");
}

/* fopen with AmigaDOS's "Please insert volume" requester turned off: a missing disk just fails. */
static FILE *fopen_quiet(const char *path, const char *mode)
{
    struct Process *me = (struct Process *)FindTask(NULL);
    APTR old = me->pr_WindowPtr;
    FILE *f;
    me->pr_WindowPtr = (APTR)-1;
    f = fopen(path, mode);
    me->pr_WindowPtr = old;
    return f;
}

/* Where a part of the catalogue is: in TurboView's own folder, or on the other TurboView floppy
   ("TurboView" is disk 1, "TurboView2" the search disk) if it is in a drive. Looking never brings
   up an "insert disk" requester. Fills path; returns 1 if found. */
static int find_part(const char *name, char *path)
{
    static const char *vols[] = { "", "TurboView:", "TurboView2:" };
    int i;
    for (i = 0; i < 3; i++) {
        FILE *f;
        strcpy(path, i ? vols[i] : catdir);
        strcat(path, name);
        if ((f = fopen_quiet(path, "r"))) { fclose(f); return 1; }
    }
    return 0;
}

static void amiga_path(const char *pc, char *out)
{
    int i, best = -1, bestlen = 0;
    for (i = 0; i < nroots; i++) {
        int n = strlen(roots_pc[i]);
        if (n > bestlen && !strncmp(pc, roots_pc[i], n) && (pc[n] == '/' || !pc[n])) {
            best = i; bestlen = n;
        }
    }
    if (best < 0) { out[0] = 0; return; }
    sprintf(out, "%s:%s", roots_vol[best], pc[bestlen] == '/' ? pc + bestlen + 1 : "");
}

static const char *flag_words(const char *f)
{
    static char buf[80];
    buf[0] = 0;
    if (strchr(f, 'G')) strcat(buf, "game ");
    if (strchr(f, 'M')) strcat(buf, "music ");
    if (strchr(f, 'P')) strcat(buf, "PROBLEM ");
    if (strchr(f, 'W')) strcat(buf, "warning ");
    if (strchr(f, 'D')) strcat(buf, "duplicate ");
    if (strchr(f, 'E')) strcat(buf, "empty ");
    if (strchr(f, 'N')) strcat(buf, "non-DOS ");
    if (strchr(f, 'H')) strcat(buf, "hard-drive ");
    if (strchr(f, 'B')) strcat(buf, "bootable ");
    if (strchr(f, 'U')) strcat(buf, "utility ");
    if (strchr(f, 'F')) strcat(buf, "FAVOURITE ");
    return buf;
}

static void stem(const char *file, char *out, int max)
{
    const char *dot = strrchr(file, '.');
    int n = dot && dot != file ? dot - file : strlen(file);
    if (n > max) n = max;
    memcpy(out, file, n);
    out[n] = 0;
}

/* ---------------------------------------------------------------- the emulator */

typedef long (*uaecall)(long cmd, long a1, long a2);
static uaecall uae;

static int find_uae(void)
{
    unsigned char *res = OpenResource("uae.resource");
    if (res) {
        uae = (uaecall)(*(unsigned long *)(res + 0x2a) + 0xFF60);
        return 1;
    }
#ifndef NO_UAE_PROBE                      /* -DNO_UAE_PROBE: for testing under vamos */
    if (*(unsigned short *)0xF0FF60 == 0x4EB9) {
        uae = (uaecall)0xF0FF60;
        return 1;
    }
#endif
    return 0;
}

/* ---------------------------------------------------------------- the catalogue */

/* Results and detail lines are handed to whoever is showing them. */
typedef void (*emit_fn)(long number, const char *text);

static int load_header(void)
{
    FILE *f = open_cat("TurboCAT.cat");
    char *fl[4];
    if (!f) return 0;
    while (fgets(line, LINE, f)) {
        chomp(line);
        if (line[0] == 'I' && line[1] == '\t') break;
        if (!strncmp(line, "MADE ", 5)) {
            strncpy(made, line + 5, sizeof(made) - 1);
            if (strchr(made, '\t')) *strchr(made, '\t') = 0;
            if (strstr(line, "ITEMS ")) nitems = atol(strstr(line, "ITEMS ") + 6);
        } else if (!strncmp(line, "ROOT\t", 5) && nroots < MAXROOTS) {
            if (fields(line, fl, 4) >= 3) {
                strncpy(roots_pc[nroots], fl[1], 159);
                strncpy(roots_vol[nroots], fl[2], 31);
                nroots++;
            }
        }
    }
    fclose(f);
    return 1;
}

/* ---------------------------------------------------------------- the packed file list
   On a floppy the list of every file (TurboCAT.fil) is too big, so TurboCAT packs it as
   TurboCAT.fz. Header, longs: "TVFZ", version, blocks, biggest unpacked, biggest packed; then per
   block: first disk, last disk, offset, packed size, unpacked size. Each block is deflate of whole
   disks: byte 1 and a number start a disk; every other line is one byte (32 + characters shared
   with the line before) and the rest of the path. One disk's contents unpacks only its block. */
static unsigned long fz_n, fz_maxu, fz_maxc, *fz_tab;
static unsigned char *fz_u, *fz_c, *fz_work;
static int fz_state;                 /* 1 ready; otherwise looked for again when wanted */
static char fz_path[260];

static unsigned char *work_area(void)          /* inflate's tables (see inflate_glue.asm) */
{
    if (!fz_work) fz_work = malloc(FZ_WORK + 16);
    return fz_work;
}

static int fz_open(void)
{
    FILE *f;
    unsigned long head[5];
    if (fz_state > 0) return 1;
    if (!find_part("TurboCAT.fz", fz_path) || !(f = fopen_quiet(fz_path, "r"))) return 0;
    if (fread(head, 4, 5, f) == 5 && head[0] == 0x5456465AUL && head[1] == 1 && head[2] > 0) {
        free(fz_tab); free(fz_u); free(fz_c);
        fz_n = head[2]; fz_maxu = head[3]; fz_maxc = head[4];
        fz_tab = malloc(fz_n * 20);
        fz_u = malloc(fz_maxu + 1);
        fz_c = malloc(fz_maxc + 1);
        if (fz_tab && fz_u && fz_c && work_area() && fread(fz_tab, 20, fz_n, f) == fz_n) fz_state = 1;
    }
    fclose(f);
    return fz_state > 0;
}

/* Unpack block i into fz_u. Returns its length, or -1. */
static long fz_unpack(unsigned long i)
{
    FILE *f;
    unsigned long *t = fz_tab + i * 5, slen = t[3];
    if (!(f = fopen_quiet(fz_path, "r"))) { fz_state = 0; return -1; }   /* its disk was taken out */
    if (fseek(f, t[2], SEEK_SET) || fread(fz_c, 1, slen, f) != slen) { fclose(f); return -1; }
    fclose(f);
    if (t[4] > fz_maxu) return -1;
    fast_inflate(fz_u, fz_c, work_area() + FZ_WORK);
    fz_u[t[4]] = 0;
    return (long)t[4];
}

/* Calls each(disk, path, ctx) for every file in block i, until it returns 0. */
static void fz_each(unsigned long i, int (*each)(long, const char *, void *), void *ctx)
{
    static char path[260];
    unsigned char *p, *end, *e;
    long len = fz_unpack(i), disk = 0;
    int plen = 0, k, n;
    if (len < 0) return;
    for (p = fz_u, end = fz_u + len; p < end; p = e + 1) {
        for (e = p; e < end && *e != '\n'; e++) ;
        if (e == p) continue;
        if (*p == 1) { disk = atol((char *)p + 1); plen = 0; continue; }
        k = *p - 32;
        if (k < 0) k = 0;
        if (k > plen) k = plen;
        n = (int)(e - p) - 1;
        if (k + n > 255) n = 255 - k;
        memcpy(path + k, p + 1, n);
        plen = k + n;
        path[plen] = 0;
        if (!each(disk, path, ctx)) return;
    }
}

struct fz_search { const char *text; emit_fn emit; long max, total; };
static int search_cut;               /* the packed list's search stopped once the list was full */

/* Unpacking every block takes minutes on a 7 MHz Amiga, so a search of the packed list can be
   stopped: fz_stop (set by the window) is asked between blocks, and Ctrl-C always works. */
static int (*fz_stop)(unsigned long done, unsigned long of);

static int fz_stopped(unsigned long done)
{
    if (SetSignal(0L, SIGBREAKF_CTRL_C) & SIGBREAKF_CTRL_C) return 1;
    return fz_stop && fz_stop(done, fz_n);
}

static int fz_found(long disk, const char *path, void *ctx)
{
    struct fz_search *s = ctx;
    char buf[ROWLEN];
    if (contains(path, s->text)) {
        if (s->total >= s->max) {       /* the list is full: the rest would only be counted, */
            search_cut = 1;             /* and counting means unpacking every block (minutes) */
            return 0;
        }
        sprintf(buf, "#%04ld %.100s", disk, path);
        s->emit(disk, buf);
        s->total++;
    }
    return 1;
}

struct fz_list { long number; emit_fn emit; int shown, max; };

static int fz_listed(long disk, const char *path, void *ctx)
{
    struct fz_list *l = ctx;
    char buf[300];
    if (disk > l->number) return 0;              /* disks are in order: this one is done */
    if (disk == l->number) {
        if (l->shown < l->max) {
            sprintf(buf, "  %.200s", path);
            l->emit(disk, buf);
        }
        l->shown++;
    }
    return 1;
}

/* ---------------------------------------------------------------- the name index (search disk)
   TurboCAT.nix: every file and folder name once, sorted, with the disks it is on, so a search
   unpacks a third as much as the full list. Header, longs: "TVNX", version, blocks, biggest names
   block unpacked/packed, biggest disks block unpacked/packed; then per block: entries, and offset,
   packed and unpacked size of its names, then of its disks. Names: one byte (32 + characters shared
   with the name before) and the rest, one per line. Disks: per name a varint count, then varint
   gaps between disk numbers. */
static unsigned long nx_n, nx_mnu, nx_mnc, nx_mdu, nx_mdc, *nx_tab;
static unsigned char *nx_u, *nx_d, *nx_c;
static int nx_state;
static char nx_path[260];

static int nx_open(void)
{
    FILE *f;
    unsigned long head[7];
    if (nx_state > 0) return 1;
    if (!find_part("TurboCAT.nix", nx_path) || !(f = fopen_quiet(nx_path, "r"))) return 0;
    if (fread(head, 4, 7, f) == 7 && head[0] == 0x54564E58UL && head[1] == 1 && head[2] > 0) {
        free(nx_tab); free(nx_u); free(nx_d); free(nx_c);
        nx_n = head[2]; nx_mnu = head[3]; nx_mnc = head[4]; nx_mdu = head[5]; nx_mdc = head[6];
        nx_tab = malloc(nx_n * 28);
        nx_u = malloc(nx_mnu + 1);
        nx_d = malloc(nx_mdu + 1);
        nx_c = malloc((nx_mnc > nx_mdc ? nx_mnc : nx_mdc) + 1);
        if (nx_tab && nx_u && nx_d && nx_c && work_area() && fread(nx_tab, 28, nx_n, f) == nx_n) nx_state = 1;
    }
    fclose(f);
    return nx_state > 0;
}

/* Unpack len packed bytes at offset of the index into out. Returns 1 if all went well. */
static int nx_unpack(unsigned long offset, unsigned long clen, unsigned long ulen, unsigned char *out)
{
    FILE *f = fopen_quiet(nx_path, "r");
    if (!f) { nx_state = 0; return 0; }
    if (fseek(f, offset, SEEK_SET) || fread(nx_c, 1, clen, f) != clen) { fclose(f); return 0; }
    fclose(f);
    fast_inflate(out, nx_c, work_area() + FZ_WORK);
    out[ulen] = 0;
    return 1;
}

static unsigned long varint(unsigned char **p)
{
    unsigned long x = 0;
    int shift = 0;
    while (**p & 128) { x |= (unsigned long)(**p & 127) << shift; shift += 7; (*p)++; }
    x |= (unsigned long)**p << shift;
    (*p)++;
    return x;
}

static int fz_stopped(unsigned long done);

static long nx_search(const char *text, emit_fn emit, long max)
{
    static char name[260];
    char buf[ROWLEN];
    unsigned long b;
    long total = 0;
    for (b = 0; b < nx_n && !search_cut; b++) {
        unsigned long *t = nx_tab + b * 7, entry = 0, at = 0;
        unsigned char *p, *end, *e, *dp = NULL;
        int len = 0, have_disks = 0;
        if (fz_stopped(b)) return -3;
        if (!nx_unpack(t[1], t[2], t[3], nx_u)) return total ? total : -1;
        for (p = nx_u, end = nx_u + t[3]; p < end && !search_cut; p = e + 1, entry++) {
            int k = *p - 32, n;
            for (e = p; e < end && *e != '\n'; e++) ;
            if (k < 0) k = 0;
            if (k > len) k = len;
            n = (int)(e - p) - 1;
            if (k + n > 255) n = 255 - k;
            memcpy(name + k, p + 1, n);
            len = k + n;
            name[len] = 0;
            if (!contains(name, text)) continue;
            if (!have_disks) {                  /* the disks block only when something matched */
                if (!nx_unpack(t[4], t[5], t[6], nx_d)) return total ? total : -1;
                have_disks = 1; dp = nx_d; at = 0;
            }
            while (at < entry) {                /* skip the disk lists of the names before */
                unsigned long c = varint(&dp);
                while (c--) varint(&dp);
                at++;
            }
            {
                unsigned long c = varint(&dp), disk = 0;
                at++;
                while (c--) {
                    disk += varint(&dp);
                    if (total >= max) { search_cut = 1; break; }
                    sprintf(buf, "#%04ld %.100s", (long)disk, name);
                    emit((long)disk, buf);
                    total++;
                }
            }
        }
    }
    return total;
}

/* Item lines: 0 I, 1 number, 2 flags, 3 type, 4 title, 5 file, 6 PC path, 7 disk */
static long search_items(const char *text, char flag, emit_fn emit, long max)
{
    FILE *f = open_cat("TurboCAT.cat");
    char *fl[9], buf[ROWLEN], name[80];
    long total = 0;
    if (!f) return -1;
    set_needle(text);
    while (fgets(line, LINE, f)) {
        if (line[0] != 'I' || line[1] != '\t') continue;
        chomp(line);
        if (fields(line, fl, 9) < 8) continue;
        if (flag && !strchr(fl[2], flag)) continue;
        if (!contains(fl[4], text) && !contains(fl[5], text) && !contains(fl[6], text)) continue;
        if (total < max) {
            stem(fl[5], name, 70);
            /* \xbb marks a favourite, * a game */
            sprintf(buf, "#%04ld %c %s", atol(fl[1]),
                    strchr(fl[2], 'F') ? '\xbb' : strchr(fl[2], 'G') ? '*' : ' ', name);
            emit(atol(fl[1]), buf);
        }
        total++;
    }
    fclose(f);
    return total;
}

static long search_files(const char *text, emit_fn emit, long max)
{
    FILE *f;
    char *fl[5], buf[ROWLEN];
    long total = 0;
    search_cut = 0;
    if (nx_open()) {                       /* the search disk's index: quickest */
        set_needle(text);
        return nx_search(text, emit, max);
    }
    f = open_cat("TurboCAT.fil");
    if (!f) {
        struct fz_search s;
        unsigned long i;
        if (!fz_open()) return -1;
        set_needle(text);
        s.text = text; s.emit = emit; s.max = max; s.total = 0;
        search_cut = 0;
        for (i = 0; i < fz_n && !search_cut; i++) {
            if (fz_stopped(i)) return -3;
            fz_each(i, fz_found, &s);
        }
        return s.total;
    }
    set_needle(text);
    while (fgets(line, LINE, f)) {
        chomp(line);
        if (fields(line, fl, 5) < 4 || !contains(fl[2], text)) continue;
        if (total < max) {
            sprintf(buf, "#%04ld %.100s", atol(fl[1]), fl[2]);
            emit(atol(fl[1]), buf);
        }
        total++;
    }
    fclose(f);
    return total;
}

/* Tune lines: 0 T, 1 number, 2 title, 3 format, 4 seconds, 5 where, 6 F (favourite) or - */
static long search_tunes(const char *text, emit_fn emit, long max, int favourites_only)
{
    FILE *f = open_cat("TurboCAT.mus");
    char *tf[8], buf[ROWLEN];
    long total = 0;
    if (!f) return -1;
    set_needle(text);
    while (fgets(line, LINE, f)) {
        int nf, fav;
        chomp(line);
        nf = fields(line, tf, 8);
        if (nf < 6 || (!contains(tf[2], text) && !contains(tf[5], text))) continue;
        fav = nf > 6 && tf[6][0] == 'F';           /* older catalogues have no favourites field */
        if (favourites_only && !fav) continue;
        if (total < max) {
            long s = atol(tf[4]);
            sprintf(buf, "#%04ld %c%-30.30s %ld:%02ld %.20s", atol(tf[1]),
                    fav ? '\xbb' : ' ', tf[2], s / 60, s % 60, tf[3]);
            emit(atol(tf[1]), buf);
        }
        total++;
    }
    fclose(f);
    return total;
}

static int find_item(long number, char *store)
{
    FILE *f = open_cat("TurboCAT.cat");
    if (!f) return 0;
    while (fgets(line, LINE, f)) {
        if (line[0] != 'I' || line[1] != '\t') continue;
        if (atol(line + 2) != number) continue;
        chomp(line);
        strcpy(store, line);
        fclose(f);
        return 1;
    }
    fclose(f);
    return 0;
}

/* Everything about one item, line by line. Returns 1 if the emulator can load it. */
static int details(long number, emit_fn emit, int maxfiles)
{
    static char item[LINE];
    char *fl[9], buf[300], apath[260];
    FILE *f;
    long offset = -1;
    int shown = 0, loadable;
    if (!find_item(number, item) || fields(item, fl, 9) < 8) {
        sprintf(buf, "There is no #%ld.", number);
        emit(number, buf);
        return 0;
    }
    sprintf(buf, "#%04ld  %.100s", number, fl[4]); emit(number, buf);
    sprintf(buf, "Type:   %s", fl[3]); emit(number, buf);
    sprintf(buf, "File:   %.200s", fl[5]); emit(number, buf);
    if (*fl[2] != '-') { sprintf(buf, "Notes:  %s", flag_words(fl[2])); emit(number, buf); }
    if (strcmp(fl[6], "-")) {             /* "-" on a TurboView floppy: no computer paths */
        sprintf(buf, "PC:     %.250s", fl[6]); emit(number, buf);
        amiga_path(fl[6], apath);
        if (apath[0]) { sprintf(buf, "Amiga:  %.250s", apath); emit(number, buf); }
    }
    loadable = strcmp(fl[7], "-") != 0;
    if (loadable && strchr(fl[2], 'B')) loadable = 2;        /* 2: it boots by itself */
    if (loadable == 1) emit(number, "Not bootable: put it in a drive and use it from Workbench.");

    f = open_cat("TurboCAT.idx");
    if (f) {
        while (fgets(line, LINE, f))
            if (atol(line) == number) { offset = atol(strchr(line, '\t') + 1); break; }
        fclose(f);
    }
    /* Tunes first: there are usually fewer of them than files */
    if (strchr(fl[2], 'M') && (f = open_cat("TurboCAT.mus"))) {
        char *tf[8];
        int tunes = 0;
        emit(number, "");
        emit(number, "Music:");
        while (fgets(line, LINE, f)) {
            int nf;
            chomp(line);
            nf = fields(line, tf, 8);
            if (nf < 6 || atol(tf[1]) != number) continue;
            if (tunes < 40) {
                long s = atol(tf[4]);
                sprintf(buf, " %c%-30.30s %ld:%02ld %.20s", nf > 6 && tf[6][0] == 'F' ? '\xbb' : ' ',
                        tf[2], s / 60, s % 60, tf[3]);
                emit(number, buf);
            }
            tunes++;
        }
        if (tunes > 40) { sprintf(buf, "  ... and %d more", tunes - 40); emit(number, buf); }
        fclose(f);
    }
    if (offset >= 0 && (f = open_cat("TurboCAT.fil"))) {
        char *ff[5];
        fseek(f, offset, SEEK_SET);
        emit(number, "");
        emit(number, "Contents:");
        while (fgets(line, LINE, f)) {
            chomp(line);
            if (fields(line, ff, 5) < 4 || atol(ff[1]) != number) break;
            if (shown < maxfiles) {
                sprintf(buf, "  %-40.200s %8s", ff[2], ff[3]);
                emit(number, buf);
            }
            shown++;
        }
        if (shown > maxfiles) { sprintf(buf, "  ... and %d more", shown - maxfiles); emit(number, buf); }
        fclose(f);
    } else if (fz_open()) {
        unsigned long i;
        for (i = 0; i < fz_n; i++) {
            if ((long)fz_tab[i * 5] <= number && number <= (long)fz_tab[i * 5 + 1]) {
                struct fz_list l;
                l.number = number; l.emit = emit; l.shown = 0; l.max = maxfiles;
                emit(number, "");
                emit(number, "Contents:");
                fz_each(i, fz_listed, &l);
                if (l.shown > maxfiles) { sprintf(buf, "  ... and %d more", l.shown - maxfiles); emit(number, buf); }
                break;
            }
        }
    } else if (nx_open()) {                /* the search disk on its own */
        emit(number, "");
        emit(number, "Contents: on disk 1 (TurboView). Boot from it,");
        emit(number, "or put it in a second drive.");
    }
    return loadable;
}

/* Put an item's disk in a drive (and restart into it). Message goes to `msg`. */
static int insert(long number, long drive, int boot, char *msg)
{
    static char item[LINE], now[260];
    char *fl[9];
    int tries;
    if (!find_item(number, item) || fields(item, fl, 9) < 8) { sprintf(msg, "There is no #%ld.", number); return 0; }
    if (!strcmp(fl[7], "-")) { sprintf(msg, "#%ld isn't a floppy the emulator can load.", number); return 0; }
    if (!uae && !find_uae()) {
        sprintf(msg, "Only inside Amiberry or another UAE emulator. On the PC: %.150s", fl[7]);
        return 0;
    }
    uae(5, (long)fl[7], drive);                       /* insert disk */
    for (tries = 0; tries < 10; tries++) {            /* it goes in a moment later */
        Delay(10);
        now[0] = 0;
        uae(14, drive, (long)now);
        if (now[0]) break;
    }
    if (!now[0]) { sprintf(msg, "DF%ld: isn't connected on this Amiga.", drive); return 0; }
    sprintf(msg, "%.80s is in DF%ld:.", fl[5], drive);
    if (boot) uae(4, 0, 0);                           /* reset */
    return 1;
}

static void drives(emit_fn emit)
{
    static char name[260];
    char buf[300];
    long d;
    if (!uae && !find_uae()) { emit(0, "Only inside Amiberry or another UAE emulator."); return; }
    emit(0, "Drives:");
    for (d = 0; d < 4; d++) {
        name[0] = 0;
        uae(14, d, (long)name);
        sprintf(buf, "  DF%ld:  %.250s", d, name[0] ? (strrchr(name, '/') ? strrchr(name, '/') + 1 : name)
                                                    : "(empty)");
        emit(0, buf);
    }
}

/* ================================================================ Shell version */

void print_row(long number, const char *text) { printf("%s\n", text); }

/* ---------------------------------------------------------------- UPDATE from newer floppies
   An installed TurboView notices newer TurboView disks in a drive (their catalogue is dated later
   than its own) and offers to update itself from them: insert disk 1, say yes. */
static int install(const char *dest);
static FILE *say_to;
static char newer[64], declined[64];

static int update_waiting(void)
{
    char head[200], *tab;
    FILE *f;
    if (!strncmp(catdir, "TurboView", 9)) return 0;        /* running from the floppies themselves */
    if (!(f = fopen_quiet("TurboView:TurboCAT.cat", "r"))) return 0;
    head[0] = 0;
    fgets(head, sizeof(head), f);                           /* TURBOVIEW 1 */
    fgets(head, sizeof(head), f);                           /* MADE <date>\tHOST ... */
    fclose(f);
    if (strncmp(head, "MADE ", 5)) return 0;
    strncpy(newer, head + 5, sizeof(newer) - 1);
    newer[sizeof(newer) - 1] = 0;
    if ((tab = strchr(newer, '\t'))) *tab = 0;
    chomp(newer);
    /* "2026-11-20 18:40" sorts by date as text; a "Not now" isn't asked again for the same disks */
    return strcmp(newer, made) > 0 && strcmp(newer, declined) != 0;
}

/* Update this TurboView's own drawer from the floppies, then read the new lists. */
static int do_update(void)
{
    char dest[200];
    int r, n;
    strcpy(dest, catdir);
    n = strlen(dest);
    if (n > 1 && dest[n - 1] == '/') dest[n - 1] = 0;      /* "DH0:TurboCAT/" -> "DH0:TurboCAT" */
    r = install(dest);
    strcpy(catdir, dest);
    n = strlen(catdir);
    if (n && catdir[n - 1] != ':' && catdir[n - 1] != '/') strcat(catdir, "/");
    nroots = 0;
    nx_state = fz_state = 0;                                /* the new lists are read afresh */
    load_header();
    return r;
}

static void shell(void)
{
    static char input[256], msg[300];
    printf("Catalogue of %s, %ld items.%s Type ? for help.\n\n", made, nitems,
           find_uae() ? " Running in an emulator: disks can be inserted." : "");
    if (update_waiting())
        printf("Newer TurboView disks are in a drive (made %s). Type update to update this TurboView.\n\n", newer);
    for (;;) {
        char *s;
        long n;
        printf("TurboView> ");
        fflush(stdout);
        if (!fgets(input, sizeof(input), stdin)) break;
        chomp(input);
        s = input;
        while (*s == ' ') s++;
        if (!*s) continue;
        if (!strcmp(s, "q") || !strcmp(s, "quit") || !strcmp(s, "x")) break;
        if (!strcmp(s, "update")) {
            if (update_waiting()) {
                say_to = stdout;
                do_update();
                printf("Catalogue of %s, %ld items.\n", made, nitems);
            } else printf("There are no newer TurboView disks in a drive.\n");
            continue;
        }
        if (!strcmp(s, "?") || !strcmp(s, "help")) {
            printf("\nType part of a name to search titles and disk names, or:\n"
                   "  9            details of #0009\n"
                   "  f name       find a file on any disk\n"
                   "  tunes name   find a music module by its title\n"
                   "  favs name    your favourites (starred in TurboCAT), disks and tunes\n"
                   "  favtunes     only your favourite tunes\n"
                   "  utils name   only utilities and applications\n"
                   "  games name   only games       music name   only disks with music\n"
                   "  problems     disks with problems\n"
                   "  insert 9     put #0009 in DF0: (\"insert 9 1\" for DF1:)\n"
                   "  boot 9       put #0009 in DF0: and restart into it\n"
                   "  drives       what is in DF0:-DF3: (in an emulator)\n"
                   "  update       update from newer TurboView disks in a drive\n"
                   "  q            quit\n\n");
            continue;
        }
        if (*s == '#') s++;
        if (*s >= '0' && *s <= '9') { printf("\n"); details(atol(s), print_row, 30); printf("\n"); continue; }
        if (!strncmp(s, "f ", 2)) {
#ifdef TIMING                                   /* test builds: how long a file search takes */
            struct DateStamp t0, t1;
            DateStamp(&t0);
            n = search_files(s + 2, print_row, 20);
            DateStamp(&t1);
            printf("TIMING %ld ticks (1/50 s)\n", (t1.ds_Minute - t0.ds_Minute) * 3000L + t1.ds_Tick - t0.ds_Tick);
#else
            n = search_files(s + 2, print_row, 20);
#endif
        }
        else if (!strncmp(s, "favtunes", 8)) n = search_tunes(s[8] ? s + 9 : "", print_row, 20, 1);
        else if (!strncmp(s, "tunes", 5)) n = search_tunes(s[5] ? s + 6 : "", print_row, 20, 0);
        else if (!strncmp(s, "favs", 4)) {
            n = search_items(s[4] ? s + 5 : "", 'F', print_row, 20);
            n += search_tunes(s[4] ? s + 5 : "", print_row, 20, 1);
        }
        else if (!strncmp(s, "utils", 5)) n = search_items(s[5] ? s + 6 : "", 'U', print_row, 20);
        else if (!strcmp(s, "drives")) { drives(print_row); continue; }
        else if (!strncmp(s, "games", 5)) n = search_items(s[5] ? s + 6 : "", 'G', print_row, 20);
        else if (!strncmp(s, "music", 5)) n = search_items(s[5] ? s + 6 : "", 'M', print_row, 20);
        else if (!strncmp(s, "problems", 8)) n = search_items("", 'P', print_row, 20);
        else if (!strncmp(s, "insert ", 7) || !strncmp(s, "boot ", 5)) {
            int boot = s[0] == 'b';
            char *p = s + (boot ? 5 : 7), *sp;
            long drive = 0;
            if (*p == '#') p++;
            sp = strchr(p, ' ');
            if (sp) drive = atol(sp + 1);
            if (drive < 0 || drive > 3) drive = 0;
            insert(atol(p), drive, boot, msg);
            printf("%s\n", msg);
            continue;
        } else n = search_items(s, 0, print_row, 20);
        if (n == -3) { printf("Stopped.\n"); continue; }
        if (n == 0) printf("Nothing found.\n");
        else if (!strncmp(s, "f ", 2) && search_cut) printf("... and more on later disks. Type more of the name to narrow it down.\n");
        else if (n > 20) printf("... and %ld more. Type more of the name to narrow it down.\n", n - 20);
    }
}

/* ================================================================ Workbench window */

enum { GID_SEARCH = 1, GID_SHOW, GID_IN, GID_RESULTS, GID_DETAILS, GID_BOOT, GID_DF0, GID_DF1,
       GID_DRIVES, GID_STATUS };

struct Row { struct Node node; long number; char text[ROWLEN]; };

/* Allocated at start-up: vbcc 0.9h's optimiser miscalculates field addresses inside a static
   array of structures, so they are reached through pointers instead. */
static struct Row *rows, *lines;
static struct List row_list, line_list;
static int nrows, nlines;

static struct Screen *scr;
static struct Screen *own_scr;        /* TurboView's own screen (SCREEN option), or NULL */
static ULONG want_mode;               /* the screen mode asked for, 0 = use the Workbench screen */
static struct Window *win;
static APTR vi;
static struct Gadget *glist, *g_search, *g_show, *g_in, *g_results, *g_details, *g_boot, *g_df0,
                     *g_df1, *g_drives, *g_status;
static char search_text[128], last_text[128], status_text[200];
static int show_mode, in_mode, selected = -1, loadable, bootable, settle;
static long current = -1;
static int in_emulator;

static STRPTR show_labels[] = { "All", "Favourites", "Games", "Utilities", "Music", "Problems",
                                "Duplicates", NULL };
static STRPTR in_labels[] = { "Titles", "Files", "Tunes", NULL };
static const char show_flags[] = { 0, 'F', 'G', 'U', 'M', 'P', 'D' };
#define FAV_SHOW 1             /* Show: Favourites also works with In: Tunes (favourite tunes) */

static void new_list(struct List *l)
{
    l->lh_Head = (struct Node *)&l->lh_Tail;
    l->lh_Tail = NULL;
    l->lh_TailPred = (struct Node *)&l->lh_Head;
}

static void add_tail(struct List *l, struct Node *n)
{
    n->ln_Succ = (struct Node *)&l->lh_Tail;
    n->ln_Pred = l->lh_TailPred;
    l->lh_TailPred->ln_Succ = n;
    l->lh_TailPred = n;
}

/* Called through emit_fn pointers, so not static: vbcc may pass a static function's
   arguments in registers when optimising, which a call through a pointer doesn't do. */
void add_row(long number, const char *text)
{
    struct Row *r;
    if (nrows >= MAXROWS) return;
    r = &rows[nrows++];
    r->number = number;
    strncpy(r->text, text, ROWLEN - 1);
    r->text[ROWLEN - 1] = 0;
    r->node.ln_Name = r->text;
    add_tail(&row_list, &r->node);
}

void add_line(long number, const char *text)
{
    struct Row *r;
    if (nlines >= MAXLINES) return;
    r = &lines[nlines++];
    r->number = number;
    strncpy(r->text, text, ROWLEN - 1);
    r->text[ROWLEN - 1] = 0;
    r->node.ln_Name = r->text;
    add_tail(&line_list, &r->node);
}

static void set_attrs(struct Gadget *g, ULONG tag1, ULONG data1)
{
    struct TagItem t[2];
    if (!g || !win) return;
    t[0].ti_Tag = tag1; t[0].ti_Data = data1;
    t[1].ti_Tag = TAG_DONE;
    GT_SetGadgetAttrsA(g, win, NULL, t);
}

static void set_status(const char *text)
{
    strncpy(status_text, text, sizeof(status_text) - 1);
    set_attrs(g_status, GTTX_Text, (ULONG)status_text);
}

static void update_buttons(void)
{
    int can = loadable && in_emulator && current >= 0;
    set_attrs(g_boot, GA_Disabled, !(can && loadable == 2));
    set_attrs(g_df0, GA_Disabled, !can);
    set_attrs(g_df1, GA_Disabled, !can);
    set_attrs(g_drives, GA_Disabled, !in_emulator);
}

static void show_details(long number)
{
    set_attrs(g_details, GTLV_Labels, ~0UL);
    new_list(&line_list);
    nlines = 0;
    current = number;
    loadable = details(number, add_line, 200);
    set_attrs(g_details, GTLV_Labels, (ULONG)&line_list);
    set_attrs(g_details, GTLV_Top, 0);
    update_buttons();
}

/* While the packed file list is searched: show how far it has got, and stop if anything is
   waiting in the window's message port (a click, a key, the close gadget). */
static int win_fz_stop(unsigned long done, unsigned long of)
{
    char buf[100];
    if (!IsMsgPortEmpty(win->UserPort)) return 1;
    sprintf(buf, "Searching every file name: %lu%% (click or press a key to stop)",
            of ? done * 100 / of : 0);
    set_status(buf);
    return 0;
}

/* The window: newer floppies in a drive? Ask, and update in a window that shows how it goes. */
static void offer_update(void);

static void run_search(void)
{
    char buf[120];
    long total;
    strcpy(last_text, search_text);
    set_attrs(g_results, GTLV_Labels, ~0UL);
    new_list(&row_list);
    nrows = 0;
    selected = -1;
    if (in_mode == 1 && strlen(search_text) < 2) total = -2;
    else if (in_mode == 1) {
        fz_stop = win_fz_stop;
        total = search_files(search_text, add_row, MAXROWS);
        fz_stop = NULL;
    }
    else if (in_mode == 2) total = search_tunes(search_text, add_row, MAXROWS, show_mode == FAV_SHOW);
    else if (show_mode == FAV_SHOW) {
        /* Favourites: everything starred in TurboCAT, disks and games first, then tunes */
        long items = search_items(search_text, 'F', add_row, MAXROWS);
        long tunes = search_tunes(search_text, add_row, items < MAXROWS ? MAXROWS - items : 0, 1);
        total = items < 0 ? tunes : tunes < 0 ? items : items + tunes;
    }
    else total = search_items(search_text, show_flags[show_mode], add_row, MAXROWS);
    set_attrs(g_results, GTLV_Labels, (ULONG)&row_list);
    set_attrs(g_results, GTLV_Top, 0);
    if (total == -2) strcpy(buf, "Type at least 2 letters of a file name.");
    else if (total == -3) strcpy(buf, "Stopped. Searching every file name from a floppy is slow.");
    else if (total < 0) strcpy(buf, "The catalogue can't be read.");
    else if (total == 0 && show_mode == FAV_SHOW && !search_text[0])
        strcpy(buf, "No favourites yet: star disks or tunes in TurboCAT (Ctrl+D).");
    else if (total == 0) strcpy(buf, "Nothing found.");
    else if (in_mode == 1 && search_cut)
        sprintf(buf, "Showing the first %d; there are more on later disks. Type more to narrow it down.", MAXROWS);
    else if (total > MAXROWS) sprintf(buf, "%ld found; showing %d. Type more to narrow it down.", total, MAXROWS);
    else sprintf(buf, "%ld found.", total);
    set_status(buf);
    if (nrows) {
        selected = 0;
        set_attrs(g_results, GTLV_Selected, 0);
        show_details(rows[0].number);
    }
}

static struct Gadget *make(ULONG kind, struct Gadget *prev, struct NewGadget *ng, ULONG id,
                           WORD x, WORD y, WORD w, WORD h, STRPTR label, ULONG flags,
                           struct TagItem *tags)
{
    ng->ng_LeftEdge = x; ng->ng_TopEdge = y; ng->ng_Width = w; ng->ng_Height = h;
    ng->ng_GadgetText = label; ng->ng_GadgetID = id; ng->ng_Flags = flags;
    return CreateGadgetA(kind, prev, ng, tags);
}

/* Lay the window out for its current size. */
static int layout(void)
{
    struct NewGadget ng;
    struct Gadget *g;
    struct TagItem t[6];
    WORD left = win->BorderLeft + 4, top = win->BorderTop + 3;
    WORD w = win->Width - win->BorderLeft - win->BorderRight - 8;
    WORD h = win->Height - win->BorderTop - win->BorderBottom - 6;
    WORD fw = scr->RastPort.Font->tf_XSize, fh = scr->RastPort.Font->tf_YSize;
    WORD rowh = fh + 6, lab = 7 * fw + 8, cyw = 12 * fw + 24, bw, by, listh, resw, x;

    memset(&ng, 0, sizeof(ng));
    ng.ng_TextAttr = scr->Font;
    ng.ng_VisualInfo = vi;
    g = CreateContext(&glist);

    /* Search box and the two switches */
    t[0].ti_Tag = GTST_String; t[0].ti_Data = (ULONG)search_text;
    t[1].ti_Tag = GTST_MaxChars; t[1].ti_Data = sizeof(search_text) - 1;
    t[2].ti_Tag = TAG_DONE;
    x = left + lab;
    g = g_search = make(STRING_KIND, g, &ng, GID_SEARCH, x, top, w - lab - 2 * (cyw + lab), rowh,
                        "Search", PLACETEXT_LEFT, t);
    t[0].ti_Tag = GTCY_Labels; t[0].ti_Data = (ULONG)show_labels;
    t[1].ti_Tag = GTCY_Active; t[1].ti_Data = show_mode;
    t[2].ti_Tag = TAG_DONE;
    x = left + w - 2 * cyw - lab;
    g = g_show = make(CYCLE_KIND, g, &ng, GID_SHOW, x, top, cyw, rowh, "Show", PLACETEXT_LEFT, t);
    t[0].ti_Data = (ULONG)in_labels;
    t[1].ti_Data = in_mode;
    g = g_in = make(CYCLE_KIND, g, &ng, GID_IN, left + w - cyw, top, cyw, rowh, "In", PLACETEXT_LEFT, t);

    /* Results on the left, details on the right; then the status line and the buttons */
    by = top + h - rowh;                              /* button row */
    listh = by - rowh - 4 - (top + rowh + fh + 8) - 4;
    resw = w * 11 / 20;
    t[0].ti_Tag = GTLV_Labels; t[0].ti_Data = (ULONG)&row_list;
    t[1].ti_Tag = GTLV_ShowSelected; t[1].ti_Data = 0;
    t[2].ti_Tag = GTLV_Selected; t[2].ti_Data = selected < 0 ? ~0UL : selected;
    t[3].ti_Tag = TAG_DONE;
    g = g_results = make(LISTVIEW_KIND, g, &ng, GID_RESULTS, left, top + rowh + fh + 6, resw - 4, listh,
                         "Results", PLACETEXT_ABOVE, t);
    t[0].ti_Data = (ULONG)&line_list;
    t[1].ti_Tag = GTLV_ReadOnly; t[1].ti_Data = TRUE;
    t[2].ti_Tag = TAG_DONE;
    g = g_details = make(LISTVIEW_KIND, g, &ng, GID_DETAILS, left + resw + 4, top + rowh + fh + 6,
                         w - resw - 4, listh, "Details", PLACETEXT_ABOVE, t);

    /* Status line, then the buttons across the width */
    t[0].ti_Tag = GTTX_Text; t[0].ti_Data = (ULONG)status_text;
    t[1].ti_Tag = GTTX_Border; t[1].ti_Data = TRUE;
    t[2].ti_Tag = TAG_DONE;
    g = g_status = make(TEXT_KIND, g, &ng, GID_STATUS, left, by - rowh - 4, w, rowh, NULL, 0, t);
    bw = (w - 3 * 4) / 4;
    t[0].ti_Tag = GA_Disabled; t[0].ti_Data = TRUE;
    t[1].ti_Tag = GT_Underscore; t[1].ti_Data = '_';
    t[2].ti_Tag = TAG_DONE;
    g = g_boot = make(BUTTON_KIND, g, &ng, GID_BOOT, left, by, bw, rowh, "_Boot it", PLACETEXT_IN, t);
    g = g_df0 = make(BUTTON_KIND, g, &ng, GID_DF0, left + bw + 4, by, bw, rowh, "Into DF_0:", PLACETEXT_IN, t);
    g = g_df1 = make(BUTTON_KIND, g, &ng, GID_DF1, left + 2 * (bw + 4), by, bw, rowh, "Into DF_1:", PLACETEXT_IN, t);
    t[0].ti_Data = !in_emulator;
    g = g_drives = make(BUTTON_KIND, g, &ng, GID_DRIVES, left + 3 * (bw + 4), by, bw, rowh, "_Drives",
                        PLACETEXT_IN, t);
    if (!g) return 0;
    AddGList(win, glist, ~0, -1, NULL);
    RefreshGList(glist, win, NULL, -1);
    GT_RefreshWindow(win, NULL);
    update_buttons();
    return 1;
}

static void relayout(void)
{
    if (g_search) strcpy(search_text, ((struct StringInfo *)g_search->SpecialInfo)->Buffer);
    RemoveGList(win, glist, -1);
    FreeGadgets(glist);
    glist = NULL;
    if (win->Height < win->BorderTop + 60) {   /* zoomed to its title bar: no room for anything */
        g_search = NULL;
        RefreshWindowFrame(win);
        return;
    }
    SetAPen(win->RPort, 0);
    RectFill(win->RPort, win->BorderLeft, win->BorderTop, win->Width - win->BorderRight - 1,
             win->Height - win->BorderBottom - 1);
    RefreshWindowFrame(win);
    layout();
}

static void offer_update(void)
{
    struct EasyStruct es;
    char text[300], buf[120];
    APTR args[1];
    if (!win || !update_waiting()) return;
    sprintf(text, "Newer TurboView disks are in a drive\n(made %s; this TurboView has %s).\n\n"
                  "Update this TurboView from them now?\nIt takes a few minutes; it asks for disk 2.",
            newer, made);
    args[0] = text;
    es.es_StructSize = sizeof(es);
    es.es_Flags = 0;
    es.es_Title = "TurboView";
    es.es_TextFormat = (UBYTE *)"%s";
    es.es_GadgetFormat = "Update|Not now";
    if (EasyRequestArgs(win, &es, NULL, args) != 1) {
        strcpy(declined, newer);
        return;
    }
    say_to = fopen("CON:40/30/560/170/Updating TurboView/CLOSE/WAIT", "w");
    if (!say_to) say_to = stdout;
    set_status("Updating from the TurboView disks...");
    do_update();
    if (say_to != stdout) fclose(say_to);            /* WAIT: it stays until it is closed */
    say_to = NULL;
    sprintf(buf, "Updated: catalogue of %s, %ld items.", made, nitems);
    run_search();
    set_status(buf);
}

static int confirm(const char *text)
{
    struct EasyStruct es;
    es.es_StructSize = sizeof(es);
    es.es_Flags = 0;
    es.es_Title = "TurboView";
    es.es_TextFormat = (UBYTE *)"%s";
    es.es_GadgetFormat = "Restart|Cancel";
    return EasyRequestArgs(win, &es, NULL, (APTR)&text) == 1;
}

static void do_insert(long drive, int boot)
{
    char msg[300], q[200];
    if (current < 0) return;
    if (boot) {
        sprintf(q, "Put #%04ld in DF0: and restart the Amiga into it?", current);
        if (!confirm(q)) return;
    }
    insert(current, drive, boot, msg);
    set_status(msg);
}

static void show_drives(void)
{
    set_attrs(g_details, GTLV_Labels, ~0UL);
    new_list(&line_list);
    nlines = 0;
    drives(add_line);
    set_attrs(g_details, GTLV_Labels, (ULONG)&line_list);
}

static void release_screen(void)
{
    if (own_scr) { CloseScreen(own_scr); own_scr = NULL; }
    else if (scr) UnlockPubScreen(NULL, scr);
    scr = NULL;
}

static int gui(void)
{
    struct TagItem t[15];
    static WORD zoom[4];
    WORD ww, wh;
    int done = 0;
    ULONG lastsecs = 0, lastmicros = 0;

    rows = malloc(sizeof(struct Row) * MAXROWS);
    lines = malloc(sizeof(struct Row) * MAXLINES);
    if (!rows || !lines) return 0;
    if (want_mode) {
        /* Its own screen at a higher resolution, so the window isn't blown up to fill a big
           monitor: 640x512 or 1280x512 (both built into Kickstart 3 on ECS/AGA Amigas). */
        static UWORD pens[] = { (UWORD)~0 };
        struct TagItem st[9];
        ULONG id = want_mode;
        if (ModeNotAvailable(id)) id = PAL_MONITOR_ID | HIRESLACE_KEY;
        if (ModeNotAvailable(id)) id = HIRESLACE_KEY;
        st[0].ti_Tag = SA_DisplayID;  st[0].ti_Data = id;
        st[1].ti_Tag = SA_Depth;      st[1].ti_Data = 2;
        st[2].ti_Tag = SA_Title;      st[2].ti_Data = (ULONG)"TurboView 4";
        st[3].ti_Tag = SA_Pens;       st[3].ti_Data = (ULONG)pens;
        st[4].ti_Tag = SA_FullPalette; st[4].ti_Data = TRUE;
        st[5].ti_Tag = SA_ShowTitle;  st[5].ti_Data = TRUE;
        st[6].ti_Tag = SA_Interleaved; st[6].ti_Data = TRUE;
        st[7].ti_Tag = TAG_DONE;
        own_scr = OpenScreenTagList(NULL, st);
    }
    scr = own_scr ? own_scr : LockPubScreen(NULL);
    if (!scr) return 0;
    if (!(vi = GetVisualInfoA(scr, NULL))) { release_screen(); return 0; }
    new_list(&row_list);
    new_list(&line_list);
    ww = scr->Width > 720 ? 720 : scr->Width;
    wh = scr->Height - scr->BarHeight - 1;
    if (wh > 460) wh = 460;
    if (own_scr) {                       /* a comfortable window in the middle of the big screen */
        ww = scr->Width >= 1280 ? 760 : 600;
        wh = scr->Height >= 480 ? 400 : wh;
    }
    t[0].ti_Tag = WA_Title;       t[0].ti_Data = (ULONG)"TurboView 4 - TurboCAT catalogue";
    t[1].ti_Tag = WA_Left;        t[1].ti_Data = (scr->Width - ww) / 2;
    t[2].ti_Tag = WA_Top;         t[2].ti_Data = own_scr ? (scr->Height - wh) / 2 : scr->BarHeight + 1;
    t[3].ti_Tag = WA_Width;       t[3].ti_Data = ww;
    t[4].ti_Tag = WA_Height;      t[4].ti_Data = wh;
    t[5].ti_Tag = own_scr ? WA_CustomScreen : WA_PubScreen;   t[5].ti_Data = (ULONG)scr;
    t[6].ti_Tag = WA_Flags;       t[6].ti_Data = WFLG_CLOSEGADGET | WFLG_DRAGBAR | WFLG_DEPTHGADGET |
                                                 WFLG_SIZEGADGET | WFLG_ACTIVATE | WFLG_SMART_REFRESH;
    t[7].ti_Tag = WA_IDCMP;       t[7].ti_Data = IDCMP_CLOSEWINDOW | IDCMP_REFRESHWINDOW | IDCMP_NEWSIZE |
                                                 IDCMP_DISKINSERTED |
                                                 IDCMP_INTUITICKS | IDCMP_VANILLAKEY | LISTVIEWIDCMP |
                                                 STRINGIDCMP | CYCLEIDCMP | BUTTONIDCMP;
    t[8].ti_Tag = WA_MinWidth;    t[8].ti_Data = 480;
    t[9].ti_Tag = WA_MinHeight;   t[9].ti_Data = 160;
    t[10].ti_Tag = WA_MaxWidth;   t[10].ti_Data = ~0UL;
    t[11].ti_Tag = WA_MaxHeight;  t[11].ti_Data = ~0UL;
    /* The zoom gadget shrinks TurboView to its title bar, out of the way until it is wanted again */
    zoom[0] = t[1].ti_Data; zoom[1] = t[2].ti_Data; zoom[2] = 300; zoom[3] = scr->BarHeight + 1;
    t[12].ti_Tag = WA_Zoom;       t[12].ti_Data = (ULONG)zoom;
    t[13].ti_Tag = TAG_DONE;
    win = OpenWindowTagList(NULL, t);
    if (!win) { FreeVisualInfo(vi); release_screen(); return 0; }

    in_emulator = find_uae();
    sprintf(status_text, "Catalogue of %s, %ld items.", made, nitems);
    if (!layout()) done = 1;
    run_search();
    offer_update();
    ActivateGadget(g_search, win, NULL);

    while (!done) {
        struct IntuiMessage *msg;
        Wait(1L << win->UserPort->mp_SigBit);
        while (!done && (msg = GT_GetIMsg(win->UserPort))) {
            ULONG class = msg->Class, secs = msg->Seconds, micros = msg->Micros;
            UWORD code = msg->Code;
            struct Gadget *gad = (struct Gadget *)msg->IAddress;
            GT_ReplyIMsg(msg);
            switch (class) {
            case IDCMP_DISKINSERTED:
                offer_update();
                break;
            case IDCMP_CLOSEWINDOW:
                done = 1;
                break;
            case IDCMP_REFRESHWINDOW:
                GT_BeginRefresh(win);
                GT_EndRefresh(win, TRUE);
                break;
            case IDCMP_NEWSIZE:
                relayout();
                break;
            case IDCMP_INTUITICKS:
                /* search as you type, once typing pauses */
                if (g_search && strcmp(((struct StringInfo *)g_search->SpecialInfo)->Buffer, last_text)) {
                    if (++settle >= 3) {
                        settle = 0;
                        strcpy(search_text, ((struct StringInfo *)g_search->SpecialInfo)->Buffer);
                        run_search();
                    }
                } else settle = 0;
                break;
            case IDCMP_VANILLAKEY:
                if (code == 27) done = 1;
                else if ((code == 'b' || code == 'B') && !(g_boot->Flags & GFLG_DISABLED)) do_insert(0, 1);
                else if (code == '0' && !(g_df0->Flags & GFLG_DISABLED)) do_insert(0, 0);
                else if (code == '1' && !(g_df1->Flags & GFLG_DISABLED)) do_insert(1, 0);
                else if (code == 'd' || code == 'D') { if (in_emulator) show_drives(); }
                else ActivateGadget(g_search, win, NULL);
                break;
            case IDCMP_GADGETUP:
                switch (gad->GadgetID) {
                case GID_SEARCH:
                    strcpy(search_text, ((struct StringInfo *)g_search->SpecialInfo)->Buffer);
                    run_search();
                    break;
                case GID_SHOW:
                    show_mode = code;
                    if (show_mode && in_mode && !(show_mode == FAV_SHOW && in_mode == 2)) {
                        in_mode = 0; set_attrs(g_in, GTCY_Active, 0);
                    }
                    run_search();
                    break;
                case GID_IN:
                    in_mode = code;
                    if (in_mode && show_mode && !(show_mode == FAV_SHOW && in_mode == 2)) {
                        show_mode = 0; set_attrs(g_show, GTCY_Active, 0);
                    }
                    run_search();
                    break;
                case GID_RESULTS:
                    if (code < nrows) {
                        if ((int)code == selected && DoubleClick(lastsecs, lastmicros, secs, micros)) {
                            if (loadable == 2 && in_emulator) do_insert(0, 1);  /* double-click: boot */
                        } else {
                            selected = code;
                            show_details(rows[code].number);
                        }
                        lastsecs = secs; lastmicros = micros;
                    }
                    break;
                case GID_BOOT:   do_insert(0, 1); break;
                case GID_DF0:    do_insert(0, 0); break;
                case GID_DF1:    do_insert(1, 0); break;
                case GID_DRIVES: show_drives(); break;
                }
                break;
            }
        }
    }
    RemoveGList(win, glist, -1);
    CloseWindow(win);
    FreeGadgets(glist);
    FreeVisualInfo(vi);
    release_screen();
    return 1;
}

/* ================================================================ start */

/* ---------------------------------------------------------------- started from Workbench */

/* A message for someone who started TurboView from its icon: there's no Shell to print in. */
static void wb_say(const char *text)
{
    struct IntuitionBase *ib = (struct IntuitionBase *)OpenLibrary("intuition.library", 33);
    if (!ib) return;
    if (ib->LibNode.lib_Version >= 36) {
        struct EasyStruct es;
        struct IntuitionBase *keep = IntuitionBase;
        IntuitionBase = ib;
        es.es_StructSize = sizeof(es);
        es.es_Flags = 0;
        es.es_Title = "TurboView";
        es.es_TextFormat = (UBYTE *)"%s";
        es.es_GadgetFormat = "OK";
        EasyRequestArgs(NULL, &es, NULL, (APTR)&text);
        IntuitionBase = keep;
    } else {                                  /* Kickstart 1.3: the old kind of requester */
        struct IntuiText body = { 0, 1, JAM2, 16, 8, NULL, NULL, NULL };
        struct IntuiText ok = { 0, 1, JAM2, 6, 3, NULL, (UBYTE *)"OK", NULL };
        struct IntuitionBase *keep = IntuitionBase;
        body.IText = (UBYTE *)text;
        IntuitionBase = ib;
        AutoRequest(NULL, &body, NULL, &ok, 0, 0, 620, 70);
        IntuitionBase = keep;
    }
    CloseLibrary((struct Library *)ib);
}

/* Started from the icon: the catalogue is in the drawer TurboView is in, unless its CATALOGUE
   tooltype says otherwise; SCREEN=HIGH/SUPER and FAVOURITES work as tooltypes too. */
static void wb_start(struct WBStartup *wb)
{
    struct DiskObject *dobj;
    catdir[0] = 0;                            /* "" = the current drawer, TurboView's own */
    if (wb->sm_NumArgs < 1) return;
    CurrentDir(wb->sm_ArgList[0].wa_Lock);
    if (!(IconBase = OpenLibrary("icon.library", 33))) return;
    if ((dobj = GetDiskObject(wb->sm_ArgList[0].wa_Name))) {
        char *v;
        if ((v = (char *)FindToolType((STRPTR *)dobj->do_ToolTypes, "CATALOGUE")) && *v) {
            strncpy(catdir, v, sizeof(catdir) - 2);
            catdir[sizeof(catdir) - 2] = 0;
            if (catdir[strlen(catdir) - 1] != ':' && catdir[strlen(catdir) - 1] != '/') strcat(catdir, "/");
        }
        if ((v = (char *)FindToolType((STRPTR *)dobj->do_ToolTypes, "SCREEN")))
            want_mode = (*v == 'S' || *v == 's') ? (PAL_MONITOR_ID | SUPERLACE_KEY)
                                                 : (PAL_MONITOR_ID | HIRESLACE_KEY);
        if (FindToolType((STRPTR *)dobj->do_ToolTypes, "FAVOURITES")) show_mode = FAV_SHOW;
        FreeDiskObject(dobj);
    }
}

/* ---------------------------------------------------------------- INSTALL to a hard drive
   "TurboView:TurboView INSTALL DH0:TurboCAT": copies TurboView and its lists from the TurboView
   floppies into a drawer, and unpacks the packed list of files there (so contents and searches are
   quick from the hard drive). Uses only TurboView itself: a TurboView floppy has no C: commands. */

static int copy_file(const char *from, const char *to)
{
    static char buf[8192];
    FILE *a = fopen(from, "r"), *b;
    size_t n;
    int ok = 1;
    if (!a) return 0;
    if (!(b = fopen(to, "w"))) { fclose(a); return 0; }
    while ((n = fread(buf, 1, sizeof(buf), a)) > 0)
        if (fwrite(buf, 1, n, b) != n) { ok = 0; break; }
    fclose(a);
    if (fclose(b)) ok = 0;
    return ok;
}

struct unpack_to { FILE *fil, *idx; long disk, lines; };

static int unpacked_line(long disk, const char *path, void *ctx)
{
    struct unpack_to *u = ctx;
    if (disk != u->disk) {                         /* the index says where each disk starts */
        fprintf(u->idx, "%ld\t%ld\n", disk, ftell(u->fil));
        u->disk = disk;
    }
    fprintf(u->fil, "F\t%ld\t%s\t-\n", disk, path);         /* sizes weren't on the floppy */
    u->lines++;
    return 1;
}

/* The installed TurboView's icon, with CATALOGUE= pointing at its drawer (so it works wherever
   the icon is dragged, e.g. into WBStartup), and an icon for the drawer if it hasn't one. */
static FILE *say_to;                  /* where INSTALL / UPDATE reports (stdout, or a window) */

static int exists_quiet(const char *path)
{
    FILE *f = fopen_quiet(path, "r");
    if (f) fclose(f);
    return f != NULL;
}

/* Icons for the installed TurboView. An icon that is already there is kept as it is: an update
   mustn't lose tooltypes or a position someone set. A new TurboView icon gets CATALOGUE= pointing at
   its drawer (so it works wherever it is dragged, e.g. into WBStartup). Returns 1 if TurboView has
   an icon afterwards. */
static int install_icons(const char *dest, const char *dir)
{
    char to[260], tool[260];
    STRPTR types[4];
    struct DiskObject *dobj;
    int n = strlen(dest);
    if (n && dest[n - 1] != ':' && dest[n - 1] != '/') {   /* a drawer, not a whole disk */
        sprintf(to, "%s.info", dest);
        if (!exists_quiet(to) && copy_file("TurboView:S/Drawer.icon", to))
            fprintf(say_to, "  %s (the drawer's icon)\n", to);
    }
    sprintf(to, "%sTurboView.info", dir);
    if (exists_quiet(to)) return 1;                        /* kept, with its tooltypes */
    if ((!IconBase && !(IconBase = OpenLibrary("icon.library", 33)))
            || !(dobj = GetDiskObject("TurboView:TurboView"))) {
        /* the floppy's own icon: from Workbench, TurboView then reads the drawer it is in */
        if (copy_file("TurboView:TurboView.info", to)) { fprintf(say_to, "  %s (TurboView's icon)\n", to); return 1; }
        fprintf(say_to, "  TurboView has no icon: start it from a Shell.\n");
        return 0;
    }
    sprintf(tool, "CATALOGUE=%s", dest);
    types[0] = (STRPTR)tool;
    types[1] = (STRPTR)"(SCREEN=HIGH)";       /* in brackets: off until the brackets are removed */
    types[2] = (STRPTR)"(FAVOURITES)";
    types[3] = NULL;
    {
        STRPTR *keep = dobj->do_ToolTypes;
        dobj->do_ToolTypes = types;
        dobj->do_CurrentX = dobj->do_CurrentY = NO_ICON_POSITION;
        sprintf(to, "%sTurboView", dir);
        n = PutDiskObject(to, dobj) ? 1 : 0;
        if (n) fprintf(say_to, "  %s.info (TurboView's icon, CATALOGUE=%s)\n", to, dest);
        dobj->do_ToolTypes = keep;
    }
    FreeDiskObject(dobj);
    return n;
}

/* Install from the TurboView floppies into dest, or update an earlier install there: copies disk
   1, unpacks its packed list of files, copies disk 2's search index, and updates a copy of the
   program someone dragged into WBStartup. Returns 0 when all went well. */
static int install(const char *dest)
{
    char to[260], from[260], dir[220];
    static const char *disk1[] = { "TurboView", "TurboCAT.cat", "TurboCAT.mus", "ReadMe",
                                   "TurboCAT.fil", "TurboCAT.idx", NULL };
    BPTR lock;
    int i, n = strlen(dest), full_list = 0;
    if (!say_to) say_to = stdout;
    strncpy(dir, dest, sizeof(dir) - 2);
    dir[sizeof(dir) - 2] = 0;
    if (n && dir[strlen(dir) - 1] != ':' && dir[strlen(dir) - 1] != '/') strcat(dir, "/");
    fprintf(say_to, "Installing TurboView in %s\n", *dest ? dest : "its own drawer");
    if (*dest) {
        if ((lock = Lock((STRPTR)dest, ACCESS_READ))) UnLock(lock);
        else if ((lock = CreateDir((STRPTR)dest))) UnLock(lock);
        else { fprintf(say_to, "Can't make the drawer %s.\n", dest); return 20; }
    }

    fprintf(say_to, "Copying from disk 1 (TurboView)...\n");
    for (i = 0; disk1[i]; i++) {
        sprintf(from, "TurboView:%s", disk1[i]);
        sprintf(to, "%s%s", dir, disk1[i]);
        if (copy_file(from, to)) {
            fprintf(say_to, "  %s\n", disk1[i]);
            if (i == 4) full_list = 1;              /* the full list was on the floppy as it is */
        } else if (i < 2) {
            fprintf(say_to, "Can't copy %s: is disk 1 (TurboView) in a drive?\n", from);
            return 20;
        }
    }
    sprintf(to, "%sTurboCAT.fil", dir);
    strcpy(catdir, "TurboView:");
    fz_state = 0;
    if (!full_list && fz_open()) {                  /* packed on the floppy: unpack it here */
        struct unpack_to u;
        unsigned long b;
        u.fil = fopen(to, "w");
        sprintf(from, "%sTurboCAT.idx", dir);
        u.idx = fopen(from, "w");
        u.disk = -1; u.lines = 0;
        if (!u.fil || !u.idx) {
            if (u.fil) fclose(u.fil);
            if (u.idx) fclose(u.idx);
            fprintf(say_to, "Can't write the list of files in %s.\n", dest);
            return 20;
        }
        for (b = 0; b < fz_n; b++) {
            fprintf(say_to, "\rUnpacking the list of every file: %lu%%  ", (b + 1) * 100 / fz_n);
            fflush(say_to);
            if (fz_stopped(b)) { fprintf(say_to, "\nStopped.\n"); fclose(u.fil); fclose(u.idx); return 5; }
            fz_each(b, unpacked_line, &u);
        }
        fclose(u.fil);
        fclose(u.idx);
        fprintf(say_to, "\r%ld files listed.                          \n", u.lines);
    }
    fprintf(say_to, "Copying the search index from disk 2 (TurboView2): put it in a drive if asked...\n");
    sprintf(to, "%sTurboCAT.nix", dir);
    if (copy_file("TurboView2:TurboCAT.nix", to)) fprintf(say_to, "  TurboCAT.nix\n");
    else {
        DeleteFile((STRPTR)to);                     /* an old index wouldn't match the new lists */
        fprintf(say_to, "  Disk 2 wasn't there: TurboView still works, its file searches are just slower.\n"
                        "  Install again with disk 2 to hand to speed them up.\n");
    }
    /* Someone may have dragged TurboView into WBStartup (which moves the program there) */
    if (exists_quiet("SYS:WBStartup/TurboView.info") && exists_quiet("SYS:WBStartup/TurboView")
            && copy_file("TurboView:TurboView", "SYS:WBStartup/TurboView"))
        fprintf(say_to, "  SYS:WBStartup/TurboView (the copy that starts with Workbench)\n");
    if (install_icons(dest, dir))
        fprintf(say_to, "\nDone. Start it by double-clicking TurboView in %s, or from a Shell:\n  %sTurboView %s\n",
                *dest ? dest : "its drawer", dir, dest);
    else
        fprintf(say_to, "\nDone. Start it from a Shell:\n  %sTurboView %s\n", dir, dest);
    fprintf(say_to, "\nThe hard drive install is new and experimental. Please tell us how it went:\n"
                    "in TurboCAT, Help > How TurboView went on your Amiga.\n");
    return 0;
}

int main(int argc, char **argv)
{
    int want_shell = 0, i, ok = 0;
    char *install_to = NULL;
    if (argc == 0) {                         /* started from Workbench: argv is its message */
        from_wb = 1;
        wb_start((struct WBStartup *)argv);
    }
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "SHELL") || !strcmp(argv[i], "shell")) want_shell = 1;
        else if ((!strcmp(argv[i], "INSTALL") || !strcmp(argv[i], "install")) && i + 1 < argc)
            install_to = argv[++i];
        else if (!strcmp(argv[i], "FAVOURITES") || !strcmp(argv[i], "favourites")) show_mode = FAV_SHOW;
        /* SCREEN=HIGH (640x512) or SCREEN=SUPER (1280x512): open on its own, sharper screen */
        else if (!strncmp(argv[i], "SCREEN=", 7) || !strncmp(argv[i], "screen=", 7))
            want_mode = (argv[i][7] == 'S' || argv[i][7] == 's') ? (PAL_MONITOR_ID | SUPERLACE_KEY)
                                                                  : (PAL_MONITOR_ID | HIRESLACE_KEY);
        else {
            strncpy(catdir, argv[i], sizeof(catdir) - 2);
            if (catdir[strlen(catdir) - 1] != ':' && catdir[strlen(catdir) - 1] != '/') strcat(catdir, "/");
        }
    }
    init_lc();
    if (install_to) return install(install_to);
    if (!load_header()) {
        if (from_wb) {
            wb_say("TurboView can't find its catalogue (TurboCAT.cat).\n"
                   "Put TurboView in the drawer TurboCAT made, or set the\n"
                   "CATALOGUE tooltype in its icon, e.g. CATALOGUE=DH0:TurboCAT");
            return 20;
        }
        printf("TurboView: no catalogue found in %s\n"
               "TurboCAT writes it there; start TurboView from TurboCAT, or give the folder:\n"
               "  TurboView DH1:TurboCAT\n", catdir);
        return 20;
    }
    if (!want_shell) {
        IntuitionBase = (struct IntuitionBase *)OpenLibrary("intuition.library", 37);
        GfxBase = (struct GfxBase *)OpenLibrary("graphics.library", 37);
        GadToolsBase = OpenLibrary("gadtools.library", 37);
        if (IntuitionBase && GfxBase && GadToolsBase) ok = gui();
        if (GadToolsBase) CloseLibrary(GadToolsBase);
        if (GfxBase) CloseLibrary((struct Library *)GfxBase);
        if (IntuitionBase) CloseLibrary((struct Library *)IntuitionBase);
    }
    if (!ok && from_wb) {
        wb_say("TurboView's window needs Kickstart 2.04 or later.\n"
               "On this Amiga, start it from a Shell instead, e.g.\n"
               "  DH0:TurboCAT/TurboView DH0:TurboCAT SHELL");
    } else if (!ok) {
        printf("\nTurboView 4 - the Amiga side of TurboCAT 4\n");
        shell();
    }
    if (IconBase) CloseLibrary(IconBase);
    return 0;
}
