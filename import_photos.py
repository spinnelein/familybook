from google_photos import list_recent_photos, download_photo
from models import db, ImportedPhoto

def import_google_photos():
    photos = list_recent_photos(page_size=20)
    for item in photos:
        if not ImportedPhoto.query.filter_by(google_id=item['id']).first():
            filename = download_photo(item)
            if filename:
                new_photo = ImportedPhoto(
                    google_id=item['id'],
                    filename=filename,
                    status='pending'
                )
                db.session.add(new_photo)
    db.session.commit()
    print("Import finished.")

if __name__ == '__main__':
    import_google_photos()