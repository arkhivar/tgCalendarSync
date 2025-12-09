
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
  - `CalendarSettings`: Stores Telegram bot configuration, monitoring settings, and initial sync state
  - `EventRecord`: Tracks calendar events with their details, status, first seen timestamp, and notification history
  - `WebhookChannel`: Stores active webhook channel information and expiration times
  - `NotificationQueue`: Queued notifications for paced delivery to prevent Telegram flooding

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
  4. Notifications queued via `NotificationQueue` for paced delivery
  5. Queue dispatcher sends messages at ~1 per 2 seconds to respect Telegram rate limits
  6. Database updated with latest event information and notification timestamps
- **Webhook Renewal**: Background scheduler renews channels every 6 days (before 7-day expiration)
- **Statistics Tracking**: Aggregates calendar activity data for reporting (last 30 days default)
- **Health Check**: Dedicated `/health` endpoint for deployment monitoring (no database queries)

### Rate-Limiting & Flood Protection
The system includes comprehensive safeguards against Telegram flooding:

- **Initial Sync Suppression**: On first calendar scan (or after `initial_sync_complete` is reset):
  - Past events (before current time) are silently stored without notifications
  - Only future events trigger notifications on initial sync
  - Prevents notification floods when app restarts or is republished
  - Controlled by `initial_sync_complete` and `initial_sync_cutoff` fields in CalendarSettings

- **Queued Notification Dispatch**:
  - All notifications go through `NotificationQueue` table
  - Background dispatcher runs every 2 seconds via APScheduler
  - Processes one message per cycle (~1 msg/2 sec) to respect Telegram limits
  - Queue tracks: message content, calendar name, topic ID, status, retry count

- **Telegram 429 Error Handling**:
  - Detects "Too Many Requests" responses from Telegram API
  - Parses `retry_after` value from error response
  - Automatically backs off and retries after the specified delay
  - Failed notifications remain in queue with incremented retry count

- **Event Tracking**:
  - `first_seen_at`: Timestamp when event was first discovered (for suppression logic)
  - `last_notified_at`: Timestamp of last notification sent (prevents duplicate notifications)

- **Past Event Highlighting**:
  - Past events are clearly marked with a "⏪ Past event added/updated/deleted" prefix
  - Makes it easy to distinguish between future event notifications and historical changes
  - Uses the `is_past_event` flag from calendar_monitor to determine event timing

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
