import logging
import collections
from flask_socketio import SocketIO

# This will be initialized by the main app/factory
sio_instance: SocketIO = None
strategy_log_buffer = collections.deque(maxlen=50)

def initialize_socketio_for_logging(sio: SocketIO):
    global sio_instance
    sio_instance = sio

class StrategyLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        # Set a default formatter if you want specific formatting for these logs
        # Or rely on the logger's existing formatter
        # self.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))


    def emit(self, record: logging.LogRecord):
        # We check sio_instance directly; an alternative is to pass it via constructor
        # but that might be tricky with how loggers are configured early.
        # This means initialize_socketio_for_logging MUST be called before logs are emitted.
        if sio_instance:
            log_entry = self.format(record) # Use the handler's or logger's formatter
            strategy_log_buffer.append(log_entry)
            try:
                sio_instance.emit('live_strategy_log', {'data': log_entry})
            except Exception as e:
                # Handle cases where emit might fail (e.g., during shutdown, tests without proper sio mock)
                # Using a simple print for now, a more robust app might log to a fallback or stderr.
                print(f"Error emitting log via Socket.IO: {e}")
        else:
            # Fallback or warning if Socket.IO instance is not yet available
            print(f"Socket.IO not initialized for StrategyLogHandler, log: {self.format(record)}")

# Function to get current buffered logs (e.g., for new client connections)
def get_buffered_strategy_logs() -> list[str]:
    return list(strategy_log_buffer)
