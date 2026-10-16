"""Generates (once, reused on restart) a self-signed AND already-expired certificate for the
chaos target's second, TLS-bad listener. Both failure modes at once: a real client gets neither
a trusted issuer nor a validity window, so the SSRF-guarded probe's TLS handshake fails exactly
the way SRS Section 15's tls-bad mode asks for.
"""

from __future__ import annotations

import datetime
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def ensure_tls_bad_cert(
    cert_path: str = "/tmp/tls-bad.crt", key_path: str = "/tmp/tls-bad.key"
) -> tuple[str, str]:
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "chaos")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)  # self-signed: issuer == subject, no real CA
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=30))
        .not_valid_after(now - datetime.timedelta(days=1))  # expired yesterday
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("chaos")]), critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path
