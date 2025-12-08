import logging
import requests
import json
from urllib.parse import quote

# Set up logging
logger = logging.getLogger(__name__)

class TelegramResult:
    """Structured result from Telegram API call"""
    def __init__(self, success, retry_after=None, error_message=None):
        self.success = success
        self.retry_after = retry_after  # Seconds to wait if rate limited
        self.error_message = error_message
    
    def __bool__(self):
        return self.success

def send_telegram_message(bot_token, chat_id, message, topic_id=None, parse_mode="Markdown"):
    """
    Send a message to a Telegram chat or supergroup with optional topic
    
    Args:
        bot_token (str): The Telegram bot token
        chat_id (str): The chat ID to send the message to
        message (str): The message to send
        topic_id (int, optional): The message thread ID for supergroup topics
        parse_mode (str, optional): The parse mode for the message (Markdown or HTML)
    
    Returns:
        TelegramResult: Structured result with success status and retry info
    """
    try:
        if not bot_token or not chat_id:
            logger.error("Missing bot token or chat ID")
            return TelegramResult(False, error_message="Missing bot token or chat ID")
        
        # Parameters for the request
        params = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        # If topic ID is provided, use it directly
        if topic_id:
            params["message_thread_id"] = int(topic_id)
            logger.info(f"Sending message to topic ID: {topic_id}")
        
        # Base API URL
        base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Send the request
        response = requests.post(base_url, json=params)
        
        # Check if request was successful
        if response.status_code == 200:
            logger.info(f"Message sent to Telegram: {message[:50]}...")
            return TelegramResult(True)
        elif response.status_code == 429:
            # Rate limited - parse retry_after
            try:
                error_data = response.json()
                retry_after = error_data.get('parameters', {}).get('retry_after', 30)
                logger.warning(f"Telegram rate limit hit. Retry after {retry_after} seconds")
                return TelegramResult(False, retry_after=retry_after, error_message="Rate limited")
            except:
                return TelegramResult(False, retry_after=30, error_message="Rate limited (unknown retry)")
        else:
            logger.error(f"Failed to send Telegram message. Status code: {response.status_code}, Response: {response.text}")
            return TelegramResult(False, error_message=f"HTTP {response.status_code}: {response.text[:100]}")
    
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        return TelegramResult(False, error_message=str(e))

def get_topic_id_from_mapping(topic_mappings, calendar_name):
    """
    Get the message thread ID for a calendar from the topic mappings
    
    Args:
        topic_mappings (dict): Dictionary mapping calendar names to topic IDs
        calendar_name (str): The name of the calendar
        
    Returns:
        int or None: The message thread ID if found, None otherwise
    """
    if not topic_mappings:
        return None
    
    # Try exact match first
    if calendar_name in topic_mappings:
        return topic_mappings[calendar_name]
    
    # Try case-insensitive match
    for cal_name, topic_id in topic_mappings.items():
        if cal_name.lower() == calendar_name.lower():
            return topic_id
    
    logger.warning(f"No topic mapping found for calendar '{calendar_name}'")
    return None


