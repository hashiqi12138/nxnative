// OpenGTX: tell the system this app is running a game, so its clock and frame governor stops guessing.
//
// Measured on the device (HBN-AL80, Maleoon 910, HarmonyOS 7.0.0.111) while Breath of the Wild ran at 20-34 fps:
//
//   gp:   GpuLoadLevel = 1        (1..10)
//   gp:   CurrentFrequency = 308000 kHz
//
// The GPU sat at its floor while the frame work took 33 ms. The system was not withholding clocks out of spite - it
// had no idea the app was a game, because nothing ever told it. HarmonyOS decides that from the app's store category
// and the user's per-game switch, and a sideloaded HAP has neither; OpenGTX is the API that lets the app say it
// itself. P3.3's probe configured and activated it against this app's own bundle and every call returned 0.
//
// SCENE_MODE rather than ADAPTIVE_MODE: ADAPTIVE (and TOUCH_MODE with it) keys the frame rate off touch input, and
// this port's input is a virtual gamepad - a finger never touches the game's surface. SCENE_MODE is driven by the
// scene the game reports, which is what a ported console game actually has.
//
// Everything here is dlopen/dlsym: libopengtx.so exists on some HarmonyOS devices and not others, and a host that
// refused to start because a vendor library was absent would be worse than one that runs without the hint.
#include <dlfcn.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>   // getpid

#include "dm.h"

typedef struct OpenGTX_Context OpenGTX_Context;

typedef struct { int32_t height, width; } GTX_Res;

// The layout the probe used, which the device accepted: field order and widths matter, this is a C ABI struct.
typedef struct {
    int mode;                     // OPENGTX_SCENE_MODE / _TOUCH_MODE / _ADAPTIVE_MODE
    int32_t targetFPS;
    char *packageName;
    char *appVersion;
    int engineType;
    char *engineVersion;
    int gameType;
    int pictureQualityMaxLevel;
    GTX_Res resolutionMaxValue;
    int32_t gameMainThreadId, gameRenderThreadId, gameKeyThreadIds[5];
    bool vulkanSupport;
} GTX_Cfg;

typedef struct {
    int sceneID;                  // 1 start, 2 in-game update, 3 login, 4 main menu, 5 loading, 6 matchmaking,
                                  // 7 in game, 8 spectator
    char *description;
    int32_t recommendFPS, minFPS, maxFPS;
    GTX_Res resolutionCurValue;
} GTX_Scene;

typedef struct { float x, y, z; } GTX_V3;
typedef struct { GTX_V3 mainCameraPosition, mainCameraRotate; } GTX_Frame;

typedef OpenGTX_Context *(*fn_create)(void *);
typedef int (*fn_cfg)(OpenGTX_Context *, const GTX_Cfg *);
typedef int (*fn_act)(OpenGTX_Context *);
typedef int (*fn_deact)(OpenGTX_Context *);
typedef int (*fn_destroy)(OpenGTX_Context **);
typedef int (*fn_scene)(OpenGTX_Context *, const GTX_Scene *);
typedef int (*fn_frame)(OpenGTX_Context *, const GTX_Frame *);

// ADAPTIVE_MODE, the mode P3.3's probe configured successfully on this device. SCENE_MODE (0x0001) is the one
// that fits a gamepad-driven port on paper, but the same call with it returned 401 (parameter check failed) here
// - the platform wants fields this build does not know, and a configuration the device rejects changes nothing.
// ADAPTIVE plus the scene dispatches below is what actually runs.
#define OPENGTX_ADAPTIVE_MODE 0x0100

static struct {
    OpenGTX_Context *ctx;
    fn_act act;
    fn_deact deact;
    fn_destroy destroy;
    fn_scene scene;
    fn_frame frame;
    int target_fps;
    int scene_id;
    int on;
} g;

// The scene the game is in. A port has no way to know the game's own scene graph, so this follows the frames: the
// first frames after start are the boot/loading path, and a steady run of presents is in game. The distinction
// matters because the platform gives a loading scene less than a playing one.
static int scene_for(uint64_t frames_presented) {
    if (frames_presented < 120) return 5;    // loading
    if (frames_presented < 600) return 4;    // main menu
    return 7;                                // in game
}

