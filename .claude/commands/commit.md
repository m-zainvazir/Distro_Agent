# /commit — Create a Well-Formatted Git Commit for Current Changes

## Steps

1. Run: git status and git diff --staged
2. Analyze what changed
3. Write a conventional commit message: type(scope): description
   Types: feat, fix, refactor, test, docs, chore
   Example: feat(scout-agent): add Google Maps Places API integration
4. Run: git add -A && git commit -m "[message]"
5. Report the commit hash