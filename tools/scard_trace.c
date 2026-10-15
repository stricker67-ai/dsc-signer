// scard_trace.c - logs PC/SC and SysV-semaphore calls made by the token's PKCS#11 driver.
// Load with DYLD_INSERT_LIBRARIES. Logs APDU headers (CLA INS P1 P2) and status words only,
// never APDU data, so the PIN never reaches the log.
#include <PCSC/winscard.h>
#include <PCSC/wintypes.h>
#include <sys/sem.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#define DYLD_INTERPOSE(_new, _old) \
    __attribute__((used)) static struct { const void *n; const void *o; } _ip_##_old \
    __attribute__((section("__DATA,__interpose"))) = { (const void *)&_new, (const void *)&_old };

static FILE *logf_;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

static void logline(const char *fmt, ...) {
    pthread_mutex_lock(&mu);
    if (!logf_) {
        const char *p = getenv("DSC_TRACE_LOG");
        logf_ = fopen(p ? p : "/tmp/dsc-sign-trace.log", "a");
    }
    if (logf_) {
        struct timeval tv; gettimeofday(&tv, NULL);
        uint64_t tid; pthread_threadid_np(NULL, &tid);
        fprintf(logf_, "%ld.%03d t%llu ", (long)tv.tv_sec % 100000, (int)(tv.tv_usec / 1000), tid);
        va_list ap; va_start(ap, fmt); vfprintf(logf_, fmt, ap); va_end(ap);
        fputc('\n', logf_); fflush(logf_);
    }
    pthread_mutex_unlock(&mu);
}

static LONG my_Connect(SCARDCONTEXT c, LPCSTR r, DWORD sm, DWORD pp, LPSCARDHANDLE h, LPDWORD ap) {
    LONG rv = SCardConnect(c, r, sm, pp, h, ap);
    logline("SCardConnect reader=%s share=%u proto=%u -> 0x%08x active=%u", r, sm, pp, (unsigned)rv, ap ? *ap : 0);
    return rv;
}
static LONG my_Reconnect(SCARDHANDLE h, DWORD sm, DWORD pp, DWORD init, LPDWORD ap) {
    LONG rv = SCardReconnect(h, sm, pp, init, ap);
    logline("SCardReconnect share=%u proto=%u init=%u -> 0x%08x", sm, pp, init, (unsigned)rv);
    return rv;
}
static LONG my_Begin(SCARDHANDLE h) {
    LONG rv = SCardBeginTransaction(h);
    logline("SCardBeginTransaction -> 0x%08x", (unsigned)rv);
    return rv;
}
static LONG my_End(SCARDHANDLE h, DWORD d) {
    LONG rv = SCardEndTransaction(h, d);
    logline("SCardEndTransaction disp=%u -> 0x%08x", d, (unsigned)rv);
    return rv;
}
static LONG my_Disconnect(SCARDHANDLE h, DWORD d) {
    LONG rv = SCardDisconnect(h, d);
    logline("SCardDisconnect disp=%u -> 0x%08x", d, (unsigned)rv);
    return rv;
}
static LONG my_Transmit(SCARDHANDLE h, const SCARD_IO_REQUEST *spci, LPCBYTE sb, DWORD sl,
                        SCARD_IO_REQUEST *rpci, LPBYTE rb, LPDWORD rl) {
    DWORD cap = rl ? *rl : 0;
    LONG rv = SCardTransmit(h, spci, sb, sl, rpci, rb, rl);
    unsigned sw = (rv == SCARD_S_SUCCESS && rl && *rl >= 2) ? (rb[*rl - 2] << 8 | rb[*rl - 1]) : 0;
    logline("SCardTransmit hdr=%02X %02X %02X %02X len=%u rbuf=%u -> 0x%08x rlen=%u sw=%04X",
            sl > 0 ? sb[0] : 0, sl > 1 ? sb[1] : 0, sl > 2 ? sb[2] : 0, sl > 3 ? sb[3] : 0,
            sl, cap, (unsigned)rv, rl ? *rl : 0, sw);
    return rv;
}
static int my_semget(key_t k, int n, int f) {
    int rv = semget(k, n, f); int e = errno;
    logline("semget key=0x%x n=%d flg=0%o -> %d errno=%d", k, n, f, rv, rv < 0 ? e : 0);
    errno = e; return rv;
}
static int my_semop(int id, struct sembuf *ops, size_t n) {
    int rv = semop(id, ops, n); int e = errno;
    logline("semop id=%d n=%zu op0=%d flg0=0x%x -> %d errno=%d", id, n,
            n ? ops[0].sem_op : 0, n ? ops[0].sem_flg : 0, rv, rv < 0 ? e : 0);
    errno = e; return rv;
}

DYLD_INTERPOSE(my_Connect, SCardConnect)
DYLD_INTERPOSE(my_Reconnect, SCardReconnect)
DYLD_INTERPOSE(my_Begin, SCardBeginTransaction)
DYLD_INTERPOSE(my_End, SCardEndTransaction)
DYLD_INTERPOSE(my_Disconnect, SCardDisconnect)
DYLD_INTERPOSE(my_Transmit, SCardTransmit)
DYLD_INTERPOSE(my_semget, semget)
DYLD_INTERPOSE(my_semop, semop)
