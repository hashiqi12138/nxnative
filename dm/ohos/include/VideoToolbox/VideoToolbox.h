// OHOS port: VideoToolbox does not exist on this platform. Upstream's hle_movie_vt.h (the compressed-input history a VideoToolbox
// session keeps for lifecycle replays) is included by hle_movie.c and hle_codec_video.c, so the types and calls it names have to exist
// and have to fail cleanly. The OHOS build has no decoder that reaches them (dm/ohos/movie_avc_ohos.c is a stub until the AVCodec
// milestone; movie_av1_stub_ohos.c refuses every frame), so a game sees "no decoder" and falls back as it does with none installed.
#pragma once
#include <stddef.h>
#include <AudioToolbox/AudioToolbox.h>   // OSStatus, noErr
#include <CoreFoundation/CoreFoundation.h>   // CFDictionaryRef, CFRetain / CFRelease

typedef const void *CMSampleBufferRef;
typedef const void *CMVideoFormatDescriptionRef;
typedef struct dm_vt_session *VTDecompressionSessionRef;

// Upstream fills this with a C function pointer and a refcon (VTDecompressionOutputCallback). It is never invoked here.
typedef struct { void *callback; void *refcon; } VTDecompressionOutputCallbackRecord;

#define kVTDecodeFrame_DoNotOutputFrame 0x1u
#define kVTVideoDecoderNotAvailableNowErr (-12906)

static inline OSStatus VTDecompressionSessionCreate(void *allocator, CMVideoFormatDescriptionRef format, CFDictionaryRef encoder_spec,
                                                   CFDictionaryRef attrs, const VTDecompressionOutputCallbackRecord *callback,
                                                   VTDecompressionSessionRef *session) {
    (void)allocator; (void)format; (void)encoder_spec; (void)attrs; (void)callback;
    if (session) *session = NULL;
    return -1;   // no decoder: the caller reports "refused" and the movie stays black
}

static inline OSStatus VTDecompressionSessionDecodeFrame(VTDecompressionSessionRef session, CMSampleBufferRef sample, unsigned flags,
                                                         void *source, void *info) {
    (void)session; (void)sample; (void)flags; (void)source; (void)info;
    return -1;
}
