// Android port: POSIX-backed semaphores, detached async calls, one-shot initialization and timer sources. Queues are dummy handles.
#pragma once
#include <semaphore.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <pthread/qos.h>
#include <sched.h>
typedef sem_t *dispatch_semaphore_t;
typedef uint64_t dispatch_time_t;
#define DISPATCH_TIME_NOW 0ull
#define DISPATCH_TIME_FOREVER (~0ull)
#ifndef NSEC_PER_SEC
#define NSEC_PER_SEC 1000000000ull
#define NSEC_PER_MSEC 1000000ull
#define NSEC_PER_USEC 1000ull
#endif
// a dispatch_time is an absolute CLOCK_REALTIME instant in ns (what sem_timedwait takes)
static inline dispatch_time_t dispatch_time(dispatch_time_t when, int64_t delta) {
    if (when == DISPATCH_TIME_FOREVER) return when;
    if (when == DISPATCH_TIME_NOW) { struct timespec t; clock_gettime(CLOCK_REALTIME, &t); when = (uint64_t)t.tv_sec * NSEC_PER_SEC + (uint64_t)t.tv_nsec; }
    return when + (uint64_t)delta;
}
static inline dispatch_semaphore_t dispatch_semaphore_create(long v) { sem_t *s = malloc(sizeof *s); sem_init(s, 0, (unsigned)v); return s; }
static inline long dispatch_semaphore_signal(dispatch_semaphore_t s) { sem_post(s); return 0; }
static inline long dispatch_semaphore_wait(dispatch_semaphore_t s, dispatch_time_t t) {
    if (t == DISPATCH_TIME_FOREVER) { while (sem_wait(s) && errno == EINTR) ; return 0; }
    struct timespec ts = {(time_t)(t / NSEC_PER_SEC), (long)(t % NSEC_PER_SEC)};
    for (;;) { if (!sem_timedwait(s, &ts)) return 0; if (errno != EINTR) return 1; }
}
static inline void dispatch_release(void *o) { if (o) { sem_destroy((sem_t *)o); free(o); } }
// The host's one queue use (hle_audio.c au_request_start): dispatch_async_f on a global concurrent queue runs a C function
// on a detached thread. A queue is a dummy handle; the global queue is concurrent, so a thread per call matches its semantics.
typedef void *dispatch_queue_t;
typedef void (*dispatch_function_t)(void *);
#define DISPATCH_QUEUE_SERIAL NULL
static inline dispatch_queue_t dispatch_get_global_queue(long qos, unsigned long flags) { (void)qos; (void)flags; return (dispatch_queue_t)1; }
struct dispatch_async_args { dispatch_function_t fn; void *ctx; };
static inline void *dispatch_async_th(void *p) { struct dispatch_async_args *a = p; dispatch_function_t fn = a->fn; void *ctx = a->ctx; free(a); fn(ctx); return NULL; }
static inline void dispatch_async_f(dispatch_queue_t q, void *ctx, dispatch_function_t fn) {
    (void)q; struct dispatch_async_args *a = malloc(sizeof *a); if (!a) { fn(ctx); return; } a->fn = fn; a->ctx = ctx;
    pthread_t t; if (!pthread_create(&t, NULL, dispatch_async_th, a)) pthread_detach(t); else { fn(ctx); free(a); }
}
typedef uintptr_t dispatch_once_t;
static inline void dispatch_once_f(dispatch_once_t *once, void *ctx, dispatch_function_t block) {
    uintptr_t expected = 0;
    if (__atomic_compare_exchange_n(once, &expected, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        if (block) block(ctx);
        __atomic_store_n(once, 2, __ATOMIC_RELEASE);
        return;
    }
    while (__atomic_load_n(once, __ATOMIC_ACQUIRE) != 2) sched_yield();
}
#define DISPATCH_SOURCE_TYPE_TIMER 0
typedef struct dispatch_source {
    pthread_t thread;
    dispatch_function_t fn;
    void *ctx;
    uint64_t start_ns, interval_ns;
    int started;
} *dispatch_source_t;
static inline void dispatch_sleep_ns(uint64_t ns) {
    struct timespec ts = {(time_t)(ns / NSEC_PER_SEC), (long)(ns % NSEC_PER_SEC)};
    while (nanosleep(&ts, &ts) && errno == EINTR) ;
}
static inline void *dispatch_timer_th(void *p) {
    dispatch_source_t s = p;
    struct timespec now; clock_gettime(CLOCK_REALTIME, &now);
    uint64_t now_ns = (uint64_t)now.tv_sec * NSEC_PER_SEC + (uint64_t)now.tv_nsec;
    if (s->start_ns > now_ns) dispatch_sleep_ns(s->start_ns - now_ns);
    for (;;) {
        if (s->fn) s->fn(s->ctx);
        if (!s->interval_ns) break;
        dispatch_sleep_ns(s->interval_ns);
    }
    return NULL;
}
static inline dispatch_source_t dispatch_source_create(const char *type, uintptr_t handle, uintptr_t mask, dispatch_queue_t q) {
    (void)type; (void)handle; (void)mask; (void)q;
    return calloc(1, sizeof(struct dispatch_source));
}
static inline void dispatch_source_set_timer(dispatch_source_t s, dispatch_time_t start, uint64_t interval, uint64_t leeway) {
    (void)leeway; s->start_ns = start; s->interval_ns = interval;
}
static inline void dispatch_source_set_event_handler_f(dispatch_source_t s, dispatch_function_t fn) { s->fn = fn; }
static inline void dispatch_resume(dispatch_source_t s) {
    if (__atomic_exchange_n(&s->started, 1, __ATOMIC_ACQ_REL)) return;
    if (pthread_create(&s->thread, NULL, dispatch_timer_th, s)) __atomic_store_n(&s->started, 0, __ATOMIC_RELEASE);
    else pthread_detach(s->thread);
}