int dm_opengtx_init(const char *package, const char *app_version, int target_fps, int vulkan) {
    const char *off = getenv("DM_OPENGTX");
    if (off && !atoi(off)) return 0;         // DM_OPENGTX=0 turns the hint off
    if (g.on) return 0;

    void *h = dlopen("libopengtx.so", RTLD_NOW);
    if (!h) { LOG("opengtx: libopengtx.so is not on this device; the frame governor runs without the hint"); return 0; }

    fn_create create = (fn_create)dlsym(h, "HMS_OpenGTX_CreateContext");
    fn_cfg cfg = (fn_cfg)dlsym(h, "HMS_OpenGTX_SetConfiguration");
    g.act = (fn_act)dlsym(h, "HMS_OpenGTX_Activate");
    g.deact = (fn_deact)dlsym(h, "HMS_OpenGTX_Deactivate");
    g.destroy = (fn_destroy)dlsym(h, "HMS_OpenGTX_DestroyContext");
    g.scene = (fn_scene)dlsym(h, "HMS_OpenGTX_DispatchGameSceneInfo");
    g.frame = (fn_frame)dlsym(h, "HMS_OpenGTX_DispatchFrameRenderInfo");
    if (!create || !cfg || !g.act) { LOG("opengtx: the library is there but not the entry points"); return 0; }

    g.ctx = create(NULL);
    if (!g.ctx) { LOG("opengtx: CreateContext returned null"); return 0; }

    // Every field the guide marks required, filled. A zero here is not "unknown, use a default": the platform reads
    // the whole structure as a declaration and answers 401 when one of them is missing. P3.3's probe filled all of
    // them and got 0; the first version of this file left engineType, engineVersion, gameType,
    // pictureQualityMaxLevel, resolutionMaxValue and the two thread ids at zero and got 401 on the same device.
    GTX_Cfg c;
    memset(&c, 0, sizeof c);
    c.mode = OPENGTX_ADAPTIVE_MODE;
    c.targetFPS = target_fps;
    c.packageName = (char *)package;
    c.appVersion = (char *)app_version;
    c.engineType = 100;                     // OTHERS_ENGINE: the game runs its own engine through a rewriter
    c.engineVersion = (char *)"nxnative";
    c.gameType = 2;                         // RPG, which is what most of this port's library is
    c.pictureQualityMaxLevel = 3;           // FHD
    c.resolutionMaxValue.height = 1080;
    c.resolutionMaxValue.width = 1920;
    // The threads the platform should watch: the process's own, which is where the guest's submit and replay work
    // runs. getpid() is what the probe used and what the device accepted.
    c.gameMainThreadId = (int32_t)getpid();
    c.gameRenderThreadId = (int32_t)getpid();
    c.vulkanSupport = vulkan != 0;

    int rc = cfg(g.ctx, &c);
    if (rc) { LOG("opengtx: SetConfiguration failed (%d); the governor keeps guessing", rc); g.destroy(&g.ctx); g.ctx = NULL; return 0; }
    rc = g.act(g.ctx);
    if (rc) { LOG("opengtx: Activate failed (%d)", rc); g.destroy(&g.ctx); g.ctx = NULL; return 0; }

    g.target_fps = target_fps;
    g.scene_id = 5;
    g.on = 1;
    LOG("opengtx: ADAPTIVE_MODE, target %d fps, vulkan %d: the system now knows this is a game", target_fps, vulkan);
    return 1;
}

// Called once a frame from the present path. Cheap: two function pointers and an integer compare, and the scene is
// only re-dispatched when it changes.
void dm_opengtx_frame(uint64_t frames_presented) {
    if (!g.on) return;
    int s = scene_for(frames_presented);
    if (s != g.scene_id && g.scene) {
        GTX_Scene sc;
        memset(&sc, 0, sizeof sc);
        sc.sceneID = s;
        sc.recommendFPS = g.target_fps;
        sc.minFPS = 30;
        sc.maxFPS = g.target_fps;
        int rc = g.scene(g.ctx, &sc);
        if (!rc) {
            g.scene_id = s;
            LOG("opengtx: scene %d (%.1f s in)", s, frames_presented / 60.0);
        }
    }
    if (g.frame) {
        GTX_Frame f;
        memset(&f, 0, sizeof f);   // no camera pose to give: the game's own is not something the host may read here
        g.frame(g.ctx, &f);
    }
}

void dm_opengtx_shutdown(void) {
    if (!g.on) return;
    if (g.deact) g.deact(g.ctx);
    if (g.destroy) g.destroy(&g.ctx);
    g.ctx = NULL;
    g.on = 0;
    LOG("opengtx: deactivated");
}
