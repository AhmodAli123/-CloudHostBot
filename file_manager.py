import os
import json
import shutil
import zipfile
import asyncio
import subprocess
import psutil
from datetime import datetime
from pathlib import Path
import sqlite3

# ======================== FILE MANAGER CLASS ========================
class FileManager:
    def __init__(self, base_dir="user_files", db_path="users.db"):
        self.base_dir = base_dir
        self.db_path = db_path
        self.ensure_base_dir()
    
    def ensure_base_dir(self):
        """Create base directory if not exists"""
        Path(self.base_dir).mkdir(exist_ok=True)
    
    def get_user_dir(self, user_id):
        """Get isolated user directory"""
        user_dir = os.path.join(self.base_dir, str(user_id))
        Path(user_dir).mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def validate_path(self, user_id, file_path):
        """Prevent directory traversal attacks"""
        user_dir = os.path.realpath(self.get_user_dir(user_id))
        file_path = os.path.realpath(file_path)
        
        if not file_path.startswith(user_dir):
            raise PermissionError("❌ Directory traversal not allowed!")
        
        return True
    
    def get_file_size_mb(self, file_path):
        """Get file size in MB"""
        return os.path.getsize(file_path) / (1024 * 1024)
    
    def get_user_storage_used(self, user_id):
        """Calculate total storage used by user"""
        user_dir = self.get_user_dir(user_id)
        total_size = 0
        
        for dirpath, dirnames, filenames in os.walk(user_dir):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except:
                    pass
        
        return total_size / (1024 * 1024)  # Convert to MB

# ======================== FILE UPLOAD HANDLER ========================
class FileUploadHandler(FileManager):
    def __init__(self, db_path="users.db"):
        super().__init__(db_path=db_path)
        self.db_path = db_path
    
    def save_file(self, user_id, file_path, filename):
        """Save uploaded file to user directory"""
        try:
            user_dir = self.get_user_dir(user_id)
            destination = os.path.join(user_dir, filename)
            
            # Validate path
            self.validate_path(user_id, destination)
            
            # Copy file
            shutil.copy2(file_path, destination)
            
            # Get file size
            file_size_mb = self.get_file_size_mb(destination)
            
            # Save to database
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (user_id, filename, file_path, file_size_mb, upload_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, filename, destination, file_size_mb, now))
            
            # Update user storage
            total_storage = self.get_user_storage_used(user_id)
            cursor.execute(
                'UPDATE users SET storage_used_mb = ? WHERE user_id = ?',
                (total_storage, user_id)
            )
            
            cursor.execute(
                'UPDATE users SET total_files = total_files + 1 WHERE user_id = ?',
                (user_id,)
            )
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "message": f"✅ ফাইল আপলোড সফল: {filename}",
                "filename": filename,
                "size_mb": file_size_mb
            }
        
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ আপলোড ব্যর্থ: {str(e)}"
            }
    
    def list_files(self, user_id):
        """List all files of user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT file_id, filename, file_size_mb, upload_date, is_running FROM files WHERE user_id = ? ORDER BY upload_date DESC',
            (user_id,)
        )
        files = cursor.fetchall()
        conn.close()
        
        return files
    
    def delete_file(self, user_id, file_id):
        """Delete file"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get file info
            cursor.execute(
                'SELECT filename, file_path, is_running FROM files WHERE file_id = ? AND user_id = ?',
                (file_id, user_id)
            )
            result = cursor.fetchone()
            
            if not result:
                return {"success": False, "message": "❌ ফাইল পাওয়া যায়নি"}
            
            filename, file_path, is_running = result
            
            if is_running:
                return {"success": False, "message": "❌ চলন্ত ফাইল ডিলিট করা যায় না। প্রথমে থামান।"}
            
            # Delete from filesystem
            self.validate_path(user_id, file_path)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Delete from database
            cursor.execute('DELETE FROM files WHERE file_id = ?', (file_id,))
            cursor.execute('UPDATE users SET total_files = total_files - 1 WHERE user_id = ?', (user_id,))
            
            # Update storage
            total_storage = self.get_user_storage_used(user_id)
            cursor.execute(
                'UPDATE users SET storage_used_mb = ? WHERE user_id = ?',
                (total_storage, user_id)
            )
            
            conn.commit()
            conn.close()
            
            return {"success": True, "message": f"✅ ফাইল ডিলিট হয়েছে: {filename}"}
        
        except Exception as e:
            return {"success": False, "message": f"❌ ডিলিট ব্যর্থ: {str(e)}"}

