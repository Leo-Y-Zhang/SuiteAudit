# Releasing

Publishing is the owner's step, every time. The pipeline builds, checks and
publishes on a version tag; nothing is published without one.

## One-time setup (before the first tag)

1. **PyPI account.** Sign in or register at https://pypi.org, then enable
   two-factor authentication under Account settings. PyPI requires 2FA for
   every account before it will accept an upload.
2. **Pending trusted publisher.** On PyPI open Account settings, then
   Publishing, and add a pending publisher with exactly these values:

   | field | value |
   |---|---|
   | PyPI project name | `suiteaudit` |
   | Owner | `Leo-Y-Zhang` |
   | Repository name | `SuiteAudit` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   A pending publisher does not reserve the name; it becomes real on the
   first successful publish. Nothing else on PyPI needs an API token.
3. **GitHub environment.** In the repository, Settings, then Environments,
   create an environment named `pypi`. Optionally add yourself as a required
   reviewer so every publish waits for one click.

## Each release

1. Update `version` in `pyproject.toml` and add the section to
   `CHANGELOG.md`. Commit on `main`; CI must be green.
2. Tag and push the tag:

   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```

   The Release workflow then: checks the tag matches the version, builds the
   sdist and wheel, runs `twine check`, installs the wheel into a fresh
   environment and runs it, publishes to PyPI through the `pypi` environment,
   and creates the GitHub release with the artifacts attached.
3. Confirm: `pip install suiteaudit==0.1.0` in a fresh environment, then
   `suiteaudit --version`.

## GitHub Marketplace (the action)

After the release exists, open it on GitHub, choose Edit, tick "Publish this
Action to the GitHub Marketplace", accept the terms, pick a category
(Continuous integration or Code quality) and publish. This needs two-factor
authentication on the GitHub account. The action's `version` input default in
`action.yml` should match the release being listed.

## pre-commit

Consumers pin an immutable `rev`, so the tag above is what makes the hook
usable:

```yaml
repos:
  - repo: https://github.com/Leo-Y-Zhang/SuiteAudit
    rev: v0.1.0
    hooks:
      - id: suiteaudit
```
