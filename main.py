import pandas as pd
import re
import os
from datetime import datetime
from constants import WI_CHARGE_MAP

def classify_charge_list(charges_str):
    """
    Parses charge string and determines severity level based on WI_CHARGE_MAP.
    Returns: 'Felony', 'Misdemeanor', 'Civil', or 'Unknown'
    """
    if pd.isna(charges_str) or str(charges_str).strip() == '':
        return 'None'
    
    # Split by semicolon and clean whitespace
    charges = [c.strip().upper() for c in str(charges_str).split(';') if c.strip() != '']
    
    levels = set()
    for charge in charges:
        # Regex to strip counts like "(1 CT)" to match keys in constants.py
        # Example: 'BAIL JUMPING (2 CT)' becomes 'BAIL JUMPING'
        charge_clean = re.sub(r'\s*\(\d+\s*CT\)\s*$', '', charge).strip()
        
        # Check map
        if charge_clean in WI_CHARGE_MAP:
            levels.add(WI_CHARGE_MAP[charge_clean])
        else:
            # Helpful logging to identify new charges for your constants.py
            print(f"  [DEBUG] Unmapped Charge Found: '{charge_clean}'")
            levels.add('Unknown')
            
    # Hierarchy Logic (Felony overrides Misdemeanor, etc.)
    if 'Felony' in levels: return 'Felony'
    if 'Misdemeanor' in levels: return 'Misdemeanor'
    if 'Civil' in levels: return 'Civil'
    return 'Unknown'

def run_scraper():
    """
    REPLACE THIS BLOCK with your actual scraping logic.
    This function should return a list of dictionaries or a DataFrame.
    """
    # Placeholder: Assuming you return a DataFrame here
    # df = pd.read_csv('your_raw_source.csv')
    # return df
    raise NotImplementedError("Please implement your specific scraping function here.")

def main():
    print("Starting pipeline...")
    
    # 1. Fetch Data
    df = run_scraper()
    
    # 2. Transform: Apply classification
    print(f"Classifying {len(df)} records...")
    df['corrected_level'] = df['charges_str'].apply(classify_charge_list)
    
    # 3. Save: Output the clean data
    filename = f"dane_jail_{datetime.now().strftime('%Y-%m-%d')}.csv"
    df.to_csv(filename, index=False)
    
    print(f"Pipeline complete. Saved data to {filename}")

if __name__ == "__main__":
    # Ensure constants.py is in the same directory
    try:
        main()
    except Exception as e:
        print(f"Pipeline failed: {e}")
