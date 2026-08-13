"""Loads .env once, as early as possible.

Import this (for its side effect) before any module-level os.environ.get()
call, so DATABASE_URL/APP_SECRET_KEY/SNAPTRADE_*/AWS_* etc. can come from a
local .env file instead of requiring shell exports - handy for anyone
forking this repo. load_dotenv() never overrides a variable already set in
the real environment, so this is safe alongside existing shell-based setups.
"""

from dotenv import load_dotenv

load_dotenv()
