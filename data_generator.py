import os
import random
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Date
from sqlalchemy.orm import declarative_base, sessionmaker
from faker import Faker

# Initialize Faker
fake = Faker()

# Define Bases for 4 distinct databases
CameraBase = declarative_base()
RTOBase = declarative_base()
InsuranceBase = declarative_base()
PoliceBase = declarative_base()

# ==========================================
# Schema Definitions
# ==========================================

class Capture(CameraBase):
    __tablename__ = 'Capture'
    capture_id = Column(Integer, primary_key=True, autoincrement=True)
    plate_id = Column(String, index=True)
    camera_loc = Column(String)
    captured_at = Column(DateTime)
    ocr_confidence = Column(Float)

class Vehicle(RTOBase):
    __tablename__ = 'Vehicle'
    reg_num = Column(String, primary_key=True)
    owner_name = Column(String)
    vehicle_class = Column(String)
    registration_date = Column(Date)
    chassis_no = Column(String, unique=True)

class Policy(InsuranceBase):
    __tablename__ = 'Policy'
    vehicle_reg_no = Column(String, primary_key=True)
    policy_no = Column(String, unique=True)
    insurer_name = Column(String)
    start_date = Column(Date)
    expiry_date = Column(Date)
    status = Column(String)

class StolenRecord(PoliceBase):
    __tablename__ = 'StolenRecord'
    license_tag = Column(String, primary_key=True)
    is_stolen = Column(Boolean)
    fir_number = Column(String, nullable=True)
    is_scrapped = Column(Boolean)
    status_updated_at = Column(DateTime)

# ==========================================
# Database Connections
# ==========================================

def setup_databases():
    # Remove existing databases to start fresh
    db_files = ['camera.db', 'rto.db', 'insurance.db', 'police.db']
    for db_file in db_files:
        if os.path.exists(db_file):
            os.remove(db_file)

    # Create engines
    engine_camera = create_engine('sqlite:///camera.db')
    engine_rto = create_engine('sqlite:///rto.db')
    engine_insurance = create_engine('sqlite:///insurance.db')
    engine_police = create_engine('sqlite:///police.db')

    # Create tables
    CameraBase.metadata.create_all(engine_camera)
    RTOBase.metadata.create_all(engine_rto)
    InsuranceBase.metadata.create_all(engine_insurance)
    PoliceBase.metadata.create_all(engine_police)

    return (
        sessionmaker(bind=engine_camera)(),
        sessionmaker(bind=engine_rto)(),
        sessionmaker(bind=engine_insurance)(),
        sessionmaker(bind=engine_police)()
    )

# ==========================================
# Data Generation
# ==========================================

def generate_data(num_records=1000):
    session_camera, session_rto, session_insurance, session_police = setup_databases()
    
    print(f"Generating {num_records} overlapping vehicle records...")
    
    # Pre-generate shared identifiers (License Plates)
    # Using a standard format e.g. AB12CD3456
    plates = [fake.unique.bothify(text='??##??####').upper() for _ in range(num_records)]
    
    vehicle_classes = ['Sedan', 'SUV', 'Hatchback', 'Motorcycle', 'Truck']
    insurers = ['SecureDrive Insurance', 'AutoGuard Ltd', 'SafeJourney', 'National Vehicle Insurers']
    
    for plate in plates:
        # 1. RTO_DB Data
        reg_date = fake.date_between(start_date='-10y', end_date='today')
        vehicle = Vehicle(
            reg_num=plate,
            owner_name=fake.name(),
            vehicle_class=random.choice(vehicle_classes),
            registration_date=reg_date,
            chassis_no=fake.unique.bothify(text='CH######??####').upper()
        )
        session_rto.add(vehicle)

        # 2. Insurance_DB Data
        # Introduce edge cases: 15% uninsured/expired, 85% insured/active
        is_insured = random.random() > 0.15
        if is_insured:
            status = 'Active'
            start_date = fake.date_between(start_date='-1y', end_date='today')
            expiry_date = start_date + timedelta(days=365)
        else:
            status = 'Expired'
            start_date = fake.date_between(start_date='-3y', end_date='-2y')
            expiry_date = start_date + timedelta(days=365)
            
        policy = Policy(
            vehicle_reg_no=plate,
            policy_no=fake.unique.bothify(text='POL-#########'),
            insurer_name=random.choice(insurers),
            start_date=start_date,
            expiry_date=expiry_date,
            status=status
        )
        session_insurance.add(policy)

        # 3. Police_DB Data
        # Introduce edge cases: 5% stolen
        is_stolen = random.random() < 0.05
        is_scrapped = random.random() < 0.02
        stolen_record = StolenRecord(
            license_tag=plate,
            is_stolen=is_stolen,
            fir_number=fake.bothify(text='FIR-####') if is_stolen else None,
            is_scrapped=is_scrapped,
            status_updated_at=fake.date_time_between(start_date='-2y', end_date='now')
        )
        session_police.add(stolen_record)

        # 4. Camera_DB Data
        # Generate 1 to 5 captures per vehicle to simulate streaming/multiple sightings
        num_captures = random.randint(1, 5)
        for _ in range(num_captures):
            capture = Capture(
                plate_id=plate,
                camera_loc=fake.street_address(),
                captured_at=fake.date_time_between(start_date='-1y', end_date='now'),
                ocr_confidence=round(random.uniform(0.65, 0.99), 2)
            )
            session_camera.add(capture)

    # Commit all sessions
    session_camera.commit()
    session_rto.commit()
    session_insurance.commit()
    session_police.commit()
    
    # Close sessions
    session_camera.close()
    session_rto.close()
    session_insurance.close()
    session_police.close()
    
    print("Database generation completed successfully!")
    print("- camera.db")
    print("- rto.db")
    print("- insurance.db")
    print("- police.db")

if __name__ == "__main__":
    generate_data(1000)
