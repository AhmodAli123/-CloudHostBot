"""
সম্পূর্ণ ক্লাউড হোস্টিং বট
সব ফিচার একসাথে
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from functools import wraps
import asyncio

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, 
    InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# ✅ এটি যথেষ্ট - কোনো sys.path ঝামেলা নেই!
from config import (
    BOT_TOKEN, ADMIN_IDS, DB_PATH, USERS_FILES_DIR, PLANS,
    PAYMENT_ACCOUNTS, LOG_LEVEL, LOG_FORMAT
)
from file_manager import FileUploadHandler, ZipHandler, EnvFileHandler, ScriptExecutor
from manual_payment_system import ManualPaymentProcessor, ManualPaymentConfig
# ======================== LOGGING SETUP ========================
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

# ======================== CONVERSATION STATES ========================
MAIN_MENU, FILE_MENU, EXECUTION_MENU, SELECT_PLAN, SELECT_PAYMENT_METHOD = range(5)
SEND_TRANSACTION_ID, SEND_SCREENSHOT, ADMIN_MENU = range(3)

# ======================== DATABASE SETUP ========================
class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                join_date TIMESTAMP,
                last_activity TIMESTAMP,
                plan TEXT DEFAULT 'free',
                premium_expiry TIMESTAMP,
                total_files INTEGER DEFAULT 0,
                total_processes INTEGER DEFAULT 0,
                storage_used_mb REAL DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
        ''')
        
        # Files table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                filename TEXT,
                file_path TEXT,
                file_size_mb REAL,
                upload_date TIMESTAMP,
                is_running INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Processes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processes (
                process_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_id INTEGER,
                process_name TEXT,
                start_time TIMESTAMP,
                pid INTEGER,
                status TEXT DEFAULT 'running',
                memory_usage_mb REAL,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(file_id) REFERENCES files(file_id)
            )
        ''')
        
        # Logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_id INTEGER,
                timestamp TIMESTAMP,
                log_message TEXT,
                FOREIGN KEY(process_id) REFERENCES processes(process_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def execute(self, query, params=()):
        """Execute query"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        result = cursor.fetchall()
        conn.close()
        return result
    
    def get_user(self, user_id):
        """Get user info"""
        result = self.execute(
            'SELECT * FROM users WHERE user_id = ?', 
            (user_id,)
        )
        return result[0] if result else None
    
    def create_user(self, user_id, username, full_name):
        """Create new user"""
        now = datetime.now().isoformat()
        self.execute('''
            INSERT INTO users (user_id, username, full_name, join_date, last_activity, plan)
            VALUES (?, ?, ?, ?, ?, 'free')
        ''', (user_id, username, full_name, now, now))
    
    def update_premium(self, user_id, plan, days=30):
        """Update user premium plan"""
        expiry = (datetime.now() + timedelta(days=days)).isoformat()
        self.execute(
            'UPDATE users SET plan = ?, premium_expiry = ? WHERE user_id = ?',
            (plan, expiry, user_id)
        )
    
    def check_premium_expiry(self, user_id):
        """Check if premium expired and downgrade"""
        user = self.get_user(user_id)
        if user and user[5] == 'premium':
            expiry = datetime.fromisoformat(user[6])
            if datetime.now() > expiry:
                self.execute(
                    'UPDATE users SET plan = ? WHERE user_id = ?',
                    ('free', user_id)
                )
                return True
        return False

# ======================== GLOBAL INSTANCES ========================
db = Database(DB_PATH)
file_handler = FileUploadHandler(DB_PATH)
zip_handler = ZipHandler(DB_PATH)
env_handler = EnvFileHandler(DB_PATH)
script_executor = ScriptExecutor(DB_PATH)
payment_processor = ManualPaymentProcessor(DB_PATH)

# ======================== DECORATORS ========================
def is_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text(
                "❌ শুধুমাত্র অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন।"
            )
            return
        return await func(update, context)
    return wrapper

