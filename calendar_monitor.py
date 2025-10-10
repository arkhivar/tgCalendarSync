import os
import logging
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as GoogleCredentials
from models import EventRecord, CalendarSettings
from app import db
from google_connector import get_access_token, get_user_email

# Set up logging
logger = logging.getLogger(__name__)

# Google Calendar API scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_google_service():
    """
    Create and return a Google Calendar API service using Replit connector
    """
    try:
        # Get access token from the Replit connector
        access_token = get_access_token()
        
        # Create credentials object with just the access token
        # The connector handles refresh automatically
        credentials = GoogleCredentials(token=access_token)
        
        # Build the service
        service = build('calendar', 'v3', credentials=credentials)
        return service

    except Exception as e:
        logger.error(f"Error creating Google service: {str(e)}")
        raise

def get_user_calendars(service):
    """
    Retrieve all calendars available to the user
    """
    try:
        # Call the Calendar API to get all calendar lists
        calendar_list = service.calendarList().list().execute()

        return calendar_list.get('items', [])

    except Exception as e:
        logger.error(f"Error retrieving user calendars: {str(e)}")
        raise

def get_calendar_events(service, calendar_id='primary', time_min=None, time_max=None):
    """
    Retrieve events from the specified calendar
    """
    try:
        # Set default time range if not provided
        if not time_min:
            time_min = datetime.utcnow() - timedelta(days=7)
        if not time_max:
            time_max = datetime.utcnow() + timedelta(days=30)

        # Format times for API request
        time_min_rfc = time_min.isoformat() + 'Z'
        time_max_rfc = time_max.isoformat() + 'Z'

        # Call the Calendar API
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min_rfc,
            timeMax=time_max_rfc,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        # Get the calendar info to include calendar name in the events
        calendar_info = None
        try:
            calendar_info = service.calendars().get(calendarId=calendar_id).execute()
        except:
            # Handling in case we can't get calendar info
            pass

        # Add calendar name to each event
        events = events_result.get('items', [])
        calendar_name = calendar_info.get('summary', calendar_id) if calendar_info else calendar_id

        for event in events:
            event['calendarName'] = calendar_name

        return events

    except Exception as e:
        logger.error(f"Error retrieving calendar events for calendar {calendar_id}: {str(e)}")
        # Return empty list instead of raising, so we can continue with other calendars
        return []

def parse_event_datetime(event_time):
    """
    Parse Google Calendar event time to Python datetime
    """
    if 'dateTime' in event_time:
        # Handle datetime format
        return datetime.fromisoformat(event_time['dateTime'].replace('Z', '+00:00'))
    elif 'date' in event_time:
        # Handle all-day events
        return datetime.fromisoformat(event_time['date'])
    return None

def get_creator_info(event):
    """
    Extract creator information from an event
    """
    creator = {}

    # Check for creator info in the event
    if 'creator' in event:
        creator = event['creator']

    return creator.get('email', ''), creator.get('displayName', '')

