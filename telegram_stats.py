"""
Telegram bot statistics and command handling module
"""

import logging
from datetime import datetime, timedelta
from models import EventRecord, CalendarSettings
from sqlalchemy import func, desc

# Set up logging
logger = logging.getLogger(__name__)

def get_calendar_stats(days=30):
    """
    Get statistics about calendar changes over the specified time period
    
    Args:
        days (int): Number of days to look back for statistics
        
    Returns:
        dict: Dictionary with statistics about calendar changes
    """
    try:
        # Calculate the date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get all event records in the date range
        events = EventRecord.query.filter(
            EventRecord.last_updated >= start_date,
            EventRecord.last_updated <= end_date
        ).all()
        
        # Track stats
        total_events = len(events)
        changes_by_calendar = {}
        changes_by_email = {}
        most_active_day = {}
        
        # Process each event
        for event in events:
            # Track changes by calendar
            calendar_id = event.calendar_id
            calendar_name = "Primary" if calendar_id == "primary" else calendar_id
            
            if calendar_name not in changes_by_calendar:
                changes_by_calendar[calendar_name] = 0
            changes_by_calendar[calendar_name] += 1
            
            # Track changes by day
            day = event.last_updated.strftime('%Y-%m-%d')
            if day not in most_active_day:
                most_active_day[day] = 0
            most_active_day[day] += 1
        
        # Sort results
        changes_by_calendar = dict(sorted(changes_by_calendar.items(), key=lambda x: x[1], reverse=True))
        changes_by_email = dict(sorted(changes_by_email.items(), key=lambda x: x[1], reverse=True))
        most_active_day = dict(sorted(most_active_day.items(), key=lambda x: x[1], reverse=True))
        
        return {
            'total_events': total_events,
            'changes_by_calendar': changes_by_calendar,
            'most_active_day': most_active_day,
            'start_date': start_date,
            'end_date': end_date
        }
    except Exception as e:
        logger.error(f"Error getting calendar stats: {str(e)}")
        # Ensure we have default values for start_date and end_date
        end_date_default = datetime.utcnow()
        start_date_default = end_date_default - timedelta(days=days)
        
        return {
            'error': str(e),
            'total_events': 0,
            'changes_by_calendar': {},
            'most_active_day': {},
            'start_date': start_date_default,
            'end_date': end_date_default
        }

def format_stats_message(stats, days=30):
    """
    Format statistics as a Telegram message
    
    Args:
        stats (dict): Dictionary with statistics
        days (int): Number of days the stats cover
        
    Returns:
        str: Formatted message for Telegram
    """
    # Build the statistics message
    message = f"📊 *Calendar Statistics (Last {days} Days)*\n\n"
    
    # Total events
    message += f"*Total Events*: {stats['total_events']}\n\n"
    
    # Most active calendars
    message += "*Most Active Calendars*:\n"
    if stats['changes_by_calendar']:
        for i, (calendar, count) in enumerate(list(stats['changes_by_calendar'].items())[:5]):
            message += f"{i+1}. {calendar}: {count} changes\n"
    else:
        message += "No calendar activity found\n"
    
    message += "\n"
    
    # Most active day
    message += "*Most Active Days*:\n"
    if stats['most_active_day']:
        for i, (day, count) in enumerate(list(stats['most_active_day'].items())[:3]):
            message += f"{i+1}. {day}: {count} changes\n"
    else:
        message += "No day activity found\n"
        
    return message

def handle_bot_mention(message_text):
    """
    Handle a bot mention in a Telegram message
    
    Args:
        message_text (str): The message text that includes the bot mention
        
    Returns:
        str or None: Response message if a command is recognized, None otherwise
    """
    # Ignore if there's no message text
    if not message_text:
        return None
        
    # Check for stats command
    if "stats" in message_text.lower():
        # Default to 30 days
        days = 30
        
        # Check if a specific number of days was requested
        words = message_text.lower().split()
        for i, word in enumerate(words):
            if word == "stats" and i+1 < len(words):
                try:
                    requested_days = int(words[i+1])
                    if 1 <= requested_days <= 365:  # Limit to 365 days
                        days = requested_days
                except:
                    pass
                    
        # Get and format stats
        stats = get_calendar_stats(days)
        return format_stats_message(stats, days)
        
    # Check for help command
    elif "help" in message_text.lower():
        return (
            "🤖 *CalendaringBot Commands*\n\n"
            "@calendaringBot stats - Show calendar statistics for the last 30 days\n"
            "@calendaringBot stats [days] - Show statistics for the specified number of days\n"
            "@calendaringBot help - Show this help message"
        )
        
    # No recognized command
    return None

# Function to process incoming webhook update from Telegram
def process_telegram_update(update):
    """
    Process an incoming update from Telegram
    
    Args:
        update (dict): The update from Telegram webhook
        
    Returns:
        dict or None: Response to send back to Telegram, or None if no response
    """
    try:
        # Add detailed debug logging
        print(f"DEBUG: process_telegram_update received update: {update}")
        
        # Check if this is a message
        if 'message' not in update:
            print("DEBUG: No message in update")
            return None
            
        message = update['message']
        print(f"DEBUG: Message content: {message}")
        
        # Check if message has text
        if 'text' not in message:
            print("DEBUG: No text in message")
            return None
            
        # Get message text and check if it mentions the bot
        message_text = message['text']
        print(f"DEBUG: Message text: {message_text}")
        
        settings = CalendarSettings.query.first()
        
        if not settings or not settings.telegram_bot_token:
            print("DEBUG: No bot token configured")
            return None
            
        # Get bot username if not set
        bot_username = "calendaringBot"  # Default fallback
        print(f"DEBUG: Using bot username: {bot_username}")
            
        # Check if the message mentions the bot
        if f"@{bot_username}" in message_text:
            print(f"DEBUG: Bot mentioned in: {message_text}")
            
            # Handle the mention
            response_text = handle_bot_mention(message_text)
            print(f"DEBUG: Response from handle_bot_mention: {response_text}")
            
            # If there's a response, send it back to the same chat
            if response_text:
                response = {
                    'chat_id': message['chat']['id'],
                    'text': response_text,
                    'parse_mode': 'Markdown'
                }
                print(f"DEBUG: Returning response: {response}")
                return response
        else:
            print(f"DEBUG: Bot not mentioned in message")
                
        return None
            
    except Exception as e:
        logger.error(f"Error processing Telegram update: {str(e)}")
        return None