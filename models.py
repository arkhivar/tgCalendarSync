from datetime import datetime
from app import db

class CalendarSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_credentials = db.Column(db.Text)
    telegram_bot_token = db.Column(db.String(100))
    chat_id = db.Column(db.String(50))
    calendar_id = db.Column(db.String(200), default='primary')
    check_interval = db.Column(db.Integer, default=15)  # In minutes
    last_check = db.Column(db.DateTime, default=datetime.utcnow)

class EventRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(200), unique=True, nullable=False)
    summary = db.Column(db.String(255))
    description = db.Column(db.Text)
    location = db.Column(db.String(255))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50))  # confirmed, tentative, cancelled
    
    def __repr__(self):
        return f'<Event {self.summary}>'
