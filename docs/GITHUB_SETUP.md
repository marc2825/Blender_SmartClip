# GitHub Setup Steps After Initial Commit

This repository includes templates with placeholders that should be updated.

## 1. Replace Placeholder Values

- `.github/CODEOWNERS`
  - Replace `@your-github-username` with actual owner(s).
- `.github/ISSUE_TEMPLATE/config.yml`
  - Replace Discussions URL with your real repository URL.
- `CITATION.cff`
  - Replace `https://github.com/<owner>/<repo>`.

## 2. Repository Settings

- Enable Issues and Discussions (recommended).
- Protect default branch (require PR + CI pass).
- Enable Dependabot alerts and security updates.

## 3. Release Flow

1. Update `CHANGELOG.md`.
2. Push semantic tag like `v1.0.1`.
3. Verify `Release Addon` workflow output includes:
   - `src-v1.0.1.zip`
   - `src-v1.0.1.sha256`

## 4. Optional Hardening

- Enforce signed commits.
- Add required reviewers via CODEOWNERS.
- Add repository secret scanning and private vulnerability reporting.
