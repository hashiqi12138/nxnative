// The runtime game profile (P4.1): one host for every game. The pack carries "profile.tsv", game.py profile's rows of
// header_one's constants, and this file fills the dm_game_t table from it before anything host-side runs (main.c
// host_preload). A builtin header (the default for Mac/iOS) has no dm_game_t and compiles this file empty.
#include "dm.h"
#include "game_profile.h"

#if defined(DM_GAME_RT)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

dm_game_t dm_games[DM_GAME_MAX_PROGRAMS];
int dm_n_games;

const dm_game_t *dm_game_cur(void) {
    static const dm_game_t *g;
    if (!g) {
        const char *e = getenv("DM_PROGRAM"); int p = e ? atoi(e) : 0;
        for (int i = 0; i < dm_n_games; i++) if (dm_games[i].program == p) g = &dm_games[i];
        if (!g && dm_n_games) g = &dm_games[0];   // no such program: the first one, as the builtin table does
        if (!g) die("[RED] game profile: no program in the table (game_profile_load was not called or refused)");
    }
    return g;
}

static const char *conv_str(const char *v) { return strdup(v); }
static uint64_t conv_u64(const char *v) { return strtoull(v, NULL, 0); }
static int conv_int(const char *v) { return (int)strtol(v, NULL, 0); }

// The scalar rows, by the field names game.py wrote (the same names the macros read).
static int set_scalar(dm_game_t *g, const char *k, const char *v) {
#define X(t, f, key) if (!strcmp(k, #key)) { g->f = conv_##t(v); return 1; }
    DM_GAME_FIELD_TABLE(X)
#undef X
    return 0;
}

// "<field>\t<v1>\t<v2>..." into up to max entries; returns how many. A value keeps an empty string as an entry (an
// empty args row is a value, not a missing one).
static int split_vals(char *v, char *out[], int max, const char *path, const char *field) {
    int n = 0;
    while (v && n < max) {
        out[n++] = v;
        char *t = strchr(v, '\t');
        if (!t) break;
        *t = 0; v = t + 1;
    }
    if (v && n == max) { LOG("[RED] game profile %s: %s has more than %d entries", path, field, max); return -1; }
    return n;
}

int game_profile_load(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        // An older pack carries no profile.tsv: start from the build's own profile, which is exactly what a builtin host
        // compiled in (DESIGN-P4.1 section 5). A profile that exists but does not parse is still refused below.
        static const dm_game_t def = DM_GAME_DEFAULT_PROFILE;   // a brace list initializes a definition, not an assignment
        dm_games[0] = def; dm_n_games = 1;
        LOG("game profile: %s not found; using the build's default profile (%s)", path, dm_games[0].id);
        return 0;
    }
    char line[8192]; dm_game_t *g = NULL; int rc = 0;
    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
        if (!n || line[0] == '#') continue;
        char *tab = strchr(line, '\t');
        if (!tab) continue;   // a key with no value: nothing to set (the struct's zero default stands)
        *tab = 0;
        const char *k = line; char *v = tab + 1;
        if (!strcmp(k, "program")) {
            if (dm_n_games == DM_GAME_MAX_PROGRAMS) { LOG("[RED] game profile %s: more than %d programs", path, DM_GAME_MAX_PROGRAMS); rc = -1; break; }
            g = &dm_games[dm_n_games++]; memset(g, 0, sizeof *g); g->program = atoi(v);
            continue;
        }
        if (!g) continue;   // rows before "program": ignored
        if (!strcmp(k, "modules") || !strcmp(k, "builds") || !strcmp(k, "versions")) {
            char *items[DM_GAME_MAX_BUILDS * 2];   // modules uses MODULES slots; builds/versions two per row
            int m = split_vals(v, items, 8, path, k);
            if (m < 0) { rc = -1; break; }
            if (!strcmp(k, "modules")) {
                if (m > DM_GAME_MAX_MODULES) { LOG("[RED] game profile %s: %d modules, at most %d", path, m, DM_GAME_MAX_MODULES); rc = -1; break; }
                for (int i = 0; i < m; i++) g->modules[i] = conv_str(items[i]);   // the line buffer is reused by the next row
                g->nmod = m;   // the row is the truth, not a separate nmod row
            } else {
                if (m % 2) { LOG("[RED] game profile %s: %s needs build/value pairs, got %d entries", path, k, m); rc = -1; break; }
                int nrow = m / 2;
                if (nrow > DM_GAME_MAX_BUILDS) { LOG("[RED] game profile %s: %s has %d rows, at most %d", path, k, nrow, DM_GAME_MAX_BUILDS); rc = -1; break; }
                if (!strcmp(k, "builds")) { for (int i = 0; i < nrow; i++) { g->builds[i].build = conv_str(items[2 * i]); g->builds[i].mods = conv_str(items[2 * i + 1]); } g->nbuilds = nrow; }
                else { for (int i = 0; i < nrow; i++) { g->versions[i].build = conv_str(items[2 * i]); g->versions[i].display = conv_str(items[2 * i + 1]); } g->nversions = nrow; }
            }
            continue;
        }
        if (!set_scalar(g, k, v)) LOG("game profile %s: unknown row %s (ignored)", path, k);
    }
    fclose(f);
    if (rc) return rc;
    for (int i = 0; i < dm_n_games; i++) {
        if (!dm_games[i].id || !dm_games[i].id[0] || !dm_games[i].nmod) {
            LOG("[RED] game profile %s: program %d has no %s", path, dm_games[i].program, dm_games[i].id ? "modules" : "id");
            return -1;
        }
    }
    if (!dm_n_games) { LOG("[RED] game profile %s: no program row", path); return -1; }
    LOG("game profile: %s (%d program%s, %d module%s)", dm_games[0].name ? dm_games[0].name : dm_games[0].id, dm_n_games,
        dm_n_games == 1 ? "" : "s", dm_games[0].nmod, dm_games[0].nmod == 1 ? "" : "s");
    return 0;
}
#endif
