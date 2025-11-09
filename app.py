import os
import logging
from datetime import datetime, timedelta
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Initialize logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Define base class for SQLAlchemy models
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy
db = SQLAlchemy(model_class=Base)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure database
# Use PostgreSQL database if DATABASE_URL is provided, otherwise fallback to SQLite
database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres"):
    # Ensure psycopg2 works properly with SQLAlchemy
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///calendar_monitor.db"
logger.info(f"Using database: {app.config['SQLALCHEMY_DATABASE_URI'].split('@')[0]}***")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the app with the SQLAlchemy extension
db.init_app(app)

# Initialize the scheduler
scheduler = BackgroundScheduler()

# Lazy initialization flag to defer expensive operations
_initialization_done = False
_initialization_lock = __import__('threading').Lock()

# Handle database migrations
def handle_db_migration():
    with app.app_context():
        inspector = sa.inspect(db.engine)
        
        # Check if we need to drop old UserCalendar table
        if inspector.has_table("user_calendar"):
            logger.info("Removing old user_calendar table")
            conn = db.engine.connect()
            conn.execute(sa.text("DROP TABLE IF EXISTS user_calendar CASCADE"))
            conn.commit()
        
        # Import models after initializing app
        from models import CalendarSettings, EventRecord
        
        # Create all tables
        db.create_all()
        
        # Check if topic_mappings column exists in calendar_settings
        if inspector.has_table("calendar_settings"):
            columns = [col['name'] for col in inspector.get_columns("calendar_settings")]
            if 'topic_mappings' not in columns:
                logger.info("Adding topic_mappings column to calendar_settings table")
                conn = db.engine.connect()
                conn.execute(sa.text("ALTER TABLE calendar_settings ADD COLUMN topic_mappings TEXT"))
                conn.commit()
                conn.close()
        
        # Check if calendar_name column exists in event_record
        if inspector.has_table("event_record"):
            columns = [col['name'] for col in inspector.get_columns("event_record")]
            if 'calendar_name' not in columns:
                logger.info("Adding calendar_name column to event_record table")
                conn = db.engine.connect()
                conn.execute(sa.text("ALTER TABLE event_record ADD COLUMN calendar_name VARCHAR(200)"))
                conn.commit()
                conn.close()
        
        logger.info("Database schema ready")

# Import here after initializing app to avoid circular imports
from models import CalendarSettings, EventRecord  
from calendar_monitor import check_calendar_changes
from telegram_notifier import send_telegram_message
from telegram_stats import process_telegram_update

