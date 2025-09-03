import logging

def setup_logger(name, log_file, level=logging.INFO):
    """Function to setup as many loggers as you want"""
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    # Prevent duplicate logging to console if root logger is also configured
    logger.propagate = False

    # Optional: If you also want to see logs in the console
    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler)

    return logger

# Example of a global logger for the strategy
strategy_logger = setup_logger('strategy_logger', 'strategy.log')
