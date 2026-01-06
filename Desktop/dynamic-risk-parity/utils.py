from datetime import datetime, timedelta

# Simple list of holidays for 2025 as requested
HOLIDAYS_2025 = [
    '2025-01-26', # Republic Day
    '2025-08-15', # Independence Day
    '2025-10-02', # Gandhi Jayanti
    '2025-12-25'  # Christmas
]

def get_next_expiry() -> str:
    """
    Calculate the next weekly expiry date (Tuesday).
    
    Logic:
    - Find next Tuesday.
    - If today is Tuesday and time < 15:30, return today.
    - If holiday, shift back to Monday.
    - Format: DD-MMM-YYYY (Month in CAPS).
    """
    now = datetime.now()
    today_date = now.date()
    
    # Tuesday is weekday 1 (Monday=0, Sunday=6)
    TARGET_WEEKDAY = 1 
    
    days_ahead = TARGET_WEEKDAY - today_date.weekday()
    
    if days_ahead < 0:
        # User defined: Find "next Tuesday". Usage usually implies upcoming.
        # If today is Wed-Sun, next Tuesday is next week.
        days_ahead += 7
    elif days_ahead == 0:
        # Today is Tuesday
        # Check time 3:30 PM (15:30)
        current_time = now.time()
        cutoff_time = datetime.strptime("15:30", "%H:%M").time()
        
        if current_time > cutoff_time:
            # Shift to next week's Tuesday
            days_ahead += 7
        else:
            # It's today
            days_ahead = 0
            
    expiry_date = today_date + timedelta(days=days_ahead)
    
    # Check for Holidays
    expiry_str_iso = expiry_date.strftime("%Y-%m-%d")
    
    if expiry_str_iso in HOLIDAYS_2025:
        # Shift back by 1 day (to Monday)
        expiry_date = expiry_date - timedelta(days=1)
        
    # Format: DD-MMM-YYYY (e.g., 30-Dec-2025)
    # %b gives 'Dec', we need 'DEC'
    formatted_date = expiry_date.strftime("%d-%b-%Y")
    
    # Manually uppercase the month part
    # Split by '-', upper the middle part, join back
    parts = formatted_date.split('-')
    parts[1] = parts[1].upper()
    final_date_str = "-".join(parts)
    
    return final_date_str

if __name__ == "__main__":
    print(f"Next Expiry: {get_next_expiry()}")
