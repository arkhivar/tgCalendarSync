
"""
Google Calendar Push Notification (Webhook) Handler
Uses Google Calendar API's watch/push notification feature for near-instant updates
"""
import os
import logging
import uuid
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as GoogleCredentials
from models import CalendarSettings
from app import db
from google_connector import get_access_token

logger = logging.getLogger(__name__)

# Store active watch channels
active_channels = {}

def create_watch_channel(service, calendar_id='primary'):
    """
    Create a push notification channel for a calendar
    
    Args:
        service: Google Calendar API service
        calendar_id: ID of the calendar to watch
    
    Returns:
        dict: Channel information including id and resource_id
    """
    try:
        # Generate a unique channel ID
        channel_id = str(uuid.uuid4())
        
        # Get the webhook URL - must be HTTPS in production
        # Replit provides HTTPS by default
        repl_slug = os.environ.get('REPL_SLUG', 'calendar-monitor')
        repl_owner = os.environ.get('REPL_OWNER', 'user')
        webhook_url = f"https://{repl_slug}.{repl_owner}.repl.co/webhook/google-calendar"
        
        # Set expiration (max 1 week for calendar API)
        expiration = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
        
        logger.info(f"🔔 Setting up webhook for {calendar_id[:40]}...")
        logger.info(f"   Webhook URL: {webhook_url}")
        
        # Create the watch request
        watch_request = {
            'id': channel_id,
            'type': 'web_hook',
            'address': webhook_url,
            'expiration': expiration
        }
        
        # Execute the watch request
        channel = service.events().watch(
            calendarId=calendar_id,
            body=watch_request
        ).execute()
        
        expiry_date = datetime.fromtimestamp(expiration / 1000)
        logger.info(f"✅ Created watch channel for {calendar_id[:40]}... (expires {expiry_date})")
        
        # Store channel info
        active_channels[calendar_id] = {
            'id': channel['id'],
            'resourceId': channel['resourceId'],
            'expiration': expiration
        }
        
        return channel
        
    except Exception as e:
        logger.error(f"❌ Error creating watch channel for calendar {calendar_id}: {str(e)}")
        raise

def stop_watch_channel(service, channel_id, resource_id):
    """
    Stop a push notification channel
    
    Args:
        service: Google Calendar API service
        channel_id: ID of the channel to stop
        resource_id: Resource ID of the channel
    """
    try:
        service.channels().stop(body={
            'id': channel_id,
            'resourceId': resource_id
        }).execute()
        
        logger.info(f"Stopped watch channel {channel_id}")
        
    except Exception as e:
        logger.error(f"Error stopping watch channel {channel_id}: {str(e)}")

def setup_all_calendar_watches():
    """
    Set up push notification channels for all calendars
    """
    try:
        from calendar_monitor import get_google_service, get_user_calendars
        
        service = get_google_service()
        calendars = get_user_calendars(service)
        
        for calendar in calendars:
            cal_id = calendar.get('id')
            try:
                create_watch_channel(service, cal_id)
            except Exception as e:
                logger.error(f"Failed to create watch for calendar {cal_id}: {str(e)}")
        
        logger.info(f"Set up watch channels for {len(calendars)} calendars")
        
    except Exception as e:
        logger.error(f"Error setting up calendar watches: {str(e)}")

def renew_expiring_channels():
    """
    Renew channels that are about to expire (within 24 hours)
    """
    try:
        from calendar_monitor import get_google_service
        
        service = get_google_service()
        current_time = int(datetime.utcnow().timestamp() * 1000)
        renewal_threshold = current_time + (24 * 60 * 60 * 1000)  # 24 hours
        
        for cal_id, channel_info in list(active_channels.items()):
            if channel_info['expiration'] < renewal_threshold:
                # Stop old channel
                try:
                    stop_watch_channel(service, channel_info['id'], channel_info['resourceId'])
                except:
                    pass
                
                # Create new channel
                try:
                    create_watch_channel(service, cal_id)
                    logger.info(f"Renewed watch channel for calendar {cal_id}")
                except Exception as e:
                    logger.error(f"Failed to renew watch for calendar {cal_id}: {str(e)}")
        
    except Exception as e:
        logger.error(f"Error renewing channels: {str(e)}")
