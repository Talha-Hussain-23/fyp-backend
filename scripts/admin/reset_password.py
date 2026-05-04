from pymongo import MongoClient
import os
from dotenv import load_dotenv
from passlib.context import CryptContext

load_dotenv()

uri = os.getenv("MONGODB_URI")
# Force correct DB
db_name = "HiringProcess" 

print(f"Connecting to {db_name}...")
client = MongoClient(uri)
db = client[db_name]

email = "mtalha23hussain@gmail.com"
new_password = "Smarthiring@123"

# Setup hashing similar to backend
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
hashed_password = pwd_context.hash(new_password)

result = db.users.update_one(
    {"email": email},
    {"$set": {
        "hashed_password": hashed_password,
        "is_verified": True # Ensure verification too
    }}
)

if result.modified_count > 0:
    print(f"✅ Password reset for {email}")
    print(f"New Password: {new_password}")
else:
    print(f"⚠️  User not found or password match.")
