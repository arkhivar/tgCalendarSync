import os
import logging
from datetime import datetime
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
                
                # Send notifications for each change
                for change in changes:
                    message = change['message']
                    calendar_name = change.get('calendar_name', 'Unknown')
                    
                    # If using a supergroup, get the topic ID from mappings
                    topic_id = None
                    if settings.is_supergroup and topic_mappings:
                        from telegram_notifier import get_topic_id_from_mapping
                        topic_id = get_topic_id_from_mapping(topic_mappings, calendar_name)
                        if not topic_id:
                            logger.warning(f"No topic mapping found for calendar '{calendar_name}', sending to General")
                    
                    logger.info(f"Calendar change detected: {message[:50]}...")
                    
                    # Send the message
                    send_telegram_message(
                        settings.telegram_bot_token,
                        settings.chat_id,
                        message,
                        topic_id
                    )
                
            # Update the last check time (naive UTC)
            from datetime import timezone
            settings.last_check = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
                        
        except Exception as e:
            logger.error(f"Error in scheduled calendar check: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

# Routes definition
@app.route('/')
def index():
    settings = CalendarSettings.query.first()
    
    # Check if Google Calendar connector is configured
    from google_connector import get_access_token, get_user_email
    google_connected = False
    google_email = 'Not configured'
    
    try:
        get_access_token()
        google_connected = True
        google_email = get_user_email()
    except Exception as e:
        logger.debug(f"Google Calendar not connected: {str(e)}")
    
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
        
        # Reschedule the job with the new interval
        if scheduler.get_jobs():
            scheduler.remove_all_jobs()
        
        scheduler.add_job(scheduled_calendar_check, 'interval', minutes=check_interval)
        
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('index'))
    
    settings = CalendarSettings.query.first()
    return render_template('settings.html', settings=settings)



@app.route('/run-now')
def run_now():
    try:
        scheduled_calendar_check()
        flash('Calendar check executed!', 'success')
    except Exception as e:
        logger.error(f"Error during manual calendar check: {str(e)}")
        flash(f'Error during calendar check: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/setup-webhooks')
def setup_webhooks():
    """Manually set up Google Calendar webhooks"""
    try:
        from google_calendar_webhook import setup_all_calendar_watches
        setup_all_calendar_watches()
        flash('Google Calendar webhooks set up successfully! You should now receive near-instant notifications.', 'success')
    except Exception as e:
        logger.error(f"Error setting up webhooks: {str(e)}")
        flash(f'Error setting up webhooks: {str(e)}', 'danger')
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

@app.route('/webhook/google-calendar', methods=['POST'])
def google_calendar_webhook():
    """
    Webhook endpoint for Google Calendar push notifications
    """
    try:
        # Google sends notifications with specific headers
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_state = request.headers.get('X-Goog-Resource-State')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        
        # Log ALL headers for debugging
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
            logger.info("Received SYNC notification from Google Calendar (initial setup)")
            return "OK", 200
        
        if resource_state == 'exists':
            # Calendar has changes, trigger a check
            logger.info("⚡ CALENDAR CHANGE DETECTED via webhook! Triggering immediate check...")
            
            # Run calendar check in background to avoid blocking webhook response
            import threading
            thread = threading.Thread(target=scheduled_calendar_check)
            thread.daemon = True
            thread.start()
        else:
            logger.warning(f"Unknown resource state: {resource_state}")
        
        return "OK", 200
        
    except Exception as e:
        logger.error(f"Error processing Google Calendar webhook: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return "OK", 200  # Still return 200 to Google to avoid retries

# Initialize database tables and start scheduler
with app.app_context():
    try:
        # Handle database migration
        handle_db_migration()
        
        # Start the scheduler if settings exist
        settings = CalendarSettings.query.first()
        if settings and settings.check_interval:
            # Add polling job as fallback (less frequent now since we have webhooks)
            scheduler.add_job(scheduled_calendar_check, 'interval', minutes=settings.check_interval)
            
            # Add job to renew webhook channels daily
            from google_calendar_webhook import renew_expiring_channels
            scheduler.add_job(renew_expiring_channels, 'interval', hours=24)
            
            scheduler.start()
            logger.info(f"Scheduler started with interval of {settings.check_interval} minutes")
            
            # Set up Google Calendar webhooks for push notifications
            try:
                from google_calendar_webhook import setup_all_calendar_watches
                setup_all_calendar_watches()
                logger.info("Google Calendar push notifications configured")
            except Exception as e:
                logger.error(f"Failed to set up Google Calendar webhooks: {str(e)}")
                logger.info("Falling back to polling mode")
            
            # Register the shutdown function
            atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
