import logging
import requests
from urllib.parse import quote

# Set up logging
logger = logging.getLogger(__name__)

def send_telegram_message(bot_token, chat_id, message):
    """
    Send a message to a Telegram chat
    
    Args:
        bot_token (str): The Telegram bot token
        chat_id (str): The chat ID to send the message to
        message (str): The message to send
    
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    try:
        if not bot_token or not chat_id:
            logger.error("Missing bot token or chat ID")
            return False
        
        # URL encode the message
        encoded_message = quote(message)
        
        # Set up the API URL
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded_message}&parse_mode=Markdown"
        
        # Send the request
        response = requests.get(url)
        
        # Check if request was successful
        if response.status_code == 200:
            logger.info(f"Message sent to Telegram: {message[:50]}...")
            return True
        else:
            logger.error(f"Failed to send Telegram message. Status code: {response.status_code}, Response: {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        return False
