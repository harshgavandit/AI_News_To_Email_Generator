"""Sync only application settings from saved .env to the linked Vercel project.

Values travel through stdin, never command arguments or output. Run locally only.
"""
import shutil
import subprocess
import sys

from dotenv import dotenv_values

KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "MY_EMAIL", "APP_PASSWORD", "ADMIN_TOKEN")


def main():
    values = dotenv_values(".env")
    executable = shutil.which("npx.cmd") or shutil.which("npx")
    if not executable:
        raise SystemExit("Install Node.js to use the Vercel CLI.")
    for key in KEYS:
        value = values.get(key)
        if not value:
            print(f"{key}: missing; skipped")
            continue
        if key == "APP_PASSWORD":
            value = value.replace(" ", "")
        process = subprocess.run(
            [executable, "--yes", "vercel@latest", "env", "add", key,
             "--environment", "production", "--force", "--yes", "--sensitive"],
            input=value, capture_output=True, text=True, timeout=90,
        )
        print(f"{key}: {'synced' if process.returncode == 0 else 'FAILED (CLI output suppressed to protect credentials)'}")
        if process.returncode:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
