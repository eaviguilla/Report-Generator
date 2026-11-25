---
description: "Push this repo: check the GitHub identity, commit every change with a conventional commit message, push the current branch, then create and push a release tag so CI publishes BLA-hardened zips. Use when the user says push."
agent: "agent"
tools: [execute, read]
---

Follow these steps in order. Stop at the first one that fails and report what it printed.

1. Check the GitHub identity. `git remote get-url --push origin` must print
   `git@github-eaviguilla:eaviguilla/Report-Generator.git`, and `ssh -T git@github-eaviguilla` must
   answer "Hi eaviguilla!". If either check fails, stop and report.
2. If `git status --short` prints nothing and the branch is not ahead of origin, say there is
   nothing to push and stop.
3. Stage every change with `git add -A`. Read `git diff --cached --stat` and the staged diff, then
   commit with a conventional commit message (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
   `chore:`) that describes what the diff does. No AI attribution: no `Co-Authored-By` trailer, no
   "Generated with" footer. If the pre-commit hook blocks the commit, stop and show its message.
4. Push the current branch with `git push`, then confirm that `git status -sb` shows it in sync
   with origin.
5. Create and push a new release tag so `.github/workflows/release.yml` builds and publishes fresh
   BLA-hardened zip assets. Use:
   - `tag="v$(date -u +%Y.%m.%d-%H%M%S)"`
   - `git tag "$tag"`
   - `git push origin "$tag"`
   Then print the tag name you pushed.
