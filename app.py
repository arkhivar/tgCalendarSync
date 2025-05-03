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
        
        # Check if we need to create tables from scratch
        if not inspector.has_table("calendar_settings"):
            logger.info("Creating new database schema")
            
            # Import models after initializing app
            from models import CalendarSettings, UserCalendar, EventRecord
            db.create_all()
            
            return
            
        # Check for existing tables to handle migration
        if inspector.has_table("calendar_settings"):
            # Check if we need to migrate from old schema to new schema
            columns = [col["name"] for col in inspector.get_columns("calendar_settings")]
            
            if "google_credentials" in columns and "is_supergroup" not in columns:
                logger.info("Migrating database schema from old to new")
                
                # Get old data
                conn = db.engine.connect()
                old_settings = list(conn.execute(sa.text("SELECT * FROM calendar_settings")).fetchall())
                
                # If we have old data, we'll migrate it
                if old_settings:
                    old_data = old_settings[0]
                    
                    # Drop existing tables
                    conn.execute(sa.text("DROP TABLE IF EXISTS event_record"))
                    conn.execute(sa.text("DROP TABLE IF EXISTS calendar_settings"))
                    conn.commit()
                    
                    # Import models and create new tables
                    from models import CalendarSettings, UserCalendar, EventRecord
                    db.create_all()
                    
                    # Create new settings
                    new_settings = CalendarSettings(
                        telegram_bot_token=old_data.telegram_bot_token,
                        chat_id=old_data.chat_id,
                        is_supergroup=False,  # Default to False for migrated data
                        check_interval=old_data.check_interval,
                        last_check=old_data.last_check if hasattr(old_data, 'last_check') else datetime.utcnow()
                    )
                    db.session.add(new_settings)
                    
                    # Create default user calendar with the old credentials
                    if hasattr(old_data, 'google_credentials') and old_data.google_credentials:
                        # Try to extract email from credentials
                        email = "default@example.com"  # Default fallback
                        try:
                            creds = json.loads(old_data.google_credentials)
                            if 'client_email' in creds:
                                email = creds['client_email']
                            elif 'email' in creds:
                                email = creds['email']
                        except:
                            pass
                            
                        user_calendar = UserCalendar(
                            email=email,
                            topic_name="General",  # Default topic
                            google_credentials=old_data.google_credentials,
                            calendar_id=old_data.calendar_id if hasattr(old_data, 'calendar_id') else 'primary',
                            last_check=old_data.last_check if hasattr(old_data, 'last_check') else datetime.utcnow()
                        )
                        db.session.add(user_calendar)
                    
                    db.session.commit()
                    logger.info("Migration completed successfully")
                else:
                    # No data to migrate, just create new tables
                    from models import CalendarSettings, UserCalendar, EventRecord
                    conn.execute(sa.text("DROP TABLE IF EXISTS calendar_settings"))
                    conn.execute(sa.text("DROP TABLE IF EXISTS event_record"))
                    conn.commit()
                    db.create_all()
            else:
                # Already migrated or new schema
                from models import CalendarSettings, UserCalendar, EventRecord
                
                # Ensure all tables exist
                db.create_all()
        else:
            # Fresh install
            from models import CalendarSettings, UserCalendar, EventRecord
            db.create_all()

# Import here after initializing app to avoid circular imports
from models import CalendarSettings, UserCalendar, EventRecord  
from calendar_monitor import check_calendar_changes
from telegram_notifier import send_telegram_message, create_topic_if_not_exists

