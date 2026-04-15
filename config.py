"""
সব কনফিগারেশন এক জায়গায়
এখানেই সব সেটিংস পরিবর্তন করবেন
"""

import os
from pathlib import Path

# ======================== BOT CONFIGURATION ========================
BOT_TOKEN = "8695141646:AAHiErFK31dIly6934d-ZkMCgf24IfBOwW0"  # @BotFather থেকে পান
ADMIN_IDS = [7165975728]  # আপনার টেলিগ্রাম ID (https://t.me/userinfobot দিয়ে পাবেন)

# ======================== DATABASE CONFIGURATION ========================
DB_PATH = "users.db"
USERS_FILES_DIR = "user_files"

# ======================== PAYMENT CONFIGURATION ========================
# bKash এর জায়গায় ম্যানুয়াল ট্রান্সফার অ্যাকাউন্ট
PAYMENT_ACCOUNTS = {
    "bkash": {
        "number": "01839978299",  # আপনার বিকাশ ��ম্বর
        "name": "আপনার নাম",
        "merchant_id": "XXXXXXXXX"  # অপশনাল
    },
    "nagad": {
        "number": "01839978299",  # আপনার নগদ নম্বর
        "name": "☁️ CloudHostBot"
    },
    "rocket": {
        "number": "01839978299",  # আপনার রকেট নম্বর
        "name": "☁️ CloudHostBot"
    }
}

# ======================== SUBSCRIPTION PLANS ========================
PLANS = {
    "free": {
        "name": "Free",
        "max_files": 2,
        "max_processes": 1,
        "max_storage_gb": 0.01,
        "price": 0
    },
    "premium": {
        "name": "Premium",
        "max_files": 10,
        "max_processes": 5,
        "max_storage_gb": 0.05,
        "price": 99,  # টাকা
        "days": 30
    },
    "pro": {
        "name": "Pro",
        "max_files": 50,
        "max_processes": 15,
        "max_storage_gb": 1,
        "price": 299,  # টাকা
        "days": 30
    }
}

# ======================== SCRIPT EXECUTION CONFIG ========================
MAX_MEMORY_PER_SCRIPT_MB = 100  # প্রতিটি স্ক্রিপ্টের ম্যাক্স মেমোরি
MAX_SCRIPT_TIMEOUT_SECONDS = 3600  # ১ ঘন্টা

# ======================== FILE UPLOAD CONFIG ========================
ALLOWED_FILE_EXTENSIONS = ('.py', '.js', '.zip', '.txt', '.json', '.env')
MAX_FILE_SIZE_MB = 50
MAX_TOTAL_STORAGE_PER_USER_MB = {
    "free": 500,
    "premium": 10 * 1024,  # 10 GB
    "pro": 100 * 1024  # 100 GB
}

# ======================== LOGGING CONFIG ========================
LOG_LEVEL = "INFO"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# ======================== DIRECTORIES ========================
Path(USERS_FILES_DIR).mkdir(exist_ok=True)

# ======================== MESSAGES ========================
MESSAGES = {
    "welcome": """
🎉 স্বাগতম {first_name}!

এটি একটি সম্পূর্ণ ক্লাউড হোস্টিং প্ল্যাটফর্ম যেখানে আপনি:
✅ পাইথন/নোড.জেএস স্ক্রিপ্ট চালাতে পারবেন
✅ ফাইল আপলোড/ডাউনলোড করতে পারবেন
✅ প্রসেস ম্যানেজ করতে পারবেন
✅ লাইভ লগ দেখতে পারবেন

👇 নিচের মেনু দিয়ে শুরু করুন
    """,
    
    "payment_instructions": """
💳 পেমেন্ট নির্দেশনা

পরিমাণ: {amount} টাকা
প্ল্যান: {plan}

📞 নিচের নম্বরে টাকা পাঠান:
{payment_method}: {account_number}
নাম: {account_name}

✅ পাঠানোর পরে:
1. ট্রানজেকশন ��ইডি কপি করুন
2. স্ক্রিনশট নিন
3. বটে পাঠান
    """
}