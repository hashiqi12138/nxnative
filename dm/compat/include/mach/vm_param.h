// Android/OHOS port: the one constant the host takes from <mach/vm_param.h>.
// hle_svc.c's gap query clips an unmapped interval at the top of the guest's address space and
// reports anything above it as outside; the kernel's macOS value is far above every mapping this
// port makes, so the arm64 user-space ceiling (64 GB) is used here.
#pragma once
#define MACH_VM_MAX_ADDRESS 0x0000001000000000ULL
