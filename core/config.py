# core/config.py

import os
import yaml

def load_config(path="config.yaml"):
    if path == "config.yaml" and os.path.exists("settings.yaml"):
        path = "settings.yaml"

    try:
        with open(path, "r") as file:
            config = yaml.safe_load(file) or {}
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}
    
    db = config.get("database", {})
    if db.get("engine") == "sqlite":
        config["SQLALCHEMY_DATABASE_URI"] = db.get(
            "path", "sqlite:///default.db"
        )
    elif db.get("engine") == "postgresql":
        config["SQLALCHEMY_DATABASE_URI"] = (
            f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"
        )

    engine_opts = {
        "pool_size": db.get("pool_size", 5),
        "max_overflow": db.get("max_overflow", 10),
    }
    config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts

    # Set a fallback
    config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    return config
