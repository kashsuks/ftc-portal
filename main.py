# main.py
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from ttkthemes import ThemedTk
import psycopg2
import psycopg2.extras
import requests
import hashlib
import json
import os
import re
from datetime import datetime

CONFIG_FILE_NAME = "ftc_portal_config.json"
FTC_SCOUT_API_BASE_URL = "https://api.ftcscout.org/rest/v1"
CURRENT_FTC_SEASON = datetime.now().year

dbConnection = None
currentUser = None
teamInfo = None
dbUrlUsed = None

def getConfigFilePath():
    homeDir = os.path.expanduser("~")
    configDir = os.path.join(homeDir, ".ftcportal")
    if not os.path.exists(configDir):
        try:
            os.makedirs(configDir)
        except OSError as e:
            print(f"Warning: Could not create config directory: {e}")
            return CONFIG_FILE_NAME
    return os.path.join(configDir, CONFIG_FILE_NAME)

def saveConfig(configData):
    filePath = getConfigFilePath()
    try:
        with open(filePath, 'w') as f:
            json.dump(configData, f, indent=4)
    except IOError as e:
        messagebox.showerror("Config Error", f"Failed to save configuration:\n{e}")

def loadConfig():
    global dbUrlUsed, currentUser
    filePath = getConfigFilePath()
    if os.path.exists(filePath):
        try:
            with open(filePath, 'r') as f:
                config = json.load(f)
                dbUrlUsed = config.get("dbUrl")
                if "username" in config:
                    currentUser = {"username": config["username"]}
                return config
        except (IOError, json.JSONDecodeError) as e:
            messagebox.showerror("Config Error", f"Failed to load configuration:\n{e}\nConfiguration file might be corrupted.")
            try:
                os.remove(filePath)
            except OSError:
                pass
    return {}

def connectDb(dbUrl):
    global dbConnection
    try:
        dbConnection = psycopg2.connect(dbUrl)
        dbConnection.autocommit = True
        print("Database connection successful.")
        return dbConnection
    except psycopg2.Error as e:
        messagebox.showerror("Database Error", f"Could not connect to the database:\n{e}\n\nPlease check the Database URL and ensure the database server is running and accessible.")
        dbConnection = None
        return None

def closeDb():
    global dbConnection
    if dbConnection:
        dbConnection.close()
        dbConnection = None
        print("Database connection closed.")

def executeQuery(query, params=None, fetch=False):
    if not dbConnection:
        messagebox.showerror("Database Error", "Not connected to the database.")
        return None
    
    cursor = None
    try:
        cursor = dbConnection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(query, params)
        if fetch:
            if cursor.description:
                return cursor.fetchall()
            else:
                return []
        return True
    except psycopg2.Error as e:
        messagebox.showerror("Database Query Error", f"Error executing query:\n{e}")
        return None
    finally:
        if cursor:
            cursor.close()

def createDatabaseSchema():
    if not dbConnection: return False
    schemaSql = """
    DROP TABLE IF EXISTS GuideVideos CASCADE;
    DROP TABLE IF EXISTS Guides CASCADE;
    DROP TABLE IF EXISTS Attendance CASCADE;
    DROP TABLE IF EXISTS Meetings CASCADE;
    DROP TABLE IF EXISTS Users CASCADE;
    DROP TABLE IF EXISTS Roles CASCADE;
    DROP TABLE IF EXISTS TeamInfo CASCADE;

    CREATE TABLE TeamInfo (
        team_number INT PRIMARY KEY,
        team_name VARCHAR(255) NOT NULL,
        team_password_hash VARCHAR(255) NOT NULL
    );

    CREATE TABLE Roles (
        role_id SERIAL PRIMARY KEY,
        role_name VARCHAR(100) UNIQUE NOT NULL
    );

    CREATE TABLE Users (
        user_id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        hashed_password VARCHAR(255) NOT NULL,
        role_id INT,
        is_pending BOOLEAN DEFAULT TRUE NOT NULL,
        is_admin BOOLEAN DEFAULT FALSE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        FOREIGN KEY (role_id) REFERENCES Roles(role_id) ON DELETE SET NULL
    );

    CREATE TABLE Meetings (
        meeting_id SERIAL PRIMARY KEY,
        meeting_date DATE NOT NULL DEFAULT CURRENT_DATE,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE Attendance (
        attendance_id SERIAL PRIMARY KEY,
        user_id INT NOT NULL,
        meeting_id INT NOT NULL,
        is_present BOOLEAN NOT NULL,    
        recorded_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (user_id, meeting_id),
        FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (meeting_id) REFERENCES Meetings(meeting_id) ON DELETE CASCADE
    );

    CREATE TABLE Guides (
        guide_id SERIAL PRIMARY KEY,
        topic_name VARCHAR(255) NOT NULL,
        created_by_user_id INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        FOREIGN KEY (created_by_user_id) REFERENCES Users(user_id) ON DELETE SET NULL
    );

    CREATE TABLE GuideVideos (
        video_id SERIAL PRIMARY KEY,
        guide_id INT NOT NULL,
        video_url VARCHAR(512) NOT NULL,
        video_title VARCHAR(255),
        added_by_user_id INT,
        added_at TIMESTAMPTZ DEFAULT NOW(),
        FOREIGN KEY (guide_id) REFERENCES Guides(guide_id) ON DELETE CASCADE,
        FOREIGN KEY (added_by_user_id) REFERENCES Users(user_id) ON DELETE SET NULL
    );
    
    INSERT INTO Roles (role_name) VALUES ('Member') ON CONFLICT (role_name) DO NOTHING;
    INSERT INTO Roles (role_name) VALUES ('Software Lead') ON CONFLICT (role_name) DO NOTHING;
    INSERT INTO Roles (role_name) VALUES ('Mechanical Lead') ON CONFLICT (role_name) DO NOTHING;
    INSERT INTO Roles (role_name) VALUES ('Outreach Lead') ON CONFLICT (role_name) DO NOTHING;
    INSERT INTO Roles (role_name) VALUES ('Admin') ON CONFLICT (role_name) DO NOTHING;
    """
    commands = [cmd.strip() for cmd in schemaSql.split(';') if cmd.strip()]
    
    try:
        cursor = dbConnection.cursor()
        for command in commands:
            if command:
                cursor.execute(command)
        cursor.close()
        print("Database schema created successfully.")
        return True
    except psycopg2.Error as e:
        messagebox.showerror("Schema Creation Error", f"Failed to create database schema:\n{e}")
        return False

def hashPassword(password):
    passwordBytes = password.encode('utf-8')
    sha256Hash = hashlib.sha256(passwordBytes)
    return sha256Hash.hexdigest()

def checkPassword(plainPassword, storedHash):
    hashed = hashPassword(plainPassword)
    return hashed == storedHash

def checkFtcTeamExists(teamNumber):
    try:
        apiUrl = f"{FTC_SCOUT_API_BASE_URL}/teams/{teamNumber}"
        print(f"API URL being called: {apiUrl}")
        response = requests.get(apiUrl)
        print(f"Full Response: {response.text}")
        if response.status_code == 200:
            try:
                teamData = response.json()
                print(f"Team Data: {teamData}")
                if 'number' in teamData:
                    return True
                else:
                    print(f"API Check Warning: Team {teamNumber} found (200 OK), but no team data in response.")
                    return False
            except json.JSONDecodeError:
                print(f"API Check Warning: Could not decode JSON response for team {teamNumber}")
                return False
        elif response.status_code == 404:
            return False
        else:
            print(f"API Check Warning: Received status code {response.status_code} for team {teamNumber}")
            return False
    except requests.RequestException as e:
        messagebox.showerror("API Error", f"Could not connect to FTC Scout API to verify team:\n{e}")
        return False

