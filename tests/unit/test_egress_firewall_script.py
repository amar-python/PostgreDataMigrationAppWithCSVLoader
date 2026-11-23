"""#310 (OIT-029, BR-37): scripts/egress_firewall.sh, which blocks one user's network at the firewall.

The in-process guard (tests/egress_guard.py) only patches Python's sockets, so a child process (``psql``, a shell loader)
or libpq could still leave the machine. The script closes that in the CI job that runs the egress-blocked tests: it
refuses every outbound packet from one throwaway user except to this machine (loopback, and the Docker bridge, which only
reaches containers), counts what it refused, and the job fails if the count is not zero. The script is run as root
(``sudo``); here a stateful fake ``iptables`` stands in, so the logic is checked without a firewall. Asserted:

  * ``install USER`` adds a chain that returns traffic on the loopback and Docker interfaces and rejects the rest, and one
    jump to it for that user's traffic only; run twice it still leaves one rule; it refuses root, a user that does not exist, and the user that
    invoked ``sudo`` (on a CI runner that is the agent reporting the job's progress, which must keep its network);
  * ``count`` prints the refused packets, ``check`` fails (exit 1, saying so) when there are any and passes when there are
    none, ``reset`` zeroes the count, and ``check`` says so (exit 3) when the block is not installed at all, so a job that
    forgot to install it cannot pass;
  * ``remove`` takes the jump and the chain away, leaves every other rule alone, and is safe to run twice;
  * ``run USER -- COMMAND`` runs the command as that user with the caller's environment.

`tooling`: these run bash, and the Windows job's `bash` is WSL's, with no distribution installed.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "egress_firewall.sh"
USER = "nobody"      # exists on every Linux and macOS; never root, and not the user running the tests (not under sudo)

FAKE_IPTABLES = '''#!{python}
"""A stateful stand-in for iptables: just the commands egress_firewall.sh uses."""
import json, sys
state_path = "{state}"
state = json.load(open(state_path))
args = sys.argv[1:]
open("{calls}", "a").write(" ".join(args) + "\\n")

def save():
    json.dump(state, open(state_path, "w"))

def fail(message):
    print("iptables: " + message, file=sys.stderr)
    sys.exit(1)

cmd, rest = args[0], args[1:]
if cmd == "-N":
    if rest[0] in state["chains"]:
        fail("Chain already exists.")
    state["chains"][rest[0]] = {{"rules": [], "pkts": 0}}
elif cmd == "-F":
    if rest[0] not in state["chains"]:
        fail("No chain/target/match by that name.")
    state["chains"][rest[0]]["rules"] = []
elif cmd == "-X":
    if rest[0] not in state["chains"]:
        fail("No chain/target/match by that name.")
    del state["chains"][rest[0]]
elif cmd in ("-A", "-I") and sum(1 for a in rest if a == "-o") > 1:
    fail("multiple -o flags not allowed")   # real iptables refuses this (found by running the script for real)
elif cmd == "-A":
    if rest[0] == "OUTPUT":
        state["output"].append(rest[1:])
    else:
        state["chains"][rest[0]]["rules"].append(rest[1:])
elif cmd == "-I":
    assert rest[0] == "OUTPUT" and rest[1] == "1", rest
    state["output"].insert(0, rest[2:])
elif cmd == "-D":
    assert rest[0] == "OUTPUT", rest
    if rest[1:] not in state["output"]:
        fail("Bad rule (does a matching rule exist in that chain?).")
    state["output"].remove(rest[1:])
elif cmd == "-S":
    print("-P OUTPUT ACCEPT")
    for rule in state["output"]:
        print("-A OUTPUT " + " ".join(rule))
elif cmd == "-L":
    name = rest[0]
    if name not in state["chains"]:
        fail("No chain/target/match by that name.")
    chain = state["chains"][name]
    print("Chain %s (1 references)" % name)
    print("    pkts      bytes target     prot opt in     out     source               destination")
    for rule in chain["rules"]:
        if rule == ["-j", "REJECT"]:
            print("%8d %10d REJECT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            "
                  "reject-with icmp-port-unreachable" % (chain["pkts"], chain["pkts"] * 60))
elif cmd == "-Z":
    state["chains"][rest[0]]["pkts"] = 0
else:
    fail("unsupported in the fake: " + cmd)
save()
'''

FAKE_SETPRIV = '''#!/bin/sh
# Records how it was called, then runs the command after the options (the real one would switch user first).
echo "$@" >> "{calls}"
while [ $# -gt 0 ]; do
  case "$1" in --*) shift ;; *) break ;; esac
done
exec "$@"
'''


@pytest.fixture
def fakes(tmp_path):
    """A PATH directory with the fake iptables and setpriv, and helpers to read and change the fake firewall."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"chains": {}, "output": []}))
    calls = tmp_path / "iptables.calls"
    setpriv_calls = tmp_path / "setpriv.calls"
    ipt = bin_dir / "iptables"
    ipt.write_text(FAKE_IPTABLES.format(python=sys.executable, state=state, calls=calls))
    sp = bin_dir / "setpriv"
    sp.write_text(FAKE_SETPRIV.format(calls=setpriv_calls))
    for tool in (ipt, sp):
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    class Fakes:
        path = str(bin_dir)

        def state(self) -> dict:
            return json.loads(state.read_text())

        def set_packets(self, n: int) -> None:
            data = self.state()
            data["chains"]["TE_EGRESS"]["pkts"] = n
            state.write_text(json.dumps(data))

        def add_other_rule(self, *rule: str) -> None:
            data = self.state()
            data["output"].append(list(rule))
            state.write_text(json.dumps(data))

        def iptables_calls(self) -> list[str]:
            return calls.read_text().splitlines() if calls.exists() else []

        def setpriv_calls(self) -> list[str]:
            return setpriv_calls.read_text().splitlines() if setpriv_calls.exists() else []

    return Fakes()


