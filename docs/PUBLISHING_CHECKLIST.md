# GitHub Publishing Checklist for Blender Addons

This file lists repository assets that are typically desirable when publishing
an addon on GitHub.

## 1. Core Repository Metadata

- [x] `README.md`
- [x] `LICENSE`
- [x] `CHANGELOG.md`
- [x] `CITATION.cff` (placeholder URL, should be customized)
- [x] `.gitignore`
- [x] `.gitattributes`
- [x] `.editorconfig`

## 2. Community and Governance

- [x] `CONTRIBUTING.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `SECURITY.md`
- [x] `SUPPORT.md`
- [x] `RELEASE_CHECKLIST.md`

## 3. GitHub Collaboration Templates

- [x] Issue template: bug report
- [x] Issue template: feature request
- [x] Issue template config
- [x] PR template
- [x] `CODEOWNERS` (placeholder, must be customized)

## 4. Automation and CI/CD

- [x] CI workflow for headless Blender tests
- [x] Release workflow for ZIP packaging and GitHub Releases
- [x] Dependabot updates for GitHub Actions
- [x] Release notes categorization config
- [x] CodeQL static analysis workflow

## 5. Testing Artifacts

- [x] Headless test runner script
- [x] Manual UI setup script

## 6. Addon Distribution Artifacts

- [x] Auto-packaged addon ZIP in release workflow
- [x] SHA256 checksum file in release workflow
- [ ] Signed artifacts (manual decision)
- [ ] SBOM / provenance attestation (optional, advanced)

## 7. Recommended But Manual (Not Auto-Added)

- [ ] Demo video or GIFs
- [ ] Screenshots in README
- [x] Real maintainer usernames in `CODEOWNERS`
- [x] Repo-specific Discussions URL in `.github/ISSUE_TEMPLATE/config.yml`
- [x] Real repo URL in `CITATION.cff`
- [ ] Repository topics and social preview image
- [ ] Clear support SLA and maintenance policy
- [ ] Optional docs site (GitHub Pages)

## Notes

- For trusted release quality, tag releases using semantic versioning:
  `vMAJOR.MINOR.PATCH`.
- Keep `CHANGELOG.md` updated before tagging.
