"""Read local QQ Music credentials without persisting or logging their values.

macOS builds use either container preferences or ~/Library/Preferences.
An unusable archive at one location does not shadow the other location.
"""
import os
import plistlib
from pathlib import Path
from plistlib import UID

DEFAULT_PLIST = os.path.expanduser(
    '~/Library/Containers/com.tencent.QQMusicMac/'
    'Data/Library/Preferences/com.tencent.QQMusicMac.plist'
)


class CredentialsError(Exception):
    pass


def _resolve(objs, value):
    return objs[value.data] if isinstance(value, UID) else value


def credential_paths(home=None):
    home = Path(home) if home is not None else Path.home()
    return (
        home / 'Library/Containers/com.tencent.QQMusicMac/Data/Library/Preferences/com.tencent.QQMusicMac.plist',
        home / 'Library/Preferences/com.tencent.QQMusicMac.plist',
    )


def _read_credentials(path):
    with open(path, 'rb') as source:
        outer = plistlib.load(source)
    if not isinstance(outer, dict) or not isinstance(outer.get('AutoLoginUserInfo'), bytes):
        raise CredentialsError('登录文件中没有 AutoLoginUserInfo，请先登录 QQ 音乐')
    archive = plistlib.loads(outer['AutoLoginUserInfo'])
    objects = archive['$objects']
    if not isinstance(objects, list):
        raise CredentialsError('登录文件归档格式不受支持')
    for obj in objects:
        if not isinstance(obj, dict) or 'strAuthst' not in obj:
            continue
        token = _resolve(objects, obj.get('strAuthst', ''))
        uin = _resolve(objects, obj.get('nUserId', obj.get('strUserAccount', '')))
        if not token or not uin:
            continue
        return {
            'uin': str(uin),
            'authst': token,
            'loginType': str(_resolve(objects, obj.get('loginType', '3'))),
            'openid': _resolve(objects, obj.get('strOpenId', '')),
            'refresh_key': _resolve(objects, obj.get('strRefreshKey', '')),
        }
    raise CredentialsError('登录文件中没有有效凭据，请重新登录 QQ 音乐')


def get_credentials(plist_path=None):
    """Try both default locations, or only the explicitly supplied plist."""
    paths = (Path(plist_path),) if plist_path is not None else credential_paths()
    denied = False
    invalid = False
    for path in paths:
        try:
            return _read_credentials(path)
        except FileNotFoundError:
            continue
        except PermissionError:
            denied = True
        except (CredentialsError, OSError, ValueError, TypeError, KeyError,
                IndexError, plistlib.InvalidFileException):
            invalid = True
    if invalid:
        raise CredentialsError('未找到有效的 QQ 音乐登录信息，请重新登录后检测')
    if denied:
        raise CredentialsError('无法读取 QQ 音乐登录文件，请检查文件访问权限')
    raise CredentialsError('未找到 QQ 音乐登录文件（已检查容器及用户资源库）')
