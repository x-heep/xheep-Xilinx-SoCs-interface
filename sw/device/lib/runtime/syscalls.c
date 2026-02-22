/* An extremely minimalist syscalls.c for newlib
 * Based on riscv newlib libgloss/riscv/sys_*.c
 *
 * Copyright 2019 Clifford Wolf
 * Copyright 2019 ETH Zürich and University of Bologna
 *
 * Permission to use, copy, modify, and/or distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
 * REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
 * INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
 * LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
 * OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
 * PERFORMANCE OF THIS SOFTWARE.
 */

#ifdef __cplusplus
extern "C" {
#endif


#include "syscalls.h"
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/time.h>
#include <sys/times.h>
#include <utime.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

/* <sys/timeb.h> is not available in picolibc; forward-declare the struct
   since _ftime is a stub that never dereferences the pointer. */
struct timeb;
#include "uart.h"
#include "soc_ctrl.h"
#include "core_v_mini_mcu.h"
#include "error.h"
#include "x-heep.h"

#define STDOUT_FILENO 1

#ifndef _LIBC
/* Provide prototypes for most of the _<systemcall> names that are
   provided in newlib for some compilers.  */
int     _close (int __fildes);
pid_t   _fork (void);
pid_t   _getpid (void);
int     _isatty (int __fildes);
int     _link (const char *__path1, const char *__path2);
off_t   _lseek (int __fildes, off_t __offset, int __whence);
int     _read (int __fd, void *__buf, int __nbyte);
void *  _sbrk (ptrdiff_t __incr);
int     _brk(void *addr);
int     _unlink (const char *__path);
int     _execve (const char *__path, char * const __argv[], char * const __envp[]);
int     _kill (pid_t pid, int sig);
void    _writestr(const void *ptr); // Not a standard function
#endif


void unimplemented_syscall()
{
    _writestr("Unimplemented system call called!\n");
}

int nanosleep(const struct timespec *rqtp, struct timespec *rmtp)
{
    errno = ENOSYS;
    return -1;
}

int _access(const char *file, int mode)
{
    errno = ENOSYS;
    return -1;
}

int _chdir(const char *path)
{
    errno = ENOSYS;
    return -1;
}

int _chmod(const char *path, mode_t mode)
{
    errno = ENOSYS;
    return -1;
}

int _chown(const char *path, uid_t owner, gid_t group)
{
    errno = ENOSYS;
    return -1;
}

__attribute__((used)) int _close(int file)
{
    return -1;
}

int _execve(const char *name, char *const argv[], char *const env[])
{
    errno = ENOMEM;
    return -1;
}

void _exit(int exit_status)
{
    soc_ctrl_t soc_ctrl;
    soc_ctrl.base_addr = mmio_region_from_addr((uintptr_t)SOC_CTRL_START_ADDRESS);
    soc_ctrl_set_exit_value(&soc_ctrl, exit_status);
    soc_ctrl_set_valid(&soc_ctrl, (uint8_t)1);

    asm volatile("wfi");
}

int _faccessat(int dirfd, const char *file, int mode, int flags)
{
    errno = ENOSYS;
    return -1;
}

pid_t _fork(void)
{
    errno = EAGAIN;
    return -1;
}

__attribute__((used)) int _fstat(int file, struct stat *st)
{
    st->st_mode = S_IFCHR;
    return 0;
    // errno = -ENOSYS;
    // return -1;
}

int _fstatat(int dirfd, const char *file, struct stat *st, int flags)
{
    errno = ENOSYS;
    return -1;
}

int _ftime(struct timeb *tp)
{
    errno = ENOSYS;
    return -1;
}

char *_getcwd(char *buf, size_t size)
{
    errno = -ENOSYS;
    return NULL;
}

pid_t _getpid()
{
    return 1;
}

int _gettimeofday(struct timeval *tp, void *tzp)
{
    errno = -ENOSYS;
    return -1;
}

__attribute__((used)) int _isatty(int file)
{
    return (file == STDOUT_FILENO);
}

int _kill(pid_t pid, int sig)
{
    errno = EINVAL;
    return -1;
}

int _link(const char *old_name, const char *new_name)
{
    errno = EMLINK;
    return -1;
}

off_t _lseek(int file, off_t ptr, int dir)
{
    return 0;
}

int _lstat(const char *file, struct stat *st)
{
    errno = ENOSYS;
    return -1;
}

int _open(const char *name, int flags, int mode)
{
    return -1;
}

int _openat(int dirfd, const char *name, int flags, int mode)
{
    errno = ENOSYS;
    return -1;
}

__attribute__((used)) int _read(int file, void *ptr, int len)
{
    return 0;
}

int _stat(const char *file, struct stat *st)
{
    st->st_mode = S_IFCHR;
    return 0;
    // errno = ENOSYS;
    // return -1;
}

long _sysconf(int name)
{

    return -1;
}

clock_t _times(struct tms *buf)
{
    return -1;
}

int _unlink(const char *name)
{
    errno = ENOENT;
    return -1;
}

int _utime(const char *path, const struct utimbuf *times)
{
    errno = ENOSYS;
    return -1;
}

int _wait(int *status)
{
    errno = ECHILD;
    return -1;
}

int _write(int file, const void *ptr, int len)
{
    if (file != STDOUT_FILENO) {
        errno = ENOSYS;
        return -1;
    }

    static uart_t uart;
    static int uart_ready = 0;

    if (!uart_ready) {
        soc_ctrl_t soc_ctrl;
        soc_ctrl.base_addr = mmio_region_from_addr((uintptr_t)SOC_CTRL_START_ADDRESS);

        uart.base_addr   = mmio_region_from_addr((uintptr_t)UART_START_ADDRESS);
        uart.baudrate    = UART_BAUDRATE;
        uart.clk_freq_hz = soc_ctrl_get_frequency(&soc_ctrl);
        #ifdef UART_NCO
        uart.nco         = UART_NCO;
        #else
        uart.nco         = ((uint64_t)uart.baudrate << (NCO_WIDTH + 4)) / uart.clk_freq_hz;
        #endif

        if (uart_init(&uart) != kErrorOk) {
            errno = ENOSYS;
            return -1;
        }
        uart_ready = 1;
    }
    return uart_write(&uart, (uint8_t *)ptr, len);

}


void _writestr(const void *ptr)
{
    _write(STDOUT_FILENO, ptr, strlen(ptr)+1);
}

/* ── picolibc tinystdio stdout/stderr ────────────────────────────────────────
 * picolibc's tinystdio routes printf/puts through FILE* stream callbacks,
 * NOT through _write().  With newlib, _write() is called directly by stdio,
 * so this block is only needed when building with picolibc. */
#ifdef __PICOLIBC__
static int _uart_put(char c, FILE *f)
{
    (void)f;
    _write(STDOUT_FILENO, &c, 1);
    return (unsigned char)c;
}

static FILE _uart_file = FDEV_SETUP_STREAM(_uart_put, NULL, NULL, _FDEV_SETUP_WRITE);
FILE *const stdout = &_uart_file;
FILE *const stderr = &_uart_file;
FILE *const stdin  = NULL;
#endif /* __PICOLIBC__ */

extern char __heap_start[];
extern char __heap_end[];
static char *brk = __heap_start;

int _brk(void *addr)
{
    if (addr >= (void *)__heap_start && addr <= (void *)__heap_end) {
        brk = addr;
        return 0; 
    } else {
        return -1; 
    }
}

void *_sbrk(ptrdiff_t incr)
{
    char *old_brk = brk;

    if (__heap_start == __heap_end) {
        return NULL; 
    }

    if (brk + incr < __heap_end && brk + incr >= __heap_start) {
        brk += incr;
    } else {
        return (void *)-1; 
    }
    return old_brk;
}

int raise(int sig)
{
    return _kill(_getpid(), sig);
}

void abort(void)
{
    _exit(-1);
}

/* ── xcv-safe stdlib overrides ───────────────────────────────────────────────
 * The pre-compiled newlib/libc_nano.a shipped with the armhf OpenHW toolchain
 * contains xcv (CV32E40P custom ISA) instructions.  Calling those routines on
 * hardware without xcv support raises an illegal-instruction exception which
 * ends in while(1) inside handler_instr_ill_fault().
 *
 * We override the most-used stdlib/stdio functions here with plain C
 * implementations that call only _write()/_exit() (our own syscalls) and
 * never touch the FILE* machinery (__sfp/__sinit/_fwalk_sglue all have xcv).
 *
 * Object-file symbols take priority over archive (.a) symbols at link time,
 * so these definitions silently replace the xcv versions from -lc.
 * ─────────────────────────────────────────────────────────────────────────── */

/* strlen ------------------------------------------------------------------- */
size_t strlen(const char *s)
{
    const char *p = s;
    while (*p) ++p;
    return (size_t)(p - s);
}

/* exit / atexit ------------------------------------------------------------ */
__attribute__((noreturn)) void exit(int status)
{
    _exit(status);
}

int atexit(void (*fn)(void))
{
    (void)fn;
    return 0;
}

/* __libc_init_array -------------------------------------------------------- *
 * Called by crt0.S to run C++ constructors.  No C++ in this project, so an  *
 * empty stub avoids executing the xcv-compiled version in libgcc.a.         */
void __libc_init_array(void) {}

/* puts / fputs ------------------------------------------------------------- */
int puts(const char *s)
{
    int n = (int)strlen(s);
    _write(STDOUT_FILENO, s, n);
    _write(STDOUT_FILENO, "\n", 1);
    return n + 1;
}

int fputs(const char *s, FILE *fp)
{
    (void)fp;
    int n = (int)strlen(s);
    _write(STDOUT_FILENO, s, n);
    return n;
}

/* minimal printf / fprintf ------------------------------------------------- */
static void _xcv_write_uint(unsigned long v, unsigned int base, int upper)
{
    char buf[32];
    int  i = (int)sizeof(buf) - 1;
    buf[i] = '\0';
    if (v == 0) {
        buf[--i] = '0';
    } else {
        const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
        while (v) { buf[--i] = digits[v % base]; v /= base; }
    }
    _write(STDOUT_FILENO, buf + i, (int)strlen(buf + i));
}

static int _xcv_vprintf(const char *fmt, va_list ap)
{
    int count = 0;
    for (; *fmt; ++fmt) {
        if (*fmt != '%') {
            _write(STDOUT_FILENO, fmt, 1);
            ++count;
            continue;
        }
        ++fmt;
        switch (*fmt) {
            case 'd': case 'i': {
                long v = (long)va_arg(ap, int);
                if (v < 0) { _write(STDOUT_FILENO, "-", 1); ++count; v = -v; }
                _xcv_write_uint((unsigned long)v, 10, 0);
                break;
            }
            case 'u':
                _xcv_write_uint((unsigned long)va_arg(ap, unsigned int), 10, 0);
                break;
            case 'x':
                _xcv_write_uint((unsigned long)va_arg(ap, unsigned int), 16, 0);
                break;
            case 'X':
                _xcv_write_uint((unsigned long)va_arg(ap, unsigned int), 16, 1);
                break;
            case 'p': {
                _write(STDOUT_FILENO, "0x", 2);
                _xcv_write_uint((unsigned long)(uintptr_t)va_arg(ap, void *), 16, 0);
                break;
            }
            case 's': {
                const char *s = va_arg(ap, const char *);
                if (!s) s = "(null)";
                int n = (int)strlen(s);
                _write(STDOUT_FILENO, s, n);
                count += n;
                break;
            }
            case 'c': {
                char c = (char)va_arg(ap, int);
                _write(STDOUT_FILENO, &c, 1);
                ++count;
                break;
            }
            case '%':
                _write(STDOUT_FILENO, "%", 1);
                ++count;
                break;
            default:
                _write(STDOUT_FILENO, "%", 1);
                _write(STDOUT_FILENO, fmt, 1);
                count += 2;
                break;
        }
    }
    return count;
}

int printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    int n = _xcv_vprintf(fmt, ap);
    va_end(ap);
    return n;
}

int fprintf(FILE *fp, const char *fmt, ...)
{
    (void)fp;
    va_list ap;
    va_start(ap, fmt);
    int n = _xcv_vprintf(fmt, ap);
    va_end(ap);
    return n;
}

int vprintf(const char *fmt, va_list ap)
{
    return _xcv_vprintf(fmt, ap);
}

int vfprintf(FILE *fp, const char *fmt, va_list ap)
{
    (void)fp;
    return _xcv_vprintf(fmt, ap);
}

#ifdef __cplusplus
}
#endif