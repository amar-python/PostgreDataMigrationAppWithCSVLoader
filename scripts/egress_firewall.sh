#!/usr/bin/env bash
# egress_firewall.sh - refuse one user's outbound network except to this machine (#310, OIT-029, BR-37)
#
# The in-process guard (tests/egress_guard.py) patches Python's sockets only, so a child process (psql, a shell loader)
# or libpq could still leave the machine. This blocks at the firewall instead, for ONE throwaway user, and counts every
# packet it refuses, so a run that tried to leave fails even if the program swallowed the error.
#
# Run as root (sudo) on Linux, with iptables:
#   egress_firewall.sh install USER        refuse USER's traffic except loopback and the Docker bridge (reaches containers only)
#   egress_firewall.sh run USER -- CMD...  run CMD as USER with the caller's environment (needs root, e.g. via sudo -E)
#   egress_firewall.sh count               print how many packets were refused
#   egress_firewall.sh reset               zero that count
#   egress_firewall.sh check               exit 1 if the count is not zero; exit 3 if the block is not installed
#   egress_firewall.sh remove              take the block away (safe to run when it is not installed)
#
# Why a separate user: on a hosted CI runner the job's steps and the agent that streams their log share one user. Blocking
# that user would cut the agent off (docs/SOVEREIGNTY.md). So the tests run as another user, and this refuses to block
# root or the user that invoked sudo.

set -u

IPT="${IPTABLES:-iptables}"
CHAIN="TE_EGRESS"
# Output interfaces that stay reachable: loopback (the local database, the DNS stub) and the Docker bridges, which only
# reach containers. iptables allows one -o per rule, so each is a RETURN rule inside the chain, ahead of the REJECT.
EXEMPT_INTERFACES=(lo docker0 'br+')

usage() {
    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 64
}

# Sets USER_ID and GROUP_ID for the named user, or exits 2.
resolve_user() {
    local name="${1:-}"
    [ -n "$name" ] || usage
    if ! USER_ID="$(id -u "$name" 2>/dev/null)"; then
        echo "egress_firewall: no such user '$name'" >&2
        exit 2
    fi
    GROUP_ID="$(id -g "$name")"
    if [ "$USER_ID" = "0" ]; then
        echo "egress_firewall: refusing to block root: the machine's own services run as root" >&2
        exit 2
    fi
    if [ -n "${SUDO_UID:-}" ] && [ "$USER_ID" = "$SUDO_UID" ]; then
        echo "egress_firewall: refusing to block '$name': that is the user running sudo. On a CI runner it is the agent that" \
             "reports the job's progress; run the tests as another user" >&2
        exit 2
    fi
}

chain_exists() { "$IPT" -L "$CHAIN" -n >/dev/null 2>&1; }

not_installed() {
    echo "egress_firewall: the block is not installed (no $CHAIN chain); run 'install USER' first" >&2
}

# Delete every jump from OUTPUT to our chain, whichever user it was made for.
drop_jumps() {
    local rule parts
    "$IPT" -S OUTPUT 2>/dev/null | grep -e " -j $CHAIN\$" | sed 's/^-A /-D /' | while IFS= read -r rule; do
        read -ra parts <<< "$rule"
        "$IPT" "${parts[@]}"
    done
    return 0
}

cmd_install() {
    resolve_user "${1:-}"
    "$IPT" -N "$CHAIN" 2>/dev/null || "$IPT" -F "$CHAIN" || exit 1
    local iface
    for iface in "${EXEMPT_INTERFACES[@]}"; do
        "$IPT" -A "$CHAIN" -o "$iface" -j RETURN || exit 1
    done
    "$IPT" -A "$CHAIN" -j REJECT || exit 1
    drop_jumps
    "$IPT" -I OUTPUT 1 -m owner --uid-owner "$USER_ID" -j "$CHAIN" || exit 1
    echo "egress blocked for '$1' (uid $USER_ID): everything except loopback and the Docker bridge is refused and counted"
}

cmd_count() {
    chain_exists || { not_installed; return 3; }
    "$IPT" -L "$CHAIN" -n -v -x | awk '$3 == "REJECT" { n += $1 } END { print n + 0 }'
}

cmd_reset() {
    chain_exists || { not_installed; exit 3; }
    "$IPT" -Z "$CHAIN"
}

cmd_check() {
    local n
    n="$(cmd_count)" || exit 3
    if [ "$n" -gt 0 ]; then
        echo "EGRESS ATTEMPTED: $n packet(s) from the blocked user to somewhere other than this machine were refused." >&2
        echo "A test, or a program it started, tried to reach the network. Find it: the application must make no outbound" \
             "call (BR-37, docs/SOVEREIGNTY.md)." >&2
        exit 1
    fi
    echo "no outbound attempt: 0 packets refused"
}

cmd_remove() {
    drop_jumps
    "$IPT" -F "$CHAIN" 2>/dev/null
    "$IPT" -X "$CHAIN" 2>/dev/null
    echo "egress block removed"
    return 0
}

cmd_run() {
    [ $# -ge 1 ] || usage
    local name="$1"
    shift
    [ "${1:-}" = "--" ] && shift
    [ $# -ge 1 ] || usage
    resolve_user "$name"
    exec setpriv --reuid="$USER_ID" --regid="$GROUP_ID" --clear-groups env "HOME=${EGRESS_HOME:-/tmp}" "$@"
}

case "${1:-}" in
    install) shift; cmd_install "$@" ;;
    run)     shift; cmd_run "$@" ;;
    count)   cmd_count; exit $? ;;
    reset)   cmd_reset ;;
    check)   cmd_check ;;
    remove)  cmd_remove ;;
    *)       usage ;;
esac
