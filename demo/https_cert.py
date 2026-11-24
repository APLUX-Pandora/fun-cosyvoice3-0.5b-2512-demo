"""A self-signed certificate for the HTTPS pages of the demo (browsers allow the microphone on HTTPS pages only)."""
import os
import subprocess

CERTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")


def self_signed(d=CERTS):
    """(cert, key) of a self-signed certificate in d, made with openssl on first use; a certificate of your own put
    there as cert.pem + key.pem is used as it is"""
    cert, key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        os.makedirs(d, exist_ok=True)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-subj",
                        "/CN=cosyvoice3", "-keyout", key, "-out", cert], check=True, capture_output=True)
    return cert, key
