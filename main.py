from src.bot import client
from src.config import ACCESS_TOKEN, PREVIEWS_DIR
from src.database import init_database

PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
init_database()
client.run(ACCESS_TOKEN)
