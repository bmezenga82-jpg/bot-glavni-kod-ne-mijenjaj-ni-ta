#!/bin/bash
# CryptoBot — systemd service setup
# Pokreni jednom iz direktorija gdje je kod:
#   bash setup_service.sh

set -e

SERVICE_NAME="cryptobot"
USER=$(whoami)
WORKDIR=$(pwd)
PYTHON=$(command -v python3 || command -v python)
GUNICORN=$(command -v gunicorn 2>/dev/null || echo "")

echo "========================================"
echo " CryptoBot — postavljanje 24/7 servisa"
echo "========================================"
echo " Korisnik:   $USER"
echo " Direktorij: $WORKDIR"
echo " Python:     $PYTHON"
echo ""

# Instaliraj gunicorn ako nije dostupan
if [ -z "$GUNICORN" ]; then
    echo "Instaliram gunicorn i eventlet..."
    $PYTHON -m pip install gunicorn eventlet
    GUNICORN=$(command -v gunicorn)
fi

echo " Gunicorn:   $GUNICORN"
echo ""

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Kreiram $SERVICE_FILE ..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=CryptoBot Trading Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=$WORKDIR
ExecStart=$GUNICORN --worker-class eventlet -w 1 app:app --bind=0.0.0.0:5000 --timeout 120 --keep-alive 5
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "Aktiviram servis..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2
STATUS=$(sudo systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown")

echo ""
echo "========================================"
if [ "$STATUS" = "active" ]; then
    echo " ✓ CryptoBot servis je AKTIVAN!"
else
    echo " ✗ Servis status: $STATUS"
    echo "   Provjeri: sudo journalctl -u $SERVICE_NAME -n 30"
fi
echo "========================================"
echo ""
echo "Korisni commandovi:"
echo "  sudo systemctl status $SERVICE_NAME       # Status"
echo "  sudo journalctl -u $SERVICE_NAME -f       # Logovi live"
echo "  sudo systemctl restart $SERVICE_NAME      # Ručni restart"
echo "  sudo systemctl stop $SERVICE_NAME         # Zaustavi"
echo ""
echo "Bot se sada automatski pokreće pri svakom restartu servera"
echo "i restarta se sam unutar 15 sekundi ako pukne."
