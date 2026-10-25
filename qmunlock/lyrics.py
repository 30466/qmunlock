"""Fetch timed LRC by exact QQ Music MID and save next to the matching audio."""
import html
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

LYRIC_URL = 'https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg'
TIMESTAMP = re.compile(r'\[(\d+):([0-5]\d)(?:[.:](\d{1,3}))?\]')


class LyricsError(Exception):
    pass


class LyricsUnavailable(LyricsError):
    pass


def normalize_lrc(text):
    if not isinstance(text, str):
        raise LyricsUnavailable('曲库未提供可用歌词')
    text = html.unescape(text).lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text or not TIMESTAMP.search(text):
        raise LyricsUnavailable('曲库未提供带时间轴的 LRC 歌词')
    if any(marker in text for marker in ('纯音乐，请欣赏', '纯音乐,请欣赏', '此歌曲为没有填词的纯音乐')):
        raise LyricsUnavailable('该曲为纯音乐，未导出占位歌词')
    return text + '\n'


def _get_json(url):
    request = urllib.request.Request(url, headers={
        'Referer': 'https://y.qq.com/', 'User-Agent': 'Mozilla/5.0 QMUnlock',
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def fetch_lyric(song_mid):
    if not re.fullmatch(r'[A-Za-z0-9]{14}', song_mid):
        raise LyricsError('歌曲 MID 无效')
    query = urllib.parse.urlencode({
        'songmid': song_mid, 'format': 'json', 'nobase64': 1, 'g_tk': 5381,
        'loginUin': 0, 'hostUin': 0, 'inCharset': 'utf8', 'outCharset': 'utf-8',
        'notice': 0, 'platform': 'yqq.json', 'needNewCode': 0,
    })
    for attempt in range(3):
        try:
            data = _get_json(LYRIC_URL + '?' + query)
            if not isinstance(data, dict) or data.get('code', 0) != 0:
                raise LyricsUnavailable('曲库未返回该歌曲的歌词')
            return normalize_lrc(data.get('lyric'))
        except LyricsUnavailable:
            raise
        except Exception:
            if attempt == 2:
                # Never include response bodies, session values, or lyric text.
                raise LyricsError('歌词请求失败，请检查网络后重试') from None
            time.sleep(0.3 * (attempt + 1))


def export_lyric(audio_path, song_mid):
    """Keep existing LRC files, including manually edited lyrics. No renaming:
    an unusable existing sidecar is reported for review instead of overwritten.
    """
    target = Path(audio_path).with_suffix('.lrc')
    if target.exists():
        try:
            normalize_lrc(target.read_text(encoding='utf-8-sig'))
        except (LyricsError, OSError, UnicodeError):
            raise LyricsError('已有同名 LRC 无法识别，已保留，请检查后重试') from None
        return str(target), 'existing'
    text = fetch_lyric(song_mid)
    try:
        with target.open('x', encoding='utf-8', newline='\n') as output:
            output.write(text)
    except FileExistsError:
        raise LyricsError('同名 LRC 已由其他任务创建，未覆盖') from None
    return str(target), 'completed'
