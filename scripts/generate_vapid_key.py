"""Print a new VAPID key pair for device alerts (Web Push).

Run once, then add the private key to Vercel as NEWS_PUSH_VAPID_PRIVATE_KEY (Production):

    uv run python -m scripts.generate_vapid_key

The private key never leaves your machine unless you paste it somewhere. Do not commit it.
"""
from cryptography.hazmat.primitives.asymmetric import ec

from app.push_alerts import b64, public_key


def main():
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    print("NEWS_PUSH_VAPID_PRIVATE_KEY=" + b64(private))
    print("Public key (sent to browsers automatically; for reference only): " + public_key(key))


if __name__ == "__main__":
    main()
