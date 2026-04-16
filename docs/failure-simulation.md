# Failure Simulation: CI/CD Monitor + Diagnosis

Use this to verify real failure detection end-to-end.

## 1. Introduce an intentional runtime failure

Edit `flask_app/app.py` and break startup, for example remove/rename the Flask import:

```python
# from flask import Flask
```

Commit and push to one of these branches: `staging`, `pre-prod`, or `production`.

## 2. Expected GitHub Actions behavior

The workflow in `.github/workflows/docker-deploy.yml` should now fail because:

- Container state check fails OR
- Health check fails OR
- Runtime validation fails

The logs include explicit failure signals:

- `Container failed to start`
- `exit 1`
- `error`
- `exception`
- `failed`

## 3. Expected monitor behavior

After the workflow_run completes:

- Monitor report is created with:

```json
{
  "name": "...",
  "branch": "...",
  "status": "FAILURE",
  "error": "2-5 lines of real failure logs",
  "time": "..."
}
```

- Error snippet is extracted from keywords:
  - error
  - failed
  - exception
  - traceback
  - exit code

## 4. Expected diagnosis behavior

Diagnosis triggers only when `monitor.status == "FAILURE"`.

Output JSON shape:

```json
{
  "name": "...",
  "branch": "...",
  "error_type": "...",
  "possible_causes": ["...", "..."],
  "latest_working_change": "file + short summary"
}
```

## 5. Restore successful state

Revert the intentional break in `flask_app/app.py`, push again, and verify monitor returns:

```json
{
  "name": "...",
  "branch": "...",
  "status": "SUCCESS",
  "time": "..."
}
```
