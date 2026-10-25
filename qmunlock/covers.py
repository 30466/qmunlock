"""Optional album art enrichment. Metadata changes only; verify before publish."""
import base64
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

from .lyrics import _get_json
from .verify import require_tools, verify_audio


class CoverError(Exception):
    pass


class CoverUnavailable(CoverError):
    pass


def require_cover_tools():
    try:
        import mutagen  # noqa: F401
    except ImportError:
        raise CoverError('封面功能需要安装 requirements.txt 中的 mutagen') from None
    require_tools()


def _pictures(audio, fmt):
    from mutagen.flac import Picture
    if fmt == 'flac':
        return list(audio.pictures)
    if fmt == 'ogg':
        result = []
        for value in audio.get('metadata_block_picture', []):
            try:
                result.append(Picture(base64.b64decode(value)))
            except Exception:
                continue
        return result
    return []


def has_front_cover(path):
    import mutagen
    fmt = Path(path).suffix[1:].lower()
    audio = mutagen.File(path)
    if audio is None:
        raise CoverError('无法识别音频标签')
    if fmt in ('flac', 'ogg'):
        return any(p.type == 3 and p.data for p in _pictures(audio, fmt))
    if fmt == 'mp3':
        return bool(audio.tags and any(p.type == 3 for p in audio.tags.getall('APIC')))
    if fmt == 'm4a':
        return bool(audio.tags and audio.tags.get('covr'))
    return False


@lru_cache(maxsize=1024)
def album_for_song(song_mid):
    if not re.fullmatch(r'[A-Za-z0-9]{14}', song_mid):
        raise CoverUnavailable('歌曲标识无效，未获取封面')
    query = urllib.parse.urlencode({'songmid': song_mid, 'platform': 'yqq',
                                   'format': 'json', 'needNewCode': 0, 'new_json': 1})
    try:
        value = _get_json('https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg?' + query)
        song = value['data'][0]
        album = song['album']
        mid = album['mid']
        if not re.fullmatch(r'[A-Za-z0-9]{14}', mid):
            raise ValueError()
        return mid, album.get('name', '')
    except Exception:
        raise CoverUnavailable('曲库未返回对应专辑封面信息') from None


def image_info(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return 'image/png', int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if data.startswith(b'\xff\xd8'):
        pos = 2
        while pos + 9 <= len(data):
            if data[pos] != 255:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                pos += 2
                continue
            length = int.from_bytes(data[pos+2:pos+4], 'big')
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                return 'image/jpeg', int.from_bytes(data[pos+7:pos+9], 'big'), int.from_bytes(data[pos+5:pos+7], 'big')
            if length < 2:
                break
            pos += length + 2
    raise CoverUnavailable('未取得有效的 JPEG 或 PNG 封面')


@lru_cache(maxsize=256)
def fetch_cover(album_mid):
    for size in (800, 500, 300):
        url = f'https://y.gtimg.cn/music/photo_new/T002R{size}x{size}M000{album_mid}.jpg'
        try:
            request = urllib.request.Request(url, headers={'Referer': 'https://y.qq.com/', 'User-Agent': 'Mozilla/5.0 QMUnlock'})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(5 * 1024 * 1024 + 1)
            mime, width, height = image_info(data)
            if len(data) <= 5 * 1024 * 1024 and 0 < width <= 10000 and 0 < height <= 10000:
                return data
        except Exception:
            continue
    raise CoverUnavailable('未找到可下载的对应专辑封面，已跳过')


def audio_digest(path):
    """FLAC: hash exact frame bytes and STREAMINFO. Other formats: hash encoded
    audio packets, excluding artwork/tags and Ogg page framing.
    """
    path = Path(path)
    if path.suffix.lower() == '.flac':
        digest = hashlib.sha256()
        with path.open('rb') as source:
            if source.read(4) != b'fLaC':
                raise CoverError('不是原生 FLAC，拒绝改写标签')
            info = None
            while True:
                head = source.read(4)
                if len(head) != 4:
                    raise CoverError('FLAC 元数据不完整')
                size = int.from_bytes(head[1:], 'big')
                data = source.read(size)
                if len(data) != size:
                    raise CoverError('FLAC 元数据不完整')
                if head[0] & 127 == 0:
                    info = data
                if head[0] & 128:
                    break
            if info is None:
                raise CoverError('FLAC 缺少 STREAMINFO')
            digest.update(info)
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()
    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
                             '-map', '0:a:0', '-c:a', 'copy', '-f', 'hash', '-hash', 'sha256', '-'],
                            capture_output=True, timeout=300)
    if result.returncode:
        raise CoverError('无法校验原始音频流')
    return result.stdout.strip().decode('ascii')


def _write_picture(path, image, description):
    import mutagen
    from mutagen.flac import Picture
    from mutagen.id3 import APIC
    from mutagen.mp4 import MP4Cover
    fmt = Path(path).suffix[1:].lower()
    audio = mutagen.File(path)
    mime, width, height = image_info(image)
    if audio is None:
        raise CoverError('无法识别音频标签')
    if fmt in ('flac', 'ogg'):
        picture = Picture()
        picture.type, picture.mime, picture.desc = 3, mime, description
        picture.width, picture.height, picture.depth = width, height, 24
        picture.data = image
        if fmt == 'flac':
            audio.add_picture(picture)
        else:
            audio['metadata_block_picture'] = audio.get('metadata_block_picture', []) + [base64.b64encode(picture.write()).decode('ascii')]
    elif fmt == 'mp3':
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc=description, data=image))
    elif fmt == 'm4a':
        if audio.tags is None:
            audio.add_tags()
        audio.tags['covr'] = [MP4Cover(image, imageformat=MP4Cover.FORMAT_PNG if mime == 'image/png' else MP4Cover.FORMAT_JPEG)]
    audio.save()


def audio_properties(path):
    import mutagen
    audio = mutagen.File(path)
    if audio is None:
        raise CoverError('无法读取音频时长信息')
    return (round(audio.info.length, 9), getattr(audio.info, 'sample_rate', None),
            getattr(audio.info, 'channels', None), getattr(audio.info, 'bits_per_sample', None))


def supplement_cover(audio_path, song_mid):
    require_cover_tools()
    path = Path(audio_path).resolve()
    fmt = path.suffix[1:].lower()
    if fmt not in ('flac', 'ogg', 'mp3', 'm4a'):
        raise CoverUnavailable('该格式暂不补封面，音频保持不变')
    if has_front_cover(path):
        return 'existing'
    album_mid, description = album_for_song(song_mid)
    image = fetch_cover(album_mid)
    before = path.stat()
    signature = (before.st_size, before.st_mtime_ns)
    digest = audio_digest(path)
    properties = audio_properties(path)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.qmunlock-cover-', suffix=path.suffix, dir=path.parent)
        import os
        os.close(fd)
        temporary = Path(name)
        shutil.copy2(path, temporary)
        _write_picture(temporary, image, description)
        if (not has_front_cover(temporary) or audio_digest(temporary) != digest
                or audio_properties(temporary) != properties):
            raise CoverError('封面写入后音频流校验失败，保留原文件')
        verify_audio(temporary, fmt, repair=False)
        current = path.stat()
        if (current.st_size, current.st_mtime_ns) != signature:
            raise CoverError('处理期间文件已被修改，保留原文件')
        temporary.replace(path)
        return 'completed'
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