# ======================== ZIP HANDLER ========================
class ZipHandler(FileManager):
    def __init__(self, db_path="users.db"):
        super().__init__(db_path=db_path)
        self.db_path = db_path
    
    def extract_zip(self, user_id, file_id):
        """Extract ZIP file"""
        try:
            user_dir = self.get_user_dir(user_id)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT filename, file_path FROM files WHERE file_id = ? AND user_id = ?',
                (file_id, user_id)
            )
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return {"success": False, "message": "❌ ফাইল পাওয়া যায়নি"}
            
            filename, file_path = result
            
            if not filename.endswith('.zip'):
                return {"success": False, "message": "❌ এটি ZIP ফাইল নয়"}
            
            # Validate path
            self.validate_path(user_id, file_path)
            
            # Extract ZIP
            extract_dir = os.path.join(user_dir, filename.replace('.zip', ''))
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            return {
                "success": True,
                "message": f"✅ ZIP এক্সট্র্যাক্ট হয়েছে: {extract_dir}",
                "path": extract_dir
            }
        
        except Exception as e:
            return {"success": False, "message": f"❌ এক্সট্র্যাক্ট ব্যর্থ: {str(e)}"}

# ======================== ENV FILE HANDLER ========================
class EnvFileHandler(FileManager):
    def __init__(self, db_path="users.db"):
        super().__init__(db_path=db_path)
        self.db_path = db_path
    
    def create_env_file(self, user_id, env_vars):
        """Create .env file from dictionary"""
        try:
            user_dir = self.get_user_dir(user_id)
            env_path = os.path.join(user_dir, ".env")
            
            self.validate_path(user_id, env_path)
            
            with open(env_path, 'w') as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={value}\n")
            
            return {"success": True, "message": "✅ .env ফাইল তৈরি হয়েছে"}
        
        except Exception as e:
            return {"success": False, "message": f"❌ ব্যর্থ: {str(e)}"}
    
    def read_env_file(self, user_id):
        """Read .env file"""
        try:
            user_dir = self.get_user_dir(user_id)
            env_path = os.path.join(user_dir, ".env")
            
            self.validate_path(user_id, env_path)
            
            if not os.path.exists(env_path):
                return {"success": False, "message": "❌ .env ফাইল পাওয়া যায়নি"}
            
            env_vars = {}
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_vars[key] = value
            
            return {"success": True, "env_vars": env_vars}
        
        except Exception as e:
            return {"success": False, "message": f"❌ পড়া ব্যর্থ: {str(e)}"}

