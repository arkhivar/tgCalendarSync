
# Google Calendar Telegram Notifier

A Flask-based web application that monitors Google Calendar events and sends instant notifications to Telegram using webhooks. The system uses Google Calendar's push notification API to deliver real-time alerts when events are created, updated, or deleted.

## 🌟 Key Features

- **Real-time Notifications**: Uses Google Calendar webhooks for instant event notifications (no polling delays)
- **Multiple Calendar Support**: Monitor multiple Google Calendars simultaneously
- **Telegram Integration**: Send notifications to Telegram groups with topic support
- **Web Dashboard**: Easy-to-use interface for configuration and monitoring
- **Automatic Webhook Renewal**: Automatically renews webhook subscriptions before they expire (every 6 days)
- **Calendar Statistics**: View event activity statistics for the last 30 days
- **Rate-Limiting Protection**: Prevents Telegram flooding with queued message delivery (~1 msg/2 sec)
- **Initial Sync Suppression**: Silently stores past events on first scan to prevent notification floods on restart

## 🏗️ Architecture

### Webhook-Based System
This application uses **Google Calendar's push notifications API** rather than polling. When you add, modify, or delete calendar events, Google instantly sends a notification to your webhook endpoint, which then forwards the notification to Telegram.

**Important Design Decision**: The system uses webhooks as the primary notification mechanism. A scheduler runs only to renew webhook channels every 6 days (Google Calendar webhooks expire after 7 days). There is NO polling scheduler - all notifications are event-driven.

### Components

1. **Flask Web Application** (`app.py`): Main application with routes and initialization
2. **Google Calendar Webhook Handler** (`google_calendar_webhook.py`): Manages webhook subscriptions and processes incoming notifications
3. **Google Connector** (`google_connector.py`): Interfaces with Replit's Google Calendar connector for OAuth
4. **Calendar Monitor** (`calendar_monitor.py`): Fetches calendar data and detects changes
5. **Telegram Notifier** (`telegram_notifier.py`): Sends formatted messages to Telegram
6. **Notification Dispatcher** (`notification_dispatcher.py`): Queues and dispatches notifications with rate limiting
7. **Database Models** (`models.py`): SQLAlchemy models for settings, events, and notification queue

## 🚀 Deployment on Replit

