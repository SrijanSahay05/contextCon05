---
name: commit-and-pr
description: Commit the current changes on a feature branch and open a GitHub pull request against main with the repo's PR template filled in. Use when asked to commit, push, open/create/raise a PR, or ship changes.
---

# Commit and open a PR

`main` is protected; all changes go through a PR. Follow the rules in `AGENTS.md` (Git workflow, Filling the PR template). Honour any commit/PR attribution rules in the user's instructions (e.g. `CLAUDE.local.md`); they override defaults.

## Steps

1. **Inspect.** `git status`, `git diff` (and `git diff --staged`). Know exactly what is changing. Never stage `.env`, `CLAUDE.local.md`, build output or secrets.
2. **Branch.** If on `main`, create a branch: `git switch -c <type>/<short-kebab-desc>` (types: feat, fix, refactor, docs, chore, ci). If already on a feature branch, stay on it.
3. **Verify.** Run `make check`. Backend tests need Postgres + Mongo (`make dev`). If anything fails, stop and fix or report; do not commit red. If a check cannot be run, note it for the PR body.
4. **Commit.** Stage specific paths (`git add <paths>`, not `git add -A` blindly). Message: Conventional Commits, `type(scope): imperative summary` ≤ 72 chars, blank line, body explaining why. Split unrelated changes into separate commits.
5. **Push.** `git push -u origin HEAD`.
6. **PR body.** Copy `.github/pull_request_template.md`, fill every section per the AGENTS.md rules, delete all HTML comments. Write it to a temp file.
7. **Open.** `gh pr create --base main --title "<type(scope): summary>" --body-file <file>`. If a PR for the branch already exists, update it with `gh pr edit` instead.
8. **Report.** Give the PR URL and what CI will run. Do not merge; merging happens after CI is green, through GitHub.
