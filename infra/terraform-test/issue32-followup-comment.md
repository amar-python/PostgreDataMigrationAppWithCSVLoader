## Follow-up: checked the remaining local-workaround options — none pan out

Investigated the four items raised as possible remaining paths. Summary: no new local fix. Cloud Shell remains the answer.

### 1. WSL2

`wsl --status` shows the WSL platform itself is already enabled on this machine (`Default Version: 2`), but `wsl -l -v` reports **zero installed distributions** — there's no Linux userland to actually test Norton's interception against. Testing this option requires `wsl --install <Distro>` first, which is a real system change (installs a distro + downloads an image), so I didn't do it unilaterally.

This is the one item worth revisiting: if you're willing to install a distro (e.g. Ubuntu), it's genuinely worth then testing `az`/`terraform` from inside it — WSL2's NAT'd virtual network adapter may or may not sit behind Norton's interception layer, and that's not knowable without a distro present to test from. Flagging as your call, not doing it myself.

### 2. Docker Desktop

Not installed — no `docker` command, no Docker service, no install directory under `Program Files`. Same reasoning as WSL2: untestable without installing it first, and I'm not installing it without checking with you.

### 3. Newer az CLI version

Installed here: `2.87.0`. Latest available: `2.89.1`. But this is not a promising path:

- OS/system trust store support for `az` CLI is an **open, backlog-status feature request** ([Azure/azure-cli#19305](https://github.com/Azure/azure-cli/issues/19305), [#28050](https://github.com/Azure/azure-cli/issues/28050)) — no PR, no milestone, not shipped in any released version.
- If anything, the trend is the opposite direction: [Azure/azure-cli#32083](https://github.com/Azure/azure-cli/issues/32083), filed against 2.77.0, shows recent `az` releases tightening X.509 validation strictness (a different but analogous "CERTIFICATE_VERIFY_FAILED... Missing Authority Key Identifier" error), not relaxing it. The only workaround mentioned there is `AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1` — a verification bypass, which is off the table here for the same reason `--insecure` is.

Upgrading `az` CLI is not expected to resolve this and isn't worth doing on that basis.

### 4. Norton fix for the "Basic Constraints not critical" defect

No documented fix, KB article, or acknowledgment found in Norton's support site or community forums for this specific defect in their SSL/TLS scanning root CA generation. Separately confirmed (read-only registry check, no settings touched) that this machine's Norton 360 is already on a current, recently auto-updated build (`26.7.11086.2615`), alongside Norton Utilities Ultimate `26.6.18812.9304` and Norton AntiTrack `4.8.7182.14364` — so this isn't a stale-software gap; the defect is present in Norton's current release with no public sign they've fixed their own cert generation.

### Conclusion

No new viable local fix. Confirming explicitly: **Norton's settings were not touched**, and **no TLS/certificate verification was weakened or bypassed** during this investigation — only read-only checks (`wsl --status`, `wsl -l -v`, Docker presence checks, registry reads, `az version`, public issue/doc research). Cloud Shell remains the recommended path for #31 until/unless a distro gets installed under WSL2 to test option 1, which is the only item left with any unexplored upside.
