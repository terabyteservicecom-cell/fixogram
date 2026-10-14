from django.conf import settings
from django.core.files.storage import FileSystemStorage


class IdentityStorage(FileSystemStorage):
    def __init__(self):
        settings.IDENTITY_ROOT.mkdir(parents=True, exist_ok=True)
        super().__init__(location=settings.IDENTITY_ROOT, base_url=None)

    def deconstruct(self):
        return ("talent.private_storage.IdentityStorage", [], {})

    def url(self, name):
        raise ValueError("مدارک هویت لینک عمومی ندارند.")
