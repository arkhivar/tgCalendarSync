import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

MIN_SEND_INTERVAL = 1.5  # Seconds between messages to stay under Telegram limits
MAX_RETRY_COUNT = 5  # Max retries before marking as failed

def enqueue_notification(event_id, calendar_id, calendar_name, message, topic_id=None):
    """Add a notification to the queue instead of sending immediately"""
    from app import db
    from models import NotificationQueue
    
    try:
        notification = NotificationQueue(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            message=message,
            topic_id=topic_id,
            status='pending',
            created_at=datetime.utcnow(),
            next_attempt_at=datetime.utcnow(),
            attempt_count=0
        )
        db.session.add(notification)
        db.session.commit()
        logger.info(f"Queued notification for event {event_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to queue notification: {str(e)}")
        db.session.rollback()
        return False

def process_notification_queue():
    """Process pending notifications from the queue with rate limiting"""
    from app import db, app
    from models import NotificationQueue, CalendarSettings
    from telegram_notifier import send_telegram_message
    
    with app.app_context():
        try:
            settings = CalendarSettings.query.first()
            if not settings or not settings.telegram_bot_token or not settings.chat_id:
                return
            
            now = datetime.utcnow()
            
            pending = NotificationQueue.query.filter(
                NotificationQueue.status == 'pending',
                NotificationQueue.next_attempt_at <= now
            ).order_by(NotificationQueue.created_at.asc()).limit(1).first()
            
            if not pending:
                return
            
            pending.status = 'sending'
            pending.attempt_count += 1
            db.session.commit()
            
            result = send_telegram_message(
                settings.telegram_bot_token,
                settings.chat_id,
                pending.message,
                pending.topic_id
            )
            
            if result.success:
                pending.status = 'sent'
                logger.info(f"Successfully sent queued notification {pending.id}")
            elif result.retry_after:
                retry_delay = result.retry_after + 5
                pending.next_attempt_at = now + timedelta(seconds=retry_delay)
                pending.status = 'pending'
                pending.last_error = result.error_message
                logger.warning(f"Notification {pending.id} rate limited, retry in {retry_delay}s")
                
                if pending.attempt_count >= MAX_RETRY_COUNT:
                    pending.status = 'failed'
                    logger.error(f"Notification {pending.id} failed after {MAX_RETRY_COUNT} attempts")
            else:
                if pending.attempt_count >= MAX_RETRY_COUNT:
                    pending.status = 'failed'
                    pending.last_error = result.error_message
                    logger.error(f"Notification {pending.id} failed: {result.error_message}")
                else:
                    pending.next_attempt_at = now + timedelta(seconds=30)
                    pending.status = 'pending'
                    pending.last_error = result.error_message
            
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error processing notification queue: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                db.session.rollback()
            except:
                pass

def get_queue_stats():
    """Get statistics about the notification queue"""
    from app import db
    from models import NotificationQueue
    
    try:
        pending_count = NotificationQueue.query.filter_by(status='pending').count()
        sending_count = NotificationQueue.query.filter_by(status='sending').count()
        sent_count = NotificationQueue.query.filter_by(status='sent').count()
        failed_count = NotificationQueue.query.filter_by(status='failed').count()
        
        return {
            'pending': pending_count,
            'sending': sending_count,
            'sent': sent_count,
            'failed': failed_count,
            'total': pending_count + sending_count + sent_count + failed_count
        }
    except Exception as e:
        logger.error(f"Error getting queue stats: {str(e)}")
        return {'pending': 0, 'sending': 0, 'sent': 0, 'failed': 0, 'total': 0}

def should_notify_event(event_id, calendar_id, is_past_event, settings):
    """
    Determine if we should send a notification for this event
    
    Args:
        event_id: The Google Calendar event ID
        calendar_id: The calendar ID
        is_past_event: Whether the event's start time is in the past
        settings: CalendarSettings object
    
    Returns:
        bool: True if we should notify, False to silently store
    """
    from models import EventRecord
    
    if not settings.initial_sync_complete:
        existing = EventRecord.query.filter_by(event_id=event_id, calendar_id=calendar_id).first()
        if not existing and is_past_event:
            logger.debug(f"Suppressing notification for past event {event_id} during initial sync")
            return False
    
    return True

def mark_initial_sync_complete():
    """Mark initial sync as complete so future past events will generate notifications"""
    from app import db
    from models import CalendarSettings
    
    try:
        settings = CalendarSettings.query.first()
        if settings and not settings.initial_sync_complete:
            settings.initial_sync_complete = True
            settings.initial_sync_cutoff = datetime.utcnow()
            db.session.commit()
            logger.info("Initial sync marked as complete. Future changes will generate notifications.")
            return True
    except Exception as e:
        logger.error(f"Error marking initial sync complete: {str(e)}")
    return False
