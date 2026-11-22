/*
 * RemotePacksSection.ets - Dedicated full-height Download Library view (S4 redesigned).
 * Lives on its own tab in LibraryPage so it never crushes or clips the installed game cards.
 */

import dmhost from 'libdmhost.so';
import { preferences } from '@kit.ArkData';
import { Bg, Text as TextToken, Semantic, Space, Font, Radius, Size } from '../theme/Tokens';
import { RemotePack, PREF_SOURCE, listRemote } from '../pages/RemoteLibrary';
import { RemoteDownloads, PackProgress, PackState, speedLabel, etaLabel, sizeLabel } from './RemoteDownloads';

const KNOWN_TITLES: Record<string, string> = {
  '01007EF00011E000': '塞尔达传说：旷野之息',
  '0100F2C0115B6000': '塞尔达传说：王国之泪',
  '01002B30028F6000': '蔚蓝 (Celeste)',
  '0100000000010000': '超级马力欧 奥德赛',
  '0100152000022000': '马力欧卡丁车 8 豪华版',
  '01009B90006DC000': '密特罗德 生存恐惧'
};

@Component
export struct RemotePacksSection {
  onImported: () => void = () => {};
  onOpenSettings: () => void = () => {};

  @State rows: PackProgress[] = [];
  @State source: string = '';
  @State listing: boolean = false;
  @State status: string = '';
  @State failed: boolean = false;
  private tick: number = -1;

  aboutToAppear(): void {
    const bump: () => void = () => {
      this.rows = RemoteDownloads.list().slice();
      if (RemoteDownloads.busy() && this.tick < 0) {
        this.tick = setInterval(() => { this.rows = RemoteDownloads.list().slice(); }, 250);
      } else if (!RemoteDownloads.busy() && this.tick >= 0) {
        clearInterval(this.tick); this.tick = -1;
      }
    };
    RemoteDownloads.subscribe(bump);
    this.load();
  }

  aboutToDisappear(): void {
    if (this.tick >= 0) { clearInterval(this.tick); this.tick = -1; }
  }

  private async load(): Promise<void> {
    try {
      const ctx = this.getUIContext().getHostContext();
      if (!ctx) return;
      const lib = await preferences.getPreferences(ctx, 'library');
      const src = lib.getSync(PREF_SOURCE, '') as string;
      this.source = typeof src === 'string' ? src : '';
      if (!this.source.length) {
        dmhost.log('remote: no source set');
        this.rows = [];
        this.status = '';
        return;
      }
      dmhost.log('remote: source ' + this.source);
      RemoteDownloads.attach(this.source, ctx.filesDir, ctx.cacheDir);
      await this.refresh();
    } catch (e) {
      this.status = '读取下载源设置失败';
      this.failed = true;
    }
  }

  async refresh(): Promise<void> {
    if (!this.source.length || this.listing) return;
    this.listing = true;
    this.status = '正在连接服务器…';
    this.failed = false;
    try {
      const packs: RemotePack[] = await listRemote(this.source);
      RemoteDownloads.setPacks(packs);
      this.rows = RemoteDownloads.list().slice();
      this.status = packs.length ? '' : '这台服务器上还没有 .nxpk 游戏包';
    } catch (e) {
      this.rows = [];
      this.failed = true;
      this.status = '无法连接服务器：' + (e instanceof Error ? e.message : JSON.stringify(e));
    } finally {
      this.listing = false;
    }
  }

  private async download(title: string): Promise<void> {
    await RemoteDownloads.start(title);
    this.rows = RemoteDownloads.list().slice();
    if (RemoteDownloads.list().some((r: PackProgress): boolean => r.state === PackState.Installed)) {
      this.onImported();
    }
  }

  private friendlyName(r: PackProgress): string {
    const key: string = r.pack.title.toUpperCase();
    const mapped: string | undefined = KNOWN_TITLES[key];
    if (mapped && mapped.length > 0) return mapped;
    return r.pack.name.replace(/\.nxpk$/i, '');
  }

  private paceLabel(r: PackProgress): string {
    if (r.state !== PackState.Downloading) return '';
    const sp: string = speedLabel(r.speed);
    const eta: string = etaLabel(r.total - r.got, r.speed);
    if (!sp.length) return '';
    return eta.length ? (sp + ' · 剩余 ' + eta) : sp;
  }