# Create a function to check for calendar changes
def scheduled_calendar_check():
    with app.app_context():
        try:
            settings = CalendarSettings.query.first()
            if not settings or not settings.telegram_bot_token or not settings.chat_id:
                logger.warning("Settings not configured, skipping calendar check")
                return
            
            # Check if Google Calendar connector is configured
            from google_connector import get_access_token
            try:
                get_access_token()
            except Exception as e:
                logger.error(f"Google Calendar connector not configured: {str(e)}")
                return
                
            logger.info("Running scheduled calendar check")
            
            # Check for calendar changes using Replit connector
            changes = check_calendar_changes()
            
            if changes:
                # Parse topic mappings if they exist
                topic_mappings = {}
                if settings.topic_mappings:
                    try:
                        topic_mappings = json.loads(settings.topic_mappings)
                    except:
                        logger.error("Failed to parse topic mappings")
                
                # Limit number of messages to prevent overwhelming Telegram
                max_messages = 20
                if len(changes) > max_messages:
                    logger.warning(f"Found {len(changes)} changes, limiting to {max_messages} to avoid rate limits")
                    changes = changes[:max_messages]
                
                # Send notifications for each change with rate limiting
                import time
                for i, change in enumerate(changes):
                    message = change['message']
                    calendar_name = change.get('calendar_name', 'Unknown')
                    
                    # If using a supergroup, get the topic ID from mappings
                    topic_id = None
                    if settings.is_supergroup and topic_mappings:
                        from telegram_notifier import get_topic_id_from_mapping
                        topic_id = get_topic_id_from_mapping(topic_mappings, calendar_name)
                        if not topic_id:
                            logger.warning(f"No topic mapping found for calendar '{calendar_name}', sending to General")
                    
                    logger.info(f"Calendar change detected ({i+1}/{len(changes)}): {message[:50]}...")
                    
                    # Send the message
                    send_telegram_message(
                        settings.telegram_bot_token,
                        settings.chat_id,
                        message,
                        topic_id
                    )
                    
                    # Add small delay between messages to avoid rate limiting (Telegram limit is 30 msg/sec)
                    if i < len(changes) - 1:
                        time.sleep(0.1)
                
            # Update the last check time (naive UTC)
            from datetime import timezone
            settings.last_check = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
                        
        except Exception as e:
            logger.error(f"Error in scheduled calendar check: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

# Lazy initialization function
def ensure_initialization():
    """Ensure expensive operations have been initialized (runs once, lazily)"""
    global _initialization_done
    if _initialization_done:
        return
    
    with _initialization_lock:
        # Double-check inside lock to prevent race condition
        if _initialization_done:
            return
        
        try:
            with app.app_context():
                logger.info("Running lazy initialization...")
                
                # Handle database migration
                handle_db_migration()
                
                # Start the scheduler if settings exist
                settings = CalendarSettings.query.first()
                if settings and not scheduler.running:
                    # Only add job to renew webhook channels every 6 days (before 7-day expiration)
                    from google_calendar_webhook import renew_expiring_channels
                    scheduler.add_job(renew_expiring_channels, 'interval', days=6, id='webhook_renewal', replace_existing=True)
                    
                    scheduler.start()
                    logger.info("Scheduler started for webhook renewal only")
                    
                    # Set up Google Calendar webhooks for push notifications automatically
                    try:
                        from google_calendar_webhook import setup_all_calendar_watches
                        logger.info("Setting up Google Calendar webhooks automatically...")
                        setup_all_calendar_watches()
                        logger.info("✅ Google Calendar push notifications configured successfully")
                    except Exception as e:
                        logger.error(f"❌ Failed to set up Google Calendar webhooks: {str(e)}")
                    
                    # Register the shutdown function
                    def shutdown_scheduler():
                        if scheduler.running:
                            scheduler.shutdown()
                    atexit.register(shutdown_scheduler)
                
                _initialization_done = True
                logger.info("✅ Lazy initialization completed successfully")
        except Exception as e:
            logger.error(f"Error during lazy initialization: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

# Health check endpoint - returns immediately without database calls
@app.route('/health')
def health():
    """Lightweight health check for deployment - no database queries"""
    return {'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}, 200

# Routes definition
@app.route('/')
def index():
    # Trigger lazy initialization in background thread to avoid blocking
    import threading
    if not _initialization_done:
        init_thread = threading.Thread(target=lambda: ensure_initialization())
        init_thread.daemon = True
        init_thread.start()
    
    # Try to get settings but don't fail if database isn't ready
    settings = None
    google_connected = False
    google_email = 'Not configured'
    
    try:
        settings = CalendarSettings.query.first()
        
        # Check if Google Calendar connector is configured
        from google_connector import get_access_token, get_user_email
        try:
            get_access_token()
            google_connected = True
            google_email = get_user_email()
        except Exception as e:
            logger.debug(f"Google Calendar not connected: {str(e)}")
    except Exception as e:
        logger.warning(f"Database not ready yet: {str(e)}")
        # Database might not be ready during initial deployment
        # Return a basic page that will auto-refresh
    
    is_configured = (settings is not None and 
                    settings.telegram_bot_token and 
                    settings.chat_id and 
                    google_connected)
                    
    return render_template(
        'index.html', 
        is_configured=is_configured,
        settings=settings,
        google_connected=google_connected,
        google_email=google_email
    )

@app.route('/debug-env')
def debug_env():
    """Debug route to check Google Calendar connector environment variables"""
    google_vars = {k: ('***' if 'secret' in k.lower() or 'token' in k.lower() else v) 
                   for k, v in os.environ.items() 
                   if 'google' in k.lower() or 'calendar' in k.lower() or 'replit_db' in k.lower()}
    return f"<pre>{json.dumps(google_vars, indent=2)}</pre>"

@app.route('/webhook/test')
def test_webhook():
    """Test endpoint to verify webhook URL is accessible"""
    return {
        'status': 'ok',
        'message': 'Webhook endpoint is accessible',
        'url': request.url
    }, 200

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    # Ensure initialization has happened
    ensure_initialization()
    
    if request.method == 'POST':
        telegram_bot_token = request.form.get('telegram_bot_token')
        chat_id = request.form.get('chat_id')
        is_supergroup = 'is_supergroup' in request.form
        check_interval = int(request.form.get('check_interval', 15))
        topic_mappings = request.form.get('topic_mappings', '{}')
        
        # Validate topic mappings JSON
        try:
            json.loads(topic_mappings)
        except:
            flash('Invalid topic mappings JSON format', 'danger')
            return redirect(url_for('settings'))
        
        settings = CalendarSettings.query.first()
        
        if not settings:
            settings = CalendarSettings(
                telegram_bot_token=telegram_bot_token,
                chat_id=chat_id,
                is_supergroup=is_supergroup,
                check_interval=check_interval,
                topic_mappings=topic_mappings,
                last_check=datetime.utcnow()
            )
            db.session.add(settings)
        else:
            settings.telegram_bot_token = telegram_bot_token
            settings.chat_id = chat_id
            settings.is_supergroup = is_supergroup
            settings.check_interval = check_interval
            settings.topic_mappings = topic_mappings
        
        db.session.commit()
        
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('index'))
    
    settings = CalendarSettings.query.first()
    return render_template('settings.html', settings=settings)



@app.route('/run-now')
def run_now():
    # Ensure initialization has happened
    ensure_initialization()
    
    try:
        # Run in background thread to avoid blocking the request
        import threading
        thread = threading.Thread(target=scheduled_calendar_check)
        thread.daemon = True
        thread.start()
        flash('Calendar check started in background! Check Telegram for notifications.', 'success')
    except Exception as e:
        logger.error(f"Error starting calendar check: {str(e)}")
        flash(f'Error starting calendar check: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/debug-webhooks')
def debug_webhooks():
    """Debug route to check webhook status and manually trigger setup"""
    # Ensure initialization has happened
    ensure_initialization()
    
    try:
        from google_calendar_webhook import setup_all_calendar_watches, get_active_webhook_status
        
        # Get current status before setup
        current_status = get_active_webhook_status()
        
        # Show detailed webhook information
        import json
        status_html = "<h3>Current Webhook Status</h3><pre>" + json.dumps(current_status, indent=2) + "</pre>"
        status_html += f"<p><strong>Total active webhooks:</strong> {len(current_status)}</p>"
        status_html += f"<p><strong>Webhook endpoint:</strong> {request.url_root}webhook/google-calendar</p>"
        
        return status_html
    except Exception as e:
        logger.error(f"Error getting webhook status: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/test-webhook-post')
def test_webhook_post():
    """Test endpoint to simulate a Google Calendar webhook POST"""
    try:
        import requests
        webhook_url = f"{request.url_root}webhook/google-calendar"
        
        # Simulate a Google Calendar webhook notification
        headers = {
            'X-Goog-Channel-ID': 'test-channel-12345',
            'X-Goog-Resource-State': 'exists',
            'X-Goog-Resource-ID': 'test-resource-67890'
        }
        
        print("=" * 80)
        print(f"🧪 SIMULATING WEBHOOK POST to {webhook_url}")
        print(f"Headers: {headers}")
        print("=" * 80)
        
        response = requests.post(webhook_url, headers=headers)
        
        flash(f'Test webhook POST sent. Status: {response.status_code}. Check console for webhook processing logs.', 'info')
    except Exception as e:
        flash(f'Error testing webhook: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/test-calendar-check')
def test_calendar_check():
    """Manually trigger a calendar check to test the notification pipeline - only checks last hour"""
    try:
        print("=" * 80)
        print("🧪 MANUAL CALENDAR CHECK TRIGGERED (Last hour only)")
        print(f"Time: {datetime.utcnow()}")
        print("This will compare Google Calendar API data with database state")
        print("=" * 80)
        
        # Temporarily set last_check to 1 hour ago for this test
        settings = CalendarSettings.query.first()
        if settings:
            from datetime import timezone
            original_last_check = settings.last_check
            settings.last_check = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
            db.session.commit()
            
            # Run the calendar check
            import threading
            def test_check_with_restore():
                try:
                    scheduled_calendar_check()
                finally:
                    # Restore original last_check time
                    with app.app_context():
                        settings_restore = CalendarSettings.query.first()
                        if settings_restore:
                            settings_restore.last_check = original_last_check
                            db.session.commit()
            
            thread = threading.Thread(target=test_check_with_restore)
            thread.daemon = True
            thread.start()
            
            flash('Manual calendar check triggered for events from the last hour only! Check Telegram for messages.', 'info')
        else:
            flash('Settings not configured', 'warning')
    except Exception as e:
        logger.error(f"Error in manual calendar check: {str(e)}")
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """
    Webhook endpoint for Telegram to receive bot commands and mentions
    """
    # Set up console handler for direct output
    import sys
    import logging
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG)
    
    # Log the webhook call
    logger.info("============= TELEGRAM WEBHOOK CALLED =============")
    
    try:
        # Check that we have a valid request
        if not request.is_json:
            logger.warning("Invalid webhook request: not JSON")
            return "Bad Request", 400
            
        # Get the update from Telegram
        update = request.get_json()
        print(f"DEBUG: Received Telegram update: {update}")
        logger.info(f"Received Telegram update: {update}")
        
        # Process the update
        print(f"DEBUG: Processing update with process_telegram_update")
        response = process_telegram_update(update)
        print(f"DEBUG: Got response: {response}")
        
        # If there's a response, send it back to Telegram
        if response:
            settings = CalendarSettings.query.first()
            if not settings or not settings.telegram_bot_token:
                logger.warning("Cannot send response: no Telegram token configured")
                return "OK", 200
                
            # Send the response back to Telegram
            bot_token = settings.telegram_bot_token
            chat_id = response.get('chat_id')
            text = response.get('text')
            parse_mode = response.get('parse_mode', 'Markdown')
            
            if chat_id and text:
                send_telegram_message(bot_token, chat_id, text, None, parse_mode)
            
        return "OK", 200
        
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return "Internal Server Error", 500

@app.route('/webhook/google-calendar', methods=['GET', 'POST'])
def google_calendar_webhook():
    """
    Webhook endpoint for Google Calendar push notifications
    """
    import sys
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    
    # Handle GET requests (for testing accessibility)
    if request.method == 'GET':
        print("=" * 80)
        print(f"🧪 WEBHOOK GET REQUEST - Testing accessibility")
        print(f"URL: {request.url}")
        print(f"Time: {datetime.utcnow()}")
        print("=" * 80)
        return {
            'status': 'ok',
            'message': 'Google Calendar webhook endpoint is accessible',
            'url': request.url,
            'timestamp': datetime.utcnow().isoformat()
        }, 200
    
    # Enhanced logging for POST requests
    import sys
    print("\n" + "=" * 80, flush=True)
    print(f"🔔 WEBHOOK POST RECEIVED at {datetime.utcnow()}", flush=True)
    print(f"From IP: {request.remote_addr}", flush=True)
    print(f"User-Agent: {request.headers.get('User-Agent', 'N/A')}", flush=True)
    print("=" * 80, flush=True)
    sys.stdout.flush()
    
    try:
        # Google sends notifications with specific headers
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_state = request.headers.get('X-Goog-Resource-State')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        
        # Log ALL headers for debugging
        import sys
        print(f"📋 Channel ID: {channel_id}", flush=True)
        print(f"📋 Resource State: {resource_state}", flush=True)
        print(f"📋 Resource ID: {resource_id}", flush=True)
        print(f"📋 All Headers:", flush=True)
        for header, value in request.headers.items():
            print(f"   {header}: {value}", flush=True)
        print(f"📋 Request Body: {request.get_data(as_text=True) or '(empty)'}", flush=True)
        print("=" * 80 + "\n", flush=True)
        sys.stdout.flush()
        
        logger.info("=" * 50)
        logger.info(f"WEBHOOK RECEIVED - Google Calendar notification")
        logger.info(f"Channel ID: {channel_id}")
        logger.info(f"Resource State: {resource_state}")
        logger.info(f"Resource ID: {resource_id}")
        logger.info(f"All headers: {dict(request.headers)}")
        logger.info("=" * 50)
        
        # Respond immediately to Google
        # Process the actual change in the background
        if resource_state == 'sync':
            # This is just a verification sync, acknowledge it
            print("✅ SYNC notification (webhook setup confirmation)")
            logger.info("✅ SYNC notification (webhook setup confirmation)")
            return "OK", 200
        
        if resource_state == 'exists':
            # Calendar has changes, trigger a check
            print("🚀 CHANGE DETECTED! Starting notification pipeline...")
            logger.info("🚀 CHANGE DETECTED! Starting notification pipeline...")
            
            # Run calendar check in background to avoid blocking webhook response
            import threading
            thread = threading.Thread(target=scheduled_calendar_check)
            thread.daemon = True
            thread.start()
            print("✅ Background notification thread started")
            logger.info("✅ Background notification thread started")
        else:
            print(f"⚠️  Unknown resource state: {resource_state}")
            logger.warning(f"⚠️  Unknown resource state: {resource_state}")
        
        return "OK", 200
        
    except Exception as e:
        print(f"ERROR in webhook: {str(e)}")
        logger.error(f"Error processing Google Calendar webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        logger.error(traceback.format_exc())
        return "OK", 200  # Still return 200 to Google to avoid retries

# Create database tables if they don't exist (lightweight operation)
with app.app_context():
    try:
        # Only import models and create tables - no expensive operations
        from models import CalendarSettings, EventRecord
        db.create_all()
        logger.info("Database tables created (if not exists)")
    except Exception as e:
        logger.warning(f"Could not create database tables during startup: {str(e)}")
        # This is okay - tables will be created during lazy initialization

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
