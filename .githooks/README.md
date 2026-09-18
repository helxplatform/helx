# Git hooks

Enable with:

```bash
make install-hooks
```

That sets `core.hooksPath` to this directory, so the hooks here run for everyone
who opts in. It needs no package manager and adds no dependencies.

`pre-push` runs `make pre-push`: the CI unit tests, `validate-config`, the
version gate, the chart lock check, and a whitespace check. Bypass a single push
with `git push --no-verify`.

`pre-push` rather than `pre-commit` is deliberate: the version gate compares
against `develop`, and mid-feature commits often precede the version bumps that
CI requires. Blocking every commit on that is noise. If you would rather have it
on commit, copy `pre-push` to `pre-commit` in this directory.
