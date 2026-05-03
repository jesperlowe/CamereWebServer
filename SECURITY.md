# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| version2 (current) | ✅ |
| main (v1) | ❌ — upgrade to version2 |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues by e-mail to: **jl@fire-eater.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

You will receive a response within 5 business days. If the issue is confirmed,
a fix will be released as soon as possible and you will be credited unless you
prefer anonymity.

## Security Design Notes

- Session secrets are generated uniquely per installation on first startup
  and stored in `config.json` (chmod 600).
- Passwords are hashed with bcrypt (cost factor ≥ 12).
- Session cookies use `HttpOnly` and `SameSite=Strict`.
- The web interface runs on HTTP by default. For production use, place it
  behind a reverse proxy (nginx/Caddy) with TLS.
- `config.json` contains credentials — protect it with filesystem permissions
  and do not commit it to version control.

## Known Limitations

- No built-in rate limiting on the login endpoint. Use a reverse proxy with
  rate limiting for internet-facing deployments.
- RTSP stream credentials are stored in plaintext in `config.json`.
