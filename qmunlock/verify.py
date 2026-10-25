"""Optional full audio validation; no transcoding or credentials are involved."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


class VerificationError(Exception):
    pass


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError('音频校验程序无法运行或超时') from exc


def require_tools():
    if not shutil.which('ffmpeg') or not shutil.which('flac'):
        raise VerificationError('--verify 需要 PATH 中有 ffmpeg 和 flac')


def verify_audio(path, fmt, *, repair=True):
    """Validate a newly decrypted file. Trim only a bounded FLAC trailer after
    all declared samples have been decoded, then require FLAC MD5/CRC checks.
    A corrupt or truncated audio frame is never accepted as a removable trailer.
    """
    require_tools()
    path = Path(path)
    removed = 0
    if fmt == 'flac':
        checked = _run(['flac', '--silent', '--test', '--', str(path)])
        if checked.returncode:
            if not repair:
                raise VerificationError('已有 FLAC 未通过校验，未改动音频文件')
            with path.open('rb') as source:
                head = source.read(42)
            if head[:4] != b'fLaC' or len(head) != 42:
                raise VerificationError('FLAC 文件头无效')
            total = int.from_bytes(head[18:26], 'big') & ((1 << 36) - 1)
            with tempfile.TemporaryDirectory(prefix='qmunlock-check-') as work:
                analysis = Path(work) / 'frames.txt'
                _run(['flac', '--silent', '--analyze', '--decode-through-errors',
                      '--force', '--output-name=' + str(analysis), '--', str(path)])
                samples, last = 0, None
                if analysis.exists():
                    with analysis.open() as source:
                        for line in source:
                            if line.startswith('frame='):
                                last = dict(re.findall(r'(\w+)=([^\t\n]+)', line))
                                samples += int(last['blocksize'])
                if not total or samples != total or last is None:
                    raise VerificationError('FLAC 音频不完整或校验失败')
                end = int(last['offset']) + int(last['bits']) // 8
                removed = path.stat().st_size - end
                if not 0 < removed <= 4096:
                    raise VerificationError('FLAC 尾部不符合可清理范围')
                with path.open('r+b') as output:
                    output.truncate(end)
            if _run(['flac', '--silent', '--test', '--', str(path)]).returncode:
                raise VerificationError('FLAC 完整性校验失败')
    decoded = _run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror',
                    '-i', str(path), '-map', '0:a:0', '-f', 'null', '-'])
    if decoded.returncode:
        raise VerificationError('整首音频解码失败，可能使用了错误的密钥')
    return removed
