<!-- markdownlint-disable-file MD013 -->

# Contributing to nonebot-plugin-htmlrender

Thanks for your interest in contributing.

This repository follows a workflow inspired by [angular/angular](https://github.com/angular/angular), adapted for the Python + NoneBot + Playwright stack.

## Quick Start

```bash
make prepare
make check
```

If your change touches real-browser behavior:

```bash
make install-browser
make test-local
```

## Contribution Workflow

1. Fork the repository.
1. Create a focused branch for one logical change.
1. Add or update tests with your code changes.
1. Run local checks before opening a PR.
1. Open a pull request with clear context and validation results.

## Before Opening a PR

Please run:

```bash
make ruff-format
make ruff-check
make typecheck
make ty
make test-ci
```

If docs were changed:

```bash
make docs-build
```

## PR Previews

When opening a PR from a branch in this repository (not a fork), the following previews are produced automatically:

- **TestPyPI build**: each push to the PR is published to TestPyPI under a dev-suffixed version. A sticky comment on the PR shows the install command.
- **Docs preview** (only when `docs/**`, `mkdocs.yml`, or `README.md` change): a sticky comment on the PR shows the preview URL under `pr-preview/pr-<NUMBER>/` of the Pages site. The preview is removed automatically when the PR is closed.

PRs from forks skip both because the workflow tokens cannot write to gh-pages or use TestPyPI trusted publishing.

## Commit Message Format

Use conventional, Angular-style commit messages:

```text
type(scope): subject
```

See the full guide:

- [提交消息指南](docs/maintainers/contributing/commit-message.md)

## Coding Standards

See:

- [编码规范](docs/maintainers/contributing/coding-standards.md)
- [工程协作与规范](docs/maintainers/contributing/engineering-guide.md)

## Code of Conduct

By participating, you agree to follow:

- [Code of Conduct](CODE_OF_CONDUCT.md)

## Security

Please report vulnerabilities according to:

- [Security Policy](SECURITY.md)
