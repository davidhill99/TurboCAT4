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
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/intuition.h>
#include <proto/graphics.h>
#include <proto/gadtools.h>

static const char version[] = "\0$VER: TurboView 4.0 alpha 2 (9.11.2026)";

long __stack = 40000;            /* the boot Shell's default 4 KB is too little for GadTools */

struct IntuitionBase *IntuitionBase;
struct GfxBase *GfxBase;
struct Library *GadToolsBase;

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
    if (*(unsigned short *)0xF0FF60 == 0x4EB9) {
        uae = (uaecall)0xF0FF60;
        return 1;
    }
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
            sprintf(buf, "#%04ld %c %s", atol(fl[1]), strchr(fl[2], 'G') ? '*' : ' ', name);
            emit(atol(fl[1]), buf);
        }
        total++;
    }
    fclose(f);
    return total;
}

static long search_files(const char *text, emit_fn emit, long max)
{
    FILE *f = open_cat("TurboCAT.fil");
    char *fl[5], buf[ROWLEN];
    long total = 0;
    if (!f) return -1;
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

static long search_tunes(const char *text, emit_fn emit, long max)
{
    FILE *f = open_cat("TurboCAT.mus");
    char *tf[7], buf[ROWLEN];
    long total = 0;
    if (!f) return -1;
    set_needle(text);
    while (fgets(line, LINE, f)) {
        chomp(line);
        if (fields(line, tf, 7) < 6 || (!contains(tf[2], text) && !contains(tf[5], text))) continue;
        if (total < max) {
            long s = atol(tf[4]);
            sprintf(buf, "#%04ld %-30.30s %ld:%02ld %.20s", atol(tf[1]), tf[2], s / 60, s % 60, tf[3]);
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
    sprintf(buf, "PC:     %.250s", fl[6]); emit(number, buf);
    amiga_path(fl[6], apath);
    if (apath[0]) { sprintf(buf, "Amiga:  %.250s", apath); emit(number, buf); }
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
        char *tf[7];
        int tunes = 0;
        emit(number, "");
        emit(number, "Music:");
        while (fgets(line, LINE, f)) {
            chomp(line);
            if (fields(line, tf, 7) < 6 || atol(tf[1]) != number) continue;
            if (tunes < 40) {
                long s = atol(tf[4]);
                sprintf(buf, "  %-30.30s %ld:%02ld %.20s", tf[2], s / 60, s % 60, tf[3]);
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

static void shell(void)
{
    static char input[256], msg[300];
    printf("Catalogue of %s, %ld items.%s Type ? for help.\n\n", made, nitems,
           find_uae() ? " Running in an emulator: disks can be inserted." : "");
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
        if (!strcmp(s, "?") || !strcmp(s, "help")) {
            printf("\nType part of a name to search titles and disk names, or:\n"
                   "  9            details of #0009\n"
                   "  f name       find a file on any disk\n"
                   "  tunes name   find a music module by its title\n"
                   "  games name   only games       music name   only disks with music\n"
                   "  problems     disks with problems\n"
                   "  insert 9     put #0009 in DF0: (\"insert 9 1\" for DF1:)\n"
                   "  boot 9       put #0009 in DF0: and restart into it\n"
                   "  drives       what is in DF0:-DF3: (in an emulator)\n"
                   "  q            quit\n\n");
            continue;
        }
        if (*s == '#') s++;
        if (*s >= '0' && *s <= '9') { printf("\n"); details(atol(s), print_row, 30); printf("\n"); continue; }
        if (!strncmp(s, "f ", 2)) n = search_files(s + 2, print_row, 20);
        else if (!strncmp(s, "tunes", 5)) n = search_tunes(s[5] ? s + 6 : "", print_row, 20);
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
        if (n == 0) printf("Nothing found.\n");
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
static struct Window *win;
static APTR vi;
static struct Gadget *glist, *g_search, *g_show, *g_in, *g_results, *g_details, *g_boot, *g_df0,
                     *g_df1, *g_drives, *g_status;
static char search_text[128], last_text[128], status_text[200];
static int show_mode, in_mode, selected = -1, loadable, bootable, settle;
static long current = -1;
static int in_emulator;

static STRPTR show_labels[] = { "All", "Games", "Music", "Problems", "Duplicates", NULL };
static STRPTR in_labels[] = { "Titles", "Files", "Tunes", NULL };
static const char show_flags[] = { 0, 'G', 'M', 'P', 'D' };

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
    else if (in_mode == 1) total = search_files(search_text, add_row, MAXROWS);
    else if (in_mode == 2) total = search_tunes(search_text, add_row, MAXROWS);
    else total = search_items(search_text, show_flags[show_mode], add_row, MAXROWS);
    set_attrs(g_results, GTLV_Labels, (ULONG)&row_list);
    set_attrs(g_results, GTLV_Top, 0);
    if (total == -2) strcpy(buf, "Type at least 2 letters of a file name.");
    else if (total < 0) strcpy(buf, "The catalogue can't be read.");
    else if (total == 0) strcpy(buf, "Nothing found.");
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
    SetAPen(win->RPort, 0);
    RectFill(win->RPort, win->BorderLeft, win->BorderTop, win->Width - win->BorderRight - 1,
             win->Height - win->BorderBottom - 1);
    RefreshWindowFrame(win);
    layout();
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

static int gui(void)
{
    struct TagItem t[14];
    WORD ww, wh;
    int done = 0;
    ULONG lastsecs = 0, lastmicros = 0;

    rows = malloc(sizeof(struct Row) * MAXROWS);
    lines = malloc(sizeof(struct Row) * MAXLINES);
    if (!rows || !lines) return 0;
    if (!(scr = LockPubScreen(NULL))) return 0;
    if (!(vi = GetVisualInfoA(scr, NULL))) { UnlockPubScreen(NULL, scr); return 0; }
    new_list(&row_list);
    new_list(&line_list);
    ww = scr->Width > 720 ? 720 : scr->Width;
    wh = scr->Height - scr->BarHeight - 1;
    if (wh > 460) wh = 460;
    t[0].ti_Tag = WA_Title;       t[0].ti_Data = (ULONG)"TurboView 4 - TurboCAT catalogue";
    t[1].ti_Tag = WA_Left;        t[1].ti_Data = (scr->Width - ww) / 2;
    t[2].ti_Tag = WA_Top;         t[2].ti_Data = scr->BarHeight + 1;
    t[3].ti_Tag = WA_Width;       t[3].ti_Data = ww;
    t[4].ti_Tag = WA_Height;      t[4].ti_Data = wh;
    t[5].ti_Tag = WA_PubScreen;   t[5].ti_Data = (ULONG)scr;
    t[6].ti_Tag = WA_Flags;       t[6].ti_Data = WFLG_CLOSEGADGET | WFLG_DRAGBAR | WFLG_DEPTHGADGET |
                                                 WFLG_SIZEGADGET | WFLG_ACTIVATE | WFLG_SMART_REFRESH;
    t[7].ti_Tag = WA_IDCMP;       t[7].ti_Data = IDCMP_CLOSEWINDOW | IDCMP_REFRESHWINDOW | IDCMP_NEWSIZE |
                                                 IDCMP_INTUITICKS | IDCMP_VANILLAKEY | LISTVIEWIDCMP |
                                                 STRINGIDCMP | CYCLEIDCMP | BUTTONIDCMP;
    t[8].ti_Tag = WA_MinWidth;    t[8].ti_Data = 480;
    t[9].ti_Tag = WA_MinHeight;   t[9].ti_Data = 160;
    t[10].ti_Tag = WA_MaxWidth;   t[10].ti_Data = ~0UL;
    t[11].ti_Tag = WA_MaxHeight;  t[11].ti_Data = ~0UL;
    t[12].ti_Tag = TAG_DONE;
    win = OpenWindowTagList(NULL, t);
    if (!win) { FreeVisualInfo(vi); UnlockPubScreen(NULL, scr); return 0; }

    in_emulator = find_uae();
    sprintf(status_text, "Catalogue of %s, %ld items.", made, nitems);
    if (!layout()) done = 1;
    run_search();
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
                    if (show_mode && in_mode) { in_mode = 0; set_attrs(g_in, GTCY_Active, 0); }
                    run_search();
                    break;
                case GID_IN:
                    in_mode = code;
                    if (in_mode && show_mode) { show_mode = 0; set_attrs(g_show, GTCY_Active, 0); }
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
    UnlockPubScreen(NULL, scr);
    return 1;
}

/* ================================================================ start */

int main(int argc, char **argv)
{
    int want_shell = 0, i, ok = 0;
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "SHELL") || !strcmp(argv[i], "shell")) want_shell = 1;
        else {
            strncpy(catdir, argv[i], sizeof(catdir) - 2);
            if (catdir[strlen(catdir) - 1] != ':' && catdir[strlen(catdir) - 1] != '/') strcat(catdir, "/");
        }
    }
    init_lc();
    if (!load_header()) {
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
    if (!ok) {
        printf("\nTurboView 4 - the Amiga side of TurboCAT 4\n");
        shell();
    }
    return 0;
}
