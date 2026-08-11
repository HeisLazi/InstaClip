"""Face-centered reframe geometry (injected faces — no mediapipe/ffmpeg)."""

import unittest

from modules import face_locator


def _face(x, y, w, h, fw=1920, fh=1080):
    return [{"x": x, "y": y, "w": w, "h": h, "frame_w": fw, "frame_h": fh,
             "area_ratio": (w * h) / (fw * fh)}]


class FaceCropTests(unittest.TestCase):
    def test_crop_centers_on_face(self):
        # Face left-of-center in a 1920x1080 frame (the cut-off-face bug scenario).
        crop = face_locator.face_centered_crop_box(
            "v.mp4", 5.0, 1920, 1080, faces=_face(400, 300, 200, 220))
        x, y, w, h = crop
        self.assertEqual((w, h), (608, 1080))       # 9:16 of full height
        face_cx = 400 + 100
        self.assertLessEqual(abs((x + w / 2) - face_cx), 1)  # centered on face

    def test_crop_clamps_at_frame_edges(self):
        crop = face_locator.face_centered_crop_box(
            "v.mp4", 5.0, 1920, 1080, faces=_face(0, 0, 150, 150))
        x, y, w, h = crop
        self.assertEqual(x, 0)                       # clamped, no negative crop
        self.assertGreaterEqual(y, 0)

    def test_none_when_no_face(self):
        self.assertIsNone(face_locator.face_centered_crop_box(
            "v.mp4", 5.0, 1920, 1080, faces=[]))
        self.assertIsNone(face_locator.face_cam_box(
            "v.mp4", 5.0, 1920, 1080, faces=[]))

    def test_cam_box_expands_and_clamps(self):
        cam = face_locator.face_cam_box(
            "v.mp4", 5.0, 1920, 1080, expand=2.0, faces=_face(1700, 100, 180, 200))
        x, y, w, h = cam
        self.assertEqual((w, h), (360, 400))
        self.assertLessEqual(x + w, 1920)            # clamped inside the frame


class EditorFaceDefaultTests(unittest.TestCase):
    def test_default_boxes_use_face_when_available(self):
        from unittest import mock
        from modules import editor
        spec = {"layout": "crop", "trim": {"start": 10, "end": 20}}
        info = {"width": 1920, "height": 1080}
        with mock.patch("modules.face_locator.locate_faces",
                        return_value=_face(200, 300, 200, 220)):
            out = editor._default_layout_boxes(spec, info, source=editor.Path("v.mp4"))
        x, y, w, h = out["crop_box"]
        self.assertEqual((w, h), (608, 1080))
        self.assertLess(x, 300)                      # near the left-side face,
        # not the centered template default (which would be x=656)

    def test_default_boxes_fall_back_to_template(self):
        from unittest import mock
        from modules import editor
        spec = {"layout": "crop"}
        info = {"width": 1920, "height": 1080}
        with mock.patch("modules.face_locator.locate_faces", return_value=[]):
            out = editor._default_layout_boxes(spec, info, source=editor.Path("v.mp4"))
        self.assertIn("crop_box", out)               # template default kept


class EnrolledFacePickTests(unittest.TestCase):
    def test_picks_enrolled_face_over_bigger_guest(self):
        # Guest face is BIGGER; enrolled signature matches the smaller face.
        guest = {"x": 800, "y": 200, "w": 400, "h": 450, "frame_w": 1920, "frame_h": 1080,
                 "area_ratio": 0.087}
        lazi = {"x": 100, "y": 100, "w": 200, "h": 220, "frame_w": 1920, "frame_h": 1080,
                "area_ratio": 0.021}
        sig_lazi = [1.0] + [0.0] * 127
        sig_guest = [0.0] * 127 + [1.0]

        def fake_sig(image, box):
            return sig_lazi if box["x"] == 100 else sig_guest

        picked = face_locator.pick_enrolled_face(
            [guest, lazi], "frame.jpg", signatures=[sig_lazi], sig_fn=fake_sig)
        self.assertEqual(picked["x"], 100)
        self.assertEqual(picked["identity"], "lazi")

    def test_falls_back_to_largest_without_enrollment(self):
        a = {"x": 0, "y": 0, "w": 300, "h": 300}
        b = {"x": 500, "y": 0, "w": 100, "h": 100}
        picked = face_locator.pick_enrolled_face([a, b], "frame.jpg", signatures=[])
        self.assertEqual(picked["x"], 0)

    def test_low_similarity_falls_back_to_largest(self):
        a = {"x": 0, "y": 0, "w": 300, "h": 300}
        sig_ref = [1.0] + [0.0] * 127
        picked = face_locator.pick_enrolled_face(
            [a], "frame.jpg", signatures=[sig_ref],
            sig_fn=lambda img, box: [0.0] * 127 + [1.0])  # nothing alike
        self.assertEqual(picked["x"], 0)
        self.assertNotIn("identity", picked)


class VoiceRefineTests(unittest.TestCase):
    def test_guest_heavy_outlier_is_dropped(self):
        import numpy as np
        import tempfile
        from pathlib import Path as P
        from modules.speaker_id import speaker_id
        tmp = tempfile.TemporaryDirectory()
        orig = speaker_id.SPEAKERS_DIR
        speaker_id.SPEAKERS_DIR = P(tmp.name)
        try:
            base = np.zeros(8, dtype=np.float32); base[0] = 1.0
            outlier = np.zeros(8, dtype=np.float32); outlier[7] = 1.0  # guest voice
            embs = {f"k{i}.mp4": base + np.float32(0.01) * i for i in range(5)}
            embs["guest.mp4"] = outlier
            rep = speaker_id.enroll_from_keepers(
                "lazi", clip_paths=[P(n) for n in embs],
                embedder=lambda p: embs[p.name])
            saved = np.load(P(tmp.name) / "lazi.npy")
            # Outlier dropped: the print points at the streamer axis, not the guest's.
            self.assertGreater(float(saved[0]), 0.95)
            self.assertLess(float(saved[7]), 0.05)
            self.assertEqual(rep["samples"], 4)  # 70% of 6 → 4 kept
        finally:
            speaker_id.SPEAKERS_DIR = orig
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
