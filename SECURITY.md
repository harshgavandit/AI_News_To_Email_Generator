# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for a suspected vulnerability.

Include the affected page or API route, steps to reproduce, and the impact you observed. You will get an acknowledgement within three working days. Fixes are released through the normal protected release flow (`docs/RELEASE-FLOW.md`), and reporters are credited unless they ask otherwise.

## Supported versions

Only the current production deployment at [getinformdaily.com](https://getinformdaily.com) is supported.

## How the code is protected

- `main` accepts changes only through pull requests from `Staging` that pass **Release CI**, **CodeQL** and the Vercel preview.
- Release CI scans for secrets (Gitleaks), known-vulnerable dependencies (npm audit, pip-audit) and high-severity Python issues (Bandit). CodeQL analyses Python, JavaScript and the workflows themselves.
- GitHub secret scanning with push protection, Dependabot alerts and weekly grouped Dependabot updates are enabled.
- Workflows run with read-only tokens by default and pin every third-party action to a full commit SHA.
