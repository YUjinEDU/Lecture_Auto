# Security Policy

Please **do not open a public issue** for vulnerabilities. Report them privately through
GitHub's *Security -> Report a vulnerability* (private advisory) on this repository.
We aim to acknowledge reports within 7 days.

## Deployment notes

- The web UI binds to `127.0.0.1:8800` in the provided compose files. Put an HTTPS reverse
  proxy in front of it; never expose the port directly.
- Keep `LECTURE_WEB_SIGNUP=closed` until you are ready to accept public signups.
- API keys stored per user are encrypted with a key in `data/web/` (or `LECTURE_WEB_SECRET`).
  Back up that directory together with the database, and never commit `.env`.
- Voice cloning requires a recorded consent per uploaded voice; do not disable that check.
