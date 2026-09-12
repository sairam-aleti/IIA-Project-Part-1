# MoT GAV Mediator System

This project is a **Global-As-View (GAV) Federated Data Mediator System** built for the Ministry of Transportation (MoT) to identify uninsured and stolen vehicles.

It solves the problem of data silos by providing a single virtual schema over 4 isolated, heterogeneous SQLite databases (RTO, Insurance, Police, Camera). It features **AI-driven algorithmic schema matching** (using `sentence-transformers`), **Data Provenance tracking**, and a **React-based SPA frontend** for full CRUD operations across all federated sources simultaneously.

---

## 🚀 Features
- **Zero Data Duplication**: Fetches live data from autonomous databases instead of maintaining a slow ETL warehouse.
- **Dynamic Schema Matching**: Uses NLP to dynamically join tables even if column names are completely different (e.g., `reg_num` vs `plate_id`).
- **Semantic Conflict Resolution**: Derives true states algorithmically (e.g., checking if `expiry_date` has passed regardless of status strings).
- **Full CRUD Support**: Add, edit, or delete a vehicle across all 4 isolated databases simultaneously.
- **Modern UI**: Fully responsive React Single Page Application loaded entirely over CDN (no Node.js/npm required).

---

## 🛠️ Setup Instructions

It is highly recommended to run this project inside a Python Virtual Environment to avoid conflicting dependencies.

### 1. Clone the repository
```bash
git clone https://github.com/sairam-aleti/IIA-Project-Part-1.git
cd IIA-Project-Part-1
```

### 2. Create and Activate a Virtual Environment
**On Windows:**
```powershell
python -m venv iia_project
.\iia_project\Scripts\activate
```

**On macOS/Linux:**
```bash
python3 -m venv iia_project
source iia_project/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🏃‍♂️ Running the Application

### 1. Generate the Mock Databases
The system requires 4 isolated SQLite databases to simulate the distributed environment. Generate them by running:
```bash
python data_generator.py
```
*(This will create `rto.db`, `insurance.db`, `police.db`, and `camera.db` in your directory.)*

### 2. Start the FastAPI Server
Run the backend server using `uvicorn`:
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
*(Note: On the first boot, it may take a few seconds to download the HuggingFace `sentence-transformers` model for schema matching.)*

### 3. Access the Dashboard
Open your web browser and navigate to:
**http://127.0.0.1:8000**

---

## 📚 Documentation
For a deep dive into the architecture, GAV query unfolding, AI math, and data flow, please see the [project_report.md](./project_report.md).
