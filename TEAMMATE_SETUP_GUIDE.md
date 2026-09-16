# 🚀 GAV Mediator - Teammate Node Setup Guide

Welcome to the project! As a node operator (RTO, Police, or Insurance), your job is to run your local database node and securely expose it to the Team Leader's Mediator over the internet. 

**Please follow these instructions carefully to avoid common setup errors.**

---

## Step 1: Download the Code Correctly
**DO NOT download the code as a ZIP file.** If you use the ZIP file, you will be missing critical Git tracking folders and won't be able to pull updates.

1. Open **Command Prompt** or **PowerShell**.
2. Navigate to the folder where you want to store the project.
3. Run the clone command specifically for **your assigned branch**.

**If you are the RTO node:**
```cmd
git clone -b node-rto https://github.com/sairam-aleti/IIA-Project-Part-1.git
```
**If you are the Police node:**
```cmd
git clone -b node-police https://github.com/sairam-aleti/IIA-Project-Part-1.git
```
**If you are the Insurance node:**
```cmd
git clone -b node-insurance https://github.com/sairam-aleti/IIA-Project-Part-1.git
```

4. Move into the downloaded folder:
```cmd
cd IIA-Project-Part-1
```

---

## Step 2: Start Your Local Server
Once you are inside the folder, simply run the automated setup script.

1. Double-click the `setup_and_run.bat` file in your File Explorer (or type `setup_and_run.bat` in your terminal and hit Enter).
2. The script will automatically create a virtual environment, install all dependencies, and boot up your API Server.
3. A **second black window** will automatically pop open. This is attempting to start a free Pinggy SSH tunnel. 
   - *If it asks for a password, ignore it and close the second window—Pinggy glitches sometimes. See Step 4 for alternatives.*

---

## Step 3: Access Your Dashboard
Your local database and dashboard are now running! 

**🚨 CRITICAL:** Do not click the `http://0.0.0.0:8000/` link in your terminal. Windows browsers do not understand `0.0.0.0` and will give you an `ERR_ADDRESS_INVALID` error.

To view your node's dashboard and insert test data, manually type this exact address into your browser:
👉 **http://localhost:8000/**

*(If you see a screen titled "GAV Mediator", your browser has cached an old page. Press `Ctrl + F5` to hard refresh, or open an Incognito window).*

---

## Step 4: Expose Your Node to the Team Leader
The Team Leader needs a public URL to connect to your local node. Depending on your internet connection (University WiFi vs Mobile Hotspot), some tunnels might be blocked by firewalls. 

Try these options in order. **Once you get a link, copy it and send it to your Team Leader immediately!**

### Option A: Serveo (Recommended if using a Mobile Hotspot)
If you are connected to a mobile hotspot, Serveo is extremely fast and reliable.
1. Leave your server running. Open a **brand new** terminal window.
2. Run this command:
   ```cmd
   ssh -R 80:localhost:8000 serveo.net
   ```
3. Copy the URL that looks like `https://xyz.serveousercontent.com`.

### Option B: LocalTunnel (Best if you are on University WiFi)
University firewalls often block SSH connections (like Pinggy or Serveo). LocalTunnel bypasses firewalls by using HTTPS.
1. If you have Node.js installed, open a **brand new** terminal window.
2. Run this command:
   ```cmd
   npx localtunnel --port 8000
   ```
3. Copy the URL that looks like `https://xyz.loca.lt`.

### Option C: Pinggy (The Default)
If the second black window that popped up in Step 2 successfully printed a giant QR code, simply look above the QR code for a link ending in `.pinggy.link` and copy it.

---

### 🎉 You are done!
Once your Team Leader puts your link into their `.env` file, your node is fully integrated into the distributed system. You can use your dashboard to add/delete records, and the Mediator will instantly be able to query them across the internet!
