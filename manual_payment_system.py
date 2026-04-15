import sqlite3
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# ✅ config.py থেকে import করুন
from config import PAYMENT_ACCOUNTS, PLANS

# ======================== MANUAL PAYMENT CONFIG ========================
class ManualPaymentConfig:
    """Manual payment configuration"""
    
    # config.py থেকে ডেটা নিন
    PAYMENT_ACCOUNTS = PAYMENT_ACCOUNTS
    PLANS = PLANS

# ======================== MANUAL PAYMENT DATABASE ========================
class ManualPaymentDB:
    """Manual payment database management"""
    
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize payment tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Manual transactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS manual_transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                plan TEXT,
                amount REAL,
                payment_method TEXT,
                transaction_ref TEXT,
                screenshot_file_id TEXT,
                status TEXT DEFAULT 'pending',
                admin_notes TEXT,
                created_at TIMESTAMP,
                verified_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Pending orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                plan TEXT,
                amount REAL,
                payment_method TEXT,
                transaction_ref TEXT,
                screenshot_file_id TEXT,
                created_at TIMESTAMP,
                FOREIGN KEY(transaction_id) REFERENCES manual_transactions(transaction_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def execute(self, query, params=()):
        """Execute database query"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        result = cursor.fetchall()
        conn.close()
        return result
    
    def create_transaction(self, user_id, username, plan, payment_method, transaction_ref):
        """Create new manual transaction"""
        now = datetime.now().isoformat()
        amount = ManualPaymentConfig.PLANS[plan]['price']
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO manual_transactions 
            (user_id, username, plan, amount, payment_method, transaction_ref, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        ''', (user_id, username, plan, amount, payment_method, transaction_ref, now))
        
        conn.commit()
        transaction_id = cursor.lastrowid
        conn.close()
        
        return transaction_id
    
    def add_screenshot(self, transaction_id, screenshot_file_id):
        """Add screenshot to transaction"""
        self.execute(
            'UPDATE manual_transactions SET screenshot_file_id = ? WHERE transaction_id = ?',
            (screenshot_file_id, transaction_id)
        )
    
    def create_order(self, transaction_id, user_id, username, full_name, plan, payment_method, amount, transaction_ref, screenshot_file_id):
        """Create pending order for admin"""
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pending_orders 
            (transaction_id, user_id, username, full_name, plan, amount, payment_method, transaction_ref, screenshot_file_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (transaction_id, user_id, username, full_name, plan, amount, payment_method, transaction_ref, screenshot_file_id, now))
        
        conn.commit()
        conn.close()
    
    def get_pending_orders(self):
        """Get all pending orders"""
        return self.execute('''
            SELECT order_id, transaction_id, user_id, username, full_name, plan, amount, 
                   payment_method, transaction_ref, screenshot_file_id, created_at 
            FROM pending_orders 
            ORDER BY created_at DESC
        ''')
    
    def get_order(self, order_id):
        """Get specific order"""
        result = self.execute(
            'SELECT * FROM pending_orders WHERE order_id = ?',
            (order_id,)
        )
        return result[0] if result else None
    
    def approve_order(self, order_id, admin_id, admin_notes=""):
        """Approve order"""
        order = self.get_order(order_id)
        if not order:
            return False
        
        transaction_id, user_id, username, full_name, plan, amount, payment_method, transaction_ref, screenshot_file_id, created_at = order[1:]
        
        # Update transaction status
        now = datetime.now().isoformat()
        self.execute(
            'UPDATE manual_transactions SET status = ?, verified_at = ?, admin_notes = ? WHERE transaction_id = ?',
            ('approved', now, f"Approved by admin {admin_id}. {admin_notes}", transaction_id)
        )
        
        # Update user plan
        days = ManualPaymentConfig.PLANS[plan]['days']
        expiry = (datetime.now() + timedelta(days=days)).isoformat()
        
        self.execute(
            'UPDATE users SET plan = ?, premium_expiry = ? WHERE user_id = ?',
            (plan, expiry, user_id)
        )
        
        # Delete order
        self.execute('DELETE FROM pending_orders WHERE order_id = ?', (order_id,))
        
        return True
    
    def reject_order(self, order_id, admin_id, reason=""):
        """Reject order"""
        order = self.get_order(order_id)
        if not order:
            return False
        
        transaction_id = order[1]
        
        # Update transaction status
        self.execute(
            'UPDATE manual_transactions SET status = ?, admin_notes = ? WHERE transaction_id = ?',
            ('rejected', f"Rejected by admin {admin_id}. Reason: {reason}", transaction_id)
        )
        
        # Delete order
        self.execute('DELETE FROM pending_orders WHERE order_id = ?', (order_id,))
        
        return True
    
    def get_transaction(self, transaction_id):
        """Get transaction details"""
        result = self.execute(
            'SELECT * FROM manual_transactions WHERE transaction_id = ?',
            (transaction_id,)
        )
        return result[0] if result else None
    
    def get_user_transactions(self, user_id):
        """Get user's transactions"""
        return self.execute(
            'SELECT * FROM manual_transactions WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )

# ======================== MANUAL PAYMENT PROCESSOR ========================
class ManualPaymentProcessor:
    """Manual payment processor"""
    
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self.payment_db = ManualPaymentDB(db_path)
    
    def get_payment_instructions(self, plan, payment_method):
        """Get payment instructions for user"""
        if plan not in ManualPaymentConfig.PLANS:
            return None
        
        if payment_method not in ManualPaymentConfig.PAYMENT_ACCOUNTS:
            return None
        
        plan_info = ManualPaymentConfig.PLANS[plan]
        account_info = ManualPaymentConfig.PAYMENT_ACCOUNTS[payment_method]
        
        instructions = f"""
📋 **পেমেন্ট নির্দেশনা**

💰 **পরিমাণ:** {plan_info['price']} টাকা
🎯 **প্ল্যান:** {plan_info['name']}

📞 **নিচের নম্বরে টাকা পাঠান:**

{payment_method.upper()}
নম্বর: {account_info['number']}
নাম: {account_info['name']}

✅ **পাঠানোর পরে:**
1. ট্রানজেকশন আইডি (Txn ID) কপি করুন
2. স্ক্রিনশট নিন
3. নিচের বার্তায় উভয়ই পাঠান

⚠️ **গুরুত্বপূর্ণ:** সঠিক পরিমাণ পাঠানো নিশ্চিত করুন
        """
        
        return instructions
    
    def create_payment_request(self, user_id, username, plan, payment_method):
        """Create payment request"""
        if plan not in ManualPaymentConfig.PLANS:
            return {"success": False, "message": "❌ অবৈধ প্ল্যান"}
        
        if payment_method not in ManualPaymentConfig.PAYMENT_ACCOUNTS:
            return {"success": False, "message": "❌ অবৈধ পেমেন্ট মেথড"}
        
        # Create transaction with temporary ref
        temp_ref = f"TEMP_{user_id}_{int(datetime.now().timestamp())}"
        transaction_id = self.payment_db.create_transaction(
            user_id, username, plan, payment_method, temp_ref
        )
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "plan": plan,
            "payment_method": payment_method,
            "amount": ManualPaymentConfig.PLANS[plan]['price']
        }
    
    def submit_payment_proof(self, transaction_id, user_id, transaction_ref, screenshot_file_id):
        """Submit payment proof"""
        transaction = self.payment_db.get_transaction(transaction_id)
        
        if not transaction:
            return {"success": False, "message": "❌ ট্রানজেকশন পাওয়া যায়নি"}
        
        if transaction[11] != 'pending':  # status column
            return {"success": False, "message": "❌ এই ট্রানজেকশন ইতিমধ্যে প্রসেস করা হয়েছে"}
        
        # Update transaction with proof
        self.payment_db.execute(
            'UPDATE manual_transactions SET transaction_ref = ?, screenshot_file_id = ? WHERE transaction_id = ?',
            (transaction_ref, screenshot_file_id, transaction_id)
        )
        
        # Get user info
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT username, full_name FROM users WHERE user_id = ?', (user_id,))
        user_info = cursor.fetchone()
        conn.close()
        
        if not user_info:
            return {"success": False, "message": "❌ ইউজার পাওয়া যায়নি"}
        
        username, full_name = user_info
        plan = transaction[3]
        amount = transaction[4]
        payment_method = transaction[5]
        
        # Create order for admin
        self.payment_db.create_order(
            transaction_id, user_id, username, full_name, plan,
            payment_method, amount, transaction_ref, screenshot_file_id
        )
        
        return {
            "success": True,
            "message": "✅ পেমেন্ট প্রমাণ জমা দেওয়া হয়েছে। অ্যাডমিন যাচাই করবে।",
            "transaction_id": transaction_id
        }