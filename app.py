# app.py

import os
from factory import create_app, socketio

# Create the Flask app instance
app = create_app()

# Expose app and socketio for external use (e.g., Azure with gunicorn)
# Azure will use: gunicorn --worker-class eventlet -w 1 app:app --bind=0.0.0.0:$PORT

# Only run the app with socketio.run() if this file is the main entry point (local dev)
if __name__ == '__main__':
    is_local = os.getenv('DEPLOY_ENV', 'local') == 'local'

    # Use Azure-injected port if available, fallback to 5000 (local)
    port = int(os.getenv('PORT', 5000))

    socketio.run(
        app,
        debug=is_local,
        host='localhost' if is_local else '0.0.0.0',
        port=port,
        use_reloader=False
    )
