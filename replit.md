
# Google Calendar Telegram Notifier - Replit Configuration

This document contains Replit-specific configuration and setup information.

## Replit-Specific Features

### Google Calendar Connector Integration
This application uses Replit's built-in Google Calendar connector for OAuth authentication. The connector automatically manages:
- OAuth2 access tokens
- Token refresh
- Credential storage

**Setup**: Add the Google Calendar connector from the Tools section in your Repl.

### Database Configuration
- **Development**: SQLite (`calendar_monitor.db`)
- **Production/Deployment**: PostgreSQL (automatically provisioned)

The application automatically detects the environment and uses the appropriate database.

### Environment Variables
The following environment variables are automatically managed by Replit:

#### Google Calendar Connector
- `REPLIT_CONNECTORS_HOSTNAME`: Connector API endpoint
- `REPL_IDENTITY`: Development authentication token
- `WEB_REPL_RENEWAL`: Deployment authentication token

#### Database
- `DATABASE_URL`: PostgreSQL connection string (deployment only)

#### Session Management
- `SESSION_SECRET`: Flask session encryption key (auto-generated if not provided)

### Workflow Configuration
The Run button is configured to start the application using gunicorn:
```bash
gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app
```

**Port 5000** is used as it's the standard forwarded port in Replit deployments.

### Deployment Configuration (Autoscale Optimized)
The application is optimized for **Autoscale deployment** to minimize costs while supporting webhook-based architecture:

**Cost-Saving Features:**
- Scales to zero when idle (no calendar events)
- Only pays for compute when processing webhooks
- Instant startup with lazy initialization pattern

**Deployment Process:**
1. Health check endpoint (`/health`) responds instantly for deployment verification
2. Lightweight startup creates database tables only
3. Expensive operations (webhook setup, scheduler) run lazily in background after first request
4. Uses PostgreSQL for production data persistence
5. Webhook channels renewed automatically every 6 days

**Technical Details:**
- Autoscale deployment target for variable traffic
- Thread-safe lazy initialization with double-checked locking
- Graceful degradation when database isn't immediately available
- Fast health checks prevent deployment timeouts

## User Preferences
- **Communication style**: Simple, everyday language
- **Code style**: Complete implementations without ellipsis

## System Architecture

### Web Framework & Backend
- **Flask Application**: Core web framework handling routing, sessions, and request processing
- **SQLAlchemy ORM**: Database abstraction layer with declarative base models for data persistence
- **Background Scheduler (APScheduler)**: Handles webhook channel renewal every 6 days (NOT for polling)
- **ProxyFix Middleware**: Ensures proper handling of reverse proxy headers for deployment environments

### Database Layer
- **Flexible Database Support**: Configured to work with both PostgreSQL (production) and SQLite (development)
  - Primary: PostgreSQL via DATABASE_URL environment variable
  - Fallback: SQLite for local development (calendar_monitor.db)
- **Connection Pooling**: Implements pool recycling (300s) and pre-ping health checks to handle connection stability
- **Data Models**:
  - `CalendarSettings`: Stores Telegram bot configuration and monitoring settings
  - `EventRecord`: Tracks calendar events with their details, status, and last update timestamps
  - `WebhookChannel`: Stores active webhook channel information and expiration times

### External Service Integration Architecture
- **Google Calendar API**: 
  - Service builder pattern for API client instantiation
  - Credential management via Replit connector
  - Supports multiple calendar monitoring per user
  - Push notification webhooks for real-time updates
- **Telegram Bot API**:
  - Direct HTTP API integration for message sending
  - Supports both regular chats and supergroups with topic threading
  - Message formatting with Markdown/HTML parse modes
  - Topic ID resolution by name for organized notifications

### Frontend Architecture
- **Template Engine**: Jinja2 templating with Flask
- **UI Framework**: Bootstrap 5 with dark theme support via Replit agent theme
- **Responsive Design**: Mobile-first approach with viewport meta tags
- **Component Structure**:
  - Dashboard (`index.html`): System status and overview
  - Settings (`settings.html`): Telegram configuration interface
  - Calendar Management (`user_calendar.html`): Google Calendar account configuration

### Monitoring & Notification System
- **Event Change Detection**: Webhook-driven real-time notifications (not polling)
- **Notification Pipeline**:
  1. Google Calendar sends webhook POST to `/webhook/google-calendar`
  2. Application fetches updated event details from Google Calendar API
  3. Changes detected by comparing with stored `EventRecord` data
  4. Telegram messages formatted and sent with event details
  5. Database updated with latest event information
- **Webhook Renewal**: Background scheduler renews channels every 6 days (before 7-day expiration)
- **Statistics Tracking**: Aggregates calendar activity data for reporting (last 30 days default)
- **Health Check**: Dedicated `/health` endpoint for deployment monitoring (no database queries)

### Configuration Management
- **Environment Variables**: Managed by Replit connector and deployment system
- **Database Configuration**: Telegram settings and topic mappings stored in CalendarSettings model
- **Webhook Channels**: Active subscriptions tracked in WebhookChannel model

## Troubleshooting on Replit

### Google Calendar Connector Not Working
1. Check if the connector is added in Tools
2. Re-authenticate with Google if needed
3. Verify connector permissions include calendar read access

### Database Migrations
When deployed, the application automatically:
- Creates missing database tables
- Adds missing columns to existing tables
- Uses PostgreSQL connection pooling

### Port Binding
Always use `0.0.0.0:5000` for the Flask application to ensure proper port forwarding in Replit deployments.
