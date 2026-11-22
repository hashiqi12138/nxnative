/*
 * TopBar.ets - NXOHOS redesigned header:
 * Brand identity on the left, segmented Library / Downloads switcher in the centre,
 * and unclipped Settings + Add Game pills on the right.
 */

import { Bg, Text as TextToken, Semantic, Space, Font, Radius, Size } from '../theme/Tokens';

@Component
export struct TopBar {
  @Prop title: string = 'NXOHOS';
  @Prop showAdd: boolean = true;
  @Prop barHeight: number = Size.topBar;
  /** Active top-level tab: 'library' | 'downloads'. */
  @Prop activeTab: string = 'library';
  /** Whether to show the segmented tab switcher (true on LibraryPage, false in GalleryPage). */
  @Prop showTabs: boolean = false;
  /** Active download indicator badge on the Downloads tab. */
  @Prop downloadActive: boolean = false;
  onTabChange: (tab: string) => void = (_tab: string) => {};
  onAdd: () => void = () => {};
  onSettings: () => void = () => {};

  build() {
    Row({ space: Space.s3 }) {
      // Brand mark
      Row({ space: Space.s2 }) {
        Column()
          .width(8)
          .height(22)
          .borderRadius(Radius.full)
          .backgroundColor(Semantic.accent)
        Text(this.title)
          .fontSize(Font.title)
          .fontColor(TextToken.primary)
          .fontWeight(FontWeight.Bold)
          .letterSpacing(0.8)
      }
      .alignItems(VerticalAlign.Center)

      if (this.showTabs) {
        Row({ space: 4 }) {
          Button('游戏库')
            .fontSize(Font.label)
            .fontWeight(this.activeTab === 'library' ? FontWeight.Bold : FontWeight.Regular)
            .fontColor(this.activeTab === 'library' ? TextToken.inverse : TextToken.secondary)
            .backgroundColor(this.activeTab === 'library' ? Semantic.accent : 'rgba(0,0,0,0)')
            .borderRadius(Radius.full)
            .height(34)
            .padding({ left: Space.s4, right: Space.s4 })
            .onClick(() => this.onTabChange('library'))

          Button() {
            Row({ space: 6 }) {
              Text('下载库')
                .fontSize(Font.label)
                .fontWeight(this.activeTab === 'downloads' ? FontWeight.Bold : FontWeight.Regular)
                .fontColor(this.activeTab === 'downloads' ? TextToken.inverse : TextToken.secondary)
              if (this.downloadActive) {
                Circle({ width: 7, height: 7 })
                  .fill(this.activeTab === 'downloads' ? TextToken.inverse : Semantic.coral)
              }
            }
            .alignItems(VerticalAlign.Center)
          }
          .backgroundColor(this.activeTab === 'downloads' ? Semantic.accent : 'rgba(0,0,0,0)')
          .borderRadius(Radius.full)
          .height(34)
          .padding({ left: Space.s4, right: Space.s4 })
          .onClick(() => this.onTabChange('downloads'))
        }
        .padding(3)
        .backgroundColor(Bg.elevated)
        .borderRadius(Radius.full)
        .border({ width: 1, color: Semantic.borderSubtle })
        .margin({ left: Space.s4 })
      }

      Blank()

      // Settings pill (replaces clipped 44vp gear button)
      Button('设置')
        .fontSize(Font.label)
        .fontColor(TextToken.primary)
        .backgroundColor(Bg.card)
        .border({ width: 1, color: Semantic.borderSubtle, radius: Radius.full })
        .borderRadius(Radius.full)
        .height(Size.buttonMd)
        .padding({ left: Space.s4, right: Space.s4 })
        .onClick(() => this.onSettings())
        .accessibilityText('设置')
        .accessibilityRole(AccessibilityRoleType.BUTTON)

      if (this.showAdd) {
        Button() {
          Row({ space: Space.s1 }) {
            Text('+')
              .fontSize(Font.body)
              .fontColor(TextToken.inverse)
              .fontWeight(FontWeight.Bold)
            Text('导入游戏')
              .fontSize(Font.label)
              .fontColor(TextToken.inverse)
              .fontWeight(FontWeight.Medium)
          }
          .alignItems(VerticalAlign.Center)
        }
        .backgroundColor(Semantic.accent)
        .borderRadius(Radius.full)
        .height(Size.buttonMd)
        .padding({ left: Space.s4, right: Space.s4 })
        .onClick(() => this.onAdd())
        .accessibilityText('导入游戏')
        .accessibilityRole(AccessibilityRoleType.BUTTON)
      }
    }
    .width('100%')
    .height(this.barHeight)
    .padding({ left: Space.s5, right: Space.s5 })
    .backgroundColor('rgba(0,0,0,0)')
  }
}
