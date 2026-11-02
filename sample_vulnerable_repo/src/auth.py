import hashlib

from Crypto.PublicKey import RSA


def make_keys():
    return RSA.generate(2048)


def hash_password(pw: str) -> str:
    return hashlib.md5(pw.encode()).hexdigest()
