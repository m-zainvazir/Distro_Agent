# Spec: Block A — Auth & Multi-Tenancy

## Overview
Replace the hardcoded "default" tenant with real accounts. Add JWT-based signup/login, a get_current_tenant dependency, and enforce tenant_id filtering on every query.

## Files to create
| File | Purpose |
|---|---|
| app/core/security.py | Password hashing (bcrypt) + JWT encode/decode |
| app/models/user.py | User model linked to Tenant |
| app/schemas/auth.py | SignupRequest, LoginRequest, TokenResponse |
| app/api/v1/auth.py | POST /signup, POST /login endpoints |
| app/core/dependencies.py | get_current_tenant + get_current_user |
| tests/api/test_auth.py | Auth flow tests |

## Data Models
User: id, email (unique), hashed_password, tenant_id FK, created_at
(Tenant already exists from Phase 1 — add relationship to User)

## Endpoints
POST /api/v1/auth/signup
  Body: { email, password, brand_name }
  Action: create Tenant + User, return JWT
  Response: { access_token, token_type: "bearer", tenant_id }

POST /api/v1/auth/login
  Body: { email, password }
  Response: { access_token, token_type: "bearer", tenant_id }

## get_current_tenant dependency
- Reads Authorization: Bearer <token> header
- Decodes JWT, extracts tenant_id
- Returns the Tenant object (or 401 if invalid)

## Behavior
- Passwords hashed with bcrypt, never stored plain
- JWT expires in 7 days, signed with settings.SECRET_KEY
- /discovery/start now requires auth and persists under the token's tenant

## Acceptance Criteria
- [x] Signup creates a Tenant + User, returns valid JWT
- [x] Login with correct password returns JWT; wrong password → 401
- [x] get_current_tenant rejects missing/invalid token with 401
- [x] An authenticated /discovery/start persists results under that tenant
- [x] Querying another tenant's data returns nothing (isolation verified)
