"""B15: weekday Drive copy of the nightly encrypted backup, digest line, deadman alert."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from importlib.machinery import SourceFileLoader

ROOT = "/root/skv-core"
SCRIPT = os.path.join(ROOT, "ops", "offsite_drive.sh")
EV = SourceFileLoader("ev_offsite", os.path.join(ROOT, "ops", "evolver.py")).load_module()
SLOTS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

FAKE = r'''#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
cmd = args[0] if args else ""
root = os.environ["FAKE_DRIVE"]
os.makedirs(root, exist_ok=True)
open(os.environ["FAKE_CALLS"], "a").write(cmd + "\n")
if cmd == "mkdir":
    sys.exit(0)
if cmd == "copyto":
    if os.environ.get("FAKE_FAIL") == "copyto":
        sys.exit(1)
    src, dest = args[1], args[2]
    name = dest.rstrip("/").split("/")[-1]
    shutil.copyfile(src, os.path.join(root, name))
    sys.exit(0)
if cmd == "lsjson":
    if os.environ.get("FAKE_FAIL") == "lsjson":
        sys.exit(1)
    out = []
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        if n.endswith(".tar.gz.gpg") and os.environ.get("FAKE_LSJSON_SIZE"):
            size = int(os.environ["FAKE_LSJSON_SIZE"])
        out.append({"Name": n, "Path": n, "Size": size, "IsDir": False})
    json.dump(out, sys.stdout)
    sys.exit(0)
sys.stderr.write("unexpected rclone args\n")
sys.exit(2)
'''


def _today_slot(now=None):
    now = now or datetime.now()
    return SLOTS[now.weekday()], now.strftime("%Y-%m-%d")


class OffsiteDriveTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="skv-offsite-")
        self.src = os.path.join(self.td, "offsite")
        self.drive = os.path.join(self.td, "drive")
        self.log = os.path.join(self.td, "drive.log")
        self.calls = os.path.join(self.td, "calls.txt")
        self.conf = os.path.join(self.td, "rclone.conf")
        self.fake = os.path.join(self.td, "rclone")
        self.state = os.path.join(self.td, "deadman.json")
        os.makedirs(self.src)
        open(self.fake, "w").write(FAKE)
        os.chmod(self.fake, 0o755)
        open(self.calls, "w").write("")
        self.env = os.environ.copy()
        self.env.update({
            "SKV_OFFSITE_DIR": self.src,
            "SKV_OFFSITE_DRIVE_LOG": self.log,
            "SKV_OFFSITE_DRIVE_DETAIL": os.path.join(self.td, "detail.log"),
            "SKV_DEADMAN_LOG": os.path.join(self.td, "alert.log"),
            "RCLONE_CONFIG": self.conf,
            "RCLONE_BIN": self.fake,
            "FAKE_DRIVE": self.drive,
            "FAKE_CALLS": self.calls,
            "DEADMAN_DRYRUN": "1",
            "DEADMAN_STATE": self.state,
            "SKV_DRIVE_REMOTE": "gdrive:SKV backups",
        })
        self.env.pop("SKV_OFFSITE_SLOT", None)
        self.env.pop("SKV_OFFSITE_DATE", None)
        self.env.pop("FAKE_FAIL", None)
        self.env.pop("FAKE_LSJSON_SIZE", None)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _run(self, extra=None):
        env = dict(self.env)
        if extra:
            env.update(extra)
        p = subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)
        log = open(self.log).read() if os.path.exists(self.log) else ""
        calls = open(self.calls).read() if os.path.exists(self.calls) else ""
        alert = ""
        ap = env["SKV_DEADMAN_LOG"]
        if os.path.exists(ap):
            alert = open(ap).read()
        return p, log, calls, alert

    def _put(self, name, data, mtime):
        path = os.path.join(self.src, name)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (mtime, mtime))
        return path

    def test_missing_conf_logs_exact_line_and_alerts_once(self):
        p, log, calls, alert = self._run()
        self.assertEqual(p.returncode, 1)
        self.assertIn("fail: no rclone conf\n", log)
        self.assertEqual(calls.strip(), "")
        self.assertIn("DRYRUN mail: SKV ALERT: drive down", alert)
        self.assertIn("no rclone conf", alert)
        p2, log2, calls2, alert2 = self._run()
        self.assertEqual(p2.returncode, 1)
        self.assertEqual(alert2.count("DRYRUN mail: SKV ALERT: drive down"), 1)
        self.assertEqual(calls2.strip(), "")
        blob = p.stdout + p.stderr + log + alert
        self.assertNotIn("rclone.conf", blob.replace(self.conf, ""))

    def test_uploads_newest_slot_sha_and_size(self):
        self._put("skv_20261119_0330.tar.gz.gpg", b"old-archive", 1000)
        path = self._put("skv_20261120_0330.tar.gz.gpg", b"new-archive-bytes", 2000)
        open(self.conf, "w").write("CANARYTOKEN_DO_NOT_LEAK\n")
        os.chmod(self.conf, 0o600)
        slot, today = _today_slot()
        p, log, calls, alert = self._run()
        self.assertEqual(p.returncode, 0, p.stderr + log)
        self.assertIn("ok %s %s skv_20261120_0330.tar.gz.gpg %d\n" % (today, slot, os.path.getsize(path)), log)
        gpg = os.path.join(self.drive, "skv_%s.tar.gz.gpg" % slot)
        sha = os.path.join(self.drive, "skv_%s.sha256" % slot)
        self.assertEqual(open(gpg, "rb").read(), b"new-archive-bytes")
        line = open(sha).read()
        digest = hashlib.sha256(b"new-archive-bytes").hexdigest()
        self.assertEqual(line, "%s  skv_20261120_0330.tar.gz.gpg\n" % digest)
        self.assertNotIn("CANARYTOKEN_DO_NOT_LEAK", p.stdout + p.stderr + log + alert + open(self.env["SKV_OFFSITE_DRIVE_DETAIL"]).read())
        self.assertNotIn("split", calls)
        names = sorted(os.listdir(self.drive))
        self.assertEqual(names, ["skv_%s.sha256" % slot, "skv_%s.tar.gz.gpg" % slot])

    def test_same_slot_overwrites_other_slot_kept(self):
        open(self.conf, "w").write("[gdrive]\ntype = drive\n")
        self._put("skv_a.tar.gz.gpg", b"aaa", 1000)
        p, log, _, _ = self._run({"SKV_OFFSITE_SLOT": "mon", "SKV_OFFSITE_DATE": datetime.now().strftime("%Y-%m-%d")})
        self.assertEqual(p.returncode, 0, log)
        self._put("skv_b.tar.gz.gpg", b"bbbb", 3000)
        p, log, _, _ = self._run({"SKV_OFFSITE_SLOT": "mon", "SKV_OFFSITE_DATE": datetime.now().strftime("%Y-%m-%d")})
        self.assertEqual(p.returncode, 0, log)
        self.assertEqual(open(os.path.join(self.drive, "skv_mon.tar.gz.gpg"), "rb").read(), b"bbbb")
        self._put("skv_c.tar.gz.gpg", b"ccc", 4000)
        p, log, _, _ = self._run({"SKV_OFFSITE_SLOT": "tue", "SKV_OFFSITE_DATE": datetime.now().strftime("%Y-%m-%d")})
        self.assertEqual(p.returncode, 0, log)
        self.assertTrue(os.path.exists(os.path.join(self.drive, "skv_mon.tar.gz.gpg")))
        self.assertEqual(open(os.path.join(self.drive, "skv_tue.tar.gz.gpg"), "rb").read(), b"ccc")
        sha = open(os.path.join(self.drive, "skv_tue.sha256")).read()
        self.assertIn("skv_c.tar.gz.gpg", sha)

    def test_size_mismatch_is_fail(self):
        open(self.conf, "w").write("[gdrive]\n")
        self._put("skv_20261120_0330.tar.gz.gpg", b"payload", 2000)
        p, log, _, alert = self._run({"FAKE_LSJSON_SIZE": "1"})
        self.assertEqual(p.returncode, 1)
        self.assertIn("size mismatch", log)
        self.assertNotIn("\nok ", "\n" + log)
        self.assertIn("DRYRUN mail: SKV ALERT: drive down", alert)

    def test_no_backup_file(self):
        open(self.conf, "w").write("[gdrive]\n")
        p, log, calls, _ = self._run()
        self.assertEqual(p.returncode, 1)
        self.assertIn("no backup file", log)
        self.assertEqual(calls.strip(), "")

    def test_drive_status_lines(self):
        slot, today = _today_slot()
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.assertEqual(EV.drive_status(log_path=os.path.join(self.td, "missing.log"), now=now), "Drive: %s FAIL no log" % slot)
        path = os.path.join(self.td, "p.log")
        open(path, "w").write("noise\nfail: no rclone conf\n")
        self.assertEqual(EV.drive_status(log_path=path, now=now), "Drive: %s FAIL no rclone conf" % slot)
        open(path, "w").write("ok %s %s skv_20261120_0330.tar.gz.gpg 42\n" % (today, slot))
        self.assertEqual(EV.drive_status(log_path=path, now=now), "Drive: %s ok" % slot)
        open(path, "w").write("fail %s %s skv_x.tar.gz.gpg 42 size mismatch remote=1\n" % (today, slot))
        self.assertEqual(EV.drive_status(log_path=path, now=now), "Drive: %s FAIL size mismatch remote=1" % slot)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        open(path, "w").write("ok %s %s skv_x.tar.gz.gpg 42\n" % (yesterday, slot))
        self.assertEqual(EV.drive_status(log_path=path, now=now), "Drive: %s FAIL stale %s" % (slot, yesterday))
        self.assertEqual(EV.drive_probe_error(log_path=os.path.join(self.td, "absent.log"), now=now), "no drive log")
        open(path, "w").write("ok %s %s skv_x.tar.gz.gpg 42\n" % (today, slot))
        self.assertIsNone(EV.drive_probe_error(log_path=path, now=now))

    def test_digest_includes_drive_line(self):
        slot, today = _today_slot()
        open(self.log, "w").write("ok %s %s skv_20261120_0330.tar.gz.gpg 42\n" % (today, slot))
        state = os.path.join(self.td, "digest-state")
        os.makedirs(state)
        os.environ["SKV_OFFSITE_DRIVE_LOG"] = self.log
        bodies = []
        try:
            ok = EV.send_digest(
                now=datetime(2026, 11, 20, 9, 15),
                mail_fn=lambda s, b: bodies.append(b) or True,
                state_dir=state,
                court_fn=lambda: "Court: 0",
                health_fn=lambda: [],
                backup_fn=lambda: "ok",
            )
        finally:
            os.environ.pop("SKV_OFFSITE_DRIVE_LOG", None)
        self.assertTrue(ok)
        self.assertIn("Drive: %s ok" % slot, bodies[0])
        self.assertIn("Backup: ok", bodies[0])

    def test_recovery_mail_after_success(self):
        p, log, _, alert = self._run()
        self.assertEqual(p.returncode, 1)
        open(self.conf, "w").write("[gdrive]\n")
        self._put("skv_20261120_0330.tar.gz.gpg", b"restored", 5000)
        p, log, _, alert = self._run()
        self.assertEqual(p.returncode, 0, log)
        self.assertIn("DRYRUN mail: SKV recovered: drive", alert)
        self.assertEqual(alert.count("DRYRUN mail: SKV ALERT: drive down"), 1)


if __name__ == "__main__":
    unittest.main()
