import logging
import requests
import json
from urllib.parse import quote

# Set up logging
logger = logging.getLogger(__name__)

def send_telegram_message(bot_token, chat_id, message, topic_name=None, parse_mode="Markdown"):
    """
    Send a message to a Telegram chat or supergroup with optional topic
    
    Args:
        bot_token (str): The Telegram bot token
        chat_id (str): The chat ID to send the message to
        message (str): The message to send
        topic_name (str, optional): The topic name for supergroups
        parse_mode (str, optional): The parse mode for the message (Markdown or HTML)
    
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    try:
        if not bot_token or not chat_id:
            logger.error("Missing bot token or chat ID")
            return False
        
        # URL encode the message
        encoded_message = quote(message)
        
        # Base API URL
        base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Parameters for the request
        params = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        # If topic name is provided, try to get the message thread ID
        if topic_name:
            thread_id = get_topic_id_by_name(bot_token, chat_id, topic_name)
            if thread_id:
                params["message_thread_id"] = thread_id
            else:
                logger.warning(f"Topic '{topic_name}' not found in chat {chat_id}. Sending without topic.")
        
        # Send the request
        response = requests.post(base_url, json=params)
        
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

def get_topic_id_by_name(bot_token, chat_id, topic_name):
    """
    Get the message thread ID for a topic in a supergroup by its name
    
    Args:
        bot_token (str): The Telegram bot token
        chat_id (str): The supergroup chat ID
        topic_name (str): The name of the topic to find
        
    Returns:
        int or None: The message thread ID if found, None otherwise
    """
    try:
        # Get forum topics (topics in supergroup)
        url = f"https://api.telegram.org/bot{bot_token}/getForumTopicsByChat"
        params = {"chat_id": chat_id}
        
        response = requests.post(url, json=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") and "result" in data:
                topics = data["result"]
                
                # Find the topic with the matching name
                for topic in topics:
                    if topic.get("name") == topic_name:
                        return topic.get("message_thread_id")
                        
            # If we couldn't find the topic, log a warning
            logger.warning(f"Topic '{topic_name}' not found in supergroup {chat_id}")
            return None
        else:
            logger.error(f"Failed to get forum topics. Status code: {response.status_code}, Response: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting forum topics: {str(e)}")
        return None

def create_topic_if_not_exists(bot_token, chat_id, topic_name):
    """
    Create a new topic in a supergroup if it doesn't already exist
    
    Args:
        bot_token (str): The Telegram bot token
        chat_id (str): The supergroup chat ID
        topic_name (str): The name for the new topic
        
    Returns:
        int or None: The message thread ID of the created or existing topic
    """
    # Check if the topic already exists
    existing_thread_id = get_topic_id_by_name(bot_token, chat_id, topic_name)
    if existing_thread_id:
        return existing_thread_id
        
    # Create a new topic
    try:
        url = f"https://api.telegram.org/bot{bot_token}/createForumTopic"
        params = {
            "chat_id": chat_id,
            "name": topic_name
        }
        
        response = requests.post(url, json=params)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") and "result" in data:
                thread_id = data["result"].get("message_thread_id")
                logger.info(f"Created new topic '{topic_name}' with thread ID {thread_id}")
                return thread_id
        
        logger.error(f"Failed to create topic. Status code: {response.status_code}, Response: {response.text}")
        return None
        
    except Exception as e:
        logger.error(f"Error creating forum topic: {str(e)}")
        return None
