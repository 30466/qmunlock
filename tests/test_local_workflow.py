"""Regression tests use synthetic logins, keys, and audio only."""
import base64
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from qmunlock import credentials, ekey, footer, pipeline, qmc2
from qmunlock.verify import VerificationError, verify_audio


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.home = Path(self.work.name)
        self.paths = credentials.credential_paths(self.home)

    def write_login(self, path, token='test-token', account=12345):
        path.parent.mkdir(parents=True, exist_ok=True)
        archive = {'$objects': [{
            'strAuthst': token, 'strUserAccount': account, 'loginType': 1,
        }]}
        path.write_bytes(plistlib.dumps({'AutoLoginUserInfo': plistlib.dumps(archive)}))

    def test_missing_container_uses_standard_preferences(self):
        self.write_login(self.paths[1])
        with patch.object(credentials, 'credential_paths', return_value=self.paths):
            self.assertEqual(credentials.get_credentials()['uin'], '12345')

    def test_invalid_or_empty_container_does_not_shadow_valid_login(self):
        self.write_login(self.paths[1])
        for content in [b'broken plist', plistlib.dumps({})]:
            self.paths[0].parent.mkdir(parents=True, exist_ok=True)
            self.paths[0].write_bytes(content)
            with patch.object(credentials, 'credential_paths', return_value=self.paths):
                self.assertEqual(credentials.get_credentials()['authst'], 'test-token')
        self.write_login(self.paths[0], token='')
        with patch.object(credentials, 'credential_paths', return_value=self.paths):
            self.assertEqual(credentials.get_credentials()['authst'], 'test-token')

    def test_explicit_path_does_not_silently_use_another_account(self):
        self.write_login(self.paths[1])
        with patch.object(credentials, 'credential_paths', return_value=self.paths):
            with self.assertRaises(credentials.CredentialsError):
                credentials.get_credentials(self.paths[0])

    def test_permission_failure_does_not_hide_readable_fallback(self):
        self.write_login(self.paths[1])
        original = credentials._read_credentials
        def read(path):
            if path == self.paths[0]:
                raise PermissionError()
            return original(path)
        with patch.object(credentials, 'credential_paths', return_value=self.paths), \
                patch.object(credentials, '_read_credentials', side_effect=read):
            self.assertEqual(credentials.get_credentials()['uin'], '12345')

    def test_errors_do_not_disclose_api_payload(self):
        response = {'req_1': {'code': 405, 'sensitive': 'test-secret-token', 'data': {}}}
        with patch.object(ekey, '_post', return_value=response):
            with self.assertRaises(ekey.EKeyError) as raised:
                ekey.fetch_ekey('test-mid', 'test-file', 'test-user', 'test-auth')
        self.assertNotIn('test-secret-token', str(raised.exception))
        self.assertNotIn('test-auth', str(raised.exception))


class FormatTests(unittest.TestCase):
    def test_random_ff_is_not_mp3_and_short_inputs_do_not_crash(self):
        for data in [b'', b'\xff', b'\xffgarbage', b'\xff\xfb\xff\x00', b'ID3bad']:
            self.assertEqual(qmc2.detect_fmt(data), 'bin')
        self.assertEqual(qmc2.detect_fmt(b'\xff\xfb\x90\x00'), 'mp3')
        self.assertEqual(qmc2.detect_fmt(b'ID3\x04\x00\x00\x00\x00\x00\x00'), 'mp3')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('flac'), 'requires ffmpeg and flac')
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.plain = self.root / 'synthetic.flac'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.25', '-c:a', 'flac',
                        str(self.plain)], check=True, capture_output=True)

    def make_encrypted(self, name, plain, key):
        path = self.root / (name + '.mflac')
        resource = 'F000' + name + '.mflac'
        tail = bytearray(192)
        mid = '001234567890ab'.encode('utf-16-le')
        filename = resource.encode('utf-16-le')
        tail[12:12+len(mid)] = mid
        tail[72:72+len(filename)] = filename
        tail[-16:-12] = (192).to_bytes(4, 'little')
        tail[-12:-8] = (1).to_bytes(4, 'little')
        tail[-8:] = b'musicex\x00'
        encrypted = qmc2.map_decrypt(bytearray(plain), key)
        path.write_bytes(encrypted + tail)
        return path, resource

    def test_trailer_is_trimmed_without_reencoding_audio(self):
        original = self.plain.read_bytes()
        self.plain.write_bytes(original + b'non-audio-tail!')
        self.assertEqual(verify_audio(self.plain, 'flac'), 15)
        self.assertEqual(self.plain.read_bytes(), original)

    def test_truncated_audio_fails_instead_of_becoming_success(self):
        self.plain.write_bytes(self.plain.read_bytes()[:-100])
        with self.assertRaises(VerificationError):
            verify_audio(self.plain, 'flac')

    def test_batch_uses_a_separate_key_for_each_file_and_preserves_sources(self):
        audio = self.plain.read_bytes()
        keys = [bytes(range(16, 48)), bytes(range(48, 80))]
        sources, by_resource = [], {}
        for name, key in zip(('001', '002'), keys):
            path, resource = self.make_encrypted(name, audio, key)
            sources.append((path, path.read_bytes()))
            by_resource[resource] = base64.b64encode(key).decode()
        out = self.root / 'out'
        def fetch(mid, resource, cred, platform):
            return by_resource[resource]
        with patch.object(ekey, 'fetch_ekey_str', side_effect=fetch) as mocked:
            results = pipeline.convert_directory(str(self.root), str(out),
                                                 cred={'test': True}, output_mode='original', verify=True)
        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(all(result['ok'] for result in results), results)
        for result in results:
            self.assertEqual(Path(result['output']).read_bytes(), audio)
        for path, original in sources:
            self.assertEqual(path.read_bytes(), original)

    def test_failed_validation_does_not_leave_audio_or_overwrite_existing(self):
        key = bytes(range(16, 48))
        source, resource = self.make_encrypted('003', b'fLaC' + b'broken audio' * 100, key)
        out = self.root / 'out'
        out.mkdir()
        existing = out / '003.flac'
        existing.write_bytes(b'keep existing file')
        with patch.object(ekey, 'fetch_ekey_str', return_value=base64.b64encode(key).decode()):
            with self.assertRaises(VerificationError):
                pipeline.convert_mgg(str(source), str(out), cred={'test': True},
                                     output_mode='original', verify=True)
        self.assertEqual(existing.read_bytes(), b'keep existing file')
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['003.flac'])


class CliTests(unittest.TestCase):
    def test_batch_failures_have_a_nonzero_exit_status(self):
        import cli
        results = [{'input': 'synthetic.mflac', 'ok': False, 'error': 'test failure'}]
        with patch('sys.argv', ['cli.py', 'synthetic-directory', '--format', 'original']), \
                patch.object(cli, 'convert_directory', return_value=results), \
                patch('builtins.print'):
            self.assertEqual(cli.main(), 1)

    def test_missing_credentials_have_a_nonzero_exit_status(self):
        import cli
        with patch('sys.argv', ['cli.py', '--creds']), \
                patch.object(cli, 'get_credentials', side_effect=credentials.CredentialsError('missing')), \
                patch('builtins.print'):
            self.assertEqual(cli.main(), 1)


if __name__ == '__main__':
    unittest.main()
