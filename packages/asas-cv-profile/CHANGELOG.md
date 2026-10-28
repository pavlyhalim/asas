# Changelog: `asas-cv-profile`

Versions follow semver, and the git tag matches this file: `asas-cv-profile/v0.1.0`.
Pre-1.0, a breaking change bumps the **minor**.

Release procedure and the historical tag mapping: [`RELEASING.md`](../../RELEASING.md).

## 0.1.0 (unreleased)

First release.

- **Profile model**: the host's sections and fields in YAML, with section kinds,
  field roles and computed fields; checked on load.
- **Lines**: `read_cv` with Document Intelligence for PDFs (`LayoutReader`, the
  `docintel` extra) and asas-cv for Word and text; refusals as `Refused` with a code.
- **Calls**: `Asker` runs the package's profile-builder release on asas-agent, with a
  cap on calls at once and a tokens-a-minute bucket.
- **Build**: `ProfileBuilder.build`, `recheck` (no model call) and `other_again`;
  values checked against their lines, follow-up calls only where the text shows a
  need, twins folded, skills kept in the CV's words, durations and totals with
  overlaps counted once, the lines no field took kept as other information.
- **Command line** `asas-cv-profile` (`schema`, `one`, `run`, `recheck`, `other`,
  `serve`) and the upload page (`upload_router`, the `serve` extra).
