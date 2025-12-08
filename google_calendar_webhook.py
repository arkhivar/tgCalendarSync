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
        # Debug: log all relevant environment variables
        print(f"🔍 Environment check:")
        print(f"   WEB_REPL_RENEWAL: {os.environ.get('WEB_REPL_RENEWAL', 'NOT SET')[:20] if os.environ.get('WEB_REPL_RENEWAL') else 'NOT SET'}")
        print(f"   REPL_IDENTITY: {os.environ.get('REPL_IDENTITY', 'NOT SET')[:20] if os.environ.get('REPL_IDENTITY') else 'NOT SET'}")
        print(f"   DATABASE_URL: {'SET' if os.environ.get('DATABASE_URL') else 'NOT SET'}")
        
        logger.info(f"🔍 Environment check:")
        logger.info(f"   WEB_REPL_RENEWAL: {os.environ.get('WEB_REPL_RENEWAL', 'NOT SET')[:20] if os.environ.get('WEB_REPL_RENEWAL') else 'NOT SET'}")
        logger.info(f"   REPL_IDENTITY: {os.environ.get('REPL_IDENTITY', 'NOT SET')[:20] if os.environ.get('REPL_IDENTITY') else 'NOT SET'}")
        logger.info(f"   DATABASE_URL: {'SET' if os.environ.get('DATABASE_URL') else 'NOT SET'}")

        # Use explicit production domain from environment variable
        production_domain = os.environ.get('PRODUCTION_DOMAIN', 'tg-calendar-sync-arkhivar.replit.app')
        
        # Always use the production domain for webhooks (Google requires stable HTTPS URL)
        webhook_url = f"https://{production_domain}/webhook/google-calendar"
        print(f"🚀 Using production domain for webhooks: {production_domain}")
        logger.info(f"🚀 Using production domain for webhooks: {production_domain}")

        # Log the exact URL being used
        print(f"📍 Using webhook URL: {webhook_url}")
        logger.info(f"📍 Using webhook URL: {webhook_url}")

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
            'expiration': expiration,
            'address': webhook_url # Store address for status reporting
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

def get_active_webhook_status():
    """
    Get status of all active webhook channels
    """
    status = []
    for cal_id, channel_info in active_channels.items():
        from datetime import datetime
        expiry = datetime.fromtimestamp(channel_info['expiration'] / 1000)
        status.append({
            'calendar_id': cal_id[:50],
            'channel_id': channel_info['id'],
            'resource_id': channel_info['resourceId'],
            'expiry': expiry.isoformat(),
            'webhook_url': channel_info.get('address', 'N/A')
        })
    return status

def setup_all_calendar_watches():
    """
    Set up watch channels for all calendars
    """
    logger.info(f"Setting up webhook channels for all calendars...")

    service = get_google_service()
    calendars = get_user_calendars(service)

    success_count = 0
    for calendar in calendars:
        try:
            calendar_id = calendar['id']
            create_watch_channel(service, calendar_id)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to set up webhook for calendar {calendar.get('id', 'unknown')}: {str(e)}")
            continue
    
    logger.info(f"✅ Set up {success_count} webhook channels out of {len(calendars)} calendars")
    return success_count

def get_google_service():
    """
    Get authenticated Google Calendar API service
    """
    try:
        access_token = get_access_token()
        credentials = GoogleCredentials(token=access_token)
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except Exception as e:
        logger.error(f"Failed to create Google Calendar service: {str(e)}")
        raise

def get_user_calendars(service):
    """
    Get list of user's calendars
    """
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        logger.info(f"Found {len(calendars)} calendars")
        return calendars
    except Exception as e:
        logger.error(f"Failed to get calendar list: {str(e)}")
        raise

def renew_expiring_channels():
    """
    Renew webhook channels that are about to expire (within 1 day)
    This should be run periodically (e.g., every 6 days)
    """
    from app import app
    
    with app.app_context():
        try:
            logger.info("Checking for expiring webhook channels...")
            current_time = datetime.utcnow().timestamp() * 1000
            
            channels_to_renew = []
            for cal_id, channel_info in active_channels.items():
                time_until_expiry = channel_info['expiration'] - current_time
                days_until_expiry = time_until_expiry / (1000 * 60 * 60 * 24)
                
                if days_until_expiry < 1:
                    channels_to_renew.append((cal_id, channel_info))
            
            if not channels_to_renew:
                logger.info("No webhook channels need renewal")
                return
            
            logger.info(f"Renewing {len(channels_to_renew)} expiring webhook channels...")
            
            service = get_google_service()
            
            for cal_id, old_channel in channels_to_renew:
                try:
                    # Stop the old channel
                    stop_watch_channel(service, old_channel['id'], old_channel['resourceId'])
                    
                    # Create a new channel
                    create_watch_channel(service, cal_id)
                    
                    logger.info(f"✅ Renewed webhook for calendar {cal_id[:40]}...")
                except Exception as e:
                    logger.error(f"Failed to renew webhook for calendar {cal_id}: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error in webhook renewal: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())