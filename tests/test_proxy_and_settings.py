import unittest
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import ui.views.settings_view as settings_view
from ui.views.settings_view import load_config, save_config, get_telegram_proxy


class TestProxyAndSettings(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_config_file = settings_view.CONFIG_FILE
        settings_view.CONFIG_FILE = os.path.join(self.temp_dir, "test_config.json")

    def tearDown(self):
        settings_view.CONFIG_FILE = self.orig_config_file
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_proxy_disabled_returns_none(self):
        cfg = load_config()
        cfg["proxy"]["enabled"] = False
        cfg["proxy"]["host"] = "127.0.0.1"
        cfg["proxy"]["port"] = "1080"
        save_config(cfg)

        proxy = get_telegram_proxy()
        self.assertIsNone(proxy)

    def test_proxy_enabled_valid_socks5(self):
        cfg = load_config()
        cfg["proxy"] = {
            "enabled": True,
            "type": "SOCKS5",
            "host": "127.0.0.1",
            "port": "1080",
            "user": "myuser",
            "pass": "mypass"
        }
        save_config(cfg)

        proxy = get_telegram_proxy()
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy["proxy_type"], "socks5")
        self.assertEqual(proxy["addr"], "127.0.0.1")
        self.assertEqual(proxy["port"], 1080)
        self.assertTrue(proxy["rdns"])
        self.assertEqual(proxy["username"], "myuser")
        self.assertEqual(proxy["password"], "mypass")

    def test_proxy_enabled_http_and_socks4(self):
        cfg = load_config()
        cfg["proxy"] = {
            "enabled": True,
            "type": "HTTP",
            "host": "proxy.example.com",
            "port": 8080,
            "user": "",
            "pass": ""
        }
        save_config(cfg)

        proxy = get_telegram_proxy()
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy["proxy_type"], "http")
        self.assertEqual(proxy["addr"], "proxy.example.com")
        self.assertEqual(proxy["port"], 8080)
        self.assertNotIn("username", proxy)
        self.assertNotIn("password", proxy)

    def test_proxy_invalid_port_returns_none(self):
        cfg = load_config()
        cfg["proxy"] = {
            "enabled": True,
            "type": "SOCKS5",
            "host": "127.0.0.1",
            "port": "invalid_port",
            "user": "",
            "pass": ""
        }
        save_config(cfg)

        proxy = get_telegram_proxy()
        self.assertIsNone(proxy)

    def test_proxy_missing_host_returns_none(self):
        cfg = load_config()
        cfg["proxy"] = {
            "enabled": True,
            "type": "SOCKS5",
            "host": "",
            "port": "1080",
            "user": "",
            "pass": ""
        }
        save_config(cfg)

        proxy = get_telegram_proxy()
        self.assertIsNone(proxy)

    def test_dark_mode_preserved_on_save(self):
        # Issue #28 reproduction & verification
        initial_cfg = load_config()
        initial_cfg["dark_mode"] = True
        initial_cfg["custom_third_party_key"] = "preserved_value"
        save_config(initial_cfg)

        # Verify it was saved
        loaded = load_config()
        self.assertTrue(loaded["dark_mode"])
        self.assertEqual(loaded["custom_third_party_key"], "preserved_value")

        # Simulate settings page saving unrelated configuration
        updated_settings = load_config()
        updated_settings.update({
            "download_path": "new_downloads_path",
            "download_limit": 10
        })
        save_config(updated_settings)

        # Verify dark_mode and custom keys survived
        after_save = load_config()
        self.assertEqual(after_save["download_path"], "new_downloads_path")
        self.assertEqual(after_save["download_limit"], 10)
        self.assertTrue(after_save.get("dark_mode"))
        self.assertEqual(after_save.get("custom_third_party_key"), "preserved_value")

    def test_normalize_channel_key(self):
        from database import normalize_channel_key
        self.assertEqual(normalize_channel_key("https://t.me/my_channel_name"), "my_channel_name")
        self.assertEqual(normalize_channel_key("@my_channel_name"), "my_channel_name")
        self.assertEqual(normalize_channel_key("-1001234567890"), "1234567890")
        self.assertEqual(normalize_channel_key("1234567890"), "1234567890")

    def test_task_pause_persistence(self):
        import database
        test_db = os.path.join(self.temp_dir, "test_tasks.db")
        orig_db = database.DB_PATH
        database.DB_PATH = test_db
        try:
            database.init_db()
            task = {
                "channel_input": "https://t.me/vision_ias_hindi_lec",
                "media_id": 6,
                "paused": False,
                "title": "Vision IAS New Video Lecture Hindi"
            }
            database.save_task_db(task)
            
            # Check initially not paused
            loaded = database.load_active_tasks_db()
            self.assertEqual(len(loaded), 1)
            self.assertFalse(loaded[0]["paused"])
            
            # Pause task
            database.update_task_paused_db("https://t.me/vision_ias_hindi_lec", is_paused=True)
            loaded_after = database.load_active_tasks_db()
            self.assertTrue(loaded_after[0]["paused"])
        finally:
            database.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
