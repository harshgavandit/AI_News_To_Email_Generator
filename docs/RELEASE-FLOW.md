# Release flow

Every change to Informa AI follows the same release flow.

1. **Push to `Staging`.** Start from the latest `main`, commit your changes, and push to `Staging`.
2. **Open a pull request from `Staging` to `main`.** Describe the change, testing, and any database or rollback steps. Review the Vercel preview.
3. **Wait for the required checks.** GitHub requires `PR comes from Staging`, `Release CI`, and `Vercel`. The PR must include the latest `main` and all review conversations must be resolved. The same rules apply to administrators.
4. **Review and merge.** The owner reviews and merges the PR using a merge commit. The repository has one maintainer, so GitHub requires zero formal approvals. Automated helpers prepare the PR for the owner's review.
5. **Verify production.** Vercel builds from `main`. Check the deployment and the separate `Site health` workflow, which reads the live site and archive.

## Release CI

`Release CI` requires the frontend build and tests, backend regression tests on Python 3.12 and 3.14, dependency audits, AI quality fixtures, and the disposable PostgreSQL migration and mail-capacity checks. The release smoke test ingests a fixture story and reads it through the normal news, article, and RSS routes. CI uses test data and disposable services.

If a check fails, fix it on `Staging` and push again. GitHub runs the checks on the updated PR. After merging, bring `Staging` forward to `main` before the next release.

## Database changes and rollback

Use additive schema changes that can coexist with the previous version during rollout. Schedule and verify any required migration with the steps in [Launch operations](LAUNCH.md).

If a release regresses production, restore the previous known-good Vercel deployment, then submit the code revert through `Staging`. A deployment rollback changes the application version. Database recovery has its own backup and migration procedure.
