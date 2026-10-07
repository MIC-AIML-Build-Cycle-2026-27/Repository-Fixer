# Security

This repository is **public**. Anything committed, including in old commits and deleted branches, should be treated as visible to everyone.

## Never commit

- API keys and access tokens (OpenAI, Azure, Hugging Face, GitHub, cloud providers, etc.)
- Passwords, database connection strings, private keys (`*.pem`, `*.key`) and certificates
- `.env` files or any file containing real credentials
- Personal data: names, contact details, recordings or other information about real people
- Private or licensed datasets that may not be redistributed

## How to handle secrets

- Store configuration in environment variables. Keep a `.env` file locally. It is already in `.gitignore`.
- Commit a `.env.example` with **variable names only** and dummy values so others know what to set.
- For GitHub Actions, use **Settings → Secrets and variables → Actions** and reference values as `${{ secrets.NAME }}`.
- Do not paste keys into issues, PRs, notebooks, screenshots or logs.

## If you commit a secret by accident

1. **Revoke or rotate the key immediately** with the provider. Deleting the commit is not enough, because the key has already been exposed.
2. Tell your Project Leads.
3. Remove the secret from the code and replace it with an environment variable.

## Reporting a security issue

If you find a vulnerability in this project, or anything sensitive committed to the repository, **do not open a public issue**.

- Use **Security → Report a vulnerability** on this repository (private vulnerability reporting), or
- Contact the Project Leads or Department Leads directly: `<add contact>`

Give enough detail to reproduce the issue. We will acknowledge it and fix it as soon as possible.
