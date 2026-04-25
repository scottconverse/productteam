# Security Policy

## Supported Versions

Security updates are provided for the latest minor release line of `productteam` published on PyPI. Older versions are not patched — please upgrade to the latest release.

| Version       | Supported          |
| ------------- | ------------------ |
| latest minor  | :white_check_mark: |
| older         | :x:                |

## Reporting a Vulnerability

If you believe you have found a security vulnerability in `productteam`, please report it privately rather than opening a public issue.

**Preferred channel:** [GitHub Security Advisories](https://github.com/scottconverse/productteam/security/advisories/new) — this opens a private report visible only to maintainers.

**Alternative:** open a minimal public issue stating "security report — please contact me privately" without disclosing details, and a maintainer will follow up to arrange a private channel.

When reporting, please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a minimal proof-of-concept.
- The affected version(s) of `productteam`.
- Any known mitigations or workarounds.

## Response Expectations

- **Acknowledgement:** within 7 days of report.
- **Initial assessment:** within 14 days.
- **Fix or mitigation:** target within 30 days for confirmed high-severity issues, depending on complexity.

We will coordinate disclosure timing with the reporter and credit the reporter in the release notes unless anonymity is requested.

## Scope

In scope:

- The `productteam` Python package as published to PyPI.
- Source code in this repository, including CI workflows and release tooling.

Out of scope:

- Vulnerabilities in third-party dependencies (please report those upstream).
- Issues that require a malicious local environment, compromised developer machine, or already-elevated privileges.
- Social engineering, physical attacks, or attacks against project infrastructure not controlled by this repository.

## Secrets and Credentials

This project does not ship secrets in source. If you discover a leaked token, key, or credential in the repository or release artifacts, please report it via the channel above so it can be rotated immediately.
