* Glue between TurboView (C, vbcc) and Keir Fraser's inflate.asm (public domain,
* github.com/keirf/amiga-stuff): unpacks one block of the packed file list.
*
*   void fast_inflate(unsigned char *out, const unsigned char *in, void *work_end);
*
* work_end is the END of a 2928-byte work area: inflate keeps its tables there rather than on
* the stack, because Kickstart 1.3 can't give TurboView a bigger stack (StackSwap is 2.0+), and
* the boot Shell's 4 KB is too little for TurboView and inflate's ~3 KB together.
* vbcc passes arguments on the stack; inflate wants a4 = output, a5 = raw DEFLATE input,
* a6 = end of the work area, and keeps every register, so only a4-a6 need saving here.

OPT_STORAGE_OFFSTACK = 1

        section code,code
        xdef    _fast_inflate

_fast_inflate:
        movem.l a4-a6,-(sp)
        move.l  16(sp),a4
        move.l  20(sp),a5
        move.l  24(sp),a6
        bsr     inflate
        movem.l (sp)+,a4-a6
        rts

        include "inflate.asm"
