# Writing in this repo

This is the house style for every issue, PR, comment and doc in this repo, whoever writes it. The product owner decided on 27 Oct 2026 that it applies to all repo writing.

## Rules

1. **Evidence before status.** Write "closed", "passing" or "verified" only when you can name the evidence: a run, a commit or an attached file. Quote test results as passed / failed / skipped, for example "297 passed, 0 failed, 0 skipped". Docs such as `VCRM.md` are claims, not evidence.
2. **No issue closes without clean evidence.** Every issue ends with a **Done when** section that says what evidence will close it. A rehearsal is not the real run.
3. **State the gaps.** Say what wasn't run, wasn't attached or couldn't be checked, as plainly as the results. If a cause is unknown, say so and list what to check.
4. **The product owner decides scope.** Present options with a recommendation, for example "Defaults I chose (please confirm)" with a Why column. Credit decisions once taken: "Approved by the product owner on 26 Oct." Don't reopen items marked "risk accepted" or "deferred by decision".
5. **Runnable commands.** PowerShell for the dev machine, and every block starts with `cd "<quoted path>"`. Linux-side steps, such as the offline VM, are labelled bash. Put Python in a `.py` file, never in a pasted multi-line block.
6. **Traceable references.** Use issue and PR numbers, short commit hashes, file paths in backticks, and absolute dates ("27 Oct 2026"). Don't use "recently" or "the earlier fix".
7. **Never write secrets.** Passwords, API keys, tokens and `PGPASSWORD` values never go into issues, PRs, docs or evidence files.

## Conventions

- **Audience:** in issues, PRs and repo docs, refer to the decision-maker as "the product owner".
- **Spelling:** Australian in prose ("authorisation", "behaviour"). Code identifiers, routes and library names keep their own spelling.
- **Footers:** no "Generated with …" footer on issues or PRs.
- **Style:**
  - Short sentences, with numbers instead of adjectives.
  - Bold lead-ins for bullets the reader will scan.
  - Avoid "robust", "seamless", "production-ready" and "should work".
  - Don't use "fully offline" until #60 has its evidence.

## Templates

**Issue**

```markdown
Found on <date> while <context>. Relates to <BR / ADR / issue>.

## What happened
<exact error in a code block; reproduction with cd first>

## Proposed
<fix; mark "to be confirmed" where scope is the product owner's call>

## Done when
<the evidence that will close it>
```

**PR**

```markdown
Fixes #N. Part of <milestone> (<BR>). <decision it implements, credited and dated>

## What changes
<bold-lead bullets or a table>

## Checks
<passed / failed / skipped counts, the commit, and whether the new tests fail with the fix reverted>
```
