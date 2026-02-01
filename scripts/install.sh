#!/bin/bash

# ==============================================================================
# DeskThing-Pi Interactive Installer
# ==============================================================================

set -e

# --- Configuration ---
INSTALL_DIR="/opt/deskthing"
SERVICE_NAME="deskthing.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC_DIR="$SCRIPT_DIR/../app" # Locating /app relative to /scripts
DUMMY_MODE=false

# --- Formatting & Colors ---
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Helper Functions ---

# Pretty Print Headers
print_header() {
    echo -e "\n${BOLD}${BLUE}============================================================${NC}"
    echo -e "${BOLD}${CYAN}  $1${NC}"
    echo -e "${BOLD}${BLUE}============================================================${NC}\n"
}

# Log Types
log_info() { echo -e "${BOLD}[INFO]${NC} $1"; }
log_success() { echo -e "${BOLD}${GREEN}[OK]${NC}   $1"; }
log_warn() { echo -e "${BOLD}${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${BOLD}${RED}[ERR]${NC}  $1"; }

# Command Executor (Handles Dummy Mode)
execute_cmd() {
    local cmd_str="$*"
    if [ "$DUMMY_MODE" = true ]; then
        echo -e "${YELLOW}[DRY-RUN] Would execute:${NC} $cmd_str"
    else
        eval "$cmd_str"
    fi
}

# User Prompt
ask_yes_no() {
    local prompt="$1"
    local default="$2"
    if [ "$DUMMY_MODE" = true ]; then
        echo -e "${YELLOW}[DRY-RUN] Question:${NC} $prompt (Auto-answering Yes)"
        return 0
    fi
    
    local yn
    while true; do
        read -p "$(echo -e "${BOLD}${prompt} [Y/n]${NC} ")" yn
        case $yn in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            "" ) return 0;; # Default to Yes
            * ) echo "Please answer yes or no.";;
        esac
    done
}

# --- Argument Parsing ---
for arg in "$@"; do
    case $arg in
        --dummy)
            DUMMY_MODE=true
            print_header "RUNNING IN DUMMY MODE (No changes will be made)"
            ;;
    esac
done

# --- Pre-flight Checks ---
if [ "$EUID" -ne 0 ] && [ "$DUMMY_MODE" = false ]; then
    log_error "This script must be run as root (sudo)."
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    DISTRO_ID=$ID
else
    OS=$(uname -s)
    DISTRO_ID="unknown"
fi

# ==============================================================================
# Start Install
# ==============================================================================

print_header "Welcome to the DeskThing Installer"
log_info "Operating System: $OS"
log_info "Source Directory: $APP_SRC_DIR"
log_info "Install Target:   $INSTALL_DIR"

if ! ask_yes_no "Do you want to proceed with the installation?"; then
    log_info "Installation aborted by user."
    exit 0
fi

# 1. System Dependencies
# ==============================================================================
print_header "Step 1: System Dependencies"

if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "raspbian" ]]; then
    if ask_yes_no "Update apt repositories and upgrade packages?"; then
        execute_cmd "export DEBIAN_FRONTEND=noninteractive"
        execute_cmd "apt-get update && apt-get upgrade -y"
    fi

    log_info "Installing dependencies (Python, Cage, Qt, WebEngine)..."
    # Specific list for Debian/RaspiOS
    DEPS="python3-pip python3-venv cage passwd \
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 \
    libxcb-xfixes0 libgl1 libegl1 libfontconfig1 \
    ffmpeg libsnappy1v5 libxcomposite1 libxdamage1 libxrandr2 libxss1 \
    libxtst6 libnss3 libasound2t64 libpci3 libopus0 libgtk-3-0 libxshmfence1 \
    libminizip1 fonts-liberation fonts-dejavu fonts-noto-cjk fonts-noto-cjk-extra"
    
    execute_cmd "apt-get install -y $DEPS"
    log_success "Dependencies installed."
else
    log_warn "Non-Debian OS detected ($DISTRO_ID). Automatic dependency installation is skipped."
    log_warn "Please manually ensure 'python3', 'cage', and necessary Qt/WebEngine libraries are installed."
    if ! ask_yes_no "Continue anyway?"; then exit 1; fi
fi

# 2. User Setup
# ==============================================================================
print_header "Step 2: User Configuration"
log_info "Setting up dedicated user 'deskthing'..."

if id "deskthing" &>/dev/null; then
    log_info "User 'deskthing' already exists. Skipping creation."
else
    execute_cmd "/usr/sbin/useradd -r -m -d $INSTALL_DIR -s /usr/sbin/nologin deskthing"
    execute_cmd "/usr/sbin/usermod -a -G video,render,tty,input deskthing"
    log_success "User created."
fi

# 3. Application Install
# ==============================================================================
print_header "Step 3: Installing Application"

# Check if source exists
if [ ! -f "$APP_SRC_DIR/main.py" ]; then
    log_error "Could not find main.py in $APP_SRC_DIR."
    log_error "Ensure the script is running from the /scripts/ folder and /app/ exists."
    exit 1
fi

execute_cmd "mkdir -p $INSTALL_DIR"
log_info "Copying files from $APP_SRC_DIR to $INSTALL_DIR..."
execute_cmd "cp $APP_SRC_DIR/main.py $INSTALL_DIR/"
execute_cmd "cp $APP_SRC_DIR/requirements.txt $INSTALL_DIR/"

log_info "Setting up Python Virtual Environment..."
execute_cmd "cd $INSTALL_DIR && python3 -m venv venv"

if [ "$DUMMY_MODE" = false ]; then
    log_info "Installing pip requirements (this may take a moment)..."
    source $INSTALL_DIR/venv/bin/activate
    pip install -r $INSTALL_DIR/requirements.txt
    deactivate
else
    echo -e "${YELLOW}[DRY-RUN] Would run: pip install -r requirements.txt${NC}"
fi

log_info "Setting permissions..."
execute_cmd "chown -R deskthing:deskthing $INSTALL_DIR"
log_success "Application files installed."

# 4. Service Creation
# ==============================================================================
print_header "Step 4: Systemd Service"

SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

if [ "$DUMMY_MODE" = false ]; then
    cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=DeskThing Kiosk Interface
Documentation=https://github.com/cage-kiosk/cage
After=systemd-user-sessions.service plymouth-quit-wait.service gettys.target network-online.target
Conflicts=getty@tty1.service
After=getty@tty1.service

[Service]
User=deskthing
WorkingDirectory=$INSTALL_DIR
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes

# Environment
Environment=XDG_SESSION_TYPE=wayland
Environment=QT_QPA_PLATFORM=wayland
Environment=QTWEBENGINE_DISABLE_SANDBOX=1
Environment=DISPLAY=:0

ExecStart=/usr/bin/cage -s -- $INSTALL_DIR/venv/bin/python main.py

Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
Alias=display-manager.service
EOF
    log_success "Service file written to $SERVICE_FILE"
else
    echo -e "${YELLOW}[DRY-RUN] Would write content to $SERVICE_FILE${NC}"
fi

if ask_yes_no "Enable deskthing service on boot?"; then
    execute_cmd "systemctl enable deskthing"
    log_success "Service enabled."
fi

# 5. Cleanup & Finish
# ==============================================================================
print_header "Step 5: Cleanup"
execute_cmd "apt-get clean"
execute_cmd "rm -rf /var/lib/apt/lists/*"

print_header "Installation Complete!"
log_success "DeskThing-pi has been successfully set up."

if ask_yes_no "Would you like to reboot now to start the Kiosk?"; then
    execute_cmd "reboot"
else
    log_info "You can start the service manually later with: systemctl start deskthing"
fi