# /tenant-audit

Verify every database query filters by tenant_id.

## Steps
1. Find all SQLAlchemy select/update/delete statements
2. For each, confirm a .where(Model.tenant_id == ...) clause exists
3. Flag any query missing tenant filtering
4. Confirm all API endpoints use the get_current_tenant dependency

## Output
Report: queries WITH tenant filter vs WITHOUT.
Any query without filtering is a security bug — must fix before deploy.