def getFtcTeamQuickStats(teamNumber, season=CURRENT_FTC_SEASON):
    try:
        url = f"{FTC_SCOUT_API_BASE_URL}/teams/{teamNumber}/quick-stats"
        params = {}
        if season:
            params['season'] = season
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"error": f"Team {teamNumber} not found or has no stats for season {season}."}
        else:
            return {"error": f"API Error: Status code {response.status_code} - {response.text}"}
    except requests.RequestException as e:
        return {"error": f"Could not connect to FTC Scout API: {e}"}

def getFtcTeamDetails(teamNumber):
    try:
        response = requests.get(f"{FTC_SCOUT_API_BASE_URL}/teams/{teamNumber}")
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"error": f"Team {teamNumber} not found."}
        else:
            return {"error": f"API Error: Status code {response.status_code} - {response.text}"}
    except requests.RequestException as e:
        return {"error": f"Could not connect to FTC Scout API: {e}"}
        
def getFtcTeamEvents(teamNumber, season=CURRENT_FTC_SEASON):
    try:
        response = requests.get(f"{FTC_SCOUT_API_BASE_URL}/teams/{teamNumber}/events/{season}")
        if response.status_code == 200:
            return response.json()
        else:
            print(f"API Info: No events found for team {teamNumber} in season {season} or other API issue (Status: {response.status_code}).")
            return []
    except requests.RequestException as e:
        return {"error": f"Could not connect to FTC Scout API: {e}"}