def run(fakes, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {"PATH": fakes.path + os.pathsep + "/usr/bin:/bin", "HOME": str(Path.home()), **(env or {})}
    return subprocess.run([shutil.which("bash"), str(SCRIPT), *args], cwd=ROOT, env=full_env,
                          capture_output=True, text=True, timeout=60)


def uid_of(user: str) -> str:
    return subprocess.run(["id", "-u", user], capture_output=True, text=True, check=True).stdout.strip()


# Loopback (the local database) and the Docker bridges (containers only) return to the normal rules; the rest is refused.
CHAIN_RULES = [["-o", "lo", "-j", "RETURN"], ["-o", "docker0", "-j", "RETURN"], ["-o", "br+", "-j", "RETURN"],
               ["-j", "REJECT"]]


def jumps(fakes) -> list[list[str]]:
    return [rule for rule in fakes.state()["output"] if rule[-2:] == ["-j", "TE_EGRESS"]]


# -- install ---------------------------------------------------------------------------------------------------------

def test_install_rejects_the_users_traffic_except_to_this_machine(fakes):
    done = run(fakes, "install", USER)
    assert done.returncode == 0, done.stderr
    assert fakes.state()["chains"]["TE_EGRESS"]["rules"] == CHAIN_RULES
    (rule,) = jumps(fakes)
    assert rule == ["-m", "owner", "--uid-owner", uid_of(USER), "-j", "TE_EGRESS"], rule


def test_install_twice_still_leaves_one_rule(fakes):
    assert run(fakes, "install", USER).returncode == 0
    assert run(fakes, "install", USER).returncode == 0
    assert len(jumps(fakes)) == 1
    assert fakes.state()["chains"]["TE_EGRESS"]["rules"] == CHAIN_RULES


def test_install_refuses_root_and_changes_nothing(fakes):
    done = run(fakes, "install", "root")
    assert done.returncode == 2 and "root" in done.stderr.lower(), done.stderr
    assert fakes.iptables_calls() == []


def test_install_refuses_a_user_that_does_not_exist(fakes):
    done = run(fakes, "install", "no_such_user_for_egress_tests")
    assert done.returncode == 2, done.stderr
    assert fakes.iptables_calls() == []


def test_install_refuses_the_user_who_ran_sudo(fakes):
    """On a CI runner that user is the agent reporting the job; cutting its network fails the job."""
    done = run(fakes, "install", USER, env={"SUDO_UID": uid_of(USER)})
    assert done.returncode == 2 and "sudo" in done.stderr.lower(), done.stderr
    assert fakes.iptables_calls() == []


def test_install_needs_a_user_argument(fakes):
    assert run(fakes, "install").returncode == 64


# -- count, check, reset -----------------------------------------------------------------------------------------------

def test_count_prints_the_refused_packets(fakes):
    run(fakes, "install", USER)
    fakes.set_packets(7)
    done = run(fakes, "count")
    assert done.returncode == 0 and done.stdout.strip() == "7", (done.stdout, done.stderr)


def test_check_passes_when_nothing_was_refused(fakes):
    run(fakes, "install", USER)
    assert run(fakes, "check").returncode == 0


def test_check_fails_when_something_tried_to_leave(fakes):
    run(fakes, "install", USER)
    fakes.set_packets(3)
    done = run(fakes, "check")
    assert done.returncode == 1, done.stdout
    assert "EGRESS ATTEMPTED" in done.stderr and "3" in done.stderr, done.stderr


def test_reset_zeroes_the_count(fakes):
    run(fakes, "install", USER)
    fakes.set_packets(5)
    assert run(fakes, "reset").returncode == 0
    assert run(fakes, "count").stdout.strip() == "0"
    assert run(fakes, "check").returncode == 0


def test_check_cannot_pass_when_the_block_was_never_installed(fakes):
    done = run(fakes, "check")
    assert done.returncode == 3 and "not installed" in done.stderr, done.stderr


# -- remove ----------------------------------------------------------------------------------------------------------

def test_remove_takes_the_rule_and_the_chain_away_and_leaves_other_rules(fakes):
    fakes.add_other_rule("-m", "owner", "--uid-owner", "999", "-j", "ACCEPT")
    run(fakes, "install", USER)
    done = run(fakes, "remove")
    assert done.returncode == 0, done.stderr
    state = fakes.state()
    assert "TE_EGRESS" not in state["chains"]
    assert state["output"] == [["-m", "owner", "--uid-owner", "999", "-j", "ACCEPT"]]


def test_remove_is_safe_when_nothing_is_installed(fakes):
    assert run(fakes, "remove").returncode == 0
    assert run(fakes, "remove").returncode == 0


# -- run -------------------------------------------------------------------------------------------------------------

def test_run_executes_the_command_as_that_user_with_the_callers_environment(fakes):
    done = run(fakes, "run", USER, "--", "printenv", "EGRESS_TEST_MARKER", env={"EGRESS_TEST_MARKER": "kept"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "kept"
    (call,) = fakes.setpriv_calls()
    assert f"--reuid={uid_of(USER)}" in call, call


def test_run_returns_the_commands_exit_status(fakes):
    assert run(fakes, "run", USER, "--", "sh", "-c", "exit 5").returncode == 5


def test_run_refuses_root(fakes):
    done = run(fakes, "run", "root", "--", "true")
    assert done.returncode == 2 and fakes.setpriv_calls() == []


def test_an_unknown_command_is_a_usage_error(fakes):
    assert run(fakes, "frobnicate").returncode == 64
    assert run(fakes).returncode == 64
