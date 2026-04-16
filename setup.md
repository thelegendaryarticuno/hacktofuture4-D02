# PipelineIQ Setup Guide

This guide explains how to configure the credentials used by `pipelineIQ` and `pipelineIQ-frontend`.

It covers:
- MongoDB Atlas
- GitHub OAuth App for login
- GitHub App for repository installation, webhooks, and installation tokens
- Localhost and Vercel environment values
- Cookie and session settings

Use this together with [`.env.example`](/home/the_devils_guy/Programming/hackathon_project/hacktofuture4-D02/.env.example:1).

## 1. Environment Variables You Need

These are the variables currently expected by the backend:

```env
# MongoDB Atlas
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/pipelineiq?retryWrites=true&w=majority
MONGODB_DB_NAME=pipelineiq

# Session / cookies
JWT_SECRET=replace-this-with-a-long-random-secret
COOKIE_DOMAIN=
COOKIE_SECURE=false

# Frontend
FRONTEND_URL=http://localhost:5173

# GitHub OAuth App
GITHUB_CLIENT_ID=your-github-oauth-client-id
GITHUB_CLIENT_SECRET=your-github-oauth-client-secret
GITHUB_REDIRECT_URI=http://localhost:8000/api/auth/github/callback
GITHUB_OAUTH_SCOPES=read:user read:org

# GitHub App
GITHUB_APP_ID=1234567
GITHUB_APP_SLUG=your-github-app-name
GITHUB_APP_INSTALL_URL=https://github.com/apps/your-github-app-name/installations/new
GITHUB_APP_WEBHOOK_SECRET=replace-with-your-webhook-secret
GITHUB_APP_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nPASTE_YOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----"
```

## 2. MongoDB Atlas Setup

### Step 1: Create an Atlas cluster

1. Go to `https://www.mongodb.com/cloud/atlas`
2. Create an account or sign in
3. Create a new project
4. Create a cluster
5. Choose the free tier if that is enough for your hackathon/demo use case

### Step 2: Create a database user

1. Open your Atlas project
2. Go to `Database Access`
3. Click `Add New Database User`
4. Choose username/password authentication
5. Save the username and password

### Step 3: Allow network access

1. Go to `Network Access`
2. Click `Add IP Address`
3. For local development, you can temporarily allow your current IP
4. For quick testing, many people use `0.0.0.0/0`, but only do that if you understand the security tradeoff

### Step 4: Get the connection string

1. Go to `Database`
2. Click `Connect`
3. Choose `Drivers`
4. Copy the connection string
5. Replace:
   - `<username>` with your Atlas DB username
   - `<password>` with your Atlas DB password
   - database name with `pipelineiq` if you want to match the default

Example:

```env
MONGODB_URI=mongodb+srv://myuser:mypassword@cluster0.abcde.mongodb.net/pipelineiq?retryWrites=true&w=majority
MONGODB_DB_NAME=pipelineiq
```

## 3. GitHub OAuth App Setup

This OAuth App is only for authentication.

It is used for:
- signing the engineer into PipelineIQ
- getting their GitHub identity
- getting the list of organizations they belong to

It is not used for repository monitoring or workflow log access.

### Step 1: Open GitHub Developer Settings

1. Go to GitHub
2. Click your profile picture
3. Open `Settings`
4. Scroll to `Developer settings`
5. Open `OAuth Apps`
6. Click `New OAuth App`

### Step 2: Fill in the OAuth App form

For localhost:

- `Application name`: `PipelineIQ Local`
- `Homepage URL`: `http://localhost:5173`
- `Authorization callback URL`: `http://localhost:8000/api/auth/github/callback`

For production:

- `Application name`: `PipelineIQ`
- `Homepage URL`: `https://your-app.vercel.app`
- `Authorization callback URL`: `https://your-backend-domain.com/api/auth/github/callback`

### Step 3: Save the credentials

After creating the OAuth App:

1. Copy `Client ID`
2. Click `Generate a new client secret`
3. Copy that secret immediately

Map them like this:

```env
GITHUB_CLIENT_ID=<Client ID from GitHub OAuth App>
GITHUB_CLIENT_SECRET=<Client Secret from GitHub OAuth App>
```

### Step 4: Set the redirect URI

This must match the callback URL you entered in GitHub exactly.

For localhost:

```env
GITHUB_REDIRECT_URI=http://localhost:8000/api/auth/github/callback
```

For production:

```env
GITHUB_REDIRECT_URI=https://your-backend-domain.com/api/auth/github/callback
```

### Step 5: Set the OAuth scopes

Use:

```env
GITHUB_OAUTH_SCOPES=read:user read:org
```

Why these scopes:
- `read:user` lets you identify the signed-in GitHub user
- `read:org` lets you fetch the organizations they belong to

## 4. GitHub App Setup

This GitHub App is the important part for repository integration.

It is used for:
- installing PipelineIQ on selected repositories
- receiving webhook events
- generating installation access tokens
- later fetching workflow logs using installation auth

### Step 1: Open GitHub App settings

1. Go to GitHub
2. Click your profile picture
3. Open `Settings`
4. Open `Developer settings`
5. Open `GitHub Apps`
6. Click `New GitHub App`

### Step 2: Fill in the GitHub App details

#### App name

Choose a unique name, for example:

`pipelineiq-monitor`

This name usually becomes the app slug.

#### Homepage URL

For localhost:

```text
http://localhost:5173
```

For production:

```text
https://your-app.vercel.app
```

#### Webhook URL

This is where GitHub sends events after the app is installed.

For localhost:

You cannot use plain `localhost` directly for GitHub webhooks. GitHub needs a public URL.

Use a tunnel such as:
- `ngrok`
- `cloudflared`

Example localhost tunnel webhook URL:

```text
https://your-tunnel.ngrok-free.app/api/github/webhooks
```

For production:

```text
https://your-backend-domain.com/api/github/webhooks
```

#### Webhook secret

Create a long random string and paste it into the GitHub App form.

Later store the exact same value in:

```env
GITHUB_APP_WEBHOOK_SECRET=<your-random-secret>
```

#### Setup URL

This is the URL GitHub returns to after installation.

For localhost:

```text
http://localhost:8000/api/github/installations/callback
```

For production:

```text
https://your-backend-domain.com/api/github/installations/callback
```

If GitHub shows an option like `Redirect on update`, enable it if you want updates to installation settings to return through the same callback flow.

### Step 3: Configure repository permissions

Set these repository permissions:

- `Actions`: `Read-only`
- `Checks`: `Read and write`
- `Contents`: `Read-only`
- `Metadata`: `Read-only`

Why:
- `Actions` is needed to read workflow runs and logs
- `Checks` is needed if you later want to write fix/status signals
- `Contents` read is needed for repo context and diff analysis
- `Metadata` is basic required repo information

Do not request write access to contents if you want to keep the app narrowly scoped.

### Step 4: Subscribe to webhook events

Enable these webhook event subscriptions:

- `Workflow run`
- `Workflow job`
- `Check run`
- `Push`

These map to the flow you described:
- `workflow_run` for pipeline started/completed/failed
- `workflow_job` for individual job states
- `push` for commit context
- `check_run` for check status

### Step 5: Create the GitHub App

Save the app after permissions and event subscriptions are configured.

### Step 6: Save GitHub App values into `.env`

After the app is created:

#### App ID

On the GitHub App settings page, copy `App ID`.

Store it as:

```env
GITHUB_APP_ID=<GitHub App ID>
```

#### App slug

The slug is the URL-safe app name.

Example:

If your app URL is:

```text
https://github.com/apps/pipelineiq-monitor
```

Then:

```env
GITHUB_APP_SLUG=pipelineiq-monitor
```

#### Install URL

Build it from the slug:

```env
GITHUB_APP_INSTALL_URL=https://github.com/apps/pipelineiq-monitor/installations/new
```

#### Private key

1. Open the GitHub App settings page
2. Scroll to `Private keys`
3. Click `Generate a private key`
4. A `.pem` file downloads
5. Open that file
6. Copy the full contents

Store it in `.env` as one string with escaped newlines:

```env
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nLINE_1\nLINE_2\nLINE_3\n-----END RSA PRIVATE KEY-----"
```

Important:
- keep the quotes
- replace real line breaks with `\n`
- never commit the real private key

## 5. JWT Secret and Cookie Settings

These are used for your app session cookie, not for GitHub.

### JWT secret

Generate a long random secret.

Example command:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the result into:

```env
JWT_SECRET=<your-generated-secret>
```

### Cookie settings for localhost

Use:

```env
COOKIE_DOMAIN=
COOKIE_SECURE=false
```

Why:
- blank `COOKIE_DOMAIN` means the browser uses the host that set the cookie
- `COOKIE_SECURE=false` is needed for plain `http://localhost`

