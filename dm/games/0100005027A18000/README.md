# Graveyard Keeper 2

Graveyard Keeper 2 runs with Unity 6000.3.9f1 IL2CPP and FMOD on SDK 21.4.4, update 1.0.4. This profile began as the NSP script's provisional profile and was checked against the survey on 2026-10-26.

- **Modules:** `main`, `subsdk0` (the SDK movie library), and `sdk`; `sdk` and `subsdk0` are Viractal's builds.
- **Memory:** the game maps its own memory without a heap, using the 5 GB guest layout, a 4.375 GB alias region, and the NPDM's 16 MB system resource. The SDK address-region node-area cut in `sdk_patches.py` is required. Maps are limited to the application pool as on Horizon; a 1 h 54 min session mapped at most 2.44 GB of the 3.21 GB pool without a refused map.
- **Frame rate:** the host writes Unity's vsync count and frame time for a 60 fps target. `present_interval display` is also required because the game requests present interval 2; the writes alone left it at 33.3 ms.
- **Shaders:** the provisional split groups `/Data/` as `data`. Shader tables remain provisional until regenerated from the complete game files.

Open: validate shader coverage and long-session memory growth on a device. No additional host-specific rule is currently recorded.
