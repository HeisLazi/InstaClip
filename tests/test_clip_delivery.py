"""Phase 3 follow-up — deliver edited clips to Discord (attach small, notice big).

No network, no real bot: a recording gateway captures posts. The public edition
has no tunnel fallback, so oversize files degrade to a local notice instead of a
public download link.
"""

import tempfile
import unittest
from pathlib import Path

from modules import clip_delivery


class RecordingGateway:
    def __init__(self):
        self.results = []   # (thread_id, version)
        self.notices = []   # text messages

    def post_candidate_card(self, card):
        return {"message_id": "m", "thread_id": "t"}

    def post_render_result(self, thread_id, version):
        self.results.append((thread_id, version))

    def notify(self, message):
        self.notices.append(message)


class ClipDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.gw = RecordingGateway()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name, size):
        p = self.tmp / name
        p.write_bytes(b"\0" * size)
        return p

    def test_small_file_attaches_via_post_render_result(self):
        p = self._file("small.mp4", 1024)
        rep = clip_delivery.deliver_clip(p, thread_id="thr-1", gateway=self.gw)
        self.assertEqual(rep["delivered"], "file")
        self.assertEqual(len(self.gw.results), 1)
        self.assertEqual(self.gw.results[0][0], "thr-1")
        self.assertEqual(self.gw.notices, [])

    def test_missing_file_falls_back_to_post_render_result(self):
        # Preserves the prior behaviour: the bot posts its "get it from the app"
        # notice when there's no attachable file on disk.
        rep = clip_delivery.deliver_clip(self.tmp / "nope.mp4", thread_id="t", gateway=self.gw)
        self.assertEqual(rep["delivered"], "notice")
        self.assertEqual(len(self.gw.results), 1)

    def test_large_file_falls_back_to_local_notice(self):
        # Public edition: no quick-tunnel URLs are ever exposed. The too-big path
        # falls through to the normal post_render_result notice (no notices array
        # entry unless the gateway itself fails).
        p = self._file("big.mp4", clip_delivery.DISCORD_ATTACH_LIMIT + 1)
        rep = clip_delivery.deliver_clip(p, thread_id="t", gateway=self.gw)
        self.assertEqual(rep["delivered"], "notice")
        self.assertEqual(len(self.gw.results), 1)
        self.assertEqual(self.gw.notices, [])

    def test_failed_attach_posts_local_notice(self):
        # Regression: real Discord 413'd a 17MB attach (10MB non-boost cap) and the
        # delivery used to die silently. Now it degrades to a local notice.
        class Boom413(RecordingGateway):
            def post_render_result(self, thread_id, version):
                raise RuntimeError("413 Payload Too Large (error code: 40005)")

        gw = Boom413()
        p = self._file("mid.mp4", 1024)
        rep = clip_delivery.deliver_clip(p, thread_id="t", gateway=gw)
        self.assertEqual(rep["delivered"], "notice")
        self.assertEqual(len(gw.notices), 1)
        self.assertIn("public tunnel delivery is not included", gw.notices[0])


if __name__ == "__main__":
    unittest.main()
