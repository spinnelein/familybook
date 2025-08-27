#!/usr/bin/env python3
"""
Google Photos Backup Solutions for 2025
Automated backup system that works around API limitations
"""

import os
import sys
import json
import shutil
import hashlib
import zipfile
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import schedule
import time

class GooglePhotosBackupManager:
    """
    Comprehensive backup manager for Google Photos post-2025 API changes
    Combines multiple approaches for reliable backup
    """
    
    def __init__(self, backup_root: str = "google_photos_backup"):
        self.backup_root = Path(backup_root)
        self.backup_root.mkdir(exist_ok=True)
        
        # Backup directories
        self.takeout_dir = self.backup_root / "takeout"
        self.organized_dir = self.backup_root / "organized"
        self.incremental_dir = self.backup_root / "incremental"
        self.metadata_dir = self.backup_root / "metadata"
        
        # Create directories
        for dir_path in [self.takeout_dir, self.organized_dir, 
                        self.incremental_dir, self.metadata_dir]:
            dir_path.mkdir(exist_ok=True)
        
        self.backup_log = self.backup_root / "backup_log.json"
        self.config_file = self.backup_root / "config.json"
        
        self.load_config()
    
    def load_config(self):
        """Load or create configuration"""
        default_config = {
            "last_takeout_check": "2024-01-01",
            "backup_schedule": "weekly",  # daily, weekly, monthly
            "organize_by_date": True,
            "check_duplicates": True,
            "compress_old_backups": True,
            "retention_months": 12,
            "notification_email": None
        }
        
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = {**default_config, **json.load(f)}
        else:
            self.config = default_config
            self.save_config()
    
    def save_config(self):
        """Save configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def log_activity(self, action: str, details: Dict):
        """Log backup activities"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details
        }
        
        logs = []
        if self.backup_log.exists():
            with open(self.backup_log, 'r') as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        # Keep last 100 entries
        logs = logs[-100:]
        
        with open(self.backup_log, 'w') as f:
            json.dump(logs, f, indent=2)
    
    def check_for_takeout_downloads(self) -> List[Path]:
        """Check for new Google Takeout downloads"""
        print("🔍 Checking for new Google Takeout files...")
        
        # Common download locations
        download_paths = [
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path("/tmp"),
            self.takeout_dir
        ]
        
        takeout_files = []
        for path in download_paths:
            if path.exists():
                takeout_files.extend(path.glob("takeout-*.zip"))
        
        print(f"Found {len(takeout_files)} takeout files")
        return takeout_files
    
    def process_takeout_archive(self, archive_path: Path) -> bool:
        """Process a single takeout archive"""
        print(f"📦 Processing {archive_path.name}...")
        
        try:
            # Extract to temporary location
            temp_extract = self.takeout_dir / f"temp_{archive_path.stem}"
            temp_extract.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract)
            
            # Find Google Photos folder
            photos_folder = temp_extract / "Takeout" / "Google Photos"
            if not photos_folder.exists():
                print("❌ No Google Photos folder found in archive")
                shutil.rmtree(temp_extract)
                return False
            
            # Process photos
            processed_count = self.organize_photos_from_takeout(photos_folder)
            
            # Clean up
            shutil.rmtree(temp_extract)
            
            # Move processed archive
            archive_backup = self.takeout_dir / "processed" / archive_path.name
            archive_backup.parent.mkdir(exist_ok=True)
            shutil.move(archive_path, archive_backup)
            
            self.log_activity("takeout_processed", {
                "archive": archive_path.name,
                "photos_processed": processed_count
            })
            
            return True
            
        except Exception as e:
            print(f"❌ Error processing {archive_path.name}: {e}")
            return False
    
    def organize_photos_from_takeout(self, photos_folder: Path) -> int:
        """Organize photos from takeout export"""
        processed_count = 0
        
        for item in photos_folder.rglob("*"):
            if item.is_file() and self.is_media_file(item):
                if self.organize_single_file(item):
                    processed_count += 1
        
        return processed_count
    
    def is_media_file(self, file_path: Path) -> bool:
        """Check if file is a media file"""
        media_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
            '.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v',
            '.heic', '.heif', '.webp', '.raw', '.dng'
        }
        return file_path.suffix.lower() in media_extensions
    
    def organize_single_file(self, file_path: Path) -> bool:
        """Organize a single media file"""
        try:
            # Try to get date from metadata file
            metadata_file = file_path.with_suffix(file_path.suffix + '.json')
            date_folder = None
            
            if metadata_file.exists():
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    creation_time = metadata.get('photoTakenTime', {}).get('timestamp')
                    if creation_time:
                        dt = datetime.fromtimestamp(int(creation_time))
                        date_folder = dt.strftime("%Y/%m")
            
            # Fallback to file modification date
            if not date_folder:
                dt = datetime.fromtimestamp(file_path.stat().st_mtime)
                date_folder = dt.strftime("%Y/%m")
            
            # Create destination
            dest_folder = self.organized_dir / date_folder
            dest_folder.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename if needed
            dest_file = dest_folder / file_path.name
            counter = 1
            while dest_file.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                dest_file = dest_folder / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # Copy file
            shutil.copy2(file_path, dest_file)
            
            # Copy metadata if exists
            if metadata_file.exists():
                metadata_dest = dest_file.with_suffix(dest_file.suffix + '.json')
                shutil.copy2(metadata_file, metadata_dest)
            
            return True
            
        except Exception as e:
            print(f"Error organizing {file_path.name}: {e}")
            return False
    
    def create_backup_index(self):
        """Create searchable index of backed up files"""
        print("📑 Creating backup index...")
        
        index = {
            "created": datetime.now().isoformat(),
            "total_files": 0,
            "total_size": 0,
            "files": []
        }
        
        for file_path in self.organized_dir.rglob("*"):
            if file_path.is_file() and self.is_media_file(file_path):
                file_info = {
                    "path": str(file_path.relative_to(self.organized_dir)),
                    "size": file_path.stat().st_size,
                    "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                    "hash": self.get_file_hash(file_path)
                }
                index["files"].append(file_info)
                index["total_files"] += 1
                index["total_size"] += file_info["size"]
        
        # Save index
        index_file = self.metadata_dir / f"index_{datetime.now().strftime('%Y%m%d')}.json"
        with open(index_file, 'w') as f:
            json.dump(index, f, indent=2)
        
        print(f"✅ Index created: {index['total_files']} files, {self.format_size(index['total_size'])}")
    
    def get_file_hash(self, file_path: Path) -> str:
        """Get MD5 hash of file"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}PB"
    
    def run_backup_cycle(self):
        """Run a complete backup cycle"""
        print("🔄 Starting backup cycle...")
        start_time = datetime.now()
        
        # Check for takeout files
        takeout_files = self.check_for_takeout_downloads()
        processed_archives = 0
        
        for archive in takeout_files:
            if self.process_takeout_archive(archive):
                processed_archives += 1
        
        # Create index
        self.create_backup_index()
        
        # Update config
        self.config["last_takeout_check"] = datetime.now().isoformat()
        self.save_config()
        
        # Log cycle
        duration = datetime.now() - start_time
        self.log_activity("backup_cycle", {
            "duration_seconds": duration.total_seconds(),
            "archives_processed": processed_archives,
            "total_archives_found": len(takeout_files)
        })
        
        print(f"✅ Backup cycle completed in {duration}")
        
        # Print summary
        self.print_backup_summary()
    
    def print_backup_summary(self):
        """Print backup summary"""
        print("\n" + "="*50)
        print("📊 BACKUP SUMMARY")
        print("="*50)
        
        if self.organized_dir.exists():
            media_files = list(self.organized_dir.rglob("*"))
            media_files = [f for f in media_files if f.is_file() and self.is_media_file(f)]
            
            total_size = sum(f.stat().st_size for f in media_files)
            
            print(f"📁 Total files: {len(media_files)}")
            print(f"💾 Total size: {self.format_size(total_size)}")
            print(f"📅 Last backup: {self.config.get('last_takeout_check', 'Never')}")
            
            # Show breakdown by year
            years = {}
            for file_path in media_files:
                year = file_path.parts[0] if len(file_path.parts) > 0 else "unknown"
                years[year] = years.get(year, 0) + 1
            
            print("\n📅 Photos by year:")
            for year in sorted(years.keys()):
                print(f"  {year}: {years[year]} files")
        
        print("="*50)
    
    def setup_automated_backup(self):
        """Setup automated backup schedule"""
        print("⏰ Setting up automated backup...")
        
        if self.config["backup_schedule"] == "daily":
            schedule.every().day.at("02:00").do(self.run_backup_cycle)
        elif self.config["backup_schedule"] == "weekly":
            schedule.every().sunday.at("02:00").do(self.run_backup_cycle)
        elif self.config["backup_schedule"] == "monthly":
            schedule.every().month.do(self.run_backup_cycle)
        
        print(f"✅ Backup scheduled: {self.config['backup_schedule']}")
        
        # Run scheduler
        while True:
            schedule.run_pending()
            time.sleep(3600)  # Check every hour

def main():
    """Main function with user interface"""
    print("🔧 Google Photos Backup Manager 2025")
    print("=====================================")
    
    backup_manager = GooglePhotosBackupManager()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "run":
            backup_manager.run_backup_cycle()
        elif command == "schedule":
            backup_manager.setup_automated_backup()
        elif command == "summary":
            backup_manager.print_backup_summary()
        else:
            print("Usage: python backup_manager.py [run|schedule|summary]")
    else:
        # Interactive mode
        while True:
            print("\nWhat would you like to do?")
            print("1. Run backup now")
            print("2. Setup automated backups")
            print("3. Show backup summary")
            print("4. Configure settings")
            print("5. Exit")
            
            choice = input("\nChoice (1-5): ").strip()
            
            if choice == "1":
                backup_manager.run_backup_cycle()
            elif choice == "2":
                backup_manager.setup_automated_backup()
                break
            elif choice == "3":
                backup_manager.print_backup_summary()
            elif choice == "4":
                print("Edit config.json in your backup folder")
            elif choice == "5":
                break
            else:
                print("Invalid choice")

if __name__ == "__main__":
    main()