import yaml
from core.backtester import run_backtest
from modules.utils import get_pairs

# with open("config.yaml", "r") as file:
#     config = yaml.safe_load(file)

pairs = get_pairs()
run_backtest(pairs)
