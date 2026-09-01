from src.bot import client
from src.config import ACCESS_TOKEN
from src.database import init_database

init_database()
client.run(ACCESS_TOKEN)
