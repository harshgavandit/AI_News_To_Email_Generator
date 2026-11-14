"""Sync only application settings from saved .env to the linked Vercel project.

Values travel through stdin, never command arguments or output. Run locally only.
"""
import shutil
import subprocess
import sys

from dotenv import dotenv_values

KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL", "MY_EMAIL", "APP_PASSWORD", "ADMIN_TOKEN",
        "RESEND_API_KEY", "SMTP_URL", "MAIL_FROM", "NEWS_DATABASE_URL", "PUBLIC_ORIGIN",
        "MAIL_SESSION_SECRET", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "CRON_SECRET",
        "FEED_REFRESH_SECRET", "PUBLIC_EMAIL_ENABLED", "MAIL_PILOT_MODE", "POSTMARK_SERVER_TOKEN",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
        "RESEND_WEBHOOK_SECRET", "MAIL_OUTBOUND_DAILY_LIMIT", "MAIL_DIGEST_DAILY_LIMIT", "MAIL_VERIFICATION_DAILY_LIMIT")


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