### Prerequisites
1. A Replit account
2. A Google account with Calendar access
3. A Telegram bot token (get it from [@BotFather](https://t.me/botfather))
4. A Telegram group or supergroup

### Setup Instructions

#### 1. Import the Repository
1. Go to [replit.com/new](https://replit.com/new)
2. Click "Import from GitHub"
3. Enter your repository URL
4. Replit will automatically detect it's a Python/Flask application

#### 2. Configure Google Calendar Connector
1. In your Repl, click the "Tools" section in the left sidebar
2. Find and add the "Google Calendar" connector
3. Click "Connect" and authenticate with your Google account
4. Grant the necessary permissions (read-only calendar access)

**Important**: The Google Calendar connector must be configured for the application to work. Without it, webhook setup will fail.

#### 3. Configure Environment Variables
The application uses PostgreSQL in production. Replit will automatically provision a database when you deploy.

Optional environment variable:
- `SESSION_SECRET`: Flask session secret (auto-generated if not provided)

#### 4. Configure the Application
1. Run the application (it will start automatically)
2. Open the web interface
3. Navigate to "Settings"
4. Enter your Telegram configuration:
   - **Bot Token**: Get from [@BotFather](https://t.me/botfather)
   - **Chat ID**: Your Telegram group's chat ID (use [@userinfobot](https://t.me/userinfobot) to find it)
   - **Topic Mappings** (optional): Map calendar names to Telegram topic IDs in JSON format

Example topic mappings:
```json
{
  "Work Calendar": 123,
  "Personal": 456
}
```

#### 5. Deploy the Application

**Critical for Webhooks**: You MUST deploy your application for webhooks to work reliably!

1. Click the "Deploy" button in Replit
2. Choose your deployment tier:
   - **Reserved VM** (recommended): Always-on, consistent performance
   - **Autoscale**: Scales based on traffic
3. Configure deployment settings (build/run commands are pre-configured)
4. Click "Deploy"

**Why deployment is required**:
- Development Repls go to sleep after inactivity
- When asleep, Google can't reach your webhook endpoint
- Missed webhook notifications = no Telegram alerts
- Deployed apps run 24/7 and receive all webhook notifications

After deployment, your webhook URL will be: `https://<your-deployment-url>/webhook/google-calendar`

#### 6. Verify Webhooks are Working
1. Check the console logs for webhook setup messages:
   ```
   ✅ Created watch channel for <calendar> (expires ...)
   ```
2. Add a test event to one of your monitored calendars
3. You should receive a Telegram notification within seconds
4. Check the logs for incoming webhook notifications:
   ```
   📥 Received Google Calendar webhook notification
   ```

### Troubleshooting

#### No Telegram Notifications
1. **Check if deployed**: Development Repls that sleep won't receive webhooks
2. **Verify webhook setup**: Look for "✅ Created watch channel" messages in logs
3. **Test the webhook endpoint**: Visit `https://<your-url>/webhook/google-calendar` - should return JSON
4. **Check Telegram settings**: Verify bot token and chat ID are correct
5. **Look for webhook notifications in logs**: Search for "📥 Received Google Calendar webhook"

#### Google Calendar Connector Issues
- Make sure the connector is properly configured in Replit
- Check that you've granted calendar read permissions
- Re-authenticate if necessary

#### Webhook Errors
- Some calendars (like public holiday calendars) don't support webhooks
- Check logs for "Push notifications are not supported" errors
- These calendars will be skipped automatically

## 📊 Database Schema

### CalendarSettings
- `telegram_bot_token`: Telegram bot authentication token
- `chat_id`: Telegram chat/group ID
- `topic_mappings`: JSON mapping of calendar names to topic IDs
- `check_interval`: Legacy field (not used in webhook mode)
- `initial_sync_complete`: Boolean flag indicating if initial sync has been performed
- `initial_sync_cutoff`: Timestamp used to suppress past event notifications on initial sync

### EventRecord
- `event_id`: Google Calendar event ID
- `calendar_id`: Source calendar ID
- `calendar_name`: Human-readable calendar name
- `summary`: Event title
- `start_time`: Event start time
- `end_time`: Event end time
- `description`: Event description
- `location`: Event location
- `status`: Event status (confirmed/cancelled)
- `last_updated`: Last modification timestamp
- `first_seen_at`: Timestamp when event was first discovered (for suppression logic)
- `last_notified_at`: Timestamp of last notification sent (prevents duplicate notifications)

### WebhookChannel
- `channel_id`: Unique webhook channel ID
- `resource_id`: Google Calendar resource ID
- `calendar_id`: Associated calendar ID
- `expiration`: When the webhook expires
- `created_at`: Channel creation timestamp

### NotificationQueue
- `id`: Auto-incremented primary key
- `message`: Notification message content
- `calendar_name`: Source calendar name for topic routing
- `topic_id`: Telegram topic ID (optional)
- `status`: Queue status (pending/sent/failed)
- `retry_count`: Number of delivery attempts
- `created_at`: When notification was queued
- `sent_at`: When notification was successfully sent
- `event_id`: Associated calendar event ID

## 🔧 Technical Details

### Google Calendar API
- Uses OAuth2 authentication via Replit connector
- Read-only access to calendar data
- Push notification webhooks for real-time updates
- Webhook channels expire after 7 days (auto-renewed every 6 days)

### Webhook Flow
1. Google Calendar detects an event change
2. Google sends POST request to `/webhook/google-calendar`
3. Application fetches updated event details
4. Compares with stored event records to detect changes
5. Formats notification message and adds to queue
6. Background dispatcher sends queued messages at ~1 per 2 seconds
7. Updates database with latest event data and notification timestamps

### Rate Limiting Protection
The system includes multiple safeguards against Telegram flooding:

1. **Initial Sync Suppression**: On first calendar scan (or after app restart):
   - Past events are silently stored without notifications
   - Only future events trigger notifications on initial sync
   - Prevents notification floods when app restarts or is republished

2. **Queued Notification Dispatch**:
   - All notifications go through a queue table
   - Background dispatcher runs every 2 seconds
   - Processes one message per cycle (~1 msg/2 sec)
   - Respects Telegram's rate limits

3. **Telegram 429 Error Handling**:
   - Detects "Too Many Requests" responses
   - Parses `retry_after` value from error response
   - Automatically backs off and retries after the specified delay
   - Failed notifications remain in queue with incremented retry count

### Message Format
Notifications include:
- Event type (New/Updated/Deleted)
- Event title
- Start and end times
- Location (if specified)
- Description (if provided)
- Calendar name

## 📝 Important Lessons from Development

### Webhook vs Polling Decision
Initially, the system used polling (checking every 5 minutes). We switched to webhooks for:
- **Instant notifications**: No 5-minute delay
- **Reduced API calls**: Google notifies us instead of us checking repeatedly
- **Better efficiency**: No wasted API quota on empty checks

### Deployment Requirement
The biggest gotcha: **Webhooks require a deployed, always-on application**. Development Repls that sleep will miss webhook notifications. This was discovered after testing showed no notifications despite successful webhook setup.

### Rate Limiting Discovery
When the app restarts or is republished, it scans all calendar events (past 7 days + future 30 days). Without safeguards, this would send 800+ notifications in seconds, causing Telegram to block the bot. Solution:
- **Initial sync suppression**: Silently store past events, only notify for future events
- **Queue-based delivery**: Process notifications at ~1 per 2 seconds
- **429 error handling**: Automatically back off when Telegram rate limits kick in

### Calendar Limitations
Not all calendars support webhooks:
- Public calendars (like holiday calendars) typically don't support push notifications
- The application gracefully handles these and continues with supported calendars

### Topic Mapping Strategy
For Telegram supergroups with topics:
- Map calendar names to topic IDs via JSON configuration
- Allows organized notifications per calendar
- Falls back to main chat if no topic mapping exists

## 🔐 Security Notes

- All sensitive credentials are stored in environment variables
- Google OAuth tokens are managed by Replit connector
- Session data is encrypted with a secret key
- Database credentials are auto-managed by Replit's PostgreSQL integration

## 📦 Dependencies

Key Python packages:
- `Flask`: Web framework
- `Flask-SQLAlchemy`: ORM for database
- `APScheduler`: Background task scheduling (webhook renewal only)
- `google-auth`: Google authentication
- `google-api-python-client`: Google Calendar API
- `requests`: HTTP client for Telegram API
- `gunicorn`: Production WSGI server

## 🎯 Future Enhancements

Potential improvements:
- Event filtering by keywords or criteria
- Custom notification templates
- Multiple Telegram destinations per calendar
- Event reminder notifications before start time
- Web interface for viewing upcoming events

## 📄 License

This project is intended for personal/organizational use with Google Calendar and Telegram integration.

## 🤝 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review console logs for error messages
3. Verify Google Calendar connector is properly configured
4. Ensure the application is deployed (not just running in dev mode)
