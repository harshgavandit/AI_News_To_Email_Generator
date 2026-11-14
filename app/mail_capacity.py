"""Daily budgets shared by verification, instant briefs, and scheduled delivery."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MailCapacity:
    outbound: int = 60
    digests: int = 45
    verification: int = 20

    def policies(self, day: str, kind: str) -> list[tuple[str, str, int]]:
        return [("outbound", day, self.outbound), (kind, day, getattr(self, kind))]


def batch_sender() -> str | None:
    # An explicit sender and key are required before increasing the Gmail-era limits.
    if os.getenv("RESEND_API_KEY") and (sender := os.getenv("MAIL_FROM", "").strip()):
        return sender
    return None


def mail_capacity() -> MailCapacity:
    if not batch_sender():
        return MailCapacity()

    def limit(name: str, default: int) -> int:
        try:
            return min(100_000, max(1, int(os.getenv(name, str(default)))))
        except ValueError:
            return default

    outbound = limit("MAIL_OUTBOUND_DAILY_LIMIT", 60)
    return MailCapacity(outbound, min(outbound, limit("MAIL_DIGEST_DAILY_LIMIT", 45)),
                        min(outbound, limit("MAIL_VERIFICATION_DAILY_LIMIT", 20)))
