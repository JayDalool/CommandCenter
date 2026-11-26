"""CC-089: the CTO deny-rule template must keep every rule the security review and Jay's question 217 require.

The glob match below approximates Claude Code's Bash(...) matcher (which does not strip sudo); the real proof is
Jay's drill (runbook). Each group below has its own fixtures, so deleting a group of rules fails a test.
"""
import fnmatch
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "scripts" / "cto" / "settings.json"
ID = "a" * 64
SB = "/srv/server/" + "backups"
HB = "/home/jay/" + "backups"


def _rules():
    return json.loads(TEMPLATE.read_text())["permissions"]["deny"]


def _denied(cmd: str) -> bool:
    for rule in _rules():
        m = re.fullmatch(r"Bash\((.*)\)", rule)
        if m and fnmatch.fnmatchcase(cmd, m.group(1)):
            return True
    return False


class Fixtures(unittest.TestCase):
    def check(self, cmds):
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                self.assertTrue(_denied(cmd))


class CtoSettingsTemplate(Fixtures):
    def test_only_deny_rules(self):
        data = json.loads(TEMPLATE.read_text())
        self.assertEqual(list(data), ["permissions"])
        self.assertEqual(list(data["permissions"]), ["deny"])  # allows nothing (CC-089)

    def test_docker_volume(self):
        self.check(["docker volume ls", "docker volume rm x", "sudo docker volume prune -f",
                    "docker -H unix:///x volume ls", "docker --context c volume rm x"])

    def test_system_and_prunes_regardless_of_flags(self):
        self.check(["docker system prune", "sudo docker system prune -a --volumes",
                    "docker image prune", "docker image prune -f", "docker image prune -a", "docker image prune --all",
                    "sudo docker image prune", "docker container prune", "docker container prune -f",
                    "docker -H x container prune"])

    def test_forced_and_volume_removes_all_aliases(self):
        self.check([f"docker rm -f {ID}", f"docker rm --force {ID}", f"docker rm -v {ID}", f"docker rm {ID} -f",
                    f"docker rm --volumes {ID}", f"sudo docker rm -f {ID}", f"docker container rm -f {ID}",
                    f"docker container remove -f {ID}", f"docker rmi -f {ID}", f"docker rmi {ID} --force",
                    f"docker image rm -f {ID}", f"docker image remove --force {ID}", f"sudo docker rmi -f {ID}",
                    f"docker rm -fv {ID}",
                    # flags after the operand (separate rules from flags before it)
                    f"docker rm {ID} -v", f"docker rm {ID} --volumes", f"docker rmi {ID} -v",
                    f"docker rmi {ID} --volumes", f"docker container rm {ID} -v",
                    f"docker image rm {ID} --volumes"])

    def test_compose_down_volumes_all_spellings(self):
        self.check(["docker compose down -v", "docker compose down --volumes", "docker compose -f x.yml down -v",
                    "docker --host h compose -p n down -v", "sudo docker compose down --volumes",
                    "docker-compose down -v", "docker-compose down --volumes", "docker-compose -f a.yml down -v",
                    "sudo docker-compose down -v", "docker compose rm -v", "docker compose rm --volumes"])

    def test_rm_recursive_any_flag_form(self):
        self.check(["rm -rf /tmp/x", "rm -fr /tmp/x", "rm -Rf /tmp/x", "rm -r -f /tmp/x", "rm -f -r /tmp/x",
                    "rm --recursive --force /tmp/x", "rm --force --recursive /tmp/x", "rm -r --force /tmp/x",
                    "rm --recursive -f /tmp/x", "rm -f --recursive /tmp/x", "rm /tmp/x -rf", "sudo rm -rf /tmp/x",
                    "rm -vrf /tmp/x", "rm -r /tmp/x"])

    def test_find_delete(self):
        self.check(["find /tmp -delete", "find /tmp -name x -delete", "sudo find /tmp -exec rm {} ;",
                    f"find {SB} -delete", f"find {HB}/ -delete", f"find {SB}/ -type f -delete"])

    def test_both_backup_trees_bash(self):
        for tree in (SB, HB):
            for operand in (tree, tree + "/", tree + "/postgres/x"):
                self.check([f"rm {operand}", f"sudo rm {operand}", f"mv {operand} /tmp", f"cp /tmp/x {operand}",
                            f"echo x > {operand}", f"echo x >> {operand}", f"truncate -s0 {operand}",
                            f"tee {operand}", f"chmod 777 {operand}", f"rsync -a /tmp/x {operand}",
                            f"sed -i s/a/b/ {operand}"])

    def test_edit_and_write_rules(self):
        rules = _rules()
        for tool in ("Edit", "Write"):
            for target in ("//srv/server/backups/**", "//srv/server/backups", "//home/jay/backups/**",
                           "//home/jay/backups", "//home/jay/cto/.claude/**", "//home/jay/cto/.claude",
                           "//home/jay/cto/CLAUDE.md", "//home/jay/.claude/settings.json",
                           "//home/jay/.claude/settings.local.json",
                           "//home/jay/command-center/board/config.json"):
                self.assertIn(f"{tool}({target})", rules)

    def test_self_protection_bash(self):
        targets = ["/home/jay/cto/.claude/settings.json", "/home/jay/cto/CLAUDE.md",
                   "/home/jay/.claude/settings.json", "/home/jay/command-center/board/config.json"]
        for t in targets:
            self.check([f"rm {t}", f"mv {t} /tmp", f"cp /tmp/x {t}", f"echo x > {t}", f"echo x >> {t}",
                        f"tee {t}", f"sed -i s/a/b/ {t}", f"truncate -s0 {t}", f"chmod 777 {t}"])
        self.check(["rm -r /home/jay/cto/.claude", "mv /home/jay/cto/.claude /tmp"])

    def test_relative_operands_from_the_cto_start_folder(self):
        self.check(["cp x CLAUDE.md", "mv a .claude/settings.json", "rm ./CLAUDE.md", "tee ./CLAUDE.md",
                    "echo x > CLAUDE.md", "echo x >> .claude/settings.json", "sed -i s/a/b/ CLAUDE.md",
                    "cp x ./.claude/settings.json", "truncate -s0 .claude/settings.json"])

    def test_home_backup_spellings(self):
        for tree in ("~/backups", "$HOME/backups"):
            for operand in (tree, tree + "/", tree + "/odoo/x"):
                self.check([f"rm {operand}", f"mv {operand} /tmp", f"cp /tmp/x {operand}",
                            f"echo x > {operand}", f"tee {operand}", f"sed -i s/a/b/ {operand}",
                            f"find {operand} -delete"])

    def test_harmless_commands_still_allowed(self):
        for cmd in [
            "docker ps", "docker ps -a", "docker images", "docker system df", "docker inspect x",
            "docker builder prune -f", f"docker rmi {ID}", f"docker rm {ID}", f"sudo docker rm {ID}",
            "docker compose up -d", "docker compose down", "docker-compose down", "docker logs x",
            "scripts/cc-cleanup --run", "scripts/cc-cleanup", f"ls {SB}", f"ls -la {HB}/",
            f"du -sh {SB}", "df -h", "rm /home/jay/.npm/_logs/old.log",
            "find /home/jay/.npm/_logs -mtime +30 -print", "cat /home/jay/cto/CLAUDE.md",
        ]:
            with self.subTest(cmd=cmd):
                self.assertFalse(_denied(cmd))


