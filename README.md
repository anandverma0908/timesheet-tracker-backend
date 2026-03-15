# Engineering Analytics Platform — Backend v3.0

## Stack
- **FastAPI** — API framework
- **PostgreSQL** — main database
- **SQLAlchemy** — ORM
- **APScheduler** — background Jira sync every 30 min
- **python-jose** — JWT tokens
- **Gmail SMTP** — free email for OTP (built-in smtplib)

## File Structure
```
backend/
├── main.py              ← All API endpoints
├── database.py          ← PostgreSQL tables (6 tables)
├── auth.py              ← OTP login, JWT, email
├── models.py            ← Pydantic request/response schemas
├── sync.py              ← Jira → DB sync logic
├── jira_client.py       ← Jira API client (unchanged)
├── report_generator.py  ← Excel export (unchanged)
├── requirements.txt
└── .env                 ← copy from .env.example
```

## Setup

### 1. PostgreSQL
```bash
# Create database
createdb timesheet-tracker-db

# Or with psql
psql -c "CREATE DATABASE timesheet-tracker-db;"
```

### 2. Environment
```bash
cp .env.example .env
# Edit .env with your values
```

Key variables:
```
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/timesheet-tracker-db
JWT_SECRET=run: python -c "import secrets; print(secrets.token_hex(32))"
JIRA_URL=https://3scsolution.atlassian.net
JIRA_EMAIL=anand.verma@3scsolution.com
JIRA_API_TOKEN=your-token
DEV_MODE=true   # shows OTP in response, no email sent
```

### 3. Install & run
```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Tables are created automatically on first run.

### 4. First-time setup (run once)
```bash
curl -X POST http://localhost:8000/api/setup \
  -H "Content-Type: application/json" \
  -d '{
    "name": "3SC Solution",
    "jira_url": "https://3scsolution.atlassian.net",
    "jira_email": "anand.verma@3scsolution.com",
    "jira_api_token": "your-token"
  }'
```

This creates your org and first admin user.

### 5. Login
```bash
# Request OTP (DEV_MODE returns code in response)
curl -X POST http://localhost:8000/api/auth/request-otp \
  -H "Content-Type: application/json" \
  -d '{"email": "anand.verma@3scsolution.com"}'

# Verify OTP → get JWT
curl -X POST http://localhost:8000/api/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"email": "anand.verma@3scsolution.com", "code": "847392"}'
```

### 6. Trigger first Jira sync
```bash
curl -X POST http://localhost:8000/api/sync \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

After sync, all API endpoints query from DB — fast, no live Jira calls.

## API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/request-otp | Send OTP to email |
| POST | /api/auth/verify-otp | Verify OTP → JWT |
| POST | /api/auth/logout | Invalidate session |
| GET  | /api/auth/me | Current user info |

### Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/summary | KPIs, by_pod, by_client, by_user |
| GET | /api/tickets | All tickets with filters + pagination |
| GET | /api/filters | Dropdown options |
| GET | /api/activity | Combined Jira + manual entries |

### Manual Entries
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | /api/manual-entries | Save AI time entry batch |
| GET    | /api/manual-entries | Fetch history |
| PUT    | /api/manual-entries/:id | Edit entry |
| DELETE | /api/manual-entries/:id | Delete entry |

### Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/export/monthly | Monthly Finance Excel |
| GET | /api/export/fy | Annual FY Excel |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | /api/users | List all users |
| POST   | /api/users/invite | Invite new user |
| PUT    | /api/users/:id | Update role/status |
| DELETE | /api/users/:id | Deactivate user |
| GET    | /api/settings | Org Jira config |
| PUT    | /api/settings/jira | Update Jira config |
| POST   | /api/sync | Trigger manual sync |
| GET    | /api/sync/status | Last sync info |
