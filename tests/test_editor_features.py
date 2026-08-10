from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import editor


class EditorPresetTests(unittest.TestCase):
    def test_sound_path_resolves_a_sound_bin_item_by_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            sounds_dir = Path(tmp)
            expected = sounds_dir / "yoooh.wav"
            expected.write_bytes(b"RIFF-test")
            with patch.object(editor, "SOUNDS_DIR", sounds_dir):
                self.assertEqual(editor.sound_path("YOOOH"), expected)
                self.assertIsNone(editor.sound_path("missing"))

    def test_custom_preset_scales_boxes_to_another_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            preset_file = Path(tmp) / "editor_presets.json"
            with patch.object(editor, "CUSTOM_PRESETS_FILE", preset_file):
                saved = editor.save_custom_preset(
                    "Discord with chat",
                    {
                        "layout": "reaction",
                        "cam_box": [960, 0, 480, 270],
                        "content_box": [0, 0, 1440, 1080],
                        "audio_normalize": True,
                    },
                    1920,
                    1080,
                )

                scaled = editor.list_custom_presets(1280, 720)[0]
                self.assertEqual(scaled["cam_box"], [640, 0, 320, 180])
                self.assertEqual(scaled["content_box"], [0, 0, 960, 720])
                self.assertTrue(scaled["audio_normalize"])
                self.assertTrue(editor.delete_custom_preset(saved["id"]))
                self.assertEqual(editor.list_custom_presets(1280, 720), [])

    def test_audio_chain_keeps_overlapping_fx_as_separate_layers(self):
        spec = {
            "sound_fx": [
                {"name": "boom", "at": 1.5, "gain": 0.9},
                {"name": "yoooh", "at": 1.5, "gain": 1.1},
            ]
        }

        chain = editor._audio_chain(spec, spec["sound_fx"])

        self.assertEqual(chain.count("adelay=1500|1500"), 2)
        self.assertIn("amix=inputs=3", chain)

    def test_missing_sound_does_not_shift_the_next_fx_timing_or_gain(self):
        # H1 regression: an unresolved sound in the MIDDLE of the list must not
        # slide the surrounding FX onto the wrong at/gain.
        with tempfile.TemporaryDirectory() as tmp:
            sounds_dir = Path(tmp)
            (sounds_dir / "boom.wav").write_bytes(b"RIFF-b")
            (sounds_dir / "yoooh.wav").write_bytes(b"RIFF-y")
            spec = {
                "sound_fx": [
                    {"name": "boom", "at": 1.5, "gain": 0.9},
                    {"name": "missing", "at": 3.0, "gain": 0.2},
                    {"name": "yoooh", "at": 4.25, "gain": 1.3},
                ]
            }

            with patch.object(editor, "SOUNDS_DIR", sounds_dir):
                resolved = editor._resolve_fx_inputs(spec)

            # The missing entry is dropped; boom + yoooh survive in order.
            self.assertEqual(
                [fx for _, fx in resolved],
                [spec["sound_fx"][0], spec["sound_fx"][2]],
            )
            chain = editor._audio_chain(spec, [fx for _, fx in resolved])
            # Each surviving FX keeps its OWN timing + gain.
            self.assertIn("adelay=1500|1500,volume=0.9", chain)
            self.assertIn("adelay=4250|4250,volume=1.3", chain)
            # The dropped sound's 3.0s timing never leaks onto another input.
            self.assertNotIn("3000|3000", chain)

    def test_compilation_with_zero_transition_skips_black_interstitial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.mp4"
            second = root / "second.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            items = [
                {"source": root / "source-a.mp4", "kind": "video", "spec": {}},
                {"source": root / "source-b.mp4", "kind": "video", "spec": {}},
            ]
            with (
                patch.object(editor, "EDITED_DIR", root),
                patch.object(editor, "render_edit", side_effect=[first, second]),
                patch.object(editor, "_render_interstitial") as interstitial,
                patch.object(editor, "_concat_parts", return_value=root / "result.mp4") as concat,
            ):
                result = editor.render_compilation(
                    items,
                    output_stem="result",
                    transition_sound=None,
                    transition_duration=0,
                )

            self.assertEqual(result, root / "result.mp4")
            interstitial.assert_not_called()
            self.assertEqual(concat.call_args.args[0], [first, second])


if __name__ == "__main__":
    unittest.main()
