"""配置层：默认值、文件、环境变量、命令行覆盖的优先级与校验。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pmocr.config import Config
from pmocr.errors import ConfigError
from tests.helpers import make_tmp


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()

    def test_defaults_are_usable(self) -> None:
        cfg = Config.load(environ={})
        self.assertEqual(cfg.threshold, 0.6)
        self.assertEqual(cfg.jev_model, "jev")
        self.assertTrue(cfg.jev_url.startswith("http://"))

    def test_json_overrides_defaults(self) -> None:
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"threshold": 0.75, "jev_url": "http://127.0.0.1:19000"}), "utf-8")
        cfg = Config.load(path, environ={})
        self.assertEqual(cfg.threshold, 0.75)
        self.assertEqual(cfg.jev_url, "http://127.0.0.1:19000")

    def test_env_overrides_file(self) -> None:
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"threshold": 0.75}), "utf-8")
        cfg = Config.load(path, environ={"PMOCR_THRESHOLD": "0.4"})
        self.assertEqual(cfg.threshold, 0.4)

    def test_overrides_beat_env(self) -> None:
        cfg = Config.load(
            None,
            overrides={"threshold": 0.5},
            environ={"PMOCR_THRESHOLD": "0.4"},
        )
        self.assertEqual(cfg.threshold, 0.5)

    def test_none_override_is_ignored(self) -> None:
        cfg = Config.load(None, overrides={"threshold": None, "jev_model": None}, environ={})
        self.assertEqual(cfg.threshold, 0.6)

    def test_unknown_key_is_rejected(self) -> None:
        path = self.tmp / "config.json"
        path.write_text(json.dumps({"thresold": 0.7}), "utf-8")
        with self.assertRaises(ConfigError) as ctx:
            Config.load(path, environ={})
        self.assertIn("thresold", str(ctx.exception))

    def test_bad_type_is_reported(self) -> None:
        with self.assertRaises(ConfigError):
            Config.load(None, overrides={"threshold": "abc"}, environ={})

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaises(ConfigError):
            Config.load(self.tmp / "nope.json", environ={})

    def test_invalid_threshold_fails_validation(self) -> None:
        with self.assertRaises(ConfigError):
            Config.load(None, overrides={"threshold": 1.5}, environ={})

    def test_invalid_url_fails_validation(self) -> None:
        with self.assertRaises(ConfigError):
            Config.load(None, overrides={"jev_url": "127.0.0.1:18499"}, environ={})

    def test_int_field_from_string(self) -> None:
        cfg = Config.load(None, overrides={"max_image_side": "800"}, environ={})
        self.assertEqual(cfg.max_image_side, 800)

    def test_as_dict_roundtrip(self) -> None:
        cfg = Config.load(None, environ={})
        clone = Config.load(None, overrides=cfg.as_dict(), environ={})
        self.assertEqual(cfg, clone)

    def test_unknown_env_var_is_ignored(self) -> None:
        cfg = Config.load(None, environ={"PMOCR_UNKNOWN": "x"})
        self.assertEqual(cfg.threshold, 0.6)


if __name__ == "__main__":
    unittest.main()