def check_calendar_changes():
    """
    Check for changes in all calendars and return a list of changes

    Returns:
        list: A list of changes detected in the calendars
    """
    try:
        # Get Google Calendar service using Replit connector
        service = get_google_service()

        # List to store changes
        changes = []

        # Current time
        current_time = datetime.utcnow()

        # Primary account email from connector
        primary_email = get_user_email()

        # Get all calendars
        calendars = get_user_calendars(service)
        logger.info(f"Found {len(calendars)} calendars")

        # Get events from each calendar
        all_events = []
        for calendar in calendars:
            cal_id = calendar.get('id')
            logger.debug(f"Getting events for calendar {cal_id}")
            calendar_events = get_calendar_events(service, cal_id)
            for event in calendar_events:
                event['sourceCalendarId'] = cal_id  # Track which calendar this came from
            all_events.extend(calendar_events)

        logger.info(f"Retrieved {len(all_events)} events from all calendars")

        # Process each event
        for event in all_events:
            event_id = event.get('id')
            summary = event.get('summary', 'No Title')
            description = event.get('description', '')
            location = event.get('location', '')
            status = event.get('status', '')
            source_calendar_id = event.get('sourceCalendarId', 'primary')

            # Parse start and end times
            start_time = None
            end_time = None

            if 'start' in event:
                start_time = parse_event_datetime(event['start'])

            if 'end' in event:
                end_time = parse_event_datetime(event['end'])

            # Get the updated time of the event
            updated_time_str = event.get('updated')
            updated_time = None
            if updated_time_str:
                updated_time = datetime.fromisoformat(updated_time_str.replace('Z', '+00:00'))

            # Get creator info (email and name)
            creator_email, creator_name = get_creator_info(event)
            creator_info = ""

            # Only add creator info if it's not the primary account
            if creator_email and creator_email.lower() != primary_email.lower():
                creator_info = f"\n👤 Modified by: {creator_name or creator_email}\n"

            # Check if this event exists in our database
            existing_event = EventRecord.query.filter_by(
                event_id=event_id,
                calendar_id=source_calendar_id
            ).first()

            if not existing_event:
                # New event
                new_event = EventRecord(
                    event_id=event_id,
                    calendar_id=source_calendar_id,
                    summary=summary,
                    description=description,
                    location=location,
                    start_time=start_time,
                    end_time=end_time,
                    last_updated=updated_time,
                    status=status
                )

                db.session.add(new_event)

                # Create notification message
                start_time_str = start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown'
                message = f"🆕 New event added: {summary}\n"
                message += f"📅 Date: {start_time_str}\n"

                # Add calendar name if it's available
                if 'calendarName' in event:
                    message += f"📆 Calendar: {event['calendarName']}\n"

                if location:
                    message += f"📍 Location: {location}\n"

                if creator_info:
                    message += creator_info

                changes.append({
                    'type': 'added',
                    'event': new_event,
                    'message': message,
                    'calendar_name': event.get('calendarName', source_calendar_id)
                })

            elif updated_time and existing_event.last_updated:
                # Make both datetimes timezone-aware for comparison
                existing_updated = existing_event.last_updated
                if existing_updated.tzinfo is None:
                    # If stored datetime is naive, make it UTC-aware
                    from datetime import timezone
                    existing_updated = existing_updated.replace(tzinfo=timezone.utc)
                
                if updated_time > existing_updated:
                    # Event was updated
                    changes_desc = []

                if existing_event.summary != summary:
                    changes_desc.append(f"Title changed from '{existing_event.summary}' to '{summary}'")
                    existing_event.summary = summary

                # Handle datetime comparison
                start_time_changed = False
                if existing_event.start_time and start_time:
                    existing_time_str = existing_event.start_time.strftime('%Y-%m-%d %H:%M')
                    new_time_str = start_time.strftime('%Y-%m-%d %H:%M')
                    start_time_changed = existing_time_str != new_time_str
                else:
                    start_time_changed = existing_event.start_time != start_time

                if start_time_changed:
                    old_time = existing_event.start_time.strftime('%Y-%m-%d %H:%M') if existing_event.start_time else 'Unknown'
                    new_time = start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown'
                    changes_desc.append(f"Start time changed from {old_time} to {new_time}")
                    existing_event.start_time = start_time

                # Handle end time comparison
                end_time_changed = False
                if existing_event.end_time and end_time:
                    existing_end_str = existing_event.end_time.strftime('%Y-%m-%d %H:%M')
                    new_end_str = end_time.strftime('%Y-%m-%d %H:%M')
                    end_time_changed = existing_end_str != new_end_str
                else:
                    end_time_changed = existing_event.end_time != end_time

                if end_time_changed:
                    old_time = existing_event.end_time.strftime('%Y-%m-%d %H:%M') if existing_event.end_time else 'Unknown'
                    new_time = end_time.strftime('%Y-%m-%d %H:%M') if end_time else 'Unknown'
                    changes_desc.append(f"End time changed from {old_time} to {new_time}")
                    existing_event.end_time = end_time

                if existing_event.location != location:
                    changes_desc.append(f"Location changed from '{existing_event.location}' to '{location}'")
                    existing_event.location = location

                if existing_event.description != description:
                    existing_event.description = description
                    changes_desc.append("Description was updated")

                if existing_event.status != status:
                    changes_desc.append(f"Status changed from '{existing_event.status}' to '{status}'")
                    existing_event.status = status

                existing_event.last_updated = updated_time

                # Only create a notification if there were actual changes
                if changes_desc:
                    message = f"🔄 Event updated: {summary}\n"
                    message += f"📅 Date: {start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown'}\n"

                    if 'calendarName' in event:
                        message += f"📆 Calendar: {event['calendarName']}\n"

                    message += "Changes:\n"

                    for change in changes_desc:
                        message += f"- {change}\n"

                    if creator_info:
                        message += creator_info

                    changes.append({
                        'type': 'updated',
                        'event': existing_event,
                        'message': message,
                        'calendar_name': event.get('calendarName', source_calendar_id)
                    })

        # Check for deleted events
        db_event_ids = {(event.event_id, event.calendar_id) for event in EventRecord.query.all()}
        api_event_ids = {(event.get('id'), event.get('sourceCalendarId')) for event in all_events}

        deleted_event_ids = db_event_ids - api_event_ids

        for event_id, cal_id in deleted_event_ids:
            deleted_event = EventRecord.query.filter_by(
                event_id=event_id,
                calendar_id=cal_id
            ).first()

            if deleted_event:
                # Check if the event's end time is in the future
                if deleted_event.end_time and deleted_event.end_time > current_time:
                    message = f"❌ Event deleted: {deleted_event.summary}\n"
                    message += f"📅 Was scheduled for: {deleted_event.start_time.strftime('%Y-%m-%d %H:%M') if deleted_event.start_time else 'Unknown'}\n"

                    changes.append({
                        'type': 'deleted',
                        'event': deleted_event,
                        'message': message,
                        'calendar_name': cal_id
                    })

                # Remove the event from the database
                db.session.delete(deleted_event)

        # Commit all changes to the database
        db.session.commit()

        return changes

    except Exception as e:
        logger.error(f"Error checking calendar changes: {str(e)}")
        db.session.rollback()
        raise