# Security Policy

## Reporting a vulnerability

Do not open a public issue with exploit details, and do not post a
proof of concept that could be used against live installations.

Report a suspected vulnerability privately through GitHub Security
Advisories on mirzasayzz/prpilot. If advisories are not available
to you, open a GitHub issue marked security with only a short
description and a request for a private channel, and do not include
exploit details in that issue.

A private contact address is a follow-up for the maintainer to add
here. No contact address is listed in this file, because inventing
one would send reports to the wrong place.

## What to include

* A short description of the issue and what an attacker could do.
* The affected area, for example webhook signature handling,
  token handling, encryption of stored keys, or configuration
  handling.
* Steps to reproduce, if you can describe them without exploit code.
* Whether you believe the issue is already being exploited, if you
  know.

## What happens next

The maintainer will triage the report. This file makes no promise
about a response time, a fix time, or a supported version window,
because no such commitment has been agreed. Security fixes are
released through the normal pull request process, and the fix
should not be disclosed publicly until a fixed version is
available, unless the maintainer says otherwise.

## Scope notes for contributors

* Never commit a real secret, token, private key, or API key to
  this repository. Use .env.example placeholders only.
* Never log a secret value. Use api/logging_util.py, which
  redacts key-like values.
* Never send a secret, token, or private key to an LLM. Only the
  code under review goes in a prompt, inside a delimited block.
* Per-repository opt-out of LLM review is a documented
  follow-up, not a current feature. Do not describe it as
  implemented.
* This project makes no billing claim and no compliance claim in
  this file. Do not add one without maintainer approval and
  evidence.
