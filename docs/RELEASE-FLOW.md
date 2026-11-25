# Release flow

## Branches and promotion

- `main` is the protected production branch. GitHub requires a pull request from this repository's capitalized `Staging` branch. It also requires up-to-date checks and resolved conversations, applies the rules to administrators, and blocks branch deletion and force pushes.
- `Staging` is the shared release candidate. Push normal changes there. GitHub blocks force pushes and branch deletion. Use a short-lived local branch for larger work and bring it into `Staging` once it is ready to share. Keep one production PR open at a time because it tracks every push to `Staging`.
- Start with `git switch Staging` and `git fetch origin`. Run `git merge --ff-only origin/Staging` to catch up with colleagues, then `git merge --ff-only origin/main` to pick up the latest release. If history has diverged, inspect it and reconcile it with a normal merge. After a production merge, fast-forward `Staging` again before the next release.
- Open a `Staging` → `main` PR using the template. Use a title such as `fix(reader): restore saved stories` and use meaningful commit messages following the same convention. An optional scope and breaking-change marker (`!`) are allowed. Link the preview, list verification, and record migration and rollback implications.
- The owner reviews the diff and Vercel preview, resolves review threads, and merges using a merge commit. This repository has one maintainer and zero required formal approvals. Add a second maintainer and require one non-author approval in GitHub before relying on independent review.

## Required checks and thresholds

| Required GitHub check | Limits and pass criteria |
| --- | --- |
| PR comes from Staging | Exact source branch and repository. Conventional Commit PR title. |
| Release CI · Python | All tests and reader intelligence fixtures pass. Ruff lint, compilation, and whitespace checks pass. Strict typing and Ruff formatting apply to the release tooling. Application type checking is a ratchet: mypy may not report more errors in any file than `scripts/mypy-baseline.json` records (68 at introduction), and new Python files must be Ruff-formatted. Maximum cyclomatic complexity of 14 per release-tool function. At least 79% aggregate branch-inclusive coverage across `app` on Python 3.12. Python 3.14 must also pass the test suite. |
| Release CI · Frontend | Locked npm install, JavaScript lint, unit tests, and the production asset build pass. Chromium exercises the homepage, theme controls, feedback dialog, and Research Desk against a disposable application server. Any uncaught page error fails the smoke test. |
| Release CI · Security | Zero new Gitleaks findings, zero high or critical npm advisories, zero known advisories in the locked Python runtime export, and zero high-severity, high-confidence Bandit findings. GitHub also scans for secrets and uses push protection. |
| Release CI · PostgreSQL | Disposable PostgreSQL 17 archive and legacy upgrade tests pass. The 10,000-recipient rehearsal uses a fake mail transport. The schema comparison blocks changes that break old writers and checks changed SQL for destructive statements. |
| CodeQL | Security-extended CodeQL analysis of Python, JavaScript and the GitHub workflows on every PR to `main` or `Staging`, on each `main` push and weekly. The code scanning check fails for new alerts of high or critical security severity, or error-level standard alerts (repository code scanning settings). |
| Vercel | The PR preview builds successfully. Separately, the Vercel production alias waits for `Release CI` on the main merge commit. |

A **Detect changed areas** job compares the merge candidate with the target branch. When a PR changes only Markdown files, the Python, frontend and PostgreSQL gates are skipped and `Release CI` accepts that; the security scan always runs. Any other file, including `docs/research` JSON that the tests read, runs every gate.

GitHub requires the stable `Release CI` check from GitHub Actions. It fails if any of its four required jobs, including either Python matrix entry, fail, are skipped, or are cancelled. The required workflow starts on every PR to `main` or `Staging` and builds the PR's merge candidate. A new push cancels its previous run. npm and uv cache downloads using their lockfiles. The schema comparison uses changed paths to skip its snapshot work on unrelated changes. The other quality gates still run.

## Environment and deployment verification

