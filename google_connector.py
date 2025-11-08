"""
Helper module to interact with Replit's Google Calendar connector
"""
import os
import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cache for the access token
_token_cache: Dict[str, Any] = {
    'access_token': None,
    'expires_at': None
}

def get_access_token():
    """
    Get a valid access token from the Replit Google Calendar connector.
    Handles token caching and refresh automatically.
    
    Returns:
        str: Valid access token for Google Calendar API
    """
    # Check if we have a cached token that's still valid
    if _token_cache['access_token'] and _token_cache['expires_at']:
        if datetime.now().timestamp() < _token_cache['expires_at']:
            return _token_cache['access_token']
    
    # Get the Replit connector hostname
    hostname = os.environ.get('REPLIT_CONNECTORS_HOSTNAME')
    
    # Get the authentication token for Replit API
    x_replit_token = None
    repl_identity = os.environ.get('REPL_IDENTITY')
    web_repl_renewal = os.environ.get('WEB_REPL_RENEWAL')
    
    if repl_identity:
        x_replit_token = 'repl ' + repl_identity
    elif web_repl_renewal:
        x_replit_token = 'depl ' + web_repl_renewal
    
    if not x_replit_token:
        raise ValueError('X_REPLIT_TOKEN not found for repl/depl')
    
    if not hostname:
        raise ValueError('REPLIT_CONNECTORS_HOSTNAME not found')
    
    # Fetch connection settings from Replit API
    url = f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=google-calendar'
    headers = {
        'Accept': 'application/json',
        'X_REPLIT_TOKEN': x_replit_token
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        items = data.get('items', [])
        
        if not items:
            raise ValueError('Google Calendar not connected')
        
        connection_settings = items[0]
        
        # Extract access token from the response
        access_token = (
            connection_settings.get('settings', {}).get('access_token') or
            connection_settings.get('settings', {}).get('oauth', {}).get('credentials', {}).get('access_token')
        )
        
        if not access_token:
            raise ValueError('Access token not found in connection settings')
        
        # Cache the token with expiration
        expires_at = connection_settings.get('settings', {}).get('expires_at')
        if expires_at:
            # Parse the expires_at timestamp
            expires_timestamp = datetime.fromisoformat(expires_at.replace('Z', '+00:00')).timestamp()
            _token_cache['expires_at'] = expires_timestamp
        
        _token_cache['access_token'] = access_token
        
        logger.info("Successfully obtained access token from Replit connector")
        return access_token
        
    except requests.RequestException as e:
        logger.error(f"Error fetching access token from Replit API: {str(e)}")
        raise
    except (KeyError, ValueError) as e:
        logger.error(f"Error parsing connection settings: {str(e)}")
        raise

def get_user_email():
    """
    Get the email address of the connected Google account
    
    Returns:
        str: Email address
    """
    hostname = os.environ.get('REPLIT_CONNECTORS_HOSTNAME')
    x_replit_token = None
    repl_identity = os.environ.get('REPL_IDENTITY')
    web_repl_renewal = os.environ.get('WEB_REPL_RENEWAL')
    
    if repl_identity:
        x_replit_token = 'repl ' + repl_identity
    elif web_repl_renewal:
        x_replit_token = 'depl ' + web_repl_renewal
    
    if not x_replit_token or not hostname:
        return 'Unknown'
    
    try:
        url = f'https://{hostname}/api/v2/connection?include_secrets=true&connector_names=google-calendar'
        headers = {
            'Accept': 'application/json',
            'X_REPLIT_TOKEN': x_replit_token
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        items = data.get('items', [])
        
        if items:
            return items[0].get('settings', {}).get('email', 'Unknown')
        
        return 'Unknown'
        
    except Exception as e:
        logger.error(f"Error getting user email: {str(e)}")
        return 'Unknown'
