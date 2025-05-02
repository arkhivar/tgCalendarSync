from datetime import datetime
from app import db

class CalendarSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_bot_token = db.Column(db.String(100))
    chat_id = db.Column(db.String(50))
    is_supergroup = db.Column(db.Boolean, default=False)
    check_interval = db.Column(db.Integer, default=15)  # In minutes
    last_check = db.Column(db.DateTime, default=datetime.utcnow)

class UserCalendar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)  # User's email/Gmail address
    display_name = db.Column(db.String(100))  # For display purposes (initials/name)
    topic_name = db.Column(db.String(100))  # Topic name in Telegram supergroup
    google_credentials = db.Column(db.Text)
    calendar_id = db.Column(db.String(200), default='primary')
    last_check = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<UserCalendar {self.email}>'

class EventRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(200), nullable=False)
    user_calendar_id = db.Column(db.Integer, db.ForeignKey('user_calendar.id'), nullable=False)
    summary = db.Column(db.String(255))
    description = db.Column(db.Text)
    location = db.Column(db.String(255))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50))  # confirmed, tentative, cancelled
    
    # Relationship to user_calendar
    user_calendar = db.relationship('UserCalendar', backref=db.backref('events', lazy=True))
    
    # Composite unique constraint for event_id and user_calendar_id
    __table_args__ = (
        db.UniqueConstraint('event_id', 'user_calendar_id', name='_event_user_calendar_uc'),
    )
    
    def __repr__(self):
        return f'<Event {self.summary}>'