### Cookie settings for production

Use:

```env
COOKIE_DOMAIN=
COOKIE_SECURE=true
```

Why:
- production should use HTTPS
- secure cookies should only be sent over HTTPS
- blank domain is usually the safest default unless you intentionally share cookies across subdomains

## 6. Localhost Example `.env`

```env
MONGODB_URI=mongodb+srv://myuser:mypassword@cluster0.abcde.mongodb.net/pipelineiq?retryWrites=true&w=majority
MONGODB_DB_NAME=pipelineiq

JWT_SECRET=your-generated-secret
COOKIE_DOMAIN=
COOKIE_SECURE=false

FRONTEND_URL=http://localhost:5173

GITHUB_CLIENT_ID=your-local-oauth-client-id
GITHUB_CLIENT_SECRET=your-local-oauth-client-secret
GITHUB_REDIRECT_URI=http://localhost:8000/api/auth/github/callback
GITHUB_OAUTH_SCOPES=read:user read:org

GITHUB_APP_ID=1234567
GITHUB_APP_SLUG=pipelineiq-monitor
GITHUB_APP_INSTALL_URL=https://github.com/apps/pipelineiq-monitor/installations/new
GITHUB_APP_WEBHOOK_SECRET=your-local-webhook-secret
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END RSA PRIVATE KEY-----"
```

If testing webhooks locally, remember:
- backend can run on localhost
- webhook URL must be public through a tunnel
- setup URL can still be localhost if your browser can reach it directly

## 7. Production Example `.env`

```env
MONGODB_URI=mongodb+srv://myuser:mypassword@cluster0.abcde.mongodb.net/pipelineiq?retryWrites=true&w=majority
MONGODB_DB_NAME=pipelineiq

JWT_SECRET=your-generated-secret
COOKIE_DOMAIN=
COOKIE_SECURE=true

FRONTEND_URL=https://your-app.vercel.app

GITHUB_CLIENT_ID=your-prod-oauth-client-id
GITHUB_CLIENT_SECRET=your-prod-oauth-client-secret
GITHUB_REDIRECT_URI=https://your-backend-domain.com/api/auth/github/callback
GITHUB_OAUTH_SCOPES=read:user read:org

GITHUB_APP_ID=1234567
GITHUB_APP_SLUG=pipelineiq-monitor
GITHUB_APP_INSTALL_URL=https://github.com/apps/pipelineiq-monitor/installations/new
GITHUB_APP_WEBHOOK_SECRET=your-prod-webhook-secret
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END RSA PRIVATE KEY-----"
```

## 8. Important Deployment Note

Right now the frontend uses cookie-based auth with credentials.

That means:
- localhost works fine with the current setup
- production works best when frontend and backend are same-site or proxied cleanly

If your frontend is on Vercel and your backend is on a different domain, cross-site cookie behavior can become tricky.

Your current backend uses:
- `HttpOnly`
- `SameSite=Lax`
- `Secure` controlled by `COOKIE_SECURE`

If you later run frontend and backend on different sites and cookies are not being sent correctly, you may need to update cookie handling to support that deployment shape.

## 9. Quick Checklist

Before running the app, confirm:

1. Atlas cluster is created
2. `MONGODB_URI` is valid
3. OAuth App is created
4. `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are copied correctly
5. `GITHUB_REDIRECT_URI` exactly matches GitHub OAuth callback config
6. GitHub App is created
7. GitHub App permissions are set correctly
8. GitHub App webhook events are enabled
9. `GITHUB_APP_ID` is correct
10. `GITHUB_APP_SLUG` is correct
11. `GITHUB_APP_INSTALL_URL` matches the slug
12. `GITHUB_APP_WEBHOOK_SECRET` matches the GitHub App webhook secret exactly
13. `GITHUB_APP_PRIVATE_KEY` contains the full PEM with escaped newlines
14. `JWT_SECRET` is random and strong
15. `COOKIE_SECURE` is `false` on localhost and `true` on production HTTPS

## 10. Helpful References

- GitHub OAuth Apps:
  `https://docs.github.com/en/developers/apps/creating-an-oauth-app`
- GitHub OAuth authorization:
  `https://docs.github.com/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps`
- Creating a GitHub App:
  `https://docs.github.com/apps/building-github-apps/creating-a-github-app`
- GitHub App permissions:
  `https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/choosing-permissions-for-a-github-app`
- GitHub App private keys:
  `https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps`
- Installation access tokens:
  `https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app`