class BaseFrame(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.grid(row=0, column=0, sticky="nsew")

    def show(self):
        self.tkraise()
        self.onShow()

    def onShow(self):
        pass


class LoginFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Login or Setup")

        self.hasConfig = bool(dbUrlUsed)

        style = ttk.Style(self)
        style.configure('Login.TButton', font=('Helvetica', 12))
        style.configure('Header.TLabel', font=('Helvetica', 18, 'bold'))

        headerLabel = ttk.Label(self, text="FTC Team Portal", style='Header.TLabel')
        headerLabel.pack(pady=20)

        self.contentFrame = ttk.Frame(self)
        self.contentFrame.pack(pady=10, padx=50, fill="x")

        self.dbUrlLabel = ttk.Label(self.contentFrame, text="Database URL:")
        self.dbUrlEntry = ttk.Entry(self.contentFrame, width=50)

        self.usernameLabel = ttk.Label(self.contentFrame, text="Username:")
        self.usernameEntry = ttk.Entry(self.contentFrame, width=30)

        self.passwordLabel = ttk.Label(self.contentFrame, text="Password:")
        self.passwordEntry = ttk.Entry(self.contentFrame, show="*", width=30)
        
        self.teamNumberLabel = ttk.Label(self.contentFrame, text="Your Team Number:")
        self.teamNumberEntry = ttk.Entry(self.contentFrame, width=15)
        self.teamNameLabel = ttk.Label(self.contentFrame, text="Your Team Name:")
        self.teamNameEntry = ttk.Entry(self.contentFrame, width=30)
        self.teamPasswordLabel = ttk.Label(self.contentFrame, text="Create Team Password:")
        self.teamPasswordEntry = ttk.Entry(self.contentFrame, show="*", width=30)
        
        self.loginButton = ttk.Button(self, text="Login", command=self.attemptLogin, style='Login.TButton')
        self.showJoinButton = ttk.Button(self, text="Join a Team", command=lambda: self.showMode('join'), style='Login.TButton')
        self.showCreateButton = ttk.Button(self, text="Create a Team", command=lambda: self.showMode('create'), style='Login.TButton')
        self.joinButton = ttk.Button(self, text="Send Join Request", command=self.attemptJoin, style='Login.TButton')
        self.createButton = ttk.Button(self, text="Create Team & Account", command=self.attemptCreateTeam, style='Login.TButton')
        self.backButton = ttk.Button(self, text="Back", command=lambda: self.showMode('initial'), style='Login.TButton')

        self.showMode('initial')

    def showMode(self, mode):
        for widget in self.contentFrame.winfo_children():
            widget.grid_forget()
        self.loginButton.pack_forget()
        self.showJoinButton.pack_forget()
        self.showCreateButton.pack_forget()
        self.joinButton.pack_forget()
        self.createButton.pack_forget()
        self.backButton.pack_forget()

        if mode == 'initial':
            if self.hasConfig:
                self.showMode('login')
            else:
                self.showJoinButton.pack(pady=10)
                self.showCreateButton.pack(pady=5)
        
        elif mode == 'login':
            self.dbUrlLabel.grid(row=0, column=0, padx=5, pady=5, sticky="w")
            self.dbUrlEntry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
            self.dbUrlEntry.delete(0, tk.END)
            if dbUrlUsed:
                self.dbUrlEntry.insert(0, dbUrlUsed)
                self.dbUrlEntry.config(state="readonly")
            else:
                self.dbUrlEntry.config(state="normal")
                self.dbUrlLabel.grid_remove()
                self.dbUrlEntry.grid_remove()

            self.usernameLabel.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.usernameEntry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
            self.passwordLabel.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.passwordEntry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
            self.contentFrame.grid_columnconfigure(1, weight=1)

            config = loadConfig()
            if config and "username" in config:
                self.usernameEntry.delete(0, tk.END)
                self.usernameEntry.insert(0, config["username"])

            self.loginButton.pack(pady=20)
            if not self.hasConfig:
                self.backButton.pack(pady=5)

        elif mode == 'join':
            self.dbUrlLabel.grid(row=0, column=0, padx=5, pady=5, sticky="w")
            self.dbUrlEntry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
            self.dbUrlEntry.config(state="normal")
            self.dbUrlEntry.delete(0, tk.END)

            self.usernameLabel.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.usernameEntry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
            self.passwordLabel.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.passwordEntry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
            self.contentFrame.grid_columnconfigure(1, weight=1)

            self.joinButton.pack(pady=20)
            self.backButton.pack(pady=5)
            
        elif mode == 'create':
            self.usernameLabel.grid(row=0, column=0, padx=5, pady=5, sticky="w")
            self.usernameEntry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
            self.passwordLabel.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.passwordEntry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
            self.dbUrlLabel.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.dbUrlEntry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
            self.dbUrlEntry.config(state="normal")
            self.dbUrlEntry.delete(0, tk.END)
            self.teamNumberLabel.grid(row=3, column=0, padx=5, pady=5, sticky="w")
            self.teamNumberEntry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
            self.teamNameLabel.grid(row=4, column=0, padx=5, pady=5, sticky="w")
            self.teamNameEntry.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
            self.teamPasswordLabel.grid(row=5, column=0, padx=5, pady=5, sticky="w")
            self.teamPasswordEntry.grid(row=5, column=1, padx=5, pady=5, sticky="ew")
            
            self.contentFrame.grid_columnconfigure(1, weight=1)

            self.createButton.pack(pady=20)
            self.backButton.pack(pady=5)

    def attemptLogin(self):
        global currentUser, teamInfo, dbUrlUsed
        
        username = self.usernameEntry.get().strip()
        password = self.passwordEntry.get()
        targetDbUrl = dbUrlUsed or self.dbUrlEntry.get().strip() 

        if not username or not password:
            messagebox.showwarning("Login Failed", "Username and password cannot be empty.")
            return
            
        if not targetDbUrl:
            messagebox.showwarning("Login Failed", "Database URL is required.")
            return

        if not connectDb(targetDbUrl):
            return

        query = "SELECT user_id, username, hashed_password, is_pending, is_admin, role_id FROM Users WHERE username = %s"
        result = executeQuery(query, (username,), fetch=True)

        if result:
            userData = result[0]
            storedHash = userData['hashed_password']
            
            if checkPassword(password, storedHash):
                if userData['is_pending']:
                    messagebox.showinfo("Login Pending", "Your account is awaiting admin approval.")
                    closeDb()
                    return
                else:
                    currentUser = {
                        'user_id': userData['user_id'],
                        'username': userData['username'],
                        'is_admin': userData['is_admin'],
                        'role_id': userData['role_id']
                    }
                    
                    teamResult = executeQuery("SELECT team_number, team_name FROM TeamInfo LIMIT 1", fetch=True)
                    if teamResult:
                        teamInfo = dict(teamResult[0])
                    else:
                        messagebox.showerror("Login Error", "Could not retrieve team information from the database.")
                        closeDb()
                        currentUser = None
                        return

                    if not self.hasConfig:
                        saveConfig({"dbUrl": targetDbUrl})
                        dbUrlUsed = targetDbUrl

                    print(f"Login successful for user: {currentUser['username']}")
                    self.controller.showFrame("DashboardFrame")
            else:
                messagebox.showerror("Login Failed", "Invalid username or password.")
                closeDb()
        else:
            messagebox.showerror("Login Failed", "Invalid username or password.")
            closeDb()


    def attemptJoin(self):
        global dbUrlUsed
        username = self.usernameEntry.get().strip()
        password = self.passwordEntry.get()
        targetDbUrl = self.dbUrlEntry.get().strip()

        if not username or not password or not targetDbUrl:
            messagebox.showwarning("Join Failed", "Username, password, and Database URL are required.")
            return
        
        if not re.match(r"postgresql://[^@]+@[^/]+/.+", targetDbUrl):
            messagebox.showwarning("Join Failed", "Invalid PostgreSQL Database URL format.\nExample: postgresql://user:password@host:port/database")
            return

        if not connectDb(targetDbUrl):
             return 
             
        checkQuery = "SELECT user_id FROM Users WHERE username = %s"
        existing = executeQuery(checkQuery, (username,), fetch=True)
        if existing:
             messagebox.showerror("Join Failed", f"Username '{username}' already exists. Please choose another.")
             closeDb()
             return

        hashedPass = hashPassword(password)
        insertQuery = """
            INSERT INTO Users (username, hashed_password, is_pending, is_admin) 
            VALUES (%s, %s, TRUE, FALSE) RETURNING user_id;
        """
        result = executeQuery(insertQuery, (username, hashedPass), fetch=True)

        if result:
            messagebox.showinfo("Join Request Sent", "Your request to join the team has been sent.\nAn administrator must approve your account before you can log in.")
            saveConfig({"dbUrl": targetDbUrl})
            dbUrlUsed = targetDbUrl
            closeDb()
            self.showMode('login')
        else:
             messagebox.showerror("Join Failed", "Could not submit join request. Please check the Database URL and try again.")
             closeDb()


    def attemptCreateTeam(self):
        global currentUser, teamInfo, dbUrlUsed
        
        adminUsername = self.usernameEntry.get().strip()
        adminPassword = self.passwordEntry.get()
        targetDbUrl = self.dbUrlEntry.get().strip()
        teamNumberStr = self.teamNumberEntry.get().strip()
        teamName = self.teamNameEntry.get().strip()
        teamPassword = self.teamPasswordEntry.get()

        if not (adminUsername and adminPassword and targetDbUrl and teamNumberStr and teamName and teamPassword):
            messagebox.showwarning("Creation Failed", "All fields are required to create a team.")
            return
            
        if not re.match(r"postgresql://[^@]+@[^/]+/.+", targetDbUrl):
            messagebox.showwarning("Creation Failed", "Invalid PostgreSQL Database URL format.")
            return

        try:
            teamNumber = int(teamNumberStr)
        except ValueError:
            messagebox.showwarning("Creation Failed", "Team Number must be a valid integer.")
            return
            
        if not checkFtcTeamExists(teamNumber):
            if not messagebox.askyesno("Team Not Found", f"Team number {teamNumber} was not found via the FTC Scout API. This might be an error or the team is new.\n\nDo you want to proceed anyway?"):
                 return

        if not connectDb(targetDbUrl):
            return
            
        checkTeamInfo = executeQuery("SELECT 1 FROM TeamInfo LIMIT 1", fetch=True)
        if checkTeamInfo:
             if not messagebox.askyesno("Database Not Empty", "This database appears to already contain team data.\nContinuing will WIPE existing data and set up a new team.\n\nAre you absolutely sure you want to proceed?"):
                 closeDb()
                 return
            
        if not createDatabaseSchema():
            closeDb()
            return

        try:
            cursor = dbConnection.cursor()
            
            hashedTeamPass = hashPassword(teamPassword)
            cursor.execute("INSERT INTO TeamInfo (team_number, team_name, team_password_hash) VALUES (%s, %s, %s)", 
                           (teamNumber, teamName, hashedTeamPass))

            hashedAdminPass = hashPassword(adminPassword)
            cursor.execute("SELECT role_id FROM Roles WHERE role_name = 'Admin'")
            adminRoleResult = cursor.fetchone()
            adminRoleId = adminRoleResult[0] if adminRoleResult else None

            cursor.execute("""
                INSERT INTO Users (username, hashed_password, is_pending, is_admin, role_id) 
                VALUES (%s, %s, FALSE, TRUE, %s) RETURNING user_id, username, is_admin, role_id
            """, (adminUsername, hashedAdminPass, adminRoleId))
            
            adminUserData = cursor.fetchone()
            cursor.close()

            if adminUserData:
                 currentUser = {
                     'user_id': adminUserData[0],
                     'username': adminUserData[1],
                     'is_admin': adminUserData[2],
                     'role_id': adminUserData[3]
                 }
                 teamInfo = {'team_number': teamNumber, 'team_name': teamName}

                 saveConfig({"dbUrl": targetDbUrl})
                 dbUrlUsed = targetDbUrl

                 messagebox.showinfo("Team Created", f"Team '{teamName}' ({teamNumber}) created successfully!\nYou are logged in as the administrator.")
                 self.controller.showFrame("DashboardFrame")
            else:
                 messagebox.showerror("Creation Failed", "Failed to create the administrator user account.")
                 closeDb()
        
        except psycopg2.Error as e:
             messagebox.showerror("Creation Error", f"An error occurred during team creation:\n{e}")
             closeDb()


# --- Main Application Window ---
class FtcPortalApp(ThemedTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_theme("arc")

        self.attributes('-fullscreen', True)
        self.bind('<Escape>', lambda e: self.quitFullscreen())

        self.title("FTC Portal")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        container = ttk.Frame(self)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}

        for F in (LoginFrame, DashboardFrame, AttendanceFrame, ScoutingFrame, GuidesFrame, SettingsFrame, AdminFrame):
            pageName = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[pageName] = frame

        print("Frames initialized:", list(self.frames.keys()))

        config = loadConfig()
        if dbUrlUsed and currentUser and "username" in currentUser:
            self.showFrame("LoginFrame")
        else:
            self.showFrame("LoginFrame")


    def showFrame(self, pageName):
        if pageName not in self.frames:
            print(f"Error: Frame '{pageName}' not found.")
            return
        frame = self.frames[pageName]
        if hasattr(frame, 'onShow') and callable(frame.onShow):
            frame.onShow() 
        frame.tkraise()
        
    def quitFullscreen(self):
        self.attributes('-fullscreen', False)
        
    def logout(self):
        global currentUser, teamInfo, dbConnection
        if dbConnection:
            closeDb()
        if currentUser:
            currentUser = {"username": currentUser.get("username", "")}
        teamInfo = None
        self.showFrame("LoginFrame")
        
    def getDbConnection(self):
        return dbConnection
        
    def getCurrentUser(self):
         return currentUser

    def getTeamInfo(self):
        return teamInfo

# --- Placeholder Frames for other sections ---

class DashboardFrame(BaseFrame):
     def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Dashboard")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1)

        self.mainContent = ttk.Frame(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        self.adminButton = ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame"))
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.welcomeLabel = ttk.Label(self.mainContent, text="Hello, ", font=("Helvetica", 16))
        self.welcomeLabel.pack(pady=20, anchor="w", padx=20)

        statsFrame = ttk.Frame(self.mainContent, style='Card.TFrame', padding=20, relief=tk.GROOVE, borderwidth=2)
        statsFrame.pack(pady=20, padx=50, fill="x")

        self.teamNameLabel = ttk.Label(statsFrame, text="Team Name: ", font=("Helvetica", 12))
        self.teamNameLabel.grid(row=0, column=0, sticky="w", pady=5)
        self.teamNumberLabel = ttk.Label(statsFrame, text="Team Number: ", font=("Helvetica", 12))
        self.teamNumberLabel.grid(row=1, column=0, sticky="w", pady=5)
        self.teammateCountLabel = ttk.Label(statsFrame, text="Number of Teammates: ", font=("Helvetica", 12))
        self.teammateCountLabel.grid(row=2, column=0, sticky="w", pady=5)

     def onShow(self):
        self.controller.title("FTC Portal - Dashboard")
        userInfo = self.controller.getCurrentUser()
        teamData = self.controller.getTeamInfo()

        if not userInfo:
            self.controller.showFrame("LoginFrame")
            return
            
        self.welcomeLabel.config(text=f"Hello, {userInfo.get('username', 'User')}")

        if teamData:
             self.teamNameLabel.config(text=f"Team Name: {teamData.get('team_name', 'N/A')}")
             self.teamNumberLabel.config(text=f"Team Number: {teamData.get('team_number', 'N/A')}")
        else:
             self.teamNameLabel.config(text="Team Name: Error loading")
             self.teamNumberLabel.config(text="Team Number: Error loading")

        countResult = executeQuery("SELECT COUNT(user_id) FROM Users WHERE is_pending = FALSE", fetch=True)
        if countResult:
             self.teammateCountLabel.config(text=f"Active Teammates: {countResult[0]['count']}")
        else:
             self.teammateCountLabel.config(text="Active Teammates: Error loading")
             
        if userInfo.get('is_admin'):
             self.adminButton.grid(row=5, column=0, sticky="ew", padx=5, pady=5)
        else:
             self.adminButton.grid_remove()


class AttendanceFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Attendance")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1) 

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        self.adminButton = ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame"))
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.mainContent = ttk.Frame(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.createMeetingButton = ttk.Button(self.mainContent, text="Create New Meeting", command=self.openCreateMeetingDialog)

        self.attendanceListFrame = ttk.Frame(self.mainContent)
        self.attendanceListFrame.pack(pady=10, padx=10, fill="both", expand=True)

        ttk.Label(self.attendanceListFrame, text="Teammate", font=("Helvetica", 12, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(self.attendanceListFrame, text="Attendance (Present/Absent)", font=("Helvetica", 12, "bold")).grid(row=0, column=1, padx=10, pady=5, sticky="w")
        
        self.attendanceRows = []


    def onShow(self):
        self.controller.title("FTC Portal - Attendance")
        userInfo = self.controller.getCurrentUser()
        if not userInfo:
             self.controller.showFrame("LoginFrame")
             return

        if userInfo.get('is_admin'):
             self.adminButton.grid(row=5, column=0, sticky="ew", padx=5, pady=5)
             self.createMeetingButton.pack(pady=10, padx=10, anchor="ne")
        else:
             self.adminButton.grid_remove()
             self.createMeetingButton.pack_forget()

        self.loadAttendanceData()

    def loadAttendanceData(self):
        for widget in self.attendanceRows:
            widget.destroy()
        self.attendanceRows = []

        usersQuery = "SELECT user_id, username FROM Users WHERE is_pending = FALSE ORDER BY username"
        users = executeQuery(usersQuery, fetch=True)
        
        if users is None:
             ttk.Label(self.attendanceListFrame, text="Error loading user data.").grid(row=1, column=0, columnspan=2)
             return
        if not users:
            ttk.Label(self.attendanceListFrame, text="No active users found.").grid(row=1, column=0, columnspan=2)
            return

        attendanceQuery = """
            SELECT user_id, is_present, COUNT(*) as count 
            FROM Attendance 
            GROUP BY user_id, is_present
        """
        attendanceDataRaw = executeQuery(attendanceQuery, fetch=True)
        
        attendanceCounts = {}
        if attendanceDataRaw:
             for record in attendanceDataRaw:
                 uid = record['user_id']
                 if uid not in attendanceCounts:
                     attendanceCounts[uid] = {'present': 0, 'absent': 0}
                 if record['is_present']:
                     attendanceCounts[uid]['present'] = record['count']
                 else:
                     attendanceCounts[uid]['absent'] = record['count']

        for i, user in enumerate(users):
            userId = user['user_id']
            username = user['username']
            
            stats = attendanceCounts.get(userId, {'present': 0, 'absent': 0})
            presentCount = stats['present']
            absentCount = stats['absent']

            nameLabel = ttk.Label(self.attendanceListFrame, text=username)
            nameLabel.grid(row=i + 1, column=0, padx=10, pady=2, sticky="w")
            
            statFrame = ttk.Frame(self.attendanceListFrame)
            statFrame.grid(row=i + 1, column=1, padx=10, pady=2, sticky="w")

            presentLabel = ttk.Label(statFrame, text=str(presentCount), foreground="green", font=("Helvetica", 10, "bold"))
            presentLabel.pack(side=tk.LEFT)
            slashLabel = ttk.Label(statFrame, text="/")
            slashLabel.pack(side=tk.LEFT)
            absentLabel = ttk.Label(statFrame, text=str(absentCount), foreground="red", font=("Helvetica", 10, "bold"))
            absentLabel.pack(side=tk.LEFT)

            self.attendanceRows.extend([nameLabel, statFrame])


    def openCreateMeetingDialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Create New Meeting")
        dialog.geometry("450x400")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Meeting Title:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        titleEntry = ttk.Entry(dialog, width=40)
        titleEntry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        ttk.Label(dialog, text="Description (Optional):").grid(row=1, column=0, padx=10, pady=5, sticky="nw")
        descText = tk.Text(dialog, height=4, width=40)
        descText.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        ttk.Label(dialog, text="Attendees:").grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        listFrame = ttk.Frame(dialog)
        listFrame.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        dialog.grid_rowconfigure(3, weight=1)
        listFrame.grid_columnconfigure(0, weight=1)

        scrollbar = ttk.Scrollbar(listFrame, orient=tk.VERTICAL)
        attendeeListbox = tk.Listbox(listFrame, selectmode=tk.MULTIPLE, yscrollcommand=scrollbar.set, exportselection=False)
        scrollbar.config(command=attendeeListbox.yview)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        attendeeListbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)


        usersQuery = "SELECT user_id, username FROM Users WHERE is_pending = FALSE ORDER BY username"
        users = executeQuery(usersQuery, fetch=True)
        userIdMap = {}
        if users:
            for i, user in enumerate(users):
                attendeeListbox.insert(tk.END, user['username'])
                userIdMap[i] = user['user_id']

        def saveMeeting():
            title = titleEntry.get().strip()
            description = descText.get("1.0", tk.END).strip()
            selectedIndices = attendeeListbox.curselection()

            if not title:
                messagebox.showwarning("Input Error", "Meeting Title cannot be empty.", parent=dialog)
                return

            if not selectedIndices:
                 if not messagebox.askyesno("No Attendees", "No attendees selected. Record meeting with zero attendance?", parent=dialog):
                     return

            meetingInsertQuery = "INSERT INTO Meetings (title, description) VALUES (%s, %s) RETURNING meeting_id"
            meetingResult = executeQuery(meetingInsertQuery, (title, description), fetch=True)

            if not meetingResult:
                 messagebox.showerror("Database Error", "Failed to create meeting record.", parent=dialog)
                 return
                 
            meetingId = meetingResult[0]['meeting_id']
            
            allUserIds = [user['user_id'] for user in users] if users else []
            presentUserIds = {userIdMap[idx] for idx in selectedIndices}

            success = True
            try:
                cursor = dbConnection.cursor()
                attendanceValues = []
                for uid in allUserIds:
                    isPresent = (uid in presentUserIds)
                    attendanceValues.append( (uid, meetingId, isPresent) )
                
                insertAttendanceQuery = "INSERT INTO Attendance (user_id, meeting_id, is_present) VALUES %s"
                psycopg2.extras.execute_values(cursor, insertAttendanceQuery, attendanceValues)
                
                cursor.close()
                
            except psycopg2.Error as e:
                messagebox.showerror("Database Error", f"Failed to record attendance:\n{e}", parent=dialog)
                success = False
                
                # Consider deleting the meeting record if attendance fails? Or leave it?
                # Optional: executeQuery("DELETE FROM Meetings WHERE meeting_id = %s", (meetingId,))

            if success:
                messagebox.showinfo("Success", "Meeting and attendance recorded.", parent=dialog)
                dialog.destroy()
                self.loadAttendanceData()
            

        buttonFrame = ttk.Frame(dialog)
        buttonFrame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(buttonFrame, text="Save Meeting", command=saveMeeting).pack(side=tk.LEFT, padx=10)
        ttk.Button(buttonFrame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=10)


class ScoutingFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Scouting")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1)

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        self.adminButton = ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame"))
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.mainContent = ttk.Frame(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        ownTeamFrame = ttk.LabelFrame(self.mainContent, text="Your Team's Stats", padding=10)
        ownTeamFrame.pack(pady=10, padx=5, fill="x")

        self.teamDetailsLabel = ttk.Label(ownTeamFrame, text="Fetching team details...", wraplength=600, justify=tk.LEFT)
        self.teamDetailsLabel.pack(pady=5, anchor="w")
        
        self.teamStatsLabel = ttk.Label(ownTeamFrame, text="Fetching quick stats...", wraplength=600, justify=tk.LEFT)
        self.teamStatsLabel.pack(pady=5, anchor="w")

        queryFrame = ttk.LabelFrame(self.mainContent, text="Query Other Teams/Events (Future Feature)", padding=10)
        queryFrame.pack(pady=20, padx=5, fill="x")
        ttk.Label(queryFrame, text="Enter Team # or Event Code:").grid(row=0, column=0, padx=5, pady=5)
        self.queryEntry = ttk.Entry(queryFrame, width=30)
        self.queryEntry.grid(row=0, column=1, padx=5, pady=5)
        self.queryButton = ttk.Button(queryFrame, text="Query API (Not Implemented)")
        self.queryButton.grid(row=0, column=2, padx=5, pady=5)
        self.queryResultsText = tk.Text(queryFrame, height=10, width=70, state=tk.DISABLED)
        self.queryResultsText.grid(row=1, column=0, columnspan=3, pady=10, padx=5)


    def onShow(self):
        self.controller.title("FTC Portal - Scouting")
        userInfo = self.controller.getCurrentUser()
        teamData = self.controller.getTeamInfo()
        if not userInfo or not teamData:
             self.controller.showFrame("LoginFrame")
             return
        
        if userInfo.get('is_admin'):
             self.adminButton.grid(row=5, column=0, sticky="ew", padx=5, pady=5)
        else:
             self.adminButton.grid_remove()

        teamNumber = teamData.get('team_number')
        if teamNumber:
            self.loadOwnTeamData(teamNumber)
        else:
            self.teamDetailsLabel.config(text="Error: Team number not found.")
            self.teamStatsLabel.config(text="")


    def loadOwnTeamData(self, teamNumber):
        details = getFtcTeamDetails(teamNumber)
        detailsText = f"Team Number: {details.get('teamNumber', 'N/A')}\n"
        detailsText += f"Team Name: {details.get('name', 'N/A')}\n"
        detailsText += f"Organization: {details.get('organization', 'N/A')}\n"
        detailsText += f"Location: {details.get('city', '')}, {details.get('stateProv', '')}, {details.get('country', '')}\n"
        detailsText += f"Rookie Year: {details.get('rookieYear', 'N/A')}\n"
        sponsors = details.get('sponsors') 
        if isinstance(sponsors, list):
             detailsText += f"Sponsors: {', '.join(sponsors) if sponsors else 'N/A'}"
        elif sponsors:
            detailsText += f"Sponsors: {sponsors}"
        else:
            detailsText += "Sponsors: N/A"
            
        if "error" in details:
            self.teamDetailsLabel.config(text=f"Error loading team details: {details['error']}")
        else:
             self.teamDetailsLabel.config(text=detailsText)

        stats = getFtcTeamQuickStats(teamNumber)
        statsText = f"Quick Stats (Season {stats.get('season', CURRENT_FTC_SEASON)}):\n"
        if "error" in stats:
            statsText += f"Error loading stats: {stats['error']}"
        elif not stats:
             statsText += "No quick stats found for the current season."
        else:
             statsText += f"  OPR: {stats.get('opr', 'N/A'):.2f}\n"
             statsText += f"  NPR: {stats.get('npr', 'N/A'):.2f}\n"
             statsText += f"  TPR: {stats.get('tpr', 'N/A'):.2f}\n"
             statsText += f"  Wins: {stats.get('wins', 'N/A')}\n"
             statsText += f"  Losses: {stats.get('losses', 'N/A')}\n"
             statsText += f"  Ties: {stats.get('ties', 'N/A')}\n"
             statsText += f"  Average Rank: {stats.get('rank', 'N/A'):.2f}\n"

        self.teamStatsLabel.config(text=statsText)
        

class GuidesFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Guides")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1)

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        self.adminButton = ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame"))
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.mainContent = ttk.Frame(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        actionBar = ttk.Frame(self.mainContent)
        actionBar.pack(fill="x", pady=5)
        self.createTopicButton = ttk.Button(actionBar, text="Create New Guide Topic", command=self.createGuideTopic)
        self.createTopicButton.pack(side=tk.LEFT, padx=5)
        self.addVideoButton = ttk.Button(actionBar, text="Add Video to Topic", command=self.addVideoToGuide)
        self.backToTopicsButton = ttk.Button(actionBar, text="< Back to Topics", command=self.showTopicsView)

        self.topicsFrame = ttk.Frame(self.mainContent)
        self.topicsFrame.pack(fill="both", expand=True)
        
        self.videosFrame = ttk.Frame(self.mainContent)

        ttk.Label(self.topicsFrame, text="Guide Topics", font=("Helvetica", 14, "bold")).pack(pady=10)
        
        self.topicsTree = ttk.Treeview(self.topicsFrame, columns=("topic"), show="headings")
        self.topicsTree.heading("topic", text="Topic Name")
        self.topicsTree.pack(fill="both", expand=True, padx=10, pady=5)
        self.topicsTree.bind("<Double-1>", self.onTopicDoubleClick)
        
        viewButton = ttk.Button(self.topicsFrame, text="View Selected Guide", command=self.viewSelectedGuide)
        viewButton.pack(pady=5)


        self.videoTopicLabel = ttk.Label(self.videosFrame, text="Videos for: ", font=("Helvetica", 14, "bold"))
        self.videoTopicLabel.pack(pady=10)

        self.videosTree = ttk.Treeview(self.videosFrame, columns=("title", "url"), show="headings")
        self.videosTree.heading("title", text="Video Title")
        self.videosTree.heading("url", text="URL")
        self.videosTree.column("url", width=300)
        self.videosTree.pack(fill="both", expand=True, padx=10, pady=5)
        openUrlButton = ttk.Button(self.videosFrame, text="Open Selected URL", command=self.openSelectedVideoUrl)
        openUrlButton.pack(pady=5)
        
        self.currentGuideId = None


    def onShow(self):
        self.controller.title("FTC Portal - Guides")
        userInfo = self.controller.getCurrentUser()
        if not userInfo:
             self.controller.showFrame("LoginFrame")
             return
             
        if userInfo.get('is_admin'):
             self.adminButton.grid(row=5, column=0, sticky="ew", padx=5, pady=5)
        else:
             self.adminButton.grid_remove()

        self.showTopicsView()


    def showTopicsView(self):
        self.createTopicButton.pack(side=tk.LEFT, padx=5)
        self.addVideoButton.pack_forget()
        self.backToTopicsButton.pack_forget()

        self.videosFrame.pack_forget()
        self.topicsFrame.pack(fill="both", expand=True)
        self.loadGuideTopics()

    def showVideosView(self, guideId, guideName):
        self.currentGuideId = guideId
        
        self.createTopicButton.pack_forget()
        self.addVideoButton.pack(side=tk.LEFT, padx=5)
        self.backToTopicsButton.pack(side=tk.LEFT, padx=5)
        
        self.topicsFrame.pack_forget()
        self.videosFrame.pack(fill="both", expand=True)
        
        self.videoTopicLabel.config(text=f"Videos for: {guideName}")
        self.loadVideosForGuide(guideId)


    def loadGuideTopics(self):
        for item in self.topicsTree.get_children():
            self.topicsTree.delete(item)

        query = "SELECT guide_id, topic_name FROM Guides ORDER BY topic_name"
        topics = executeQuery(query, fetch=True)

        if topics:
            for topic in topics:
                self.topicsTree.insert("", tk.END, iid=topic['guide_id'], values=(topic['topic_name'],))
        elif topics is None:
             self.topicsTree.insert("", tk.END, values=("Error loading topics",))


    def createGuideTopic(self):
        topicName = simpledialog.askstring("New Guide Topic", "Enter the name for the new topic:", parent=self)
        if topicName and topicName.strip():
             userId = self.controller.getCurrentUser().get('user_id')
             query = "INSERT INTO Guides (topic_name, created_by_user_id) VALUES (%s, %s)"
             if executeQuery(query, (topicName.strip(), userId)):
                 self.loadGuideTopics()
             else:
                  messagebox.showerror("Error", "Failed to create guide topic.")
        elif topicName is not None:
             messagebox.showwarning("Input Error", "Topic name cannot be empty.")

    def onTopicDoubleClick(self, event):
        self.viewSelectedGuide()

    def viewSelectedGuide(self):
        selectedItem = self.topicsTree.focus()
        if not selectedItem:
            messagebox.showwarning("Selection Error", "Please select a guide topic to view.")
            return
            
        guideId = selectedItem
        topicName = self.topicsTree.item(selectedItem)['values'][0]
        self.showVideosView(guideId, topicName)


    def loadVideosForGuide(self, guideId):
        for item in self.videosTree.get_children():
            self.videosTree.delete(item)

        query = "SELECT video_id, video_title, video_url FROM GuideVideos WHERE guide_id = %s ORDER BY added_at"
        videos = executeQuery(query, (guideId,), fetch=True)

        if videos:
            for video in videos:
                title = video['video_title'] or "No Title"
                url = video['video_url']
                self.videosTree.insert("", tk.END, iid=video['video_id'], values=(title, url))
        elif videos is None:
            self.videosTree.insert("", tk.END, values=("Error loading videos", ""))


    def addVideoToGuide(self):
        if not self.currentGuideId: return

        dialog = tk.Toplevel(self)
        dialog.title("Add Video")
        dialog.geometry("400x150")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Video Title (Optional):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        titleEntry = ttk.Entry(dialog, width=40)
        titleEntry.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(dialog, text="Video URL (YouTube, etc.):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        urlEntry = ttk.Entry(dialog, width=40)
        urlEntry.grid(row=1, column=1, padx=10, pady=5)

        def saveVideo():
            title = titleEntry.get().strip()
            url = urlEntry.get().strip()
            
            if not url:
                messagebox.showwarning("Input Error", "Video URL cannot be empty.", parent=dialog)
                return
                
            if not (url.startswith("http://") or url.startswith("https://")):
                 messagebox.showwarning("Input Error", "Please enter a valid URL starting with http:// or https://", parent=dialog)
                 return

            userId = self.controller.getCurrentUser().get('user_id')
            query = """
                INSERT INTO GuideVideos (guide_id, video_url, video_title, added_by_user_id) 
                VALUES (%s, %s, %s, %s)
            """
            videoTitle = title if title else None 
            
            if executeQuery(query, (self.currentGuideId, url, videoTitle, userId)):
                dialog.destroy()
                self.loadVideosForGuide(self.currentGuideId)
            else:
                messagebox.showerror("Error", "Failed to add video.", parent=dialog)

        saveButton = ttk.Button(dialog, text="Add Video", command=saveVideo)
        saveButton.grid(row=2, column=0, columnspan=2, pady=15)
        urlEntry.focus()

    def openSelectedVideoUrl(self):
        selectedItem = self.videosTree.focus()
        if not selectedItem:
             messagebox.showwarning("Selection Error", "Please select a video to open.")
             return
             
        url = self.videosTree.item(selectedItem)['values'][1]
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open URL:\n{e}")


class SettingsFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Settings")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1)

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        self.adminButton = ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame"))
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.mainContent = ttk.Frame(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ttk.Label(self.mainContent, text="Settings", font=("Helvetica", 16, "bold")).pack(pady=10)
        ttk.Label(self.mainContent, text="Settings section is currently under daevelopment.").pack(pady=20)

    def onShow(self):
        self.controller.title("FTC Portal - Settings")
        userInfo = self.controller.getCurrentUser()
        if not userInfo:
             self.controller.showFrame("LoginFrame")
             return
             
        if userInfo.get('is_admin'):
             self.adminButton.grid(row=5, column=0, sticky="ew", padx=5, pady=5)
        else:
             self.adminButton.grid_remove()


class AdminFrame(BaseFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, controller)
        self.controller.title("FTC Portal - Admin Panel")
        
        self.sidebar = ttk.Frame(self, width=150, style='Card.TFrame', relief=tk.RIDGE)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=5, pady=5)
        self.sidebar.grid_rowconfigure(6, weight=1)

        ttk.Button(self.sidebar, text="Dashboard", command=lambda: controller.showFrame("DashboardFrame")).grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Attendance", command=lambda: controller.showFrame("AttendanceFrame")).grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Scouting", command=lambda: controller.showFrame("ScoutingFrame")).grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Guides", command=lambda: controller.showFrame("GuidesFrame")).grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Settings", command=lambda: controller.showFrame("SettingsFrame")).grid(row=4, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Admin Panel", command=lambda: controller.showFrame("AdminFrame")).grid(row=5, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(self.sidebar, text="Logout", command=controller.logout).grid(row=7, column=0, sticky="ew", padx=5, pady=10)

        self.mainContent = ttk.Notebook(self)
        self.mainContent.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.userMgmtTab = ttk.Frame(self.mainContent, padding=10)
        self.mainContent.add(self.userMgmtTab, text='User Management')
        
        pendingFrame = ttk.LabelFrame(self.userMgmtTab, text="Pending Join Requests", padding=10)
        pendingFrame.pack(fill="x", pady=10)
        
        self.pendingUsersTree = ttk.Treeview(pendingFrame, columns=("username", "requested_at"), show="headings")
        self.pendingUsersTree.heading("username", text="Username")
        self.pendingUsersTree.heading("requested_at", text="Requested At")
        self.pendingUsersTree.column("requested_at", width=150)
        self.pendingUsersTree.pack(fill="x", expand=True, side=tk.LEFT, padx=(0, 5))
        
        pendingActionsFrame = ttk.Frame(pendingFrame)
        pendingActionsFrame.pack(side=tk.LEFT, fill="y", padx=(5,0))
        ttk.Button(pendingActionsFrame, text="Approve Selected", command=self.approveSelectedUser).pack(pady=5, fill="x")
        ttk.Button(pendingActionsFrame, text="Reject Selected", command=self.rejectSelectedUser).pack(pady=5, fill="x")

        activeFrame = ttk.LabelFrame(self.userMgmtTab, text="Active Users & Roles", padding=10)
        activeFrame.pack(fill="both", expand=True, pady=10)
        
        self.activeUsersTree = ttk.Treeview(activeFrame, columns=("username", "role", "is_admin"), show="headings")
        self.activeUsersTree.heading("username", text="Username")
        self.activeUsersTree.heading("role", text="Assigned Role")
        self.activeUsersTree.heading("is_admin", text="Admin Status")
        self.activeUsersTree.column("is_admin", width=80, anchor=tk.CENTER)
        self.activeUsersTree.pack(fill="both", expand=True, side=tk.LEFT, padx=(0, 5))

        roleActionsFrame = ttk.Frame(activeFrame)
        roleActionsFrame.pack(side=tk.LEFT, fill="y", padx=(5,0))
        ttk.Label(roleActionsFrame, text="Assign Role:").pack(pady=(0,2))
        self.roleCombobox = ttk.Combobox(roleActionsFrame, state="readonly", width=15)
        self.roleCombobox.pack(pady=(0, 5), fill="x")
        ttk.Button(roleActionsFrame, text="Set Role", command=self.assignSelectedUserRole).pack(pady=2, fill="x")
        self.toggleAdminButton = ttk.Button(roleActionsFrame, text="Toggle Admin", command=self.toggleSelectedUserAdmin)
        self.toggleAdminButton.pack(pady=10, fill="x")
        ttk.Button(roleActionsFrame, text="Remove User", command=self.removeSelectedUser).pack(pady=10, fill="x")


        self.teamSettingsTab = ttk.Frame(self.mainContent, padding=10)
        self.mainContent.add(self.teamSettingsTab, text='Team Settings')

        ttk.Label(self.teamSettingsTab, text="Team Name:").grid(row=0, column=0, padx=5, pady=10, sticky="w")
        self.teamNameSettingEntry = ttk.Entry(self.teamSettingsTab, width=40)
        self.teamNameSettingEntry.grid(row=0, column=1, padx=5, pady=10)
        ttk.Button(self.teamSettingsTab, text="Update Name", command=self.updateTeamName).grid(row=0, column=2, padx=10, pady=10)

        ttk.Label(self.teamSettingsTab, text="Team Password:").grid(row=1, column=0, padx=5, pady=10, sticky="w")
        self.teamPwdSettingEntry = ttk.Entry(self.teamSettingsTab, show="*", width=40)
        self.teamPwdSettingEntry.grid(row=1, column=1, padx=5, pady=10)
        ttk.Button(self.teamSettingsTab, text="Update Password", command=self.updateTeamPassword).grid(row=1, column=2, padx=10, pady=10)
        
        ttk.Label(self.teamSettingsTab, text="Database URL:", foreground="grey").grid(row=2, column=0, padx=5, pady=10, sticky="w")
        self.dbUrlSettingLabel = ttk.Label(self.teamSettingsTab, text=dbUrlUsed or "N/A", foreground="grey", wraplength=300)
        self.dbUrlSettingLabel.grid(row=2, column=1, padx=5, pady=10, sticky="w")
        ttk.Label(self.teamSettingsTab, text="(Cannot change via app)", foreground="grey").grid(row=2, column=2, padx=10, pady=10, sticky="w")
        

    def onShow(self):
        self.controller.title("FTC Portal - Admin Panel")
        userInfo = self.controller.getCurrentUser()
        if not userInfo or not userInfo.get('is_admin'):
             messagebox.showerror("Access Denied", "You do not have permission to access the Admin Panel.")
             self.controller.showFrame("DashboardFrame")
             return

        self.loadPendingUsers()
        self.loadActiveUsersAndRoles()
        self.loadTeamSettings()
        self.loadAvailableRoles()

    def loadPendingUsers(self):
         for item in self.pendingUsersTree.get_children():
            self.pendingUsersTree.delete(item)
            
         query = "SELECT user_id, username, created_at FROM Users WHERE is_pending = TRUE ORDER BY created_at"
         users = executeQuery(query, fetch=True)
         
         if users:
              for user in users:
                  reqTime = user['created_at'].strftime('%Y-%m-%d %H:%M') if user['created_at'] else 'N/A'
                  self.pendingUsersTree.insert("", tk.END, iid=user['user_id'], values=(user['username'], reqTime))
         elif users is None:
             self.pendingUsersTree.insert("", tk.END, values=("Error loading requests", ""))

    def loadActiveUsersAndRoles(self):
        for item in self.activeUsersTree.get_children():
            self.activeUsersTree.delete(item)

        query = """
            SELECT u.user_id, u.username, u.is_admin, r.role_name 
            FROM Users u
            LEFT JOIN Roles r ON u.role_id = r.role_id
            WHERE u.is_pending = FALSE 
            ORDER BY u.username
        """
        users = executeQuery(query, fetch=True)
        
        if users:
             for user in users:
                 roleName = user['role_name'] or "None"
                 isAdmin = "Yes" if user['is_admin'] else "No"
                 self.activeUsersTree.insert("", tk.END, iid=user['user_id'], values=(user['username'], roleName, isAdmin))
        elif users is None:
             self.activeUsersTree.insert("", tk.END, values=("Error loading users", "", ""))


    def loadAvailableRoles(self):
        query = "SELECT role_id, role_name FROM Roles ORDER BY role_name"
        roles = executeQuery(query, fetch=True)
        self.roleMap = {role['role_name']: role['role_id'] for role in roles} if roles else {}
        roleNames = list(self.roleMap.keys())
        self.roleCombobox['values'] = roleNames
        if roleNames:
            self.roleCombobox.set(roleNames[0])
            
    def loadTeamSettings(self):
        teamData = self.controller.getTeamInfo()
        if teamData:
             self.teamNameSettingEntry.delete(0, tk.END)
             self.teamNameSettingEntry.insert(0, teamData.get('team_name', ''))
             self.teamPwdSettingEntry.delete(0, tk.END)
             self.dbUrlSettingLabel.config(text=dbUrlUsed or "N/A")
        else:
            self.teamNameSettingEntry.delete(0, tk.END)
            self.teamNameSettingEntry.insert(0, "Error loading")
            self.teamNameSettingEntry.config(state=tk.DISABLED)
            self.teamPwdSettingEntry.config(state=tk.DISABLED)

    def approveSelectedUser(self):
        selectedItem = self.pendingUsersTree.focus()
        if not selectedItem: return
        userId = selectedItem

        if messagebox.askyesno("Confirm Approval", f"Approve user '{self.pendingUsersTree.item(userId)['values'][0]}'?"):
             query = "UPDATE Users SET is_pending = FALSE WHERE user_id = %s AND is_pending = TRUE"
             if executeQuery(query, (userId,)):
                 messagebox.showinfo("Success", "User approved.")
                 self.loadPendingUsers()
                 self.loadActiveUsersAndRoles()
             else:
                 messagebox.showerror("Error", "Failed to approve user.")

    def rejectSelectedUser(self):
        selectedItem = self.pendingUsersTree.focus()
        if not selectedItem: return
        userId = selectedItem
        username = self.pendingUsersTree.item(userId)['values'][0]

        if messagebox.askyesno("Confirm Rejection", f"Reject and DELETE join request for '{username}'? This cannot be undone."):
             query = "DELETE FROM Users WHERE user_id = %s AND is_pending = TRUE"
             if executeQuery(query, (userId,)):
                  messagebox.showinfo("Success", "User request rejected and removed.")
                  self.loadPendingUsers()
             else:
                  messagebox.showerror("Error", "Failed to reject user.")

    def assignSelectedUserRole(self):
        selectedItem = self.activeUsersTree.focus()
        selectedRoleName = self.roleCombobox.get()
        
        if not selectedItem:
            messagebox.showwarning("Selection Error", "Please select a user from the 'Active Users' list.")
            return
        if not selectedRoleName:
            messagebox.showwarning("Selection Error", "Please select a role to assign.")
            return
            
        userId = selectedItem
        roleId = self.roleMap.get(selectedRoleName)
        
        if roleId is None:
             messagebox.showerror("Internal Error", "Selected role ID not found.")
             return

        query = "UPDATE Users SET role_id = %s WHERE user_id = %s"
        if executeQuery(query, (roleId, userId)):
             self.loadActiveUsersAndRoles()
        else:
             messagebox.showerror("Error", "Failed to update user role.")

    def toggleSelectedUserAdmin(self):
         selectedItem = self.activeUsersTree.focus()
         if not selectedItem:
             messagebox.showwarning("Selection Error", "Please select a user from the 'Active Users' list.")
             return
             
         userId = selectedItem
         username = self.activeUsersTree.item(userId)['values'][0]
         currentAdminStatus = self.activeUsersTree.item(userId)['values'][2] == "Yes"
         
         action = "Remove admin status from" if currentAdminStatus else "Grant admin status to"
         newStatus = not currentAdminStatus
         
         if messagebox.askyesno("Confirm Admin Toggle", f"{action} user '{username}'?"):
              query = "UPDATE Users SET is_admin = %s WHERE user_id = %s"
              if executeQuery(query, (newStatus, userId)):
                   self.loadActiveUsersAndRoles()
              else:
                   messagebox.showerror("Error", "Failed to update admin status.")


    def removeSelectedUser(self):
        selectedItem = self.activeUsersTree.focus()
        if not selectedItem:
            messagebox.showwarning("Selection Error", "Please select a user from the 'Active Users' list to remove.")
            return
            
        userId = selectedItem
        username = self.activeUsersTree.item(userId)['values'][0]
        currentUserInfo = self.controller.getCurrentUser()
        
        if currentUserInfo and currentUserInfo.get('user_id') == int(userId):
             messagebox.showerror("Action Denied", "You cannot remove your own account.")
             return

        if messagebox.askyesno("Confirm Removal", f"Permanently REMOVE user '{username}' and all their associated data (attendance, etc.)? This cannot be undone."):
            query = "DELETE FROM Users WHERE user_id = %s"
            if executeQuery(query, (userId,)):
                 messagebox.showinfo("Success", f"User '{username}' removed.")
                 self.loadActiveUsersAndRoles()
            else:
                 messagebox.showerror("Error", f"Failed to remove user '{username}'.")


    def updateTeamName(self):
        newName = self.teamNameSettingEntry.get().strip()
        teamData = self.controller.getTeamInfo()
        if not newName:
             messagebox.showwarning("Input Error", "Team name cannot be empty.")
             return
        if not teamData or 'team_number' not in teamData:
             messagebox.showerror("Error", "Cannot update - current team info not loaded.")
             return
             
        currentTeamNumber = teamData['team_number']
        
        query = "UPDATE TeamInfo SET team_name = %s WHERE team_number = %s"
        if executeQuery(query, (newName, currentTeamNumber)):
             messagebox.showinfo("Success", "Team name updated.")
             teamInfo['team_name'] = newName
        else:
             messagebox.showerror("Error", "Failed to update team name.")

    def updateTeamPassword(self):
        newPassword = self.teamPwdSettingEntry.get()
        teamData = self.controller.getTeamInfo()

        if not newPassword:
             messagebox.showwarning("Input Error", "Team password cannot be empty.")
             return
        if not teamData or 'team_number' not in teamData:
             messagebox.showerror("Error", "Cannot update - current team info not loaded.")
             return
             
        currentTeamNumber = teamData['team_number']
        
        if messagebox.askyesno("Confirm Password Change", "Are you sure you want to change the team password?"):
             hashedPass = hashPassword(newPassword)
             query = "UPDATE TeamInfo SET team_password_hash = %s WHERE team_number = %s"
             if executeQuery(query, (hashedPass, currentTeamNumber)):
                  messagebox.showinfo("Success", "Team password updated.")
                  self.teamPwdSettingEntry.delete(0, tk.END)
             else:
                  messagebox.showerror("Error", "Failed to update team password.")


# --- Main Execution ---
if __name__ == "__main__":
    app = FtcPortalApp()
    
    def onClosing():
        print("Closing application...")
        closeDb()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", onClosing)
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected, closing.")
        onClosing()