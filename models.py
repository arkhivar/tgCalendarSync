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

    def __repr__(self):
        return f'<EventRecord {self.event_id}>'