def is_not_banned(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        if user and user[10] == 1:  # is_banned column
            await update.message.reply_text(
                "⛔ আপনি ব্যান করা হয়েছেন।"
            )
            return
        return await func(update, context)
    return wrapper

# ======================== KEYBOARD HELPERS ========================
def get_main_keyboard():
    """Main menu reply keyboard"""
    keyboard = [
        ["📁 ফাইল ম্যানেজমেন্ট", "⚙️ স্ক্রিপ্ট এক্সিকিউশন"],
        ["📊 স্ট্যাটিস্টিক্স", "💳 প্রিমিয়াম কিনুন"],
        ["❓ সাহায্য", "👤 প্রোফাইল"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_file_keyboard():
    """File management keyboard"""
    keyboard = [
        ["📤 ফাইল আপলোড", "📋 আমার ফাইলগুলি"],
        ["🗑️ ফাইল ডিলিট", "🔙 ফিরে যান"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_execution_keyboard():
    """Script execution keyboard"""
    keyboard = [
        ["▶️ স্ক্রিপ্ট চালান", "⏹️ স্ক্রিপ্ট থামান"],
        ["📜 লগ দেখুন", "🔙 ফিরে যান"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    """Admin panel keyboard"""
    keyboard = [
        ["👥 সব ইউজার", "📊 সিস্টেম স্ট্যাটাস"],
        ["💳 অপেক্ষমান অর্ডার", "🚫 ব্যান ম্যানেজমেন্ট"],
        ["📢 ব্রডকাস্ট", "🔙 ফিরে যান"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ======================== START COMMAND ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Register user"""
    user = update.effective_user
    user_id = user.id
    
    # Check if user exists
    existing_user = db.get_user(user_id)
    
    if not existing_user:
        # Create new user
        db.create_user(user_id, user.username, user.full_name)
        welcome_text = f"""
🎉 স্বাগতম {user.first_name}!

আপনার একটি নতুন অ্যাকাউন্ট তৈরি হয়েছে।

📋 **আপনার প্ল্যান:** Free
📁 **ম্যাক্স ফাইল:** 10
⚙️ **ম্যাক্স প্রসেস:** 1
💾 **স্টোরেজ:** 500 MB
        """
    else:
        welcome_text = f"""
👋 আপনি ফিরে এসেছেন {user.first_name}!
        """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard()
    )

# ======================== MAIN MENU HANDLER ========================
@is_not_banned
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu handler"""
    text = update.message.text
    user_id = update.effective_user.id
    
    # Update last activity
    now = datetime.now().isoformat()
    db.execute(
        'UPDATE users SET last_activity = ? WHERE user_id = ?',
        (now, user_id)
    )
    
    # Check if premium expired
    db.check_premium_expiry(user_id)
    
    user = db.get_user(user_id)
    
    if text == "📁 ফাইল ম্যানেজমেন্ট":
        await update.message.reply_text(
            "📁 **ফাইল ম্যানেজমেন্ট প্যানেল**",
            reply_markup=get_file_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return FILE_MENU
    
    elif text == "⚙️ স্ক্রিপ্ট এক্সিকিউশন":
        await update.message.reply_text(
            "⚙️ **স্ক্রিপ্ট এক্সিকিউশন**",
            reply_markup=get_execution_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return EXECUTION_MENU
    
    elif text == "📊 স্ট্যাটিস্টিক্স":
        stats_text = f"""
📊 **আপনার স্ট্যাটিস্টিক্স**

👤 **ইউজার আইডি:** {user_id}
📅 **জয়েন ডেট:** {user[3]}
📁 **মোট ফাইল:** {user[8]}
⚙️ **চালু প্রসেস:** {user[9]}
💾 **ব্যবহৃত স্টোরেজ:** {user[10]:.2f} MB
📈 **প্ল্যান:** {user[5].upper()}
        """
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU
    
    elif text == "💳 প্রিমিয়াম কিনুন":
        return await start_payment(update, context)
    
    elif text == "❓ সাহায্য":
        help_text = """
❓ **সাহায্য ও ডকুমেন্টেশন**

/start - নতুন শুরু করুন
/help - এই সাহায্য বার্তা
/profile - আপনা��� প্রোফাইল দেখুন
/admin - অ্যাডমিন প্যানেল

📞 **সমস্যা হলে:** যোগাযোগ করুন
        """
        await update.message.reply_text(help_text)
        return MAIN_MENU
    
    elif text == "👤 প্রোফাইল":
        profile_text = f"""
👤 **আপনার প্রোফাইল**

📊 **ব্যক্তিগত তথ্য:**
• নাম: {user[2]}
• ইউজারনেম: @{user[1]}
• ইউজার আইডি: {user_id}

📈 **সাবস্ক্রিপশন:**
• প্ল্যান: {user[5].upper()}
• মেয়াদ শেষ: {user[6] if user[6] else 'চিরস্থায়ী (ফ্রি)'}

📊 **রিসোর্স ব্যবহার:**
• ফাইল: {user[8]}/{PLANS[user[5]]['max_files']}
• প্রসেস: {user[9]}/{PLANS[user[5]]['max_processes']}
• স্টোরেজ: {user[10]:.2f}/{PLANS[user[5]]['max_storage_gb']} GB
        """
        await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN)
        return MAIN_MENU

# ======================== FILE MANAGEMENT HANDLERS ========================

async def file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """File menu handler"""
    text = update.message.text
    
    if text == "📤 ফাইল আপলোড":
        await update.message.reply_text(
            "📤 ফাইল আপলোড করুন (.py, .js, .zip, .txt, .json, .env)"
        )
        return FILE_MENU
    
    elif text == "📋 আমার ফাইলগুলি":
        user_id = update.effective_user.id
        files = file_handler.list_files(user_id)
        
        if not files:
            await update.message.reply_text("📁 আপনার কোনো ফাইল নেই।")
            return FILE_MENU
        
        files_text = "📁 **আপনার ফাইলগুলি:**\n\n"
        for file in files:
            file_id, filename, size_mb, upload_date, is_running = file
            status = "▶️ চলছে" if is_running else "⏸️ থেমে আছে"
            
            files_text += f"""
🔹 **{filename}**
   ID: `{file_id}`
   সাইজ: {size_mb:.2f} MB
   স্ট্যাটাস: {status}
            """
        
        await update.message.reply_text(files_text, parse_mode=ParseMode.MARKDOWN)
        return FILE_MENU
    
    elif text == "🗑️ ফাইল ডিলিট":
        await update.message.reply_text("ডিলিট করতে ফাইল ID লিখুন:")
        context.user_data['action'] = 'delete_file'
        return FILE_MENU
    
    elif text == "🔙 ফিরে যান":
        await update.message.reply_text("👈 মূল মেনুতে ফিরেছেন", reply_markup=get_main_keyboard())
        return MAIN_MENU

# ======================== SCRIPT EXECUTION HANDLERS ========================

async def execution_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execution menu handler"""
    text = update.message.text
    
    if text == "▶️ স্ক্রিপ্ট চালান":
        await update.message.reply_text("চালাতে ফাইল ID লিখুন:")
        context.user_data['action'] = 'run_script'
        return EXECUTION_MENU
    
    elif text == "⏹️ স্ক্রিপ্ট থামান":
        await update.message.reply_text("থামাতে প্রসেস ID লিখুন:")
        context.user_data['action'] = 'stop_script'
        return EXECUTION_MENU
    
    elif text == "📜 লগ দেখুন":
        await update.message.reply_text("লগ দেখতে প্রসেস ID লিখুন:")
        context.user_data['action'] = 'view_logs'
        return EXECUTION_MENU
    
    elif text == "🔙 ফিরে যান":
        await update.message.reply_text("👈 মূল মেনুতে ফিরেছেন", reply_markup=get_main_keyboard())
        return MAIN_MENU

# ======================== PAYMENT HANDLERS ========================

async def start_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start payment process"""
    keyboard = [
        ["💳 Premium - ৯৯ টাকা"],
        ["💳 Pro - ২৯৯ টাকা"],
        ["🔙 ফিরে যান"]
    ]
    
    await update.message.reply_text(
        """
💳 **প্রিমিয়াম প্ল্যান নির্বাচন করুন:**

🎯 **Premium - ৯৯ টাকা/মাস**
   📁 ম্যাক্স ফাইল: 100
   ⚙️ ম্যাক্স প্রসেস: 5
   💾 স্টোরেজ: 10 GB

🎯 **Pro - ২৯৯ টাকা/মাস**
   📁 ম্যাক্স ফাইল: 500
   ⚙️ ম্যাক্স প্রসেস: 20
   💾 স্টোরেজ: 100 GB
        """,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN
    )
    return SELECT_PLAN

async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan selection"""
    text = update.message.text
    
    if text == "🔙 ফিরে যান":
        await update.message.reply_text("❌ পেমেন্ট বাতিল করা হয়েছে।", reply_markup=get_main_keyboard())
        return MAIN_MENU
    
    if "Premium" in text and "Pro" not in text:
        plan = "premium"
    elif "Pro" in text:
        plan = "pro"
    else:
        return SELECT_PLAN
    
    context.user_data['selected_plan'] = plan
    
    keyboard = [
        ["📱 bKash", "📱 Nagad"],
        ["📱 Rocket", "🔙 ফিরে যান"]
    ]
    
    await update.message.reply_text(
        "📱 **পেমেন্ট মেথড নির্বাচন করুন:**",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN
    )
    return SELECT_PAYMENT_METHOD

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment method selection"""
    text = update.message.text
    
    if text == "🔙 ফিরে যান":
        await update.message.reply_text("❌ পেমেন্ট বাতিল করা হয়েছে।", reply_markup=get_main_keyboard())
        return MAIN_MENU
    
    if text == "📱 bKash":
        payment_method = "bkash"
    elif text == "📱 Nagad":
        payment_method = "nagad"
    elif text == "📱 Rocket":
        payment_method = "rocket"
    else:
        return SELECT_PAYMENT_METHOD
    
    context.user_data['payment_method'] = payment_method
    
    # Create payment request
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    plan = context.user_data['selected_plan']
    
    result = payment_processor.create_payment_request(user_id, username, plan, payment_method)
    
    if not result['success']:
        await update.message.reply_text(result['message'])
        return MAIN_MENU
    
    context.user_data['transaction_id'] = result['transaction_id']
    
    # Send payment instructions
    instructions = payment_processor.get_payment_instructions(plan, payment_method)
    
    await update.message.reply_text(
        instructions,
        parse_mode=ParseMode.MARKDOWN
    )
    
    await update.message.reply_text(
        "💬 **ট্রানজেকশন আইডি** পাঠান (যেমন: TXN123456789)"
    )
    
    return SEND_TRANSACTION_ID

async def handle_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transaction ID input"""
    text = update.message.text
    
    if text == "🔙 ফিরে যান":
        await update.message.reply_text("❌ পেমেন্ট বাতিল করা হয়েছে।", reply_markup=get_main_keyboard())
        return MAIN_MENU
    
    context.user_data['transaction_ref'] = text
    
    await update.message.reply_text(
        """
📸 **এখন স্ক্রিনশট পাঠান:**

স্ক্রিনশটে নিম্নলিখিত তথ্য স্পষ্ট থাকতে হবে:
✓ ট্রানজেকশন আইডি
✓ পরিমাণ
✓ প্রাপক নম্বর
✓ তারিখ এবং সময়
        """
    )
    
    return SEND_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle screenshot upload"""
    if not update.message.photo:
        await update.message.reply_text("❌ অনুগ্রহ করে একটি ছবি পাঠান")
        return SEND_SCREENSHOT
    
    user_id = update.effective_user.id
    transaction_id = context.user_data.get('transaction_id')
    transaction_ref = context.user_data.get('transaction_ref')
    
    if not transaction_id or not transaction_ref:
        await update.message.reply_text("❌ ত্রুটি: ট্রানজেকশন তথ্য পাওয়া যায়নি")
        return MAIN_MENU
    
    # Get photo file ID
    photo = update.message.photo[-1]
    screenshot_file_id = photo.file_id
    
    # Submit payment proof
    result = payment_processor.submit_payment_proof(
        transaction_id, user_id, transaction_ref, screenshot_file_id
    )
    
    if result['success']:
        await update.message.reply_text(
            f"""
✅ **পেমেন্ট প্রমাণ সফলভাবে জমা দেওয়া হয়েছিল!**

🔄 **স্ট্যাটাস:** অপেক্ষমান যাচাইকরণ
📌 **ট্রানজেকশন ID:** {transaction_ref}
🆔 **রেফারেন্স:** {transaction_id}

⏳ অ্যাডমিন ২৪ ঘন্টার মধ্যে যাচাই করবে।
            """,
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(result['message'])
    
    return MAIN_MENU

# ======================== ADMIN HANDLERS ========================

@is_admin
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    text = update.message.text if update.message else None
    
    if text == "👥 সব ইউজার":
        users = db.execute('SELECT user_id, username, full_name, plan FROM users LIMIT 50')
        users_text = f"👥 **সব ইউজার (মোট: {len(users)})**\n\n"
        
        for i, user in enumerate(users, 1):
            users_text += f"{i}. {user[2]} (@{user[1]}) - [{user[3].upper()}]\n"
        
        await update.message.reply_text(users_text, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "📊 সিস্টেম স্ট্যাটাস":
        users_count = db.execute('SELECT COUNT(*) FROM users')[0][0]
        files_count = db.execute('SELECT COUNT(*) FROM files')[0][0]
        procs_count = db.execute("SELECT COUNT(*) FROM processes WHERE status = 'running'")[0][0]
        
        stats_text = f"""
📊 **সিস্টেম স্ট্যাটিস্টিক্স**

👥 মোট ইউজার: {users_count}
📁 মোট ফাইল: {files_count}
⚙️ চলমান প্রসেস: {procs_count}
        """
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "💳 অপেক্ষমান অর্ডার":
        orders = payment_processor.payment_db.get_pending_orders()
        
        if not orders:
            await update.message.reply_text("✅ কোনো অপেক্ষমান অর্ডার নেই!")
            return
        
        orders_text = f"📋 **অপেক্ষমান অর্ডার: {len(orders)} টি**\n\n"
        
        for order in orders[:10]:
            order_id, txn_id, user_id, username, full_name, plan, amount, method, ref, screenshot_id, created_at = order
            
            orders_text += f"""
{order_id}️⃣ **অর্ডার #{order_id}**
👤 {full_name} (@{username})
💰 {amount} টাকা - {plan.upper()}
📱 {method.upper()} - Ref: {ref}
            """
        
        keyboard = []
        for order in orders[:5]:
            keyboard.append([
                InlineKeyboardButton(f"অর্ডার #{order[0]} ✅", callback_data=f"approve_order_{order[0]}"),
                InlineKeyboardButton("❌", callback_data=f"reject_order_{order[0]}")
            ])
        
        await update.message.reply_text(
            orders_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )
    
    elif text == "🔙 ফিরে যান":
        await update.message.reply_text("👈 মূল মেনুতে ফিরেছেন", reply_markup=get_main_keyboard())

# ======================== DOCUMENT HANDLER ========================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document upload"""
    user_id = update.effective_user.id
    document = update.message.document
    
    # Validate file type
    allowed_extensions = ('.py', '.js', '.zip', '.txt', '.json', '.env')
    if not document.file_name.endswith(allowed_extensions):
        await update.message.reply_text(
            "❌ ফাইল টাইপ সাপোর্টেড নয়।"
        )
        return
    
    # Check file size (50 MB limit)
    if document.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("❌ ফাইল খুব বড়। সর্বোচ্চ 50 MB।")
        return
    
    # Download file
    try:
        await update.message.chat.send_action(ChatAction.TYPING)
        
        file = await context.bot.get_file(document.file_id)
        
        # Create temp path
        temp_path = f"/tmp/{document.file_name}"
        await file.download_to_drive(temp_path)
        
        # Save file
        result = file_handler.save_file(user_id, temp_path, document.file_name)
        
        if result['success']:
            await update.message.reply_text(
                f"✅ ফাইল আপলোড সফল!\n\n"
                f"📄 ফাইল: {result['filename']}\n"
                f"📊 সাইজ: {result['size_mb']:.2f} MB",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(result['message'])
        
        # Clean temp file
        os.remove(temp_path)
    
    except Exception as e:
        await update.message.reply_text(f"❌ আপলোড ব্যর্থ: {str(e)}")

# ======================== TEXT INPUT HANDLER ========================

@is_not_banned
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for various actions"""
    text = update.message.text
    action = context.user_data.get('action')
    
    if not action:
        return await main_menu(update, context)
    
    if action == 'delete_file':
        try:
            file_id = int(text)
            user_id = update.effective_user.id
            result = file_handler.delete_file(user_id, file_id)
            await update.message.reply_text(result['message'])
        except ValueError:
            await update.message.reply_text("❌ ভুল ID ফরম্যাট")
    
    elif action == 'run_script':
        try:
            file_id = int(text)
            user_id = update.effective_user.id
            result = script_executor.run_script(user_id, file_id)
            await update.message.reply_text(result['message'])
        except ValueError:
            await update.message.reply_text("❌ ভুল ID ফরম্যাট")
    
    elif action == 'stop_script':
        try:
            process_id = int(text)
            user_id = update.effective_user.id
            result = script_executor.stop_script(process_id, user_id)
            await update.message.reply_text(result['message'])
        except ValueError:
            await update.message.reply_text("❌ ভুল ID ফরম্যাট")
    
    elif action == 'view_logs':
        try:
            process_id = int(text)
            user_id = update.effective_user.id
            result = script_executor.get_logs(process_id, user_id, lines=50)
            if result['success']:
                logs = result['logs']
                if len(logs) > 4000:
                    for chunk in [logs[i:i+4000] for i in range(0, len(logs), 4000)]:
                        await update.message.reply_text(
                            f"```\n{chunk}\n```",
                            parse_mode=ParseMode.MARKDOWN
                        )
                else:
                    await update.message.reply_text(
                        f"```\n{logs}\n```",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await update.message.reply_text(result['message'])
        except ValueError:
            await update.message.reply_text("❌ ভুল ID ফরম্যাট")
    
    context.user_data['action'] = None

# ======================== CALLBACK QUERY HANDLER ========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('approve_order_'):
        order_id = int(data.split('_')[2])
        admin_id = query.from_user.id
        
        # Approve order
        result = payment_processor.payment_db.approve_order(order_id, admin_id, "")
        
        if result:
            await query.edit_message_text(
                f"✅ **অর্ডার #{order_id} অনুমোদিত!**",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text("❌ অনুমোদন ব্যর্থ হয়েছে।")
    
    elif data.startswith('reject_order_'):
        order_id = int(data.split('_')[2])
        admin_id = query.from_user.id
        
        # Reject order
        result = payment_processor.payment_db.reject_order(order_id, admin_id, "User request")
        
        if result:
            await query.edit_message_text(
                f"❌ **অর্ডার #{order_id} প্রত্যাখ্যান করা হয়েছে**",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text("❌ প্রত্যাখ্যান ব���যর্থ হয়েছে।")

# ======================== ERROR HANDLER ========================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

# ======================== MAIN APPLICATION ========================

def main():
    """Start the bot"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Payment conversation handler
    payment_handler = ConversationHandler(
        entry_points=[CommandHandler("buy_premium", start_payment)],
        states={
            SELECT_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plan_selection)],
            SELECT_PAYMENT_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_method)],
            SEND_TRANSACTION_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transaction_id)],
            SEND_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )
    
    app.add_handler(payment_handler)
    
    # File menu conversation handler
    file_menu_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("📁 ফাইল ম্যানেজমেন্ট"), main_menu)],
        states={
            FILE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, file_menu)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(file_menu_handler)
    
    # Execution menu conversation handler
    execution_menu_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("⚙️ স্ক্রিপ্ট এক্সিকিউশন"), main_menu)],
        states={
            EXECUTION_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, execution_menu)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(execution_menu_handler)
    
    # Admin menu handler
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex("(👥|📊|💳|🚫|📢|🔙)"),
        admin_panel
    ))
    
    # Document handler
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Callback query handler
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Main menu handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    logger.info("🚀 বট সম্পূর্ণ সিস্টেম সহ শুরু হয়েছে...")
    app.run_polling()

if __name__ == "__main__":
    main()