class CtoRulesFile(unittest.TestCase):
    def test_exists_and_names_d058(self):
        self.assertIn("D-058", (ROOT / "scripts" / "cto" / "CLAUDE.md").read_text())

    def test_handoff_text_in_both_docs(self):
        for p in (ROOT / "scripts" / "cto" / "CLAUDE.md", ROOT / "docs" / "decisions" / "D-058.md"):
            t = " ".join(p.read_text().split()).lower()
            for phrase in ["jay does it himself", "cc-cleanup --done --yes-from jay --ref", "cc-101"]:
                with self.subTest(file=p.name, phrase=phrase):
                    self.assertIn(phrase, t)

    def test_runbook_steps(self):
        t = (ROOT / "docs" / "runbooks" / "cto-deny-rules.md").read_text()
        self.assertIn("scripts/cto/CLAUDE.md", t)
        self.assertEqual(t.count("restart ccd"), 2)  # install and rollback (chat_cto_root is read at start)
        self.assertIn("settings.json", t)
        self.assertIn("Edit", t)  # the settings-Edit denial drill

    def test_my_actions_points_to_runbook(self):
        t = (ROOT / "docs" / "jay" / "MY_ACTIONS.md").read_text()
        line = next(x for x in t.splitlines() if "CC-089" in x)
        self.assertTrue(line.startswith("- [ ] CC-089 · Install CTO deny rules in /home/jay/cto · "))
        self.assertTrue(line.endswith("docs/runbooks/cto-deny-rules.md"))


class DecisionD058(unittest.TestCase):
    def test_names_tiers_and_rules(self):
        t = (ROOT / "docs" / "decisions" / "D-058.md").read_text().lower()
        for phrase in ["tier 1", "tier 2", "tier 3", "6 months", "scripts/cto/settings.json", "cc-101",
                       "changes need jay", "/home/jay/cto", "/home/jay/backups", "/srv/server/backups",
                       "container prune", "image prune", "sudo", "board config", "user settings"]:
            self.assertIn(phrase, t)


if __name__ == "__main__":
    unittest.main()
