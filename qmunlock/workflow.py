"""Audio workflow with optional timed LRC; the CLI enables cover enrichment in both modes.

Plain audio can be enriched without replacing or re-encoding its audio stream. Its exact
MID must come from a same-stem original musicex file, never a fuzzy title search.
"""
from pathlib import Path
from . import covers, footer, lyrics
from .verify import verify_audio

ENCRYPTED_EXTENSIONS = ('.mflac', '.mgg', '.mmp4')
AUDIO_EXTENSIONS = ('.flac', '.ogg', '.mp3', '.m4a', '.opus', '.wav')


def read_mid(path):
    with Path(path).open('rb') as source:
        source.seek(0, 2)
        length = source.tell()
        source.seek(max(0, length - 256))
        return footer.parse_footer(source.read())['mid']


def metadata_index(directory):
    result = {}
    if directory is None:
        return result
    root = Path(directory)
    if not root.is_dir():
        raise ValueError('原始下载目录不存在')
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.name.startswith('._') and path.suffix.lower() in ENCRYPTED_EXTENSIONS:
            result.setdefault(path.stem, []).append(path)
    return result


def matching_mid(audio, index):
    mids = set()
    for source in index.get(Path(audio).stem, []):
        try:
            mids.add(read_mid(source))
        except (OSError, footer.NotMusicExError):
            continue
    if not mids:
        raise lyrics.LyricsError('找不到同名原始下载文件，无法精确匹配歌词；请指定 --metadata-dir')
    if len(mids) != 1:
        raise lyrics.LyricsError('同名原始文件对应多个歌曲版本，已停止歌词匹配')
    return mids.pop()


def process_file(input_path, outdir=None, *, mode='audio', output_mode='mp3',
                 verify=False, cred=None, platform='20', index=None, converter=None, cover=False):
    if mode not in ('audio', 'audio-lyrics'):
        raise ValueError('mode must be audio or audio-lyrics')
    if converter is None:
        from .pipeline import convert_mgg
        converter = convert_mgg
    source = Path(input_path)
    result = {'input': str(source), 'output': None, 'ok': False,
              'audio_ok': False, 'lyrics_status': 'not_requested', 'lyrics': None,
              'lyrics_error': None, 'error': None,
              'cover_status': 'not_requested', 'cover_error': None}
    try:
        if source.suffix.lower() in ENCRYPTED_EXTENSIONS:
            output = converter(str(source), outdir, cred=cred, platform=platform,
                               output_mode=output_mode, verify=verify)
            result['audio_status'] = 'completed'
        elif source.suffix.lower() in AUDIO_EXTENSIONS:
            if not source.is_file():
                raise ValueError('音频文件不存在')
            # This path is specifically for supplementing already decoded files.
            # Refuse to silently move or transcode them under --format/OUTPUT.
            if outdir and Path(outdir).resolve() != source.parent.resolve():
                raise ValueError('为已有音频补歌词时请省略输出目录，歌词将写在音频旁')
            if verify:
                verify_audio(source, source.suffix[1:].lower(), repair=False)
            output = str(source)
            result['audio_status'] = 'existing'
        else:
            raise ValueError('不支持的输入格式')
        result.update(output=output, audio_ok=True, ok=True)
    except Exception as exc:
        result['error'] = str(exc)
        return result
    mid = None
    if cover:
        try:
            if covers.has_front_cover(output):
                result['cover_status'] = 'existing'
            else:
                mid = read_mid(source) if source.suffix.lower() in ENCRYPTED_EXTENSIONS else matching_mid(source, index or {})
                result['cover_status'] = covers.supplement_cover(output, mid)
        except covers.CoverUnavailable as exc:
            result.update(cover_status='unavailable', cover_error=str(exc))
        except Exception as exc:
            message = str(exc) if isinstance(exc, (covers.CoverError, lyrics.LyricsError)) else '封面处理失败，原音频保留'
            result.update(ok=False, cover_status='failed', cover_error=message)
    if mode == 'audio':
        return result
    try:
        if mid is None and not Path(output).with_suffix('.lrc').exists():
            mid = read_mid(source) if source.suffix.lower() in ENCRYPTED_EXTENSIONS else matching_mid(source, index or {})
        result['lyrics'], result['lyrics_status'] = lyrics.export_lyric(output, mid)
    except lyrics.LyricsUnavailable as exc:
        result.update(ok=False, lyrics_status='unavailable', lyrics_error=str(exc))
    except Exception as exc:
        message = str(exc) if isinstance(exc, lyrics.LyricsError) else '歌词处理失败'
        result.update(ok=False, lyrics_status='failed', lyrics_error=message)
    return result
