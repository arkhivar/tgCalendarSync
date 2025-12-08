from datetime import datetime
from app import db

class CalendarSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_bot_token = db.Column(db.String(255))
    chat_id = db.Column(db.String(255))
    is_supergroup = db.Column(db.Boolean, default=False)
    check_interval = db.Column(db.Integer, default=15)  # In minutes
    last_check = db.Column(db.DateTime, default=datetime.utcnow)
    topic_mappings = db.Column(db.Text)  # JSON string mapping calendar names to topic IDs
    initial_sync_complete = db.Column(db.Boolean, default=False)  # Track if initial sync is done
    initial_sync_cutoff = db.Column(db.DateTime)  # When initial sync started (events before this are silently stored)

class EventRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(200), nullable=False)
    calendar_id = db.Column(db.String(200), default='primary')  # Track which calendar this event is from
    summary = db.Column(db.String(200))
    description = db.Column(db.Text)
    location = db.Column(db.String(200))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    last_updated = db.Column(db.DateTime)
    status = db.Column(db.String(50))
    calendar_name = db.Column(db.String(200))  # Store the display name of the calendar
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)  # When we first discovered this event
    last_notified_at = db.Column(db.DateTime)  # Last time we sent a notification for this event

    def __repr__(self):
        return f'<EventRecord {self.event_id}>'

class NotificationQueue(db.Model):
    """Queue for rate-limited Telegram notifications"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(200), nullable=False)
    calendar_id = db.Column(db.String(200))
    calendar_name = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    topic_id = db.Column(db.Integer)
    status = db.Column(db.String(50), default='pending')  # pending, sending, sent, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    next_attempt_at = db.Column(db.DateTime, default=datetime.utcnow)
    attempt_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    
    def __repr__(self):
        return f'<NotificationQueue {self.id} - {self.status}>'