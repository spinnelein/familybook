"""
Pacific timezone utility functions for handling time conversions.
"""
from datetime import datetime
import pytz


def get_pacific_timezone():
    """Get Pacific timezone (handles PST/PDT automatically)"""
    return pytz.timezone('America/Los_Angeles')


def get_pacific_now():
    """Get current time in Pacific timezone as ISO string"""
    pacific_tz = get_pacific_timezone()
    return datetime.now(pacific_tz).strftime('%Y-%m-%d %H:%M:%S')


def utc_to_pacific(utc_string):
    """Convert UTC timestamp string to Pacific time string"""
    if not utc_string:
        return utc_string
    try:
        # Parse UTC time
        utc_dt = datetime.fromisoformat(utc_string.replace('T', ' ').replace('Z', ''))
        utc_dt = pytz.UTC.localize(utc_dt)
        
        # Convert to Pacific
        pacific_tz = get_pacific_timezone()
        pacific_dt = utc_dt.astimezone(pacific_tz)
        return pacific_dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return utc_string