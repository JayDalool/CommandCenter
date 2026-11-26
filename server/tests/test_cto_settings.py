"""CC-089: the CTO deny-rule template must keep every rule CC-089 c6 requires.

The glob match below approximates Claude Code's Bash(...) matcher; the real proof is Jay's drill (runbook).
"""
import fnmatch
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "scripts" / "cto" / "settings.json"
ID = "a" * 64
BK = "/srv/server/" + "backups"


def _rules():
    return json.loads(TEMPLATE.read_text())["permissions"]["deny"]


def _denied(cmd: str) -> bool:
    for rule in _rules():
        m = re.fullmatch(r"Bash\((.*)\)", rule)
        if m and fnmatch.fnmatchcase(cmd, m.group(1)):
            return True
    return False


class CtoSettingsTemplate(unittest.TestCase):
    def test_only_deny_rules(self):
        data = json.loads(TEMPLATE.read_text())
        self.assertEqual(list(data), ["permissions"])
        self.assertEqual(list(data["permissions"]), ["deny"])  # no allow, defaultMode or hooks (CC-089)

    def test_required_commands_denied(self):
        for cmd in [
            "docker volume ls", "docker volume rm x", "docker volume prune -f",
            "docker system prune", "docker system prune -a --volumes",
            "docker image prune -a", "docker image prune --all", "docker image prune -f -a",
            f"docker rm -f {ID}", f"docker rm --force {ID}", f"docker rm -v {ID}", f"docker rm {ID} -f",
            f"docker container rm -f {ID}", f"docker rmi -f {ID}", f"docker rmi {ID} --force",
            f"docker image rm -f {ID}", f"docker rm --volumes {ID}",
            "docker compose down -v", "docker compose down --volumes", "docker compose -f x.yml down -v",
            "docker-compose down -v", "docker-compose down --volumes",
            "rm -rf /tmp/x", "rm -fr /tmp/x", "rm -Rf /tmp/x", "rm -r -f /tmp/x",
            "rm --recursive --force /tmp/x", "rm /tmp/x -rf", "sudo rm -rf /tmp/x",
            f"rm {BK}/postgres/x", f"mv {BK}/x /tmp", f"cp /tmp/x {BK}/x",
            f"echo x > {BK}/x", f"echo x >> {BK}/x", f"truncate -s0 {BK}/x",
            f"tee {BK}/x", f"chmod 777 {BK}/x",
        ]:
            with self.subTest(cmd=cmd):
                self.assertTrue(_denied(cmd))

    def test_file_edits_under_backups_denied(self):
        rules = _rules()
        self.assertIn("Edit(//srv/server/backups/**)", rules)
        self.assertIn("Write(//srv/server/backups/**)", rules)

    def test_harmless_commands_still_allowed(self):
        for cmd in [
            "docker ps", "docker ps -a", "docker images", "docker system df",
            "docker builder prune -f", f"docker rmi {ID}", f"docker rm {ID}",
            "docker image prune", "docker compose up -d", "docker compose down",
            "scripts/cc-cleanup --run", "scripts/cc-cleanup", f"ls {BK}",
            f"ls -la {BK}/postgres", "df -h",
        ]:
            with self.subTest(cmd=cmd):
                self.assertFalse(_denied(cmd))


class DecisionD058(unittest.TestCase):
    def test_names_tiers_and_rules(self):
        t = (ROOT / "docs" / "decisions" / "D-058.md").read_text().lower()
        for phrase in ["tier 1", "tier 2", "tier 3", "6 months", "scripts/cto/settings.json", "cc-101",
                       "changes need jay", "/home/jay/cto"]:
            self.assertIn(phrase, t)


if __name__ == "__main__":
    unittest.main()
