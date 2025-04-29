import logging
import json
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

def format_datetime(dt):
    """
    Format a datetime object for display
    """
    if not dt:
        return "N/A"
    
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.error(f"Error formatting datetime: {str(e)}")
        return "Invalid date"

def is_json_valid(json_str):
    """
    Check if a string is valid JSON
    """
    try:
        json.loads(json_str)
        return True
    except:
        return False

def parse_telegram_chat_id(chat_id_str):
    """
    Parse and validate a Telegram chat ID
    """
    try:
        # Remove any whitespace
        chat_id_str = chat_id_str.strip()
        
        # Try to convert to integer (personal chat IDs are usually numeric)
        try:
            return str(int(chat_id_str))
        except ValueError:
            # If not numeric, it might be a channel name
            if chat_id_str.startswith('@'):
                return chat_id_str
            else:
                return '@' + chat_id_str
    except Exception as e:
        logger.error(f"Error parsing Telegram chat ID: {str(e)}")
        return None
