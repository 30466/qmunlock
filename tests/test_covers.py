"""Cover metadata tests with generated audio and a synthetic 1x1 PNG."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from qmunlock import covers, workflow


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\x40\x80\xc0')) + chunk(b'IEND', b''))


try:
    import mutagen
except ImportError:
    mutagen = None


@unittest.skipUnless(mutagen and shutil.which('ffmpeg') and shutil.which('flac'), 'requires optional cover tools')
class CoverTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)

    def audio(self, fmt):
        path = self.root / ('synthetic.' + fmt)
        codec = {'flac': 'flac', 'ogg': 'libvorbis', 'mp3': 'libmp3lame', 'm4a': 'aac'}[fmt]
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.25', '-c:a', codec, str(path)],
                       check=True, capture_output=True)
        return path

    def test_metadata_edit_preserves_encoded_audio_for_all_supported_formats(self):
        for fmt in ('flac', 'ogg', 'mp3', 'm4a'):
            with self.subTest(fmt=fmt):
                path = self.audio(fmt)
                before = covers.audio_digest(path)
                with patch.object(covers, 'album_for_song', return_value=('001234567890ab', 'Synthetic album')), \
                        patch.object(covers, 'fetch_cover', return_value=png()):
                    self.assertEqual(covers.supplement_cover(path, '001234567890ab'), 'completed')
                self.assertTrue(covers.has_front_cover(path))
                self.assertEqual(covers.audio_digest(path), before)

    def test_existing_front_cover_is_kept_without_network_request(self):
        path = self.audio('flac')
        covers._write_picture(path, png(), 'Existing synthetic cover')
        before = path.read_bytes()
        with patch.object(covers, 'album_for_song') as lookup:
            self.assertEqual(covers.supplement_cover(path, '001234567890ab'), 'existing')
        lookup.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_verification_failure_does_not_replace_original_file(self):
        path = self.audio('flac')
        before = path.read_bytes()
        with patch.object(covers, 'album_for_song', return_value=('001234567890ab', 'Synthetic')), \
                patch.object(covers, 'fetch_cover', return_value=png()), \
                patch.object(covers, 'verify_audio', side_effect=covers.CoverError('test failure')):
            with self.assertRaises(covers.CoverError):
                covers.supplement_cover(path, '001234567890ab')
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(self.root.glob('.qmunlock-cover-*')))

    def test_no_available_cover_is_optional_and_does_not_fail_audio(self):
        path = self.audio('flac')
        before = path.read_bytes()
        with patch.object(workflow, 'matching_mid', return_value='001234567890ab'), \
                patch.object(covers, 'supplement_cover', side_effect=covers.CoverUnavailable('not found')):
            result = workflow.process_file(path, mode='audio', cover=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['cover_status'], 'unavailable')
        self.assertEqual(path.read_bytes(), before)

    def test_duration_change_is_rejected_before_publishing(self):
        path = self.audio('flac')
        before = path.read_bytes()
        properties = covers.audio_properties(path)
        changed = (properties[0] + 1, *properties[1:])
        with patch.object(covers, 'album_for_song', return_value=('001234567890ab', 'Synthetic')), \
                patch.object(covers, 'fetch_cover', return_value=png()), \
                patch.object(covers, 'audio_properties', side_effect=[properties, changed]):
            with self.assertRaises(covers.CoverError):
                covers.supplement_cover(path, '001234567890ab')
        self.assertEqual(path.read_bytes(), before)

    def test_mp4_mislabeled_flac_is_rejected_without_rewriting(self):
        from qmunlock.verify import verify_audio, VerificationError
        source = self.audio('flac')
        mislabeled = self.root / 'mp4-container.flac'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source),
                        '-c:a', 'copy', '-strict', '-2', '-f', 'mp4', str(mislabeled)],
                       check=True, capture_output=True)
        before = mislabeled.read_bytes()
        with self.assertRaises(VerificationError):
            verify_audio(mislabeled, 'flac', repair=False)
        self.assertEqual(mislabeled.read_bytes(), before)

    def test_back_cover_is_preserved_when_adding_front_cover(self):
        from mutagen.flac import FLAC, Picture
        path = self.audio('flac')
        image = Picture()
        image.type, image.mime, image.width, image.height = 4, 'image/png', 1, 1
        image.data = png()
        audio = FLAC(path)
        audio.add_picture(image)
        audio.save()
        with patch.object(covers, 'album_for_song', return_value=('001234567890ab', 'Synthetic')), \
                patch.object(covers, 'fetch_cover', return_value=png()):
            covers.supplement_cover(path, '001234567890ab')
        self.assertEqual(sorted(p.type for p in FLAC(path).pictures), [3, 4])


if __name__ == '__main__':
    unittest.main()
