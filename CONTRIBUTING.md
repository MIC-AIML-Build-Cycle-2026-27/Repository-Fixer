# Contributing

Thanks for contributing. This guide covers the everyday workflow for this repository. The department-wide version, with more background, is in the [Build Cycle Handbook](https://github.com/MIC-AIML-Build-Cycle-2026-27/build-cycle-handbook).

If anything here gets in the way of building, talk to your Project Leads. The process exists to help, not to slow you down.

## 1. Get the code

Team members have write access, so **clone the repository directly**. You do not need a fork.

```bash
git clone https://github.com/MIC-AIML-Build-Cycle-2026-27/<repository-name>.git
cd <repository-name>
```

People outside the team should fork the repository and open pull requests from their fork.

Keep your local `main` up to date:

```bash
git switch main
git pull
```

## 2. Start from an issue

Every piece of work should have an issue, so the team can see who is doing what.

- Look on the project board for an issue assigned to you, or pick an unassigned one after checking with your Project Leads.
- If the work is not tracked yet, create an issue using the closest template (Feature, Bug, Task, Research, Experiment, Documentation).
- Assign yourself and set the milestone (Review 1, Review 2 or Final Review).

Small fixes such as typos do not need an issue.

## 3. Create a branch

Never commit directly to `main`. Create a branch from an up-to-date `main`:

```bash
git switch main
git pull
git switch -c feature/short-description
```

| Prefix | Use for | Example |
|---|---|---|
| `feature/` | New functionality | `feature/document-parser` |
| `fix/` | Bug fixes | `fix/empty-input-crash` |
| `research/` | Literature review, investigation, spikes | `research/retrieval-approaches` |
| `experiment/` | Model / prompt / parameter experiments | `experiment/baseline-v1` |
| `docs/` | Documentation only | `docs/setup-guide` |

Use lowercase and hyphens. Adding the issue number is optional but helpful, for example `feature/42-document-parser`.

## 4. Make changes

- Keep each branch focused on one issue.
- Follow the existing code style and structure.
- Add or update tests when you change behaviour.
- Update documentation when you change how something is used or set up.
- **Never commit secrets** (API keys, passwords, tokens) or large datasets. See [SECURITY.md](SECURITY.md).

## 5. Commit

Write commit messages that explain *what* changed. Use the imperative mood:

```
Add PDF text extraction for shipping documents
Fix crash when the input list is empty
Document local setup steps
```

Avoid messages like `update`, `fix stuff` or `final final v2`. Commit often, and keep each commit about one thing.

## 6. Open a pull request

```bash
git push -u origin feature/short-description
```

Then open a pull request on GitHub. The PR template will guide you through:

- **What changed and why**
- **Related issue.** Write `Closes #42` so the issue closes automatically when the PR merges.
- **How it was tested**
- **Results / screenshots** where relevant

Keep PRs small. Under about 400 changed lines is a good target. Open a **draft PR** early if you want feedback before you finish.

## 7. Review

- Every PR needs **at least one approval** and **passing CI** before it can merge into `main`.
- Project Leads are requested as reviewers automatically (see `.github/CODEOWNERS`), but any teammate can and should review.
- As a reviewer, be specific and kind. Explain *why* something should change, and approve when it is good enough, not perfect.
- As an author, reply to every comment. Push follow-up commits to the same branch.

## 8. Merge

- Use **Squash and merge** unless your team agrees otherwise. This keeps `main` history readable.
- Delete the branch after merging.
- Move the issue to **Done** on the board if it did not move automatically.

## Testing

Run the tests locally before pushing. See the *Testing* section of the README for the command. CI runs the same checks on every pull request.

## Documentation

- The README is the front door. Keep *Getting Started*, *Usage* and *Current Progress* accurate.
- Design notes go in `docs/architecture.md`.
- Record significant decisions (for example, why you chose one model or framework over another) in `docs/`.
- Research and experiment findings go in the issue, and are summarised in `docs/` when they affect the design.

## Communication

- Use issues and PR comments for technical discussion, so decisions are recorded.
- Use the team's chat for quick coordination.
- **If you are blocked for more than a day, say so.** Add the `status: blocked` label and tell your Project Leads. Asking early is expected.
