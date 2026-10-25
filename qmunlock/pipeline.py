"""完整编排：musicex → 逐文件获取 ekey → 解密 → 可选整首校验 → 原格式或 MP3。

这是给上层（app / cli）用的主入口：
    from qmunlock.pipeline import convert_mgg, convert_directory

    convert_mgg("刘欢-千万次的问.mgg", outdir="/tmp/out")      # 单首
    convert_directory("/path/to/iQmc", outdir="/tmp/out")      # 批量
"""
import os
from pathlib import Path

from . import credentials, footer, ekey, convert, qmc2
from .verify import require_tools, verify_audio


class DecryptError(Exception):
    pass


def _ekey_cache():
    return {}


def convert_mgg(mgg_path, outdir=None, cred=None, platform="20", log=print,
                output_mode="mp3", verify=False):
    """解密单个 musicex 文件，output_mode=original 保留原音频编码。

    参数：
      mgg_path   加密文件路径
      outdir     输出目录（默认同目录）
      cred       credentials.get_credentials() 结果（缺省则自动读 plist）
      platform   "20"=macOS / "27"=Windows
    """
    if output_mode not in ('original', 'mp3'):
        raise ValueError('output_mode must be original or mp3')
    if verify:
        require_tools()
    outdir = outdir or os.path.dirname(mgg_path) or '.'
    os.makedirs(outdir, exist_ok=True)
    if cred is None:
        cred = credentials.get_credentials()

    with open(mgg_path, 'rb') as f:
        data = f.read()

    # 1. footer → mid + filename
    info = footer.parse_footer(data)
    mid, fname = info['mid'], info['filename']

    # 2. API → ekey
    ekey_b64 = ekey.fetch_ekey_str(mid, fname, cred, platform=platform)

    # 3. 解密（只解 audio 部分）
    alen = footer.audio_length(data)
    plaintext, fmt = qmc2.decrypt_qmc2(data[:alen], ekey_b64)

    # Never publish unknown bytes or overwrite an existing output.
    if fmt not in ('ogg', 'flac', 'm4a', 'mp3'):
        raise DecryptError('解密结果不是已识别的音频，可能使用了错误密钥')
    base = os.path.splitext(os.path.basename(mgg_path))[0]
    mid_path = os.path.join(outdir, base + '.' + fmt)
    suffix = 1
    while True:
        try:
            target = open(mid_path, 'xb')
            break
        except FileExistsError:
            mid_path = os.path.join(outdir, f'{base} ({suffix}).{fmt}')
            suffix += 1
    try:
        with target:
            target.write(plaintext)
        if verify:
            verify_audio(mid_path, fmt)
        if output_mode == 'original' or fmt == 'mp3':
            return mid_path
        return convert.to_mp3(mid_path, outdir)
    except Exception:
        # This file was exclusively created by this call; leave existing files alone.
        os.remove(mid_path)
        raise


def convert_directory(dir_path, outdir=None, cred=None, platform="20",
                      exts=(".mgg", ".mflac", ".mmp4"), log=print,
                      output_mode="mp3", verify=False, mode="audio", metadata_dir=None, cover=False):
    """递归批量解密；每个文件获取对应 ekey，失败继续处理并单独报告。

    返回 [{input, output, ok, error}] 列表。单首失败不中断整批。
    """
    if verify:
        require_tools()
    from .workflow import AUDIO_EXTENSIONS, metadata_index, process_file
    if cover:
        from .covers import require_cover_tools
        require_cover_tools()
    if mode not in ("audio", "audio-lyrics"):
        raise ValueError("mode must be audio or audio-lyrics")
    metadata_root = metadata_dir or (dir_path if os.path.isdir(dir_path) else os.path.dirname(dir_path) or '.')
    index = metadata_index(metadata_root) if mode == "audio-lyrics" or cover else {}
    results = []
    files = []
    if os.path.isfile(dir_path):
        files = [dir_path]
    else:
        for root, _, names in os.walk(dir_path):
            for n in sorted(names):
                if (not n.startswith("._") and
                        n.lower().endswith(exts + (AUDIO_EXTENSIONS if mode == "audio-lyrics" or cover else ()))):
                    files.append(os.path.join(root, n))
    # Defer login access entirely when only filling lyrics beside existing audio.
    if any(Path(fp).suffix.lower() in exts for fp in files):
        cred = cred or credentials.get_credentials()
    for count, fp in enumerate(files, 1):
        result = process_file(fp, outdir, mode=mode, output_mode=output_mode,
                              verify=verify, cred=cred, platform=platform,
                              index=index, converter=convert_mgg, cover=cover)
        results.append(result)
        if mode == "audio-lyrics" or cover:
            log(f"[{count}/{len(files)}] {os.path.basename(fp)} · 音频={'完成' if result['audio_ok'] else '失败'} · 歌词={result['lyrics_status']} · 封面={result['cover_status']}")
    return results


# 便捷别名
convert_file = convert_mgg
