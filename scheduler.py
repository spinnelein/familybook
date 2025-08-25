from apscheduler.schedulers.background import BackgroundScheduler
from import_photos import import_google_photos

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run the import once every day
    scheduler.add_job(import_google_photos, 'interval', days=1)
    scheduler.start()
    print("Scheduler started: Google Photos import will run daily.")