#!/usr/bin/env python3
"""命令行入口。

用法:
  python cli.py <file.mgg> [输出目录]        # 单首 → mp3
  python cli.py <目录> [输出目录] --format original --verify
  python cli.py --list <目录>                # 只列出可解的 .mgg
  python cli.py --creds                      # 检查本机凭据
"""
import argparse
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qmunlock import (convert_mgg, convert_directory,  # noqa: E402
                       get_credentials, CredentialsError)


def main():
    ap = argparse.ArgumentParser(description="QQ音乐批量处理：解码＋封面，或解码＋封面＋歌词")
    ap.add_argument('target', nargs='?', default=None, help="加密文件或目录，也可为已有音频补封面/歌词")
    ap.add_argument('outdir', nargs='?', default=None, help="输出目录（默认同目录）")
    ap.add_argument('--list', action='store_true', help="只列出可解文件")
    ap.add_argument('--creds', action='store_true', help="检查本机凭据后退出")
    ap.add_argument('--platform', default='20', help="20=macOS 27=Windows")
    ap.add_argument('--format', choices=('original', 'mp3'), default='original',
                    dest='output_mode', help='默认 original 保留原编码；已有音频补封面/歌词时保持原格式')
    ap.add_argument('--verify', action='store_true', default=True, help='默认已启用整首校验；清理合法 FLAC 尾部，需要 ffmpeg 和 flac')
    ap.add_argument('--mode', choices=('audio', 'audio-lyrics'), default='audio',
                    help='audio=解码＋封面（默认）；audio-lyrics=解码＋封面＋同名 LRC')
    ap.add_argument('--metadata-dir', help='为已有音频补封面/歌词时，用同名原始下载文件精确匹配歌曲版本')
    ap.add_argument('--report', help='将逐文件音频/封面/歌词结果另存为 JSON（不包含歌词正文或密钥）')
    args = ap.parse_args()

    if args.creds:
        try:
            get_credentials()
            # authst 是登录凭据，绝不能输出到终端、日志或 CI 记录中。
            print("✅ QQ 音乐登录凭据已读取（不显示帐号或令牌）")
        except CredentialsError as e:
            print(f"❌ {e}")
            return 1
        return 0

    if not args.target:
        ap.print_usage()
        print("需要 <文件.mgg> 或 <目录>（或用 --creds / --list）")
        return 1

    if args.list:
        p = args.target
        if os.path.isfile(p):
            files = [p]
        else:
            files = [os.path.join(r, n) for r, _, ns in os.walk(p)
                     for n in sorted(ns) if n.lower().endswith(('.mgg', '.mflac', '.mmp4'))]
        print(f"找到 {len(files)} 个加密文件:")
        for f in files:
            print("  ", f)
        return 0

    results = convert_directory(args.target, args.outdir, platform=args.platform,
                                output_mode=args.output_mode, verify=args.verify,
                                mode=args.mode, metadata_dir=args.metadata_dir, cover=True)
    ok = [r for r in results if r['ok']]
    bad = [r for r in results if not r['ok']]
    for result in results:
        if result['ok']:
            suffix = f" · 歌词 {result.get('lyrics_status')}" if args.mode == 'audio-lyrics' else ''
            print(f"  ✅ {result['output']}{suffix}")
        else:
            print(f"  ⚠️ {result['input']} → {result.get('error') or result.get('lyrics_error') or result.get('cover_error')}")
    print(f"\n完成: {len(ok)} 成功, {len(bad)} 未全部完成")
    summary = {
        'mode': args.mode, 'total': len(results), 'successful': len(ok),
        'audio_successful': sum(r.get('audio_ok', r['ok']) for r in results),
        'lyrics_successful': sum(r.get('lyrics_status') in ('completed', 'existing') for r in results),
        'lyrics_unavailable': sum(r.get('lyrics_status') == 'unavailable' for r in results),
        'cover_successful': sum(r.get('cover_status') in ('completed', 'existing') for r in results),
        'cover_unavailable': sum(r.get('cover_status') == 'unavailable' for r in results),
        'failed': len(bad), 'files': results,
    }
    if args.mode == 'audio-lyrics':
        print(f"音频完成 {summary['audio_successful']} · 歌词配对 {summary['lyrics_successful']} · 无可用歌词 {summary['lyrics_unavailable']}")
    print(f"封面完成 {summary['cover_successful']} · 未找到封面 {summary['cover_unavailable']}")
    if args.report:
        from pathlib import Path
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if bad else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Do not leak raw API responses, credentials, or ekeys through tracebacks.
        print(f"❌ 处理失败（{type(exc).__name__}），请检查登录状态、文件和校验工具", file=sys.stderr)
        sys.exit(1)