| Environment | How to use it |
| --- | --- |
| Local and GitHub CI | Mock integrations, a fresh SQLite database, or disposable PostgreSQL. No live email, credentials, production writes, or publisher synchronization. |
| Vercel preview and staging | The Vercel preview from `Staging` is the staging environment. Other previews use the same Preview target. Preview data, if provisioned, must belong to an isolated database with test accounts. Production credentials belong only in Production. |
| Vercel production | The live site at [getinformdaily.com](https://getinformdaily.com) is promoted from `main`, after the required Vercel check on the main commit. |

After a successful main CI run, **Production release smoke** waits up to 10 minutes for the exact Git SHA on the canonical domain and reads the health API, homepage, Research Desk, archive API, and latest RSS. It records the SHA and outcome in the GitHub Actions run. Use Vercel's deployment page to correlate the SHA, alias, build logs, and runtime logs. GitHub Actions records failed jobs and provides failure notifications according to each maintainer's GitHub notification settings. **Site health** monitors archive/feed readiness separately.

Keep Vercel's automatic system environment variables enabled so the health endpoint can report `VERCEL_GIT_COMMIT_SHA`. Keep GitHub's required checks bound to the GitHub Actions and Vercel apps. Recheck those settings after renaming a workflow or disconnecting an integration.

## Supply chain and repository security

- Every action in every workflow is pinned to a full commit SHA (`tests/test_pipeline_policy.py` fails otherwise), and the repository requires SHA pinning. Workflow tokens are read-only unless a job asks for more.
- Dependabot alerts are on. `.github/dependabot.yml` opens grouped weekly updates for uv, npm and GitHub Actions against `Staging`, so each update passes Release CI and is promoted like any other change. Dependabot's automatic security-update PRs target `main` and would fail the Staging-first rule, so they stay off; alerts are handled through the weekly updates or a manual `Staging` change.
- GitHub secret scanning with push protection and private vulnerability reporting are on. `SECURITY.md` tells reporters where to go. `.github/CODEOWNERS` requests the maintainer's review on every PR.

## Failure notifications and audit trail

- A failed `Python checks` run on `main`, or a failed production smoke for the current `main` revision, opens a `release-incident` issue (or comments on the open one) with the revision and run link. Watchers get GitHub's issue notifications. Close the issue once production serves a verified revision again.
- Each PR keeps its Release CI summary table, CodeQL results and Vercel preview link. Each production smoke run records the verified SHA. Vercel keeps the deployment history used for rollback.

## Database changes

Use expand-and-contract. Add nullable columns or database defaults first, deploy code that can operate during the transition, and backfill independently. Verify legacy upgrades and backup/recovery before a future removal. The schema gate covers declared SQLAlchemy tables and common destructive SQL in affected paths. Review handcrafted data migrations, constraints, and backfills in the PR. See [Launch operations](LAUNCH.md) for production database procedures.

## Rollback

1. Compare the failed GitHub release smoke SHA with the current Vercel alias. Check Vercel logs and determine whether the regression belongs to that deployment.
2. Identify the last known-good deployment in Vercel and verify that it can use the current production database and that its stored environment variables and cron settings are valid. Use **Instant Rollback** or `vercel rollback <deployment-url>` with the project linked. Preserve the failing and restored deployment IDs in the incident record.
3. Run `python -m scripts.check_production_release <restored-commit-sha> --wait-seconds 0` from the repository. For a deployment that predates the revision header, verify the alias and Git SHA in Vercel and check the public routes manually. Recover data separately from the verified backup if writes themselves caused damage.
4. Bring the latest `main` into `Staging` and create a revert PR. After the revert passes the required gates, promote the validated deployment and verify automatic alias assignment is enabled again.

## Settings to recheck by hand

These live in GitHub or Vercel rather than in the repository. They were set on 25 November 2026:

| Where | Setting |
| --- | --- |
| Branches → `main` | Require a PR, required checks `PR comes from Staging`, `Release CI`, `CodeQL` and `Vercel`, branches up to date, conversation resolution, no bypass for admins, no force pushes or deletion. |
| Rulesets → Protect Staging history | Block force pushes and deletion of `Staging`. |
| General → Pull requests | Merge commits only, titled from the PR; always suggest updating PR branches; do not delete head branches automatically (that would delete `Staging`). |
| Actions → General | Read-only default token, Actions may not approve PRs, require actions pinned to a full SHA. |
| Advanced Security | Dependency graph, Dependabot alerts, secret scanning with push protection, private vulnerability reporting; code scanning failure thresholds as above. |
| Vercel | Deployment Checks wait for `Release CI` before promoting `main`; automatic system environment variables stay enabled. |

A second maintainer is the remaining gap: with one maintainer, GitHub cannot require an approval from someone other than the author. Add one and require one approving review when possible.
