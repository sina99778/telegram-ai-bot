---
description: Automatically push all file changes to GitHub after every edit
---

# Auto-Push Workflow

After creating or editing ANY files in this project, ALWAYS run the following steps immediately — do NOT wait for the user to ask.

// turbo-all

1. Stage all changes:
```
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User"); git add -A
```

2. Commit with a descriptive message:
```
git commit -m "<descriptive commit message>"
```

3. Push to origin:
```
git push origin master
```