# Create a function to check for calendar changes
def scheduled_calendar_check():
    with app.app_context():
        try:
            settings = CalendarSettings.query.first()
            if not settings or not settings.telegram_bot_token or not settings.chat_id:
                logger.warning("Settings not configured, skipping calendar check")
                return
                
            # Get all active user calendars
            user_calendars = UserCalendar.query.filter_by(is_active=True).all()
            if not user_calendars:
                logger.warning("No active user calendars found, skipping calendar check")
                return
                
            logger.info(f"Running scheduled calendar check for {len(user_calendars)} user(s)")
            
            for user_calendar in user_calendars:
                if not user_calendar.google_credentials:
                    logger.warning(f"No Google credentials for user {user_calendar.email}, skipping")
                    continue
                    
                # Check for calendar changes for this user
                changes = check_calendar_changes(
                    user_calendar.google_credentials,
                    user_calendar.calendar_id,
                    user_calendar.id
                )
                
                if changes:
                    # Determine the topic name to use
                    topic_name = None
                    if settings.is_supergroup and user_calendar.topic_name:
                        topic_name = user_calendar.topic_name
                        
                        # Make sure the topic exists
                        create_topic_if_not_exists(
                            settings.telegram_bot_token, 
                            settings.chat_id, 
                            topic_name
                        )
                    
                    # Send notifications for each change
                    for change in changes:
                        message = change['message']
                        
                        # If using a supergroup but no topic was specified for this user,
                        # prefix the message with the user's email
                        if settings.is_supergroup and not topic_name:
                            prefix = user_calendar.email.split('@')[0]
                            message = f"[{prefix}] {message}"
                        
                        logger.info(f"Calendar change detected for {user_calendar.email}: {message[:50]}...")
                        
                        # Send the message
                        send_telegram_message(
                            settings.telegram_bot_token,
                            settings.chat_id,
                            message,
                            topic_name
                        )
                        
                # Update the last check time
                user_calendar.last_check = datetime.utcnow()
                db.session.commit()
                        
        except Exception as e:
            logger.error(f"Error in scheduled calendar check: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

# Routes definition
@app.route('/')
def index():
    settings = CalendarSettings.query.first()
    user_calendars = UserCalendar.query.all()
    
    is_configured = (settings is not None and 
                    settings.telegram_bot_token and 
                    settings.chat_id and 
                    len(user_calendars) > 0 and 
                    any(cal.google_credentials for cal in user_calendars))
                    
    return render_template(
        'index.html', 
        is_configured=is_configured,
        settings=settings,
        user_calendars=user_calendars
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        telegram_bot_token = request.form.get('telegram_bot_token')
        chat_id = request.form.get('chat_id')
        is_supergroup = 'is_supergroup' in request.form
        check_interval = int(request.form.get('check_interval', 15))
        
        settings = CalendarSettings.query.first()
        
        if not settings:
            settings = CalendarSettings(
                telegram_bot_token=telegram_bot_token,
                chat_id=chat_id,
                is_supergroup=is_supergroup,
                check_interval=check_interval,
                last_check=datetime.utcnow()
            )
            db.session.add(settings)
        else:
            settings.telegram_bot_token = telegram_bot_token
            settings.chat_id = chat_id
            settings.is_supergroup = is_supergroup
            settings.check_interval = check_interval
        
        db.session.commit()
        
        # Reschedule the job with the new interval
        if scheduler.get_jobs():
            scheduler.remove_all_jobs()
        
        scheduler.add_job(scheduled_calendar_check, 'interval', minutes=check_interval)
        
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('index'))
    
    settings = CalendarSettings.query.first()
    return render_template('settings.html', settings=settings)

@app.route('/calendar/<int:user_id>', methods=['GET', 'POST'])
def edit_user_calendar(user_id):
    user_calendar = UserCalendar.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user_calendar.email = request.form.get('email')
        user_calendar.topic_name = request.form.get('topic_name')
        user_calendar.google_credentials = request.form.get('google_credentials')
        
        # Handle calendar ID selection
        calendar_id = request.form.get('calendar_id')
        if calendar_id == 'primary' or calendar_id == 'all':
            user_calendar.calendar_id = calendar_id
        else:
            # Check for custom calendar ID
            custom_calendar_id = request.form.get('custom_calendar_id')
            if custom_calendar_id and custom_calendar_id.strip():
                user_calendar.calendar_id = custom_calendar_id.strip()
            else:
                user_calendar.calendar_id = 'primary'  # Default if no valid selection
        
        user_calendar.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Calendar settings updated successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('user_calendar.html', user_calendar=user_calendar)

@app.route('/calendar/new', methods=['GET', 'POST'])
def new_user_calendar():
    if request.method == 'POST':
        # Handle calendar ID selection
        calendar_id = request.form.get('calendar_id')
        if calendar_id == 'primary' or calendar_id == 'all':
            final_calendar_id = calendar_id
        else:
            # Check for custom calendar ID
            custom_calendar_id = request.form.get('custom_calendar_id')
            if custom_calendar_id and custom_calendar_id.strip():
                final_calendar_id = custom_calendar_id.strip()
            else:
                final_calendar_id = 'primary'  # Default if no valid selection
        
        user_calendar = UserCalendar(
            email=request.form.get('email'),
            topic_name=request.form.get('topic_name'),
            google_credentials=request.form.get('google_credentials'),
            calendar_id=final_calendar_id,
            is_active=True,
            last_check=datetime.utcnow()
        )
        
        db.session.add(user_calendar)
        db.session.commit()
        
        flash('New calendar added successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('user_calendar.html', user_calendar=None)

@app.route('/calendar/delete/<int:user_id>', methods=['POST'])
def delete_user_calendar(user_id):
    user_calendar = UserCalendar.query.get_or_404(user_id)
    
    # Delete associated events first
    EventRecord.query.filter_by(user_calendar_id=user_id).delete()
    
    # Then delete the user calendar
    db.session.delete(user_calendar)
    db.session.commit()
    
    flash('Calendar deleted successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/run-now')
def run_now():
    scheduled_calendar_check()
    flash('Calendar check executed!', 'success')
    return redirect(url_for('index'))

# Initialize database tables and start scheduler
with app.app_context():
    try:
        # Handle database migration
        handle_db_migration()
        
        # Start the scheduler if settings exist
        settings = CalendarSettings.query.first()
        if settings and settings.check_interval:
            scheduler.add_job(scheduled_calendar_check, 'interval', minutes=settings.check_interval)
            scheduler.start()
            logger.info(f"Scheduler started with interval of {settings.check_interval} minutes")
            
            # Register the shutdown function
            atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
