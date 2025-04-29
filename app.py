import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

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
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///calendar_monitor.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the app with the SQLAlchemy extension
db.init_app(app)

# Import modules after initializing app to avoid circular imports
from models import CalendarSettings, EventRecord
from calendar_monitor import check_calendar_changes
from telegram_notifier import send_telegram_message

# Initialize the scheduler
scheduler = BackgroundScheduler()

# Create a function to check for calendar changes
def scheduled_calendar_check():
    with app.app_context():
        try:
            settings = CalendarSettings.query.first()
            if settings and settings.google_credentials and settings.telegram_bot_token and settings.chat_id:
                logger.info("Running scheduled calendar check")
                changes = check_calendar_changes(settings.google_credentials, 
                                                 settings.calendar_id)
                
                if changes:
                    for change in changes:
                        message = change['message']
                        logger.info(f"Calendar change detected: {message}")
                        send_telegram_message(settings.telegram_bot_token, 
                                              settings.chat_id, 
                                              message)
        except Exception as e:
            logger.error(f"Error in scheduled calendar check: {str(e)}")

# Routes definition
@app.route('/')
def index():
    settings = CalendarSettings.query.first()
    is_configured = settings is not None and settings.google_credentials and settings.telegram_bot_token
    return render_template('index.html', is_configured=is_configured)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        google_credentials = request.form.get('google_credentials')
        telegram_bot_token = request.form.get('telegram_bot_token')
        chat_id = request.form.get('chat_id')
        calendar_id = request.form.get('calendar_id', 'primary')
        check_interval = int(request.form.get('check_interval', 15))
        
        settings = CalendarSettings.query.first()
        
        if not settings:
            settings = CalendarSettings(
                google_credentials=google_credentials,
                telegram_bot_token=telegram_bot_token,
                chat_id=chat_id,
                calendar_id=calendar_id,
                check_interval=check_interval,
                last_check=datetime.utcnow()
            )
            db.session.add(settings)
        else:
            settings.google_credentials = google_credentials
            settings.telegram_bot_token = telegram_bot_token
            settings.chat_id = chat_id
            settings.calendar_id = calendar_id
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

@app.route('/run-now')
def run_now():
    scheduled_calendar_check()
    flash('Calendar check executed!', 'success')
    return redirect(url_for('index'))

# Initialize database tables and start scheduler when app context is ready
with app.app_context():
    db.create_all()
    
    # Start the scheduler if settings exist
    settings = CalendarSettings.query.first()
    if settings and settings.check_interval:
        scheduler.add_job(scheduled_calendar_check, 'interval', minutes=settings.check_interval)
        scheduler.start()
        logger.info(f"Scheduler started with interval of {settings.check_interval} minutes")
        
        # Register the shutdown function
        atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
