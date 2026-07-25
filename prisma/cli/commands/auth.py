#!/usr/bin/env python3
"""
Auth CLI Commands

Generates the bcrypt password hash used by ADR-011's password-mode auth
(server.auth.mode: password in config.yaml) — the server never sees or
stores the plaintext password itself.
"""

import getpass

import bcrypt
import click


@click.group(name='auth')
def auth_group():
    """Server authentication management (ADR-011)."""
    pass


@auth_group.command('hash-password')
def hash_password():
    """Prompt for a password and print its bcrypt hash.

    Paste the output into ~/.config/prisma/config.yaml under
    server.auth.password_hash, and set server.auth.mode: password.
    """
    pw = getpass.getpass("Password: ")
    if not pw:
        raise click.ClickException("password cannot be empty")
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        raise click.ClickException("passwords did not match")
    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    click.echo(hashed)
