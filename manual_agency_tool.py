import sqlite3
import argparse
import json

def add_vehicle_manual(plate, case_ref):
    """
    Manually insert a vehicle directly into the POLICE database.
    This simulates a local police officer entering data into their siloed system,
    completely bypassing the Global-As-View integration API.
    """
    print(f"\n[+] Manually adding vehicle {plate} to police.db...")
    
    conn = sqlite3.connect("police.db")
    cursor = conn.cursor()
    
    # Notice we must use their specific column names: plate_marking, reported_stolen, case_ref
    try:
        cursor.execute("""
            INSERT INTO theft_and_scrap_register 
            (plate_marking, reported_stolen, case_ref) 
            VALUES (?, ?, ?)
        """, (plate, True, case_ref))
        conn.commit()
        print(f"    -> Success! Inserted {plate} into the local Police database.")
    except sqlite3.IntegrityError:
        print(f"    -> Error: {plate} already exists in the Police database.")
    finally:
        conn.close()

def fetch_vehicle_manual(plate):
    """
    Manually fetch a vehicle directly from the POLICE database using raw SQL.
    """
    print(f"\n[*] Manually searching for {plate} in police.db...")
    
    conn = sqlite3.connect("police.db")
    # This row_factory allows us to fetch rows as dictionaries
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    # We write a raw SQL query specifically tailored for the police schema
    cursor.execute("""
        SELECT * FROM theft_and_scrap_register 
        WHERE plate_marking = ?
    """, (plate,))
    
    rows = cursor.fetchall()
    
    if not rows:
        print("    -> No records found in the local police database.")
    else:
        print(f"    -> Found {len(rows)} record(s):")
        for row in rows:
            # Convert the sqlite3.Row object to a standard Python dictionary for easy viewing
            row_dict = dict(row)
            print(json.dumps(row_dict, indent=4))
            
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manual Local Agency Tool (Bypasses the GAV Integration)")
    parser.add_argument("action", choices=["add", "fetch"], help="The manual action to perform")
    parser.add_argument("plate", type=str, help="The license plate to insert or search for (e.g. DL99GHOST)")
    parser.add_argument("--case", type=str, default="POL-MANUAL-1", help="The FIR case number (only used when adding)")
    
    args = parser.parse_args()
    
    if args.action == "add":
        add_vehicle_manual(args.plate, args.case)
    elif args.action == "fetch":
        fetch_vehicle_manual(args.plate)