# ======================== SCRIPT EXECUTOR (PM2 STYLE) ========================
class ScriptExecutor(FileManager):
    def __init__(self, db_path="users.db"):
        super().__init__(db_path=db_path)
        self.db_path = db_path
        self.processes = {}  # {process_id: {pid, user_id, file_id}}
    
    def create_virtual_env(self, user_id):
        """Create Python virtual environment for user"""
        try:
            user_dir = self.get_user_dir(user_id)
            venv_path = os.path.join(user_dir, "venv")
            
            if not os.path.exists(venv_path):
                subprocess.run(
                    ["python3", "-m", "venv", venv_path],
                    check=True,
                    capture_output=True
                )
            
            return {"success": True, "venv_path": venv_path}
        
        except Exception as e:
            return {"success": False, "message": f"❌ venv তৈরি ব্যর্থ: {str(e)}"}
    
    def install_requirements(self, user_id, requirements_file):
        """Install Python packages from requirements.txt"""
        try:
            user_dir = self.get_user_dir(user_id)
            venv_path = os.path.join(user_dir, "venv")
            pip_path = os.path.join(venv_path, "bin", "pip")
            
            # Create venv if not exists
            if not os.path.exists(venv_path):
                self.create_virtual_env(user_id)
            
            # Install requirements
            result = subprocess.run(
                [pip_path, "install", "-r", requirements_file],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"❌ ইনস্টলেশন ব্যর্থ: {result.stderr}"
                }
            
            return {
                "success": True,
                "message": "✅ প্যাকেজ ইনস্টল হয়েছে",
                "output": result.stdout
            }
        
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "❌ ইনস্টলেশন টাইমআউট (সময় উত্তীর্ণ)"}
        except Exception as e:
            return {"success": False, "message": f"❌ ত্রুটি: {str(e)}"}
    
    def run_script(self, user_id, file_id, max_memory_mb=100):
        """Execute script with PM2-like management"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get file info
            cursor.execute(
                'SELECT filename, file_path FROM files WHERE file_id = ? AND user_id = ?',
                (file_id, user_id)
            )
            result = cursor.fetchone()
            
            if not result:
                return {"success": False, "message": "❌ ফাইল পাওয়া যায়নি"}
            
            filename, file_path = result
            
            # Validate path
            self.validate_path(user_id, file_path)
            
            user_dir = self.get_user_dir(user_id)
            
            # Determine script type
            if filename.endswith('.py'):
                venv_path = os.path.join(user_dir, "venv")
                python_path = os.path.join(venv_path, "bin", "python3")
                
                if not os.path.exists(python_path):
                    self.create_virtual_env(user_id)
                
                cmd = [python_path, file_path]
            
            elif filename.endswith('.js'):
                cmd = ["node", file_path]
            
            else:
                return {"success": False, "message": "❌ সাপোর্টেড ফাইল টাইপ নয় (.py বা .js)"}
            
            # Create process entry in database
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO processes (user_id, file_id, process_name, start_time, status)
                VALUES (?, ?, ?, ?, 'running')
            ''', (user_id, file_id, filename, now))
            conn.commit()
            
            process_id = cursor.lastrowid
            
            # Update file status
            cursor.execute('UPDATE files SET is_running = 1 WHERE file_id = ?', (file_id,))
            cursor.execute('UPDATE users SET total_processes = total_processes + 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            # Run script in background
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            
            # Read .env file if exists
            env_path = os.path.join(user_dir, ".env")
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            key, value = line.split('=', 1)
                            env[key] = value
            
            # Start process with resource limits
            process = subprocess.Popen(
                cmd,
                cwd=user_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                preexec_fn=lambda: self._set_resource_limits(max_memory_mb)
            )
            
            self.processes[process_id] = {
                "pid": process.pid,
                "user_id": user_id,
                "file_id": file_id,
                "process": process
            }
            
            # Start log collection thread
            asyncio.create_task(self._collect_logs(process_id, process))
            
            return {
                "success": True,
                "message": f"✅ স্ক্রিপ্ট চালু হয়েছে",
                "process_id": process_id,
                "pid": process.pid
            }
        
        except Exception as e:
            return {"success": False, "message": f"❌ এক্সিকিউশন ব্যর্থ: {str(e)}"}
    
    def _set_resource_limits(self, max_memory_mb):
        """Set resource limits for subprocess"""
        try:
            import resource
            # Limit memory
            memory_limit = max_memory_mb * 1024 * 1024
            resource.setrlimit(
                resource.RLIMIT_AS,
                (memory_limit, memory_limit)
            )
        except:
            pass
    
    async def _collect_logs(self, process_id, process):
        """Collect logs from running process"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO logs (process_id, timestamp, log_message)
                    VALUES (?, ?, ?)
                ''', (process_id, now, line.strip()))
                conn.commit()
        
        finally:
            conn.close()
    
    def stop_script(self, process_id, user_id):
        """Stop running script"""
        try:
            if process_id not in self.processes:
                return {"success": False, "message": "❌ প্রসেস পাওয়া যায়নি"}
            
            proc_info = self.processes[process_id]
            if proc_info['user_id'] != user_id:
                return {"success": False, "message": "❌ অননুমোদিত"}
            
            proc = proc_info['process']
            proc.terminate()
            
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            
            # Update database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE processes SET status = ? WHERE process_id = ?',
                ('stopped', process_id)
            )
            
            file_id = proc_info['file_id']
            cursor.execute('UPDATE files SET is_running = 0 WHERE file_id = ?', (file_id,))
            cursor.execute('UPDATE users SET total_processes = total_processes - 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            del self.processes[process_id]
            
            return {"success": True, "message": "✅ স্ক্রিপ্ট থামানো হয়েছে"}
        
        except Exception as e:
            return {"success": False, "message": f"❌ থামানো ব্যর্থ: {str(e)}"}
    
    def get_logs(self, process_id, user_id, lines=50):
        """Get last N lines of logs"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Verify user ownership
            cursor.execute(
                'SELECT user_id FROM processes WHERE process_id = ?',
                (process_id,)
            )
            result = cursor.fetchone()
            
            if not result or result[0] != user_id:
                return {"success": False, "message": "❌ অননুমোদিত"}
            
            # Get logs
            cursor.execute('''
                SELECT timestamp, log_message FROM logs 
                WHERE process_id = ? 
                ORDER BY log_id DESC 
                LIMIT ?
            ''', (process_id, lines))
            
            logs = cursor.fetchall()
            conn.close()
            
            logs.reverse()
            
            log_text = "\n".join([f"[{log[0]}] {log[1]}" for log in logs])
            
            return {"success": True, "logs": log_text}
        
        except Exception as e:
            return {"success": False, "message": f"❌ লগ পড়া ব্যর্থ: {str(e)}"}
    
    def get_process_status(self, process_id, user_id):
        """Get process status and resource usage"""
        try:
            if process_id not in self.processes:
                return {"success": False, "message": "❌ প্রসেস পাওয়া যায়নি"}
            
            proc_info = self.processes[process_id]
            if proc_info['user_id'] != user_id:
                return {"success": False, "message": "❌ অননুমোদিত"}
            
            pid = proc_info['pid']
            process = psutil.Process(pid)
            
            return {
                "success": True,
                "status": "running",
                "pid": pid,
                "memory_mb": process.memory_info().rss / (1024 * 1024),
                "cpu_percent": process.cpu_percent(interval=1)
            }
        
        except psutil.NoSuchProcess:
            return {"success": False, "message": "❌ প্রসেস চলছে না"}
        except Exception as e:
            return {"success": False, "message": f"❌ স্ট্যাটাস পড়া ব্যর্থ: {str(e)}"}