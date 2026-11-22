/*
 * Tokens.ets - NXOHOS upgraded console design tokens.
 * Backwards-compatible with all existing S1/S2/S4/S5 imports while elevating surface depth,
 * OLED pure-black gameplay framing, and cyan/coral handheld console accents.
 */

export class Bg {
  static readonly base: string = '#0B0F17';
  static readonly rail: string = '#0E1420';
  static readonly elevated: string = '#131C2E';
  static readonly card: string = '#182235';
  static readonly cardHover: string = '#22314A';
  static readonly overlay: string = 'rgba(4,8,16,0.74)';
  static readonly drawerGlass: string = 'rgba(13,19,31,0.94)';
  static readonly oledBlack: string = '#000000';
}

export class Text {
  static readonly primary: string = '#F1F5F9';
  static readonly secondary: string = '#9FB0C7';
  static readonly tertiary: string = '#64748B';
  static readonly inverse: string = '#0B0F17';
}

export class Semantic {
  static readonly accent: string = '#38BDF8';
  static readonly accentHover: string = '#7DD3FC';
  static readonly accentGlow: string = 'rgba(56,189,248,0.34)';
  static readonly accentSoft: string = 'rgba(56,189,248,0.16)';
  static readonly coral: string = '#F43F5E';
  static readonly coralSoft: string = 'rgba(244,63,94,0.22)';
  static readonly danger: string = '#EF4444';
  static readonly dangerHover: string = '#F87171';
  static readonly success: string = '#22C55E';
  static readonly successSoft: string = 'rgba(34,197,94,0.18)';
  static readonly warning: string = '#F59E0B';
  static readonly warningSoft: string = 'rgba(245,158,11,0.18)';
  static readonly borderSubtle: string = 'rgba(255,255,255,0.09)';
  static readonly borderStrong: string = 'rgba(255,255,255,0.20)';
  static readonly borderFocus: string = '#38BDF8';
  static readonly track: string = 'rgba(255,255,255,0.10)';
}

export class CoverPalette {
  static readonly colors: string[] = [
    '#1D4E89',   // deep ocean blue
    '#5B2C6F',   // twilight violet
    '#1B6B50',   // wild emerald
    '#8A4B1E',   // amber bronze
    '#8B2635',   // crimson
    '#155E75'    // deep cyan
  ];

  static forTitle(titleId: string): string {
    let sum: number = 0;
    for (let i = 0; i < titleId.length; i++) sum += titleId.charCodeAt(i);
    return CoverPalette.colors[sum % CoverPalette.colors.length];
  }

  static initialOf(name: string): string {
    const trimmed: string = name.trim();
    return trimmed.length ? trimmed.substring(0, 1).toUpperCase() : '?';
  }

  static rgba(hex: string, a: number): string {
    const r: number = parseInt(hex.substring(1, 3), 16);
    const g: number = parseInt(hex.substring(3, 5), 16);
    const b: number = parseInt(hex.substring(5, 7), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  static darken(hex: string, f: number): string {
    const r: number = Math.round(parseInt(hex.substring(1, 3), 16) * f);
    const g: number = Math.round(parseInt(hex.substring(3, 5), 16) * f);
    const b: number = Math.round(parseInt(hex.substring(5, 7), 16) * f);
    const to2: (n: number) => string = (n: number): string => n.toString(16).padStart(2, '0');
    return `#${to2(r)}${to2(g)}${to2(b)}`;
  }
}

export class Space {
  static readonly s1: number = 4;
  static readonly s2: number = 8;
  static readonly s3: number = 12;
  static readonly s4: number = 16;
  static readonly s5: number = 24;
  static readonly s6: number = 32;
  static readonly s7: number = 48;
  static readonly s8: number = 64;
}

export class Font {
  static readonly display: number = 30;
  static readonly displayLine: number = 38;
  static readonly title: number = 20;
  static readonly titleLine: number = 28;
  static readonly body: number = 16;
  static readonly bodyLine: number = 24;
  static readonly label: number = 14;
  static readonly labelLine: number = 20;
  static readonly caption: number = 12;
  static readonly captionLine: number = 16;
  static readonly coverInitial: number = 56;
  static readonly coverInitialLine: number = 64;
}

export class Radius {
  static readonly sm: number = 8;
  static readonly md: number = 12;
  static readonly lg: number = 16;
  static readonly cover: number = 20;
  static readonly full: number = 999;
}

export class Motion {
  static readonly fast: number = 120;
  static readonly base: number = 200;
  static readonly slow: number = 320;
  static readonly scalePress: number = 0.96;
  static readonly scaleFocus: number = 1.06;
  static readonly curve: Curve = Curve.FastOutSlowIn;
  static enabled: boolean = true;

  static duration(ms: number): number {
    return Motion.enabled ? ms : 0;
  }
}

export class Z {
  static readonly base: number = 0;
  static readonly sticky: number = 10;
  static readonly sheet: number = 20;
  static readonly modal: number = 30;
  static readonly toast: number = 40;
}

export class Size {
  static readonly topBar: number = 64;
  static readonly cardCoverLandscape: number = 248;
  static readonly cardCoverPortrait: number = 96;
  static readonly cardRowPortrait: number = 112;
  static readonly buttonLg: number = 48;
  static readonly buttonMd: number = 40;
  static readonly buttonSm: number = 32;
  static readonly touchTarget: number = 48;
  static readonly progressHeight: number = 8;
  static readonly progressHeightThin: number = 4;
  static readonly focusRing: number = 2;
  static readonly focusGlow: number = 8;
  static readonly sheetHandleWidth: number = 40;
  static readonly sheetHandleHeight: number = 4;
  static readonly dialogWidth: number = 480;
}
