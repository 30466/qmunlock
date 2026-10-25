"""Synthetic LRC/MID fixtures; never fetch real lyrics in the test suite."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qmunlock import credentials, lyrics, pipeline, workflow

MID = '001234567890ab'
LRC = '[ti:Synthetic test]\n[00:01.20]第一行测试文字\n[00:02.50]第二行测试文字\n'


class LyricTextTests(unittest.TestCase):
    def test_html_escapes_line_endings_and_timestamps_are_preserved(self):
        raw = '\ufeff[00:01.20]A &amp; B&#10;[00:02.50]测试\r\n'
        self.assertEqual(lyrics.normalize_lrc(raw), '[00:01.20]A & B\n[00:02.50]测试\n')

    def test_missing_untimed_or_instrumental_placeholder_is_reported(self):
        for text in ['', None, '没有时间戳', '[00:00.00]纯音乐，请欣赏']:
            with self.assertRaises(lyrics.LyricsUnavailable):
                lyrics.normalize_lrc(text)

    def test_fetch_uses_exact_mid_and_no_login_credentials(self):
        with patch.object(lyrics, '_get_json', return_value={'code': 0, 'lyric': LRC}) as request:
            self.assertEqual(lyrics.fetch_lyric(MID), LRC)
        url = request.call_args.args[0]
        self.assertIn('songmid=' + MID, url)
        self.assertNotIn('authst', url)

    def test_network_errors_are_retried_without_disclosing_response(self):
        with patch.object(lyrics, '_get_json', side_effect=RuntimeError('private-response')) as request, \
                patch.object(lyrics.time, 'sleep'):
            with self.assertRaises(lyrics.LyricsError) as raised:
                lyrics.fetch_lyric(MID)
        self.assertEqual(request.call_count, 3)
        self.assertNotIn('private-response', str(raised.exception))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.audio = self.root / '歌手-测试 (Live).flac'
        self.audio.write_bytes(b'synthetic audio, do not rewrite')
        self.downloads = self.root / 'downloads'
        self.downloads.mkdir()
        self.encrypted = self.downloads / (self.audio.stem + '.mflac')
        self.encrypted.write_bytes(b'synthetic encrypted fixture')
        self.index = workflow.metadata_index(self.downloads)

    def test_sidecar_matches_audio_name_and_preserves_audio(self):
        original = self.audio.read_bytes()
        with patch.object(workflow, 'read_mid', return_value=MID), \
                patch.object(lyrics, 'fetch_lyric', return_value=LRC):
            result = workflow.process_file(self.audio, mode='audio-lyrics', index=self.index)
        self.assertTrue(result['ok'], result)
        self.assertEqual(Path(result['lyrics']), self.audio.with_suffix('.lrc'))
        self.assertEqual(self.audio.with_suffix('.lrc').read_text(encoding='utf-8'), LRC)
        self.assertEqual(self.audio.read_bytes(), original)

    def test_audio_only_never_requests_or_writes_lyrics(self):
        with patch.object(lyrics, 'export_lyric') as export:
            result = workflow.process_file(self.audio, mode='audio')
        self.assertTrue(result['ok'])
        self.assertEqual(result['lyrics_status'], 'not_requested')
        export.assert_not_called()
        self.assertFalse(self.audio.with_suffix('.lrc').exists())

    def test_existing_lrc_is_kept_and_not_downloaded_again(self):
        target = self.audio.with_suffix('.lrc')
        target.write_text(LRC, encoding='utf-8')
        with patch.object(lyrics, 'fetch_lyric') as request:
            path, status = lyrics.export_lyric(self.audio, MID)
        self.assertEqual(status, 'existing')
        self.assertEqual(Path(path).read_text(encoding='utf-8'), LRC)
        request.assert_not_called()

    def test_unreadable_existing_lrc_is_not_overwritten(self):
        target = self.audio.with_suffix('.lrc')
        target.write_bytes(b'preserve manually edited untimed text')
        with self.assertRaises(lyrics.LyricsError):
            lyrics.export_lyric(self.audio, MID)
        self.assertEqual(target.read_bytes(), b'preserve manually edited untimed text')

    def test_missing_lyrics_keep_successful_audio_and_report_partial_result(self):
        original = self.audio.read_bytes()
        with patch.object(workflow, 'read_mid', return_value=MID), \
                patch.object(lyrics, 'fetch_lyric', side_effect=lyrics.LyricsUnavailable('no timed lyrics')):
            result = workflow.process_file(self.audio, mode='audio-lyrics', index=self.index)
        self.assertFalse(result['ok'])
        self.assertTrue(result['audio_ok'])
        self.assertEqual(result['lyrics_status'], 'unavailable')
        self.assertEqual(self.audio.read_bytes(), original)
        self.assertFalse(self.audio.with_suffix('.lrc').exists())

    def test_ambiguous_song_versions_are_not_guessed(self):
        other = self.downloads / 'another.mgg'
        other.write_bytes(b'fixture')
        with patch.object(workflow, 'read_mid', side_effect=[MID, '00different001']):
            with self.assertRaises(lyrics.LyricsError):
                workflow.matching_mid(self.audio, {self.audio.stem: [self.encrypted, other]})

    def test_backfill_needs_no_login_and_never_calls_audio_converter(self):
        inputs = self.root / 'existing'
        inputs.mkdir()
        audio = inputs / self.audio.name
        audio.write_bytes(self.audio.read_bytes())
        with patch.object(credentials, 'get_credentials', side_effect=AssertionError('must not read login')), \
                patch.object(pipeline, 'convert_mgg', side_effect=AssertionError('must not decrypt')), \
                patch.object(workflow, 'read_mid', return_value=MID), \
                patch.object(lyrics, 'fetch_lyric', return_value=LRC):
            results = pipeline.convert_directory(str(inputs), mode='audio-lyrics',
                                                 metadata_dir=str(self.downloads), log=lambda _: None)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['ok'], results)
        self.assertEqual(audio.read_bytes(), self.audio.read_bytes())

    def test_audio_and_lyrics_mode_works_for_encrypted_input_too(self):
        output = self.root / 'new-output.flac'
        def converter(*args, **kwargs):
            output.write_bytes(b'newly decrypted fixture')
            return str(output)
        with patch.object(workflow, 'read_mid', return_value=MID), \
                patch.object(lyrics, 'fetch_lyric', return_value=LRC):
            result = workflow.process_file(self.encrypted, mode='audio-lyrics', converter=converter)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['audio_status'], 'completed')
        self.assertEqual(output.with_suffix('.lrc').read_text(encoding='utf-8'), LRC)

    def test_completed_artwork_and_lrc_need_no_original_metadata(self):
        self.audio.with_suffix('.lrc').write_text(LRC, encoding='utf-8')
        with patch.object(workflow.covers, 'has_front_cover', return_value=True), \
                patch.object(workflow, 'matching_mid', side_effect=AssertionError('no lookup needed')), \
                patch.object(lyrics, 'fetch_lyric', side_effect=AssertionError('no network needed')):
            result = workflow.process_file(self.audio, mode='audio-lyrics', cover=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['cover_status'], 'existing')
        self.assertEqual(result['lyrics_status'], 'existing')

    def test_existing_audio_verification_cannot_trim_source_files(self):
        from qmunlock.verify import verify_audio, VerificationError
        original = self.audio.read_bytes()
        response = type('Response', (), {'returncode': 1})()
        with patch('qmunlock.verify.require_tools'), patch('qmunlock.verify._run', return_value=response):
            with self.assertRaises(VerificationError):
                verify_audio(self.audio, 'flac', repair=False)
        self.assertEqual(self.audio.read_bytes(), original)


class CliModeTests(unittest.TestCase):
    def test_audio_lyrics_flag_and_partial_result_are_reported(self):
        import cli
        import json
        with tempfile.TemporaryDirectory() as root:
            report = Path(root) / 'report.json'
            result = {'input': 'sample.flac', 'output': 'sample.flac', 'ok': False,
                      'audio_ok': True, 'lyrics_status': 'unavailable',
                      'error': None, 'lyrics_error': 'no timed lyrics'}
            args = ['cli.py', 'existing-audio', '--mode', 'audio-lyrics',
                    '--metadata-dir', 'downloads', '--report', str(report)]
            with patch('sys.argv', args), patch('builtins.print'), \
                    patch.object(cli, 'convert_directory', return_value=[result]) as process:
                self.assertEqual(cli.main(), 1)
            self.assertEqual(process.call_args.kwargs['mode'], 'audio-lyrics')
            self.assertTrue(process.call_args.kwargs['cover'])
            self.assertEqual(process.call_args.kwargs['metadata_dir'], 'downloads')
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['audio_successful'], 1)
            self.assertEqual(data['lyrics_unavailable'], 1)

    def test_default_mode_remains_audio_only(self):
        import cli
        with patch('sys.argv', ['cli.py', 'downloads']), patch('builtins.print'), \
                patch.object(cli, 'convert_directory', return_value=[]) as process:
            self.assertEqual(cli.main(), 0)
        self.assertEqual(process.call_args.kwargs['mode'], 'audio')
        self.assertEqual(process.call_args.kwargs['output_mode'], 'original')
        self.assertTrue(process.call_args.kwargs['verify'])
        self.assertTrue(process.call_args.kwargs['cover'])


if __name__ == '__main__':
    unittest.main()