  build() {
    Column({ space: Space.s3 }) {
      if (!this.source.length) {
        Column({ space: Space.s4 }) {
          Text('尚未配置局域网下载服务器')
            .fontSize(Font.title)
            .fontWeight(FontWeight.Bold)
            .fontColor(TextToken.primary)
          Text('在设置中填入电脑端 pack_server 地址（例如 192.168.2.2:28899），即可在此直接流式下载并增量更新游戏。')
            .fontSize(Font.body)
            .fontColor(TextToken.secondary)
            .textAlign(TextAlign.Center)
            .constraintSize({ maxWidth: 460 })
          Button('前往设置配置下载源')
            .height(Size.buttonMd)
            .padding({ left: Space.s5, right: Space.s5 })
            .fontSize(Font.label)
            .fontWeight(FontWeight.Medium)
            .fontColor(TextToken.inverse)
            .backgroundColor(Semantic.accent)
            .borderRadius(Radius.full)
            .onClick(() => this.onOpenSettings())
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else {
        // 顶部服务器连接胶囊
        Row({ space: Space.s3 }) {
          Circle({ width: 9, height: 9 })
            .fill(this.listing ? Semantic.warning : (this.failed ? Semantic.danger : Semantic.success))
          Column({ space: 2 }) {
            Text(this.source.replace(/^https?:\/\//, ''))
              .fontSize(Font.body)
              .fontWeight(FontWeight.Medium)
              .fontColor(TextToken.primary)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(this.listing ? '正在拉取清单…'
              : (this.failed ? this.status : `已连接 · 共 ${this.rows.length} 个可用包 · 支持 HTTP Range 断点续传`))
              .fontSize(Font.caption)
              .fontColor(this.failed ? Semantic.dangerHover : TextToken.secondary)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start)

          Button('更改地址')
            .height(34)
            .fontSize(Font.caption)
            .fontColor(TextToken.secondary)
            .backgroundColor(Bg.elevated)
            .border({ width: 1, color: Semantic.borderSubtle, radius: Radius.full })
            .borderRadius(Radius.full)
            .padding({ left: Space.s3, right: Space.s3 })
            .onClick(() => this.onOpenSettings())

          Button(this.listing ? '刷新中…' : '刷新清单')
            .height(34)
            .fontSize(Font.caption)
            .fontWeight(FontWeight.Medium)
            .fontColor(TextToken.inverse)
            .backgroundColor(Semantic.accent)
            .borderRadius(Radius.full)
            .padding({ left: Space.s4, right: Space.s4 })
            .enabled(!this.listing)
            .onClick(() => { this.refresh(); })
        }
        .width('100%')
        .padding(Space.s4)
        .backgroundColor(Bg.card)
        .borderRadius(Radius.lg)
        .border({ width: 1, color: Semantic.borderSubtle })

        if (this.rows.length === 0 && !this.listing) {
          Column({ space: Space.s2 }) {
            Text(this.status.length ? this.status : '暂无可下载数据包')
              .fontSize(Font.body)
              .fontColor(this.failed ? Semantic.dangerHover : TextToken.secondary)
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
        } else {
          List({ space: Space.s3 }) {
            ForEach(this.rows, (r: PackProgress) => {
              ListItem() {
                Column({ space: Space.s2 }) {
                  Row({ space: Space.s3 }) {
                    Column({ space: 3 }) {
                      Text(this.friendlyName(r))
                        .fontSize(Font.body)
                        .fontWeight(FontWeight.Medium)
                        .fontColor(TextToken.primary)
                        .maxLines(1)
                        .textOverflow({ overflow: TextOverflow.Ellipsis })
                      Text(r.state === PackState.Failed
                        ? ('失败：' + r.note)
                        : `${r.pack.name} · ${r.pack.title} · ${sizeLabel(r.pack.bytes)}`)
                        .fontSize(Font.caption)
                        .fontColor(r.state === PackState.Failed ? Semantic.dangerHover : TextToken.tertiary)
                        .maxLines(1)
                        .textOverflow({ overflow: TextOverflow.Ellipsis })
                    }
                    .layoutWeight(1)
                    .alignItems(HorizontalAlign.Start)

                    if (r.state === PackState.Downloading) {
                      Button(r.total > 0 ? (`暂停 ${Math.floor(r.got * 100 / r.total)}%`) : '暂停')
                        .height(36)
                        .fontSize(Font.caption)
                        .fontColor(Semantic.warning)
                        .backgroundColor(Semantic.warningSoft)
                        .borderRadius(Radius.full)
                        .padding({ left: Space.s4, right: Space.s4 })
                        .onClick(() => { RemoteDownloads.cancel(r.pack.title); })
                    } else if (r.state === PackState.Importing) {
                      Text('正在解包导入…')
                        .fontSize(Font.label)
                        .fontColor(Semantic.accent)
                    } else if (r.state === PackState.Installed) {
                      Text('✓ 已安装')
                        .fontSize(Font.label)
                        .fontWeight(FontWeight.Medium)
                        .fontColor(Semantic.success)
                        .padding({ left: Space.s3, right: Space.s3, top: 6, bottom: 6 })
                        .backgroundColor(Semantic.successSoft)
                        .borderRadius(Radius.full)
                    } else {
                      Button(r.state === PackState.Failed ? '重试' : '下载')
                        .height(36)
                        .fontSize(Font.label)
                        .fontWeight(FontWeight.Medium)
                        .fontColor(TextToken.inverse)
                        .backgroundColor(r.state === PackState.Failed ? Semantic.coral : Semantic.accent)
                        .borderRadius(Radius.full)
                        .padding({ left: Space.s5, right: Space.s5 })
                        .onClick(() => { this.download(r.pack.title); })
                    }
                  }
                  .width('100%')

                  if (r.state === PackState.Downloading) {
                    Progress({ value: r.total > 0 ? r.got : 0, total: r.total > 0 ? r.total : 1, type: ProgressType.Linear })
                      .width('100%')
                      .height(4)
                      .color(Semantic.accent)
                      .backgroundColor(Semantic.track)
                    Row() {
                      Text(`${sizeLabel(r.got)} / ${sizeLabel(r.total > 0 ? r.total : r.pack.bytes)}`)
                        .fontSize(Font.caption)
                        .fontColor(TextToken.secondary)
                      Blank()
                      Text(this.paceLabel(r))
                        .fontSize(Font.caption)
                        .fontColor(Semantic.accent)
                    }
                    .width('100%')
                  }
                }
                .width('100%')
                .padding(Space.s4)
                .backgroundColor(Bg.card)
                .borderRadius(Radius.md)
                .border({ width: 1, color: Semantic.borderSubtle })
              }
            }, (r: PackProgress) => `${r.pack.title}:${r.state}:${r.got}`)
          }
          .width('100%')
          .layoutWeight(1)
          .scrollBar(BarState.Auto)
        }
      }
    }
    .width('100%')
    .layoutWeight(1)
    .padding({ left: Space.s5, right: Space.s5, top: Space.s2, bottom: Space.s4 })
  }
}
