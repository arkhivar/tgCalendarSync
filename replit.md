# Google Calendar Telegram Notifier

## Overview

A Flask-based web application that monitors Google Calendar events and sends notifications to Telegram when changes are detected. The system periodically checks configured Google Calendars for new, updated, or deleted events and notifies users via a Telegram bot. It supports multiple calendar monitoring, supergroup topics, and provides a web dashboard for configuration and statistics.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Web Framework & Backend
- **Flask Application**: Core web framework handling routing, sessions, and request processing
- **SQLAlchemy ORM**: Database abstraction layer with declarative base models for data persistence
- **Background Scheduler (APScheduler)**: Handles periodic calendar checking at configurable intervals
- **ProxyFix Middleware**: Ensures proper handling of reverse proxy headers for deployment environments

### Database Layer
- **Flexible Database Support**: Configured to work with both PostgreSQL (production) and SQLite (development)
  - Primary: PostgreSQL via DATABASE_URL environment variable
  - Fallback: SQLite for local development (calendar_monitor.db)
- **Connection Pooling**: Implements pool recycling (300s) and pre-ping health checks to handle connection stability
- **Data Models**:
  - `CalendarSettings`: Stores Telegram bot configuration, check intervals, and monitoring settings
  - `EventRecord`: Tracks calendar events with their details, status, and last update timestamps

### Authentication & Authorization
- **Google OAuth2 Integration**: Uses Replit connector environment variables for Google Calendar API access
  - Supports both lowercase and uppercase environment variable formats
  - Implements token refresh mechanism for sustained access
  - Scopes: Read-only calendar access (`calendar.readonly`)
- **Session Management**: Flask session-based user state management with configurable secret key

### External Service Integration Architecture
- **Google Calendar API**: 
  - Service builder pattern for API client instantiation
  - Credential management via environment variables from Replit connector
  - Supports multiple calendar monitoring per user
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
- **Event Change Detection**: Compares event records against Google Calendar API responses
- **Notification Pipeline**:
  1. Background scheduler triggers calendar checks at configured intervals
  2. Google Calendar API fetched for event updates
  3. Changes detected by comparing with stored `EventRecord` data
  4. Telegram messages formatted and sent with event details
  5. Database updated with latest event information
- **Statistics Tracking**: Aggregates calendar activity data for reporting (last 30 days default)

### Configuration Management
- **Environment Variables**:
  - `SESSION_SECRET`: Flask session encryption key
  - `DATABASE_URL`: PostgreSQL connection string
  - `google_calendar_*`: Google OAuth credentials from Replit connector
  - `GOOGLE_CALENDAR_*`: Alternative uppercase format support
- **Database Configuration**: Check intervals, chat IDs, and bot tokens stored in CalendarSettings model

## External Dependencies

### Third-Party Services
- **Google Calendar API (v3)**: Primary data source for calendar events
  - Authentication: OAuth2 with access/refresh tokens
  - API Client: `googleapiclient.discovery`
  
- **Telegram Bot API**: Notification delivery platform
  - Direct HTTP API integration via `requests` library
  - Supports message threading in supergroups

### Python Libraries
- **Flask**: Web framework and routing (`flask`, `render_template`, `request`, `redirect`, `session`)
- **Flask-SQLAlchemy**: ORM and database management
- **APScheduler**: Background task scheduling (`BackgroundScheduler`)
- **Google Auth Libraries**: 
  - `google-auth-oauthlib`: OAuth flow handling
  - `google-auth`: Credentials and token management
  - `googleapiclient`: Google API client library
- **Werkzeug**: WSGI utilities (`ProxyFix` for proxy handling)
- **Requests**: HTTP client for Telegram API calls

### Database Systems
- **PostgreSQL**: Primary production database (requires psycopg2 driver)
- **SQLite**: Development/fallback database (built-in support)

### Frontend Dependencies
- **Bootstrap 5.3.0**: UI component framework (CDN)
- **Bootstrap Icons 1.11.1**: Icon library (CDN)
- **Replit Agent Dark Theme**: Custom Bootstrap theme for dark mode

### Development & Deployment
- **Replit Platform**: Deployment environment with integrated connectors
  - Google Calendar connector for OAuth credential management
  - Environment variable injection for sensitive configuration