from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

class DownloadRequest(Base):
    __tablename__ = "download_requests"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    file_name = Column(String)
    status = Column(String, default="pending")
    requested_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    downloaded_size = Column(Integer, default=0)
    total_size = Column(Integer, default=0)
    save_path = Column(String, nullable=True)
    password = Column(String, nullable=True)
    direct_link = Column(String, nullable=True)

    def as_dict(self):
        data = {}
        for c in self.__table__.columns:
            value = getattr(self, c.name)
            if isinstance(value, datetime.datetime):
                data[c.name] = value.isoformat() if value else None
            elif c.name in ['downloaded_size', 'total_size'] and value is None:
                data[c.name] = 0 # Ensure these are always numbers
            else:
                data[c.name] = value
        return data